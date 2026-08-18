"""LLM 用量/成本统计聚合端点（供 Web Admin 成本视图）。

聚合 SQL 内聚在 ``LLMUsageStore.summary/timeline``（与 schema 同居）；本路由只做
auth（由 app.py 的 protected_dependencies 保证）+ asyncio.to_thread 卸载 + range 解析。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from quickquip.llm.usage_store import window_start

router = APIRouter()

_RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}


def _cutoff(range_key: str) -> str:
    """与 timeline 网格同起点的统一下界，保证汇总卡片与趋势合计口径一致。"""
    return window_start(_RANGES[range_key]).isoformat()


def _days(range_key: str) -> int:
    try:
        return _RANGES[range_key]
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="range must be one of 1d, 7d, 30d, 90d") from exc


def _filters(provider: str | None, model: str | None, feature: str | None, group: str | None, state: str | None) -> dict[str, str | None]:
    return {"provider_id": provider, "model": model, "feature": feature, "group_id": group, "state": state}


@router.get("/llm-usage/summary")
async def get_summary(
    range_: str = Query("7d", alias="range"),
    provider: str | None = None,
    model: str | None = None,
    feature: str | None = None,
    group: str | None = Query(None, alias="group"),
    state: str | None = None,
):
    from quickquip.llm.usage_store import usage_store

    _days(range_)
    return await asyncio.to_thread(usage_store.summary, _cutoff(range_), **_filters(provider, model, feature, group, state))


@router.get("/llm-usage/timeline")
async def get_timeline(
    range_: str = Query("7d", alias="range"),
    metric: str = Query("cost"),
    provider: str | None = None,
    model: str | None = None,
    feature: str | None = None,
    group: str | None = Query(None, alias="group"),
    state: str | None = None,
):
    from quickquip.llm.usage_store import usage_store

    days = _days(range_)
    if metric not in {"cost", "tokens", "requests", "errors", "duration"}:
        raise HTTPException(status_code=422, detail="unsupported metric")
    return await asyncio.to_thread(
        usage_store.timeline,
        _cutoff(range_),
        range_days=days,
        metric=metric,
        **_filters(provider, model, feature, group, state),
    )


@router.get("/llm-usage/events")
async def get_events(
    range_: str = Query("7d", alias="range"),
    limit: int = Query(50, ge=1, le=100),
    cursor: int | None = Query(None, ge=1),
    provider: str | None = None,
    model: str | None = None,
    feature: str | None = None,
    group: str | None = Query(None, alias="group"),
    state: str | None = None,
):
    from quickquip.llm.usage_store import usage_store

    _days(range_)
    return await asyncio.to_thread(
        usage_store.events,
        cutoff=_cutoff(range_),
        limit=limit,
        cursor=cursor,
        **_filters(provider, model, feature, group, state),
    )


@router.get("/llm-usage/events/{event_id}")
async def get_event(event_id: int):
    from quickquip.llm.usage_store import usage_store

    event = await asyncio.to_thread(usage_store.event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="usage event not found")
    return event
