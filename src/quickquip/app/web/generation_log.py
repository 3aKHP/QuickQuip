"""报文「生成日志」归因：run_id 精确匹配优先，时间窗兜底（供 summaries / period_reports 路由共用）。

历史报文行没有 run_id（1.15.3 之前），按时间窗兜底：下界取 max(上一条同群同类
报文 generated_at, 本报文 generated_at - 6h)，上界为本报文 generated_at。6h 封顶
防止周月报共用 feature='period_report' 时跨类型长窗污染（月报窗口吞进周报跳）。
窗口内的手动触发（/summary now，不入库）事件会被归入相邻报文，属已知近似。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_FALLBACK_WINDOW = timedelta(hours=6)


def generation_log_response(artifact: dict, prev_generated_at: str | None, *, feature: str) -> dict:
    """run_id 精确归因优先；历史报文（无 run_id）按时间窗兜底。"""
    from quickquip.llm.usage_store import usage_store

    run_id = (artifact.get("run_id") or "").strip()
    generated_at = artifact["generated_at"]
    attribution = "run_id" if run_id else "time_window"
    try:
        if run_id:
            hops = usage_store.list_generation_hops(run_id=run_id)
        else:
            floor = (datetime.fromisoformat(generated_at) - _FALLBACK_WINDOW).isoformat()
            since = max(prev_generated_at or "", floor)
            hops = usage_store.list_generation_hops(
                feature=feature,
                group_id=artifact["group_id"],
                since=since,
                until=generated_at,
            )
    except (sqlite3.Error, ValueError):
        logger.warning("generation-log: 用量库暂不可用或报文时间戳异常")
        hops = []
    return {
        "ok": True,
        "attribution": attribution,
        "run_id": run_id or None,
        "hops": hops,
    }
