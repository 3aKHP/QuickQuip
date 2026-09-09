"""报文「生成日志」归因：run_id 精确匹配优先，时间窗兜底（供 summaries / period_reports 路由共用）。

历史报文行没有 run_id（1.15.3 之前），按 (上一条同群同类报文 generated_at, 本报文
generated_at] 窗口兜底归因；日报/周报/月报对同一群同类型至少间隔一天，窗口不会重叠。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_FALLBACK_WINDOW = timedelta(hours=6)


def generation_log_response(artifact: dict, prev_generated_at: str | None, *, feature: str) -> dict:
    """run_id 精确归因优先；历史报文（无 run_id）按时间窗 (上一条报文, 本报文] 兜底。"""
    from quickquip.llm.usage_store import usage_store

    run_id = (artifact.get("run_id") or "").strip()
    generated_at = artifact["generated_at"]
    attribution = "run_id" if run_id else "time_window"
    try:
        if run_id:
            hops = usage_store.list_generation_hops(run_id=run_id)
        else:
            since = prev_generated_at
            if not since:
                since = (datetime.fromisoformat(generated_at) - _FALLBACK_WINDOW).isoformat()
            hops = usage_store.list_generation_hops(
                feature=feature,
                group_id=artifact["group_id"],
                since=since,
                until=generated_at,
            )
    except sqlite3.Error:
        logger.warning("generation-log: 用量库暂不可用")
        hops = []
    return {
        "ok": True,
        "attribution": attribution,
        "run_id": run_id or None,
        "hops": hops,
    }
