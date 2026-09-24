"""纪元看板路由：锯齿时间轴、窗口构成元数据与实时快照入队（只读域）。

数据口径：
- points 取 usage.db（``epoch_series``，按 agent_loop_id 每轮取首行——
  Agent Loop 内同值，禁止 SUM/重复计）；
- events 取 llm.db ``epoch_events``（bot 进程旁路落库的锚点推进事实）；
- window 只取 id/role/token 元数据（``row_budget`` 与纪元预算同口径），
  绝不经本路由触碰正文展示——正文浏览走 conversations 域。
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from quickquip.app.web.action_queue import action_queue
from quickquip.common.paths import LLM_DB_PATH
from quickquip.llm.epoch import row_budget
from quickquip.llm.usage_store import usage_store, window_start

router = APIRouter()

_DB = LLM_DB_PATH

_GROUP_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")
_RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}

# 锚点前采样（构成条"已出窗区"色块）与窗口读的行数上限。
_MAX_BEFORE_ROWS = 200
_MAX_WINDOW_ROWS = 1024
# 出窗区 token 求和的扫描上限（COUNT 精确，token 超限时按截断值标近似）。
_OUT_TOKENS_SCAN_CAP = 2000


def _validate_group_key(group_key: str) -> str:
    key = group_key.strip()
    if not _GROUP_KEY_RE.match(key):
        raise HTTPException(
            status_code=422, detail="group_key must be 5-12 digits or 'private:USER_ID'"
        )
    return key


def _days(range_key: str) -> int:
    days = _RANGES.get(range_key)
    if days is None:
        raise HTTPException(status_code=422, detail="range must be one of 1d/7d/30d/90d")
    return days


def _normalize_before_ts(value: str | None) -> str | None:
    """before_ts 归一为 UTC ISO（``+00:00`` 后缀），与 created_at 落库格式对齐。

    created_at 由 ``_utc_now()`` 写为 Python UTC ISO（六位微秒）；前端
    toISOString() 给的是 "Z" 后缀三位毫秒，裸文本比较会在小数位宽度与
    后缀不一致处错序（如 ".123456+00:00" vs ".123Z"）。统一 parse 后
    astimezone(UTC) 输出再下传 SQL 比较。
    """
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="before_ts must be ISO 8601") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _dedup_per_loop(rows: list[dict]) -> list[dict]:
    """按 agent_loop_id 每轮取首行（NULL loop 各自成轮）。

    三项纪元计量全 NULL 的行（briefing/card_le_nearest 等不携带纪元口径的
    特性）对锯齿没有贡献，只把时间轴尾巴拖到无窗口数据的时刻——一并剔除。
    """
    seen: set[str] = set()
    points: list[dict] = []
    for row in rows:
        if (
            row["epoch_history_tokens"] is None
            and row["epoch_history_rows"] is None
            and row["envelope_tokens"] is None
        ):
            continue
        loop_id = row.get("agent_loop_id")
        marker = f"loop:{loop_id}" if loop_id else f"row:{row['id']}"
        if marker in seen:
            continue
        seen.add(marker)
        points.append(
            {
                "ts": row["ts"],
                "epoch_tokens": row["epoch_history_tokens"],
                "epoch_rows": row["epoch_history_rows"],
                "envelope_tokens": row["envelope_tokens"],
            }
        )
    return points


def _list_epoch_events_sync(
    group_key: str, cutoff: str, provider: str | None, model: str | None
) -> list[dict]:
    if not _DB.exists():
        return []
    clauses = ["scope_key = ?", "ts >= ?"]
    params: list[object] = [group_key, cutoff]
    if provider:
        clauses.append("provider_id = ?")
        params.append(provider)
    if model:
        clauses.append("model = ?")
        params.append(model)
    try:
        conn = sqlite3.connect(_DB, timeout=10)
    except sqlite3.Error:
        return []
    conn.row_factory = sqlite3.Row
    try:
        # 超限保最新（与锯齿 points 的截断方向一致）：内层 DESC 截断，外层回正序
        rows = conn.execute(
            f"""
            SELECT ts, provider_id, model, reason, old_anchor_id, new_anchor_id,
                   epoch_tokens, evicted_rows, evicted_tokens
            FROM (
                SELECT * FROM epoch_events
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT 2000
            )
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _map_role(role: str) -> str:
    if role == "assistant":
        return "bot"
    if role == "user":
        return "user"
    return "other"


def _read_window_sync(
    group_key: str,
    anchor_id: int,
    before_ts: str | None,
    before: int,
    limit: int,
) -> dict:
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="conversation store not found")
    head_clause = "AND created_at <= ?" if before_ts else ""
    head_params: list[object] = [before_ts] if before_ts else []
    conn = sqlite3.connect(_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        window_rows = conn.execute(
            f"""
            SELECT id, role, created_at, raw_content, content
            FROM conversation_messages
            WHERE group_id = ? AND id >= ? {head_clause}
            ORDER BY id ASC
            LIMIT ?
            """,
            [group_key, anchor_id, *head_params, limit],
        ).fetchall()
        out_rows = conn.execute(
            f"""
            SELECT id, role, created_at, raw_content, content
            FROM conversation_messages
            WHERE group_id = ? AND id < ? {head_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            [group_key, anchor_id, *head_params, before],
        ).fetchall()
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total FROM conversation_messages
            WHERE group_id = ? AND id < ? {head_clause}
            """,
            [group_key, anchor_id, *head_params],
        ).fetchone()
        stat_rows = conn.execute(
            f"""
            SELECT raw_content, content FROM conversation_messages
            WHERE group_id = ? AND id < ? {head_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            [group_key, anchor_id, *head_params, _OUT_TOKENS_SCAN_CAP],
        ).fetchall()
    finally:
        conn.close()

    def _meta(row: sqlite3.Row) -> dict:
        return {
            "id": int(row["id"]),
            "role": _map_role(row["role"]),
            "tokens": row_budget(
                {"raw_content": row["raw_content"], "content": row["content"]}
            ),
            "ts": row["created_at"],
        }

    out_total_rows = int(count_row["total"]) if count_row is not None else 0
    return {
        "anchor_id": anchor_id,
        "window": [_meta(row) for row in window_rows],
        "out": [_meta(row) for row in out_rows],
        "out_total_rows": out_total_rows,
        "out_total_tokens": sum(
            row_budget({"raw_content": row["raw_content"], "content": row["content"]})
            for row in stat_rows
        ),
        "out_tokens_approx": out_total_rows > len(stat_rows),
    }


@router.get("/epochs/timeline")
async def epoch_timeline(
    group_key: str,
    provider: str | None = None,
    model: str | None = None,
    range_: str = "7d",
):
    key = _validate_group_key(group_key)
    days = _days(range_)
    cutoff = window_start(days).isoformat()
    rows = await asyncio.to_thread(
        usage_store.epoch_series,
        cutoff=cutoff,
        group_id=key,
        provider_id=provider,
        model=model,
    )
    events = await asyncio.to_thread(
        _list_epoch_events_sync, key, cutoff, provider, model
    )
    return {"points": _dedup_per_loop(rows), "events": events}


@router.get("/epochs/window")
async def epoch_window(
    group_key: str,
    anchor_id: int,
    before_ts: str | None = None,
    before: int = 26,
    limit: int = 1024,
):
    key = _validate_group_key(group_key)
    anchor_id = max(0, anchor_id)
    before = max(0, min(before, _MAX_BEFORE_ROWS))
    limit = max(1, min(limit, _MAX_WINDOW_ROWS))
    normalized_before_ts = _normalize_before_ts(before_ts)
    return await asyncio.to_thread(
        _read_window_sync, key, anchor_id, normalized_before_ts, before, limit
    )


@router.post("/epochs/snapshot")
def queue_epoch_snapshot():
    # 只读 RPC（结果经 GET 轮询取走，不变更状态）：不记审计——
    # 看板 60s 自动轮询，否则每天灌入上千条无信息量的 queue 日志。
    action = action_queue.enqueue("epoch_snapshot", {})
    return {"ok": True, "queued": True, "action": action}
