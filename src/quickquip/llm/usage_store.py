"""Persistent LLM usage/cost metering store (always-on, decoupled from trace).

每次 ``complete()`` 落一行（成功/错误/取消皆记），**不存请求/响应正文**——
与 ``trace.py`` 的 debug-only 全正文 trace 一刀切：trace=调试、14 天、标志门控；
usage=常驻计量、90 天、永不被标志门控。两者唯一共享面是 ``LLMResponse``。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quickquip.common.constants import BEIJING_TIMEZONE
from quickquip.common.paths import LLM_USAGE_DB_PATH

logger = logging.getLogger(__name__)

_USAGE_RETENTION_DAYS = 90
_SQLITE_BUSY_TIMEOUT_MS = 10_000
_SQLITE_BUSY_RETRY_DELAY_SECONDS = 0.1
_SQLITE_BUSY_RETRY_ATTEMPTS = 100
_SQLITE_RETRYABLE_LOCK_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}

# 统计业务时区固定为项目既有的 Asia/Shanghai；数据库时间戳持续使用 UTC，
# 仅在窗口边界与聚合分桶时换算。偏移后缀与 SQLite 修正子从同一时区推导，
# 保证 SQL 分桶与桶标签锁步一致。
_BUSINESS_TZ = ZoneInfo(BEIJING_TIMEZONE)


def _tz_offset_parts() -> tuple[str, int, int]:
    offset = datetime.now(_BUSINESS_TZ).utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    absolute = abs(total_minutes)
    return sign, absolute // 60, absolute % 60


_TZ_SIGN, _TZ_HOURS, _TZ_MINUTES = _tz_offset_parts()
_TZ_LABEL_SUFFIX = f"{_TZ_SIGN}{_TZ_HOURS:02d}:{_TZ_MINUTES:02d}"
_SQLITE_TZ_MODIFIER = f"{_TZ_SIGN}{_TZ_HOURS} hours" + (
    f" {_TZ_MINUTES} minutes" if _TZ_MINUTES else ""
)

# NULL 维度桶（provider/model/feature/group/persona）统一显示标签，由后端下发；
# 它不是任何列的真实值，不能作为筛选条件传给 API。
UNATTRIBUTED_LABEL = "(未归因)"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def window_start(range_days: int) -> datetime:
    """趋势网格起点（业务时区 Asia/Shanghai 边界），返回等效 UTC 瞬时，
    同时作为同 range 汇总/明细查询的统一下界。

    1d：业务时区当前整点 - 23h（24 个小时桶）；多天：业务时区今天 - (N-1)
    的零点（N 个日历日桶）。summary/timeline/events 共用该起点，保证趋势
    合计与总成本卡片口径一致。
    """
    now = datetime.now(_BUSINESS_TZ)
    if range_days <= 1:
        start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    else:
        start_date = now.date() - timedelta(days=range_days - 1)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=_BUSINESS_TZ)
    return start.astimezone(timezone.utc)


class LLMUsageStore:
    """SQLite WAL store for LLM usage/cost events. 克隆 trace.py 的连接/保留机械。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._last_cleanup_date: str | None = None

    def connect(self) -> sqlite3.Connection:
        """打开一个 WAL 连接（row_factory=Row）；调用方用 ``with`` 包裹。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=0")
            for attempt in range(_SQLITE_BUSY_RETRY_ATTEMPTS):
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as error:
                    error_code = getattr(error, "sqlite_errorcode", None)
                    if (
                        error_code is None
                        or error_code & 0xFF not in _SQLITE_RETRYABLE_LOCK_CODES
                        or attempt == _SQLITE_BUSY_RETRY_ATTEMPTS - 1
                    ):
                        raise
                    time.sleep(_SQLITE_BUSY_RETRY_DELAY_SECONDS)
            conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            conn.close()
            raise
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return conn

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self.connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS llm_usage_events (
                        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts                    TEXT NOT NULL,
                        provider_id           TEXT NOT NULL,
                        protocol              TEXT NOT NULL,
                        model                 TEXT NOT NULL,
                        feature               TEXT,
                        group_id              TEXT,
                        persona_id            TEXT,
                        agent_loop_id         TEXT,
                        envelope_tokens       INTEGER,
                        epoch_history_tokens  INTEGER,
                        media_image_count     INTEGER,
                        patch_tokens          INTEGER,
                        stream                INTEGER NOT NULL,
                        duration_ms           REAL,
                        input_tokens          INTEGER,
                        fresh_input_tokens    INTEGER,
                        total_tokens          INTEGER,
                        input_token_semantics TEXT,
                        output_tokens         INTEGER,
                        cache_creation_tokens INTEGER,
                        cache_read_tokens     INTEGER,
                        thinking_tokens       INTEGER,
                        cost_usd              REAL NOT NULL DEFAULT 0.0,
                        input_cost_usd        REAL NOT NULL DEFAULT 0.0,
                        output_cost_usd       REAL NOT NULL DEFAULT 0.0,
                        cache_read_cost_usd   REAL NOT NULL DEFAULT 0.0,
                        cache_creation_cost_usd REAL NOT NULL DEFAULT 0.0,
                        pricing_model         TEXT,
                        pricing_source        TEXT,
                        pricing_confidence    TEXT,
                        priced                INTEGER NOT NULL DEFAULT 0,
                        state                 TEXT NOT NULL DEFAULT 'ok',
                        error_message         TEXT
                    );
                    """
                )
                # 发版瞬间 quickquip 与 web-admin 两个容器会并发首开同一旧库，
                # 进程内锁挡不住跨进程：另一进程可能在本进程迁移途中已补列。
                # 因此每列 ALTER 前重查表结构；仍撞上 duplicate column name
                # （该错误只会源于列已存在）同样视为已存在，保证两边都不抛。
                migrations = {
                    "feature": "TEXT",
                    "group_id": "TEXT",
                    "persona_id": "TEXT",
                    "agent_loop_id": "TEXT",
                    "envelope_tokens": "INTEGER",
                    "epoch_history_tokens": "INTEGER",
                    "media_image_count": "INTEGER",
                    "patch_tokens": "INTEGER",
                    "duration_ms": "REAL",
                    "fresh_input_tokens": "INTEGER",
                    "total_tokens": "INTEGER",
                    "input_token_semantics": "TEXT",
                    "input_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "output_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "cache_read_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "cache_creation_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "pricing_model": "TEXT",
                    "pricing_source": "TEXT",
                    "pricing_confidence": "TEXT",
                }
                for name, definition in migrations.items():
                    columns = {
                        row[1]
                        for row in conn.execute("PRAGMA table_info(llm_usage_events)")
                    }
                    if name in columns:
                        continue
                    try:
                        conn.execute(
                            f"ALTER TABLE llm_usage_events ADD COLUMN {name} {definition}"
                        )
                    except sqlite3.OperationalError as error:
                        if "duplicate column name" not in str(error):
                            raise
                conn.executescript(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usage_ts       ON llm_usage_events(ts DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_provider ON llm_usage_events(provider_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_feature  ON llm_usage_events(feature, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_group    ON llm_usage_events(group_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_model    ON llm_usage_events(model, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_persona  ON llm_usage_events(persona_id, ts DESC);
                    """
                )
                # 历史 claude 行标签 backfill（issue #202）：input_tokens 列自始存
                # exclusive 原始值，落库标签却恒写 inclusive。UPDATE 天然幂等，
                # 首次执行修完全库后，后续重跑 0 行受影响
                conn.execute(
                    """
                    UPDATE llm_usage_events
                    SET input_token_semantics = 'exclusive'
                    WHERE protocol = 'claude' AND input_token_semantics = 'inclusive'
                    """
                )
            self._schema_ready = True

    def record(self, row: dict) -> None:
        """落一行用量（ts 自动补 UTC now）。row 的键须是表列子集。"""
        self._ensure_schema()
        self._cleanup_if_due()
        full = {"ts": _utc_now(), **row}
        cols = list(full.keys())
        placeholders = ", ".join("?" for _ in cols)
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO llm_usage_events ({', '.join(cols)}) VALUES ({placeholders})",
                list(full.values()),
            )

    def summary(self, cutoff: str, **filters: str | None) -> dict:
        """聚合用量/成本（仅 state='ok' 行计入金额；error/cancelled 单独计数）。"""
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._fresh_input_expr()} ELSE 0 END), 0) AS fresh_input, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN output_tokens ELSE 0 END), 0) AS output, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cache_read_tokens ELSE 0 END), 0) AS cache_read, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cache_creation_tokens ELSE 0 END), 0) AS cache_creation, "
                f"COUNT(*) AS calls, COALESCE(SUM(CASE WHEN state = 'ok' THEN 1 ELSE 0 END), 0) AS successes, "
                f"COALESCE(AVG(duration_ms), 0) AS avg_duration, "
                f"AVG(CASE WHEN state = 'ok' THEN envelope_tokens END) AS avg_envelope, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' AND envelope_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS envelope_tracked, "
                f"AVG(CASE WHEN state = 'ok' THEN epoch_history_tokens END) AS avg_epoch_history, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' AND epoch_history_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS epoch_tracked, "
                f"AVG(CASE WHEN state = 'ok' THEN media_image_count END) AS avg_media_images, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' AND media_image_count IS NOT NULL THEN 1 ELSE 0 END), 0) AS media_tracked, "
                f"AVG(CASE WHEN state = 'ok' THEN patch_tokens END) AS avg_patch, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' AND patch_tokens IS NOT NULL THEN 1 ELSE 0 END), 0) AS patch_tracked "
                f"FROM llm_usage_events WHERE {where}",
                params,
            ).fetchone()
            unpriced = conn.execute(
                f"SELECT COUNT(*) AS c, COALESCE(SUM({self._total_tokens_expr()}), 0) AS t "
                f"FROM llm_usage_events WHERE {where} AND priced = 0 AND state = 'ok'",
                params,
            ).fetchone()
            states = conn.execute(
                f"SELECT state, COUNT(*) AS c FROM llm_usage_events WHERE {where} GROUP BY state",
                params,
            ).fetchall()
            state_counts = {r["state"]: r["c"] for r in states}
            input_total = total["fresh_input"] + total["cache_read"] + total["cache_creation"]
            return {
                "total_cost": round(total["cost"], 6),
                "total_tokens": total["tokens"],
                "total_fresh_input_tokens": total["fresh_input"],
                "total_output_tokens": total["output"],
                "total_cache_read_tokens": total["cache_read"],
                "total_cache_creation_tokens": total["cache_creation"],
                "request_count": total["calls"],
                "success_count": total["successes"],
                "total_calls": total["successes"],
                "success_rate": round((total["successes"] or 0) / total["calls"], 4) if total["calls"] else 0.0,
                "average_duration_ms": round(total["avg_duration"], 2),
                "cache_hit_rate": round(total["cache_read"] / input_total, 4) if input_total else 0.0,
                # 第四张账本【信封】：Agent Loop 内每行同值，只可按 AVG 解读为
                # 每轮成本，禁止 SUM；coverage = 有估算行的成功调用占比
                "avg_envelope_tokens": round(total["avg_envelope"], 1) if total["avg_envelope"] is not None else 0.0,
                "envelope_coverage": round(total["envelope_tracked"] / total["successes"], 4) if total["successes"] else 0.0,
                # 第五张账本【纪元】：[anchor, head) history 段 token 估算；同信封口径
                # 只可按 AVG 解读（验收口径 ≈4.2k），coverage 语义同上
                "avg_epoch_history_tokens": round(total["avg_epoch_history"], 1) if total["avg_epoch_history"] is not None else 0.0,
                "epoch_coverage": round(total["epoch_tracked"] / total["successes"], 4) if total["successes"] else 0.0,
                # 第六张账本【媒体】：当轮实际随请求附带的图片数；同信封口径
                # 只可按 AVG 解读，coverage 语义同上
                "avg_media_image_count": round(total["avg_media_images"], 1) if total["avg_media_images"] is not None else 0.0,
                "media_coverage": round(total["media_tracked"] / total["successes"], 4) if total["successes"] else 0.0,
                # 第七张账本【现场补丁】：【现场】块 token 估算（与预算同单位，
                # AVG 直接读作预算利用率）；尾巴段每轮全价，不计入纪元 CTX 预算
                "avg_patch_tokens": round(total["avg_patch"], 1) if total["avg_patch"] is not None else 0.0,
                "patch_coverage": round(total["patch_tracked"] / total["successes"], 4) if total["successes"] else 0.0,
                "by_provider": self._group_by(conn, "provider_id", where, params),
                "by_feature": self._group_by(conn, "feature", where, params),
                "by_model": self._group_by(conn, "model", where, params),
                "by_group": self._group_by(conn, "group_id", where, params),
                "by_persona": self._group_by(conn, "persona_id", where, params),
                "unattributed_label": UNATTRIBUTED_LABEL,
                "unpriced_calls_count": unpriced["c"],
                "unpriced_tokens_total": unpriced["t"],
                "error_count": state_counts.get("error", 0),
                "cancelled_count": state_counts.get("cancelled", 0),
                "bounds_note": "总成本为下界：不含失败/超时/未定价调用",
            }

    def timeline(
        self,
        cutoff: str,
        *,
        range_days: int | None = None,
        metric: str = "cost",
        **filters: str | None,
    ) -> list[dict]:
        if metric not in {"cost", "tokens", "requests", "errors", "duration"}:
            raise ValueError("unsupported metric")
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        fill_buckets = range_days is not None
        effective_days = range_days or 7
        aligned_start = window_start(effective_days)
        if effective_days <= 1:
            # 小时桶按业务时区打标签（显式偏移后缀），不再把本地桶伪装成 UTC Z 标签
            bucket_expr = (
                f"strftime('%Y-%m-%dT%H:00:00{_TZ_LABEL_SUFFIX}', ts, '{_SQLITE_TZ_MODIFIER}')"
            )
            step = timedelta(hours=1)
            start = aligned_start.astimezone(_BUSINESS_TZ)
            fmt = f"%Y-%m-%dT%H:00:00{_TZ_LABEL_SUFFIX}"
        else:
            bucket_expr = f"strftime('%Y-%m-%d', ts, '{_SQLITE_TZ_MODIFIER}')"
            step = timedelta(days=1)
            start = aligned_start.astimezone(_BUSINESS_TZ).date()
            fmt = "%Y-%m-%d"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {bucket_expr} AS d, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
                f"COUNT(*) AS requests, SUM(CASE WHEN state = 'error' THEN 1 ELSE 0 END) AS errors, "
                f"COALESCE(AVG(duration_ms), 0) AS duration "
                f"FROM llm_usage_events WHERE {where} GROUP BY d ORDER BY d",
                params,
            ).fetchall()
        indexed = {r["d"]: r for r in rows}
        result = []
        cursor = start
        now_business = datetime.now(_BUSINESS_TZ)
        end = (
            now_business.replace(minute=0, second=0, microsecond=0)
            if effective_days <= 1
            else now_business.date()
        )
        if not fill_buckets:
            return [
                {"date": r["d"], "cost": round(r["cost"], 6), "tokens": r["tokens"],
                 "requests": r["requests"], "errors": r["errors"], "duration": round(r["duration"], 2),
                 "value": self._timeline_value(r, metric)}
                for r in rows
            ]
        while cursor <= end:
            key = cursor.strftime(fmt)
            row = indexed.get(key)
            result.append({
                "date": key,
                "cost": round(row["cost"], 6) if row else 0.0,
                "tokens": row["tokens"] if row else 0,
                "requests": row["requests"] if row else 0,
                "errors": row["errors"] if row else 0,
                "duration": round(row["duration"], 2) if row else 0.0,
                "value": self._timeline_value(row, metric),
            })
            cursor += step
        return result

    @staticmethod
    def _group_by(conn, col: str, where: str, params: list[object]) -> list[dict]:
        """按某列聚合 cost/calls（仅 state='ok'）。col 受控（非用户输入）。"""
        rows = conn.execute(
            f"SELECT {col} AS k, COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
            f"COUNT(*) AS calls, COALESCE(SUM(CASE WHEN state = 'ok' THEN {LLMUsageStore._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
            f"SUM(CASE WHEN state = 'error' THEN 1 ELSE 0 END) AS errors "
            f"FROM llm_usage_events WHERE {where} GROUP BY {col} "
            f"ORDER BY cost DESC",
            params,
        ).fetchall()
        return [
            {"key": r["k"] if r["k"] is not None else UNATTRIBUTED_LABEL, "cost": round(r["cost"], 6), "calls": r["calls"], "tokens": r["tokens"], "errors": r["errors"]}
            for r in rows
        ]

    @staticmethod
    def _total_tokens_expr() -> str:
        return "COALESCE(total_tokens, CASE WHEN input_token_semantics = 'exclusive' OR (input_token_semantics IS NULL AND protocol = 'claude') THEN COALESCE(input_tokens, 0) + COALESCE(cache_read_tokens, 0) + COALESCE(cache_creation_tokens, 0) ELSE COALESCE(input_tokens, 0) END + COALESCE(output_tokens, 0))"

    @staticmethod
    def _fresh_input_expr() -> str:
        return "COALESCE(fresh_input_tokens, CASE WHEN input_token_semantics = 'exclusive' OR (input_token_semantics IS NULL AND protocol = 'claude') THEN COALESCE(input_tokens, 0) ELSE MAX(0, COALESCE(input_tokens, 0) - COALESCE(cache_read_tokens, 0) - COALESCE(cache_creation_tokens, 0)) END)"

    @staticmethod
    def _timeline_value(row: sqlite3.Row | None, metric: str) -> float | int:
        if row is None:
            return 0.0 if metric in {"cost", "duration"} else 0
        return {
            "cost": round(row["cost"], 6),
            "tokens": row["tokens"],
            "requests": row["requests"],
            "errors": row["errors"],
            "duration": round(row["duration"], 2),
        }[metric]

    @staticmethod
    def _where(cutoff: str, filters: dict[str, str | None]) -> tuple[str, list[object]]:
        clauses = ["ts >= ?"]
        params: list[object] = [cutoff]
        for key in ("provider_id", "model", "feature", "group_id", "persona_id", "state"):
            value = filters.get(key)
            if value:
                clauses.append(f"{key} = ?")
                params.append(value)
        return " AND ".join(clauses), params

    def dimensions(self, cutoff: str) -> dict:
        """range 内可选筛选维度。仅受 cutoff 约束，不受页面其它筛选影响；
        NULL 不返回（不可筛选，由 unattributed_label 统一显示）。"""
        self._ensure_schema()
        with self.connect() as conn:

            def distinct(col: str) -> list[str]:
                rows = conn.execute(
                    f"SELECT DISTINCT {col} AS v FROM llm_usage_events "
                    f"WHERE ts >= ? AND {col} IS NOT NULL ORDER BY v",
                    (cutoff,),
                ).fetchall()
                return [r["v"] for r in rows]

            return {
                "providers": distinct("provider_id"),
                "models": distinct("model"),
                "features": distinct("feature"),
                "groups": distinct("group_id"),
                "personas": distinct("persona_id"),
                "unattributed_label": UNATTRIBUTED_LABEL,
            }

    def events(
        self,
        *,
        cutoff: str,
        limit: int = 50,
        cursor: int | None = None,
        **filters: str | None,
    ) -> dict:
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        if cursor is not None:
            where += " AND id < ?"
            params.append(cursor)
        limit = max(1, min(limit, 100))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM llm_usage_events WHERE {where} ORDER BY id DESC LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"items": [dict(row) for row in rows], "next_cursor": str(rows[-1]["id"]) if has_more and rows else None}

    def event(self, event_id: int) -> dict | None:
        self._ensure_schema()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM llm_usage_events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def _cleanup_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        if self._last_cleanup_date == today:
            return
        with self._cleanup_lock:
            if self._last_cleanup_date == today:
                return
            cutoff = (now - timedelta(days=_USAGE_RETENTION_DAYS)).isoformat()
            with self.connect() as conn:
                conn.execute("DELETE FROM llm_usage_events WHERE ts < ?", (cutoff,))
            self._last_cleanup_date = today

    def storage_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += Path(f"{self.path}{suffix}").stat().st_size
            except OSError:
                pass
        return total

    def close(self) -> None:
        """每次操作开/关连接，无持久连接需关。"""


usage_store = LLMUsageStore(LLM_USAGE_DB_PATH)
