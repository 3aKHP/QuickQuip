"""LLM 用量/成本统计聚合端点（供 Web Admin 成本视图）。

聚合 SQL 内聚在 ``LLMUsageStore.summary/timeline``（与 schema 同居）；本路由只做
auth（由 app.py 的 protected_dependencies 保证）+ asyncio.to_thread 卸载 + range 解析。
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


@router.get("/llm-usage/summary")
async def get_summary(range_: str = Query("7d", alias="range")):
    from quickquip.app.message_pipeline import usage_store

    return await asyncio.to_thread(usage_store.summary, _cutoff(range_))


@router.get("/llm-usage/timeline")
async def get_timeline(range_: str = Query("7d", alias="range")):
    from quickquip.app.message_pipeline import usage_store

    return await asyncio.to_thread(usage_store.timeline, _cutoff(range_))
