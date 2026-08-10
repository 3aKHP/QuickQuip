"""LLM 用量/成本统计聚合端点（供 Web Admin 成本视图）。

照搬 game_economy.py 的 connect()+GROUP BY 范式 + logs.py 的 asyncio.to_thread 卸载。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

router = APIRouter()

_RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}


def _cutoff(range_key: str) -> str:
    days = _RANGES.get(range_key, 7)
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _group_by(conn, col: str, cutoff: str) -> list[dict]:
    """按某列聚合 cost/calls（仅 state='ok' 行）。col 受控（非用户输入）。"""
    rows = conn.execute(
        f"SELECT {col} AS k, COALESCE(SUM(cost_usd), 0) AS cost, COUNT(*) AS calls "
        f"FROM llm_usage_events WHERE ts >= ? AND state = 'ok' GROUP BY {col} "
        f"ORDER BY cost DESC",
        (cutoff,),
    ).fetchall()
    return [
        {"key": r["k"] if r["k"] is not None else "(未归因)", "cost": round(r["cost"], 6), "calls": r["calls"]}
        for r in rows
    ]


def _summary(store, cutoff: str) -> dict:
    store._ensure_schema()
    with store.connect() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS cost, "
            "COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens, "
            "COUNT(*) AS calls FROM llm_usage_events WHERE ts >= ? AND state = 'ok'",
            (cutoff,),
        ).fetchone()
        unpriced = conn.execute(
            "SELECT COUNT(*) AS c, "
            "COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS t "
            "FROM llm_usage_events WHERE ts >= ? AND priced = 0 AND state = 'ok'",
            (cutoff,),
        ).fetchone()
        err = conn.execute(
            "SELECT COUNT(*) AS c FROM llm_usage_events WHERE ts >= ? AND state = 'error'",
            (cutoff,),
        ).fetchone()
        cancelled = conn.execute(
            "SELECT COUNT(*) AS c FROM llm_usage_events WHERE ts >= ? AND state = 'cancelled'",
            (cutoff,),
        ).fetchone()
        return {
            "total_cost": round(total["cost"], 6),
            "total_tokens": total["tokens"],
            "total_calls": total["calls"],
            "by_provider": _group_by(conn, "provider_id", cutoff),
            "by_feature": _group_by(conn, "feature", cutoff),
            "by_model": _group_by(conn, "model", cutoff),
            "by_group": _group_by(conn, "group_id", cutoff),
            "unpriced_calls_count": unpriced["c"],
            "unpriced_tokens_total": unpriced["t"],
            "error_count": err["c"],
            "cancelled_count": cancelled["c"],
            "bounds_note": "总成本为下界：不含失败/超时/未定价调用",
        }


def _timeline(store, cutoff: str) -> list[dict]:
    store._ensure_schema()
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT strftime('%Y-%m-%d', ts) AS d, COALESCE(SUM(cost_usd), 0) AS cost, "
            "COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens "
            "FROM llm_usage_events WHERE ts >= ? AND state = 'ok' GROUP BY d ORDER BY d",
            (cutoff,),
        ).fetchall()
    return [{"date": r["d"], "cost": round(r["cost"], 6), "tokens": r["tokens"]} for r in rows]


@router.get("/llm-usage/summary")
async def get_summary(range_: str = Query("7d", alias="range")):
    from quickquip.app.message_pipeline import usage_store

    return await asyncio.to_thread(_summary, usage_store, _cutoff(range_))


@router.get("/llm-usage/timeline")
async def get_timeline(range_: str = Query("30d", alias="range")):
    from quickquip.app.message_pipeline import usage_store

    return await asyncio.to_thread(_timeline, usage_store, _cutoff(range_))
