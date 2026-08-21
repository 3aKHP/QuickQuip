"""每日总结 / 群周报 / 群月报的生成与发布编排。

本模块拥有"窗口读取 → min_messages 门槛 → persona 兜底 → name_table 构建 →
LLM 生成 → 入库 / 发布状态机"的纯业务编排，不依赖 NoneBot。协作者
（llm service、collector、store、enabled groups、stats tracker）由调用方
（adapters/nonebot/daily_summary_plugin.py）显式注入；发送动作以 send 回调注入，
adapter 负责 bot 获取、bot_action_trace、合并转发节点与 int(group_id) 协议转换。

不变量（T4 characterization 钉住）：
- 生成编排返回 (content, model_used) 或 None，绝不外抛；多群并发用
  gather(return_exceptions=True) 隔离单群失败。
- 发布闸门顺序：send → mark_published → delete_date_file（日报删窗口两天）；
  send 失败不 mark 不删。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.period_report import (
    PERIOD_WEEKLY,
    compute_period_window,
    sample_messages_by_day,
)
from quickquip.llm.summarize import generate_daily_summary, generate_period_report

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)

# 发送回调契约：接收 store 行（含 group_id/content/model_used 等），送达失败时抛异常。
# 由 adapter 提供，内部负责 bot_action_trace、合并转发节点与 int(group_id) 转换。
SendRow = Callable[[dict], Awaitable[None]]


# ── 每日总结 ─────────────────────────────────────────────────────────────


async def run_summary_generation(
    group_id: str,
    start_ts: float,
    end_ts: float,
    date_label: str,
    *,
    svc,
    collector,
    stats_tracker,
) -> tuple[str, str] | None:
    """Core generation logic shared by the scheduled job and the manual command.

    Returns (content, model_used) on success, None if skipped or failed.
    Does NOT persist to the store — callers decide what to do with the result.
    """
    messages = collector.read_window(group_id, start_ts, end_ts)
    llm_config = svc.config
    daily_config = llm_config.daily_summary

    if len(messages) < daily_config.min_messages:
        logger.info(
            "daily_summary: group %s has %d messages (< %d), skipping",
            group_id, len(messages), daily_config.min_messages,
        )
        return None

    settings = svc.get_group_settings(group_id)
    persona = llm_config.personas.get(settings.persona_id) or next(
        iter(llm_config.personas.values()), None
    )
    if persona is None:
        logger.warning("daily_summary: no persona available for group %s", group_id)
        return None

    gs = stats_tracker.get_stats(group_id)
    name_table: dict[str, str] = dict(gs.user_names) if gs and gs.user_names else {}

    try:
        return await generate_daily_summary(
            messages=messages,
            persona=persona,
            group_id=group_id,
            date_label=date_label,
            name_table=name_table,
            summary_config=daily_config,
            llm_config=llm_config,
            default_provider_id=settings.provider_id,
            default_model=settings.model,
            local_tz=_LOCAL_TZ,
        )
    except Exception:
        logger.exception("daily_summary: generation failed for group %s", group_id)
        return None


async def generate_summary_one(
    group_id: str,
    start_ts: float,
    end_ts: float,
    date_label: str,
    summary_date: str,
    *,
    svc,
    collector,
    store,
    stats_tracker,
) -> None:
    """Generate and persist a summary for one group. Used by the scheduled job."""
    result = await run_summary_generation(
        group_id, start_ts, end_ts, date_label,
        svc=svc, collector=collector, stats_tracker=stats_tracker,
    )
    if result is not None:
        content, model_used = result
        store.upsert(group_id, summary_date, content, model_used)


async def generate_summaries_job(
    *,
    svc,
    collector,
    store,
    enabled_groups,
    stats_tracker,
) -> None:
    """06:00 scheduled job: generate summaries for the previous 06:00–06:00 window."""
    now = datetime.now(tz=_LOCAL_TZ)
    today_06 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    yesterday_06 = today_06 - timedelta(days=1)

    start_ts = yesterday_06.timestamp()
    end_ts = today_06.timestamp()
    summary_date = yesterday_06.date().isoformat()
    date_label = (
        yesterday_06.strftime("%Y年%m月%d日 06:00")
        + " 至 "
        + today_06.strftime("%m月%d日 06:00")
    )

    # Run all groups concurrently to avoid blocking the event loop for O(n) LLM calls
    tasks = [
        generate_summary_one(
            gid, start_ts, end_ts, date_label, summary_date,
            svc=svc, collector=collector, store=store, stats_tracker=stats_tracker,
        )
        for gid in enabled_groups.all_groups()
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def publish_summary_one(
    row: dict,
    *,
    store,
    collector,
    send: SendRow,
) -> None:
    """Send one summary to its group; mark published and clean up raw files on success."""
    group_id = row["group_id"]
    summary_date = row["summary_date"]
    try:
        await send(row)
        store.mark_published(group_id, summary_date)
        # Delete JSONL files only after confirmed delivery; covers the two dates in the window
        d = date.fromisoformat(summary_date)
        collector.delete_date_file(group_id, d)
        collector.delete_date_file(group_id, d - timedelta(days=1))
        logger.info("daily_summary: published for group %s (%s)", group_id, summary_date)
    except Exception:
        logger.warning(
            "daily_summary: publish failed for group %s (%s)", group_id, summary_date,
            exc_info=True,
        )


async def publish_summaries_job(
    *,
    store,
    collector,
    enabled_groups,
    send: SendRow,
) -> None:
    """12:00 scheduled job: publish all unpublished summaries."""
    unpublished = store.get_unpublished()
    if not unpublished:
        return

    # Only publish for groups that are still enabled
    enabled = set(enabled_groups.all_groups())
    tasks = [
        publish_summary_one(row, store=store, collector=collector, send=send)
        for row in unpublished
        if row["group_id"] in enabled
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


# ── 群周报 / 群月报 ──────────────────────────────────────────────────────


async def run_period_generation(
    group_id: str,
    period_type: str,
    start_ts: float,
    end_ts: float,
    period_label: str,
    *,
    svc,
    collector,
    stats_tracker,
) -> tuple[str, str] | None:
    """Core generation logic shared by the scheduled job and the manual command.

    Returns (content, model_used) on success, None if skipped or failed.
    Does NOT persist to the store — callers decide what to do with the result.
    """
    llm_config = svc.config

    if period_type == PERIOD_WEEKLY:
        cfg = llm_config.weekly_report
    else:
        cfg = llm_config.monthly_report

    messages = collector.read_window(group_id, start_ts, end_ts)
    if len(messages) < cfg.min_messages:
        logger.info(
            "period_report[%s]: group %s has %d messages (< %d), skipping",
            period_type, group_id, len(messages), cfg.min_messages,
        )
        return None

    sampled = sample_messages_by_day(messages, cfg.sample_per_day)
    if not sampled:
        return None

    settings = svc.get_group_settings(group_id)
    persona = llm_config.personas.get(settings.persona_id) or next(
        iter(llm_config.personas.values()), None
    )
    if persona is None:
        logger.warning("period_report[%s]: no persona available for group %s", period_type, group_id)
        return None

    gs = stats_tracker.get_stats(group_id)
    name_table: dict[str, str] = dict(gs.user_names) if gs and gs.user_names else {}

    try:
        return await generate_period_report(
            sampled,
            persona,
            group_id,
            period_label=period_label,
            period_kind=period_type,
            name_table=name_table,
            length_hint=cfg.length_hint,
            model_cascade=cfg.model_cascade,
            llm_config=llm_config,
            default_provider_id=settings.provider_id,
            default_model=settings.model,
            local_tz=_LOCAL_TZ,
        )
    except Exception:
        logger.exception("period_report[%s]: generation failed for group %s", period_type, group_id)
        return None


async def generate_period_one(
    group_id: str,
    period_type: str,
    *,
    svc,
    collector,
    store,
    stats_tracker,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Generate and persist a period report for one group. Used by the scheduled job."""
    if now is None:
        now = datetime.now(tz=_LOCAL_TZ)
    start_ts, end_ts, period_key, period_label = compute_period_window(period_type, now)

    result = await run_period_generation(
        group_id, period_type, start_ts, end_ts, period_label,
        svc=svc, collector=collector, stats_tracker=stats_tracker,
    )
    if result is not None:
        content, model_used = result
        store.upsert(group_id, period_type, period_key, content, model_used)
    return result


async def generate_period_reports_job(
    period_type: str,
    *,
    svc,
    collector,
    store,
    enabled_groups,
    stats_tracker,
) -> None:
    """定时生成 job：为所有启用群生成上一个完整周期的周期报告。"""
    groups = enabled_groups.all_groups()
    if not groups:
        return
    now = datetime.now(tz=_LOCAL_TZ)
    tasks = [
        generate_period_one(
            gid, period_type,
            svc=svc, collector=collector, store=store, stats_tracker=stats_tracker, now=now,
        )
        for gid in groups
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def publish_period_one(
    row: dict,
    period_type: str,
    *,
    store,
    send: SendRow,
) -> None:
    """发送单个周期报告到群里并标记已发布。"""
    group_id = row["group_id"]
    period_key = row["period_key"]
    try:
        await send(row)
        store.mark_published(group_id, period_type, period_key)
        logger.info("period_report[%s]: published for group %s (%s)", period_type, group_id, period_key)
    except Exception:
        logger.warning(
            "period_report[%s]: publish failed for group %s (%s)", period_type, group_id, period_key,
            exc_info=True,
        )


async def publish_period_reports_job(
    period_type: str,
    *,
    store,
    enabled_groups,
    send: SendRow,
) -> None:
    """定时发布 job：把所有未发布的周期报告发出去。"""
    unpublished = store.get_unpublished(period_type)
    if not unpublished:
        return
    enabled = set(enabled_groups.all_groups())
    tasks = [
        publish_period_one(row, period_type, store=store, send=send)
        for row in unpublished
        if row["group_id"] in enabled
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
