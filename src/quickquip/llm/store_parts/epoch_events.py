"""EpochEventsStoreMixin：纪元推进事件的落库与读取（旁路事件表）。

真值仍在 EpochManager 进程内存；本表只记录锚点推进的时序事实，服务
Web Admin 纪元看板的历史时间轴（悬崖标注/纪元分段/驱逐统计）与生产
排障（"为什么忘了"不再翻日志）。写入频率 = 推进频率（低频），调用方
（epoch.py）自带失败容忍，本 mixin 不做重试。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from quickquip.llm.epoch import row_budget
from quickquip.llm.store_parts._base import _utc_now

logger = logging.getLogger(__name__)

# 驱逐统计的扫描上限：clear 等大范围事件的 token 求和封顶（超出按截断值，
# rows 计数仍精确——COUNT 不受此限）。
_EVICTED_SCAN_CAP = 4096

# 事件表保留窗口：与看板最大 range（90d）及 usage 计量保留对齐；按日节流清理。
_EPOCH_EVENTS_RETENTION_DAYS = 90
_EPOCH_EVENTS_CLEANUP_LOCK = threading.Lock()


class EpochEventsStoreMixin:
    """纪元事件存储域。依赖 _StoreBase 的 _connect / _unavailable。"""

    def record_epoch_event(
        self,
        *,
        scope_key: str,
        provider_id: str,
        model: str,
        reason: str,
        old_anchor_id: int,
        new_anchor_id: int | None,
        epoch_tokens: int = -1,
        evicted_rows: int = 0,
        evicted_tokens: int = 0,
    ) -> None:
        """落一行锚点推进事件（reason ∈ cold/hot/rows/persona/init/clear）。"""
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO epoch_events (
                    ts, scope_key, provider_id, model, reason,
                    old_anchor_id, new_anchor_id, epoch_tokens,
                    evicted_rows, evicted_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now(),
                    scope_key,
                    provider_id,
                    model,
                    reason,
                    int(old_anchor_id),
                    None if new_anchor_id is None else int(new_anchor_id),
                    int(epoch_tokens),
                    int(evicted_rows),
                    int(evicted_tokens),
                ),
            )
        try:
            self._cleanup_epoch_events_if_due()
        except sqlite3.Error:
            logger.warning("epoch_events 过期清理失败（不影响事件落库）", exc_info=True)

    def _cleanup_epoch_events_if_due(self) -> None:
        """按日节流清理过期事件：表只增不减会无界累积，窗口与看板 90d 对齐。"""
        today = _utc_now()[:10]
        if self._epoch_events_cleanup_date == today:
            return
        with _EPOCH_EVENTS_CLEANUP_LOCK:
            if self._epoch_events_cleanup_date == today:
                return
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=_EPOCH_EVENTS_RETENTION_DAYS)
            ).isoformat()
            with self._connect() as conn:
                conn.execute("DELETE FROM epoch_events WHERE ts < ?", (cutoff,))
            self._epoch_events_cleanup_date = today

    def list_epoch_events(
        self,
        scope_key: str,
        *,
        cutoff: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        """按 scope 读取推进事件（id ASC = 时间序），供看板时间轴。

        超限保留最新若干条（内层 DESC 截断、外层回正序）：丢最新事件会让
        最近时刻的锚点推导停在过期值，比丢最旧的危害大。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        clauses = ["scope_key = ?"]
        params: list[object] = [scope_key]
        if cutoff:
            clauses.append("ts >= ?")
            params.append(cutoff)
        if provider_id:
            clauses.append("provider_id = ?")
            params.append(provider_id)
        if model:
            clauses.append("model = ?")
            params.append(model)
        params.append(max(1, min(int(limit), 2000)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ts, provider_id, model, reason,
                       old_anchor_id, new_anchor_id, epoch_tokens,
                       evicted_rows, evicted_tokens
                FROM (
                    SELECT * FROM epoch_events
                    WHERE {' AND '.join(clauses)}
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def conversation_range_stats(
        self, scope_key: str, start_id: int, end_id: int | None = None
    ) -> tuple[int, int]:
        """[start_id, end_id) 区间的行数与纪元预算口径 token 估算。

        end_id 为 None 表示开区间到 head（clear 事件的驱逐统计）。token 求和
        扫描封顶 _EVICTED_SCAN_CAP 行，超出部分按截断值估算（行数始终精确）。
        """
        if self._unavailable:
            raise RuntimeError("LLM存储 数据库不可用")
        range_clause = "id >= ?" if end_id is None else "id >= ? AND id < ?"
        range_params: list[object] = (
            [int(start_id)] if end_id is None else [int(start_id), int(end_id)]
        )
        with self._connect() as conn:
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total FROM conversation_messages
                WHERE group_id = ? AND {range_clause}
                """,
                [scope_key, *range_params],
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT raw_content, content FROM conversation_messages
                WHERE group_id = ? AND {range_clause}
                ORDER BY id ASC
                LIMIT ?
                """,
                [scope_key, *range_params, _EVICTED_SCAN_CAP],
            ).fetchall()
        total_rows = int(count_row["total"]) if count_row is not None else 0
        # 与纪元推进判定同口径（row_budget 单源），勿在此另立估算公式
        tokens = sum(row_budget(dict(row)) for row in rows)
        return total_rows, tokens
