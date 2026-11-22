"""每日总结 / 群周报 / 群月报的生成与发布编排。

本模块拥有"窗口读取 → min_messages 门槛 → persona 兜底 → name_table 构建 →
LLM 生成 → 入库 / 发布状态机"的纯业务编排，不依赖 NoneBot。协作者
（llm service、collector、store、enabled groups、stats tracker）由调用方
（adapters/nonebot/daily_summary_plugin.py）显式注入；发送动作以 send 回调注入，
adapter 负责 bot 获取、bot_action_trace、合并转发节点与 int(group_id) 协议转换。

不变量（T4 characterization 钉住）：
- 生成编排返回 (content, model_used) 或 None，绝不外抛；多群并发用
  gather(return_exceptions=True) 隔离单群失败。
- 发布闸门顺序：send → mark_published；send 失败不 mark。
  1.15.2 起消息归档永不删除，发布不再清理原始数据。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.llm.runtime_snapshot import leased_service
from quickquip.chat.period_report import (
    PERIOD_WEEKLY,
    compute_period_window,
)
from quickquip.chat.period_serializer import bot_user_ids_from_env
from quickquip.llm.summarize import generate_daily_summary, generate_period_report
from quickquip.llm.usage import current_usage_run_id

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)

# 自动定时发布的重试上限与补发窗口：防止历史上被平台拦截或退群的失败记录无限重放。
MAX_PUBLISH_ATTEMPTS = 3
DAILY_PUBLISH_MAX_AGE_DAYS = 2
WEEKLY_PUBLISH_MAX_AGE_DAYS = 14
MONTHLY_PUBLISH_MAX_AGE_DAYS = 35

# 发送回调契约：接收 store 行（含 group_id/content/model_used 等），送达失败时抛异常。
# 由 adapter 提供，内部负责 bot_action_trace、合并转发节点与 int(group_id) 转换。
SendRow = Callable[[dict], Awaitable[None]]


def _is_daily_summary_expired(
    summary_date: str,
    today: date,
    max_age_days: int,
) -> bool:
    try:
        parsed = date.fromisoformat(str(summary_date))
    except ValueError:
        return False
    return (today - parsed).days > max_age_days


def _is_period_report_expired(
    row: dict,
    now: datetime,
    max_age_days: int,
) -> bool:
    raw = row.get("generated_at")
    if not raw:
        return False
    try:
        generated = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=_LOCAL_TZ)
    return (now - generated).total_seconds() > max_age_days * 86400


# ── 每日总结 ─────────────────────────────────────────────────────────────



def _identity_resolver_from_svc(svc, group_id: str):
    """QQ → 标准身份（空串=未登记）；归档消费链读时重解析用。

    索引不可得（降级实例/测试替身）时返回 None，序列化回退显示名形态。
    """

    get_group_index = getattr(svc, "group_identities", None)
    if get_group_index is None:
        return None
    try:
        identity_index = get_group_index(group_id)
    except Exception:
        logger.warning("period_report: 身份索引不可用，按显示名序列化 group=%s", group_id)
        return None

    def _resolve(qq: str) -> str:
        return identity_index.resolve_user(qq).canonical_name

    return _resolve


@leased_service(lambda *args, **kwargs: kwargs["svc"])
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
            bot_user_ids=bot_user_ids_from_env(),
            identity_resolver=_identity_resolver_from_svc(svc, group_id),
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
        store.upsert(group_id, summary_date, content, model_used, run_id=current_usage_run_id())


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
    send: SendRow,
) -> None:
    """Send one summary to its group and mark published on success.

    1.15.2 起：消息归档永不删除（chat_archive 契约），发布成功只标记状态。
    发送失败时不标记 published_at，并记录失败次数以受重试上限约束。
    """
    group_id = row["group_id"]
    summary_date = row["summary_date"]
    try:
        await send(row)
        store.mark_published(group_id, summary_date)
        logger.info("daily_summary: published for group %s (%s)", group_id, summary_date)
    except Exception as exc:
        record_failure = getattr(store, "record_publish_failure", None)
        attempts: int | None = None
        if callable(record_failure):
            try:
                attempts = record_failure(group_id, summary_date, str(exc))
            except Exception:
                logger.warning(
                    "daily_summary: failed to record publish failure for group %s (%s)",
                    group_id, summary_date,
                    exc_info=True,
                )
        logger.warning(
            "daily_summary: publish failed for group %s (%s)%s",
            group_id,
            summary_date,
            f" (attempt {attempts})" if attempts is not None else "",
            exc_info=True,
        )


async def publish_summaries_job(
    *,
    store,
    enabled_groups,
    send: SendRow,
    max_age_days: int = DAILY_PUBLISH_MAX_AGE_DAYS,
    max_attempts: int = MAX_PUBLISH_ATTEMPTS,
    now: datetime | None = None,
) -> None:
    """定时发布 job：发布近期未发布的每日总结。

    过滤已禁用群、超过补发窗口的过期记录与达到重试上限的记录；
    同群多条记录按 summary_date 升序串行发送，不同群之间并发隔离。
    """
    unpublished = store.get_unpublished()
    if not unpublished:
        return

    current = now if now is not None else datetime.now(tz=_LOCAL_TZ)
    today = current.astimezone(_LOCAL_TZ).date()
    enabled = set(enabled_groups.all_groups())

    by_group: dict[str, list[dict]] = defaultdict(list)
    for row in unpublished:
        group_id = row["group_id"]
        summary_date = row["summary_date"]
        if group_id not in enabled:
            continue
        attempts = int(row.get("publish_attempts") or 0)
        if attempts >= max_attempts:
            logger.warning(
                "daily_summary: skipping group %s (%s), reached max publish attempts (%d/%d)",
                group_id, summary_date, attempts, max_attempts,
            )
            continue
        if _is_daily_summary_expired(summary_date, today, max_age_days):
            logger.info(
                "daily_summary: skipping expired summary for group %s (%s, > %d days)",
                group_id, summary_date, max_age_days,
            )
            continue
        by_group[group_id].append(row)

    if not by_group:
        return

    async def _publish_group(rows: list[dict]) -> None:
        for row in sorted(rows, key=lambda r: str(r["summary_date"])):
            await publish_summary_one(row, store=store, send=send)

    tasks = [_publish_group(rows) for rows in by_group.values()]
    await asyncio.gather(*tasks, return_exceptions=True)


# ── 群周报 / 群月报 ──────────────────────────────────────────────────────


@leased_service(lambda *args, **kwargs: kwargs["svc"])
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

    # 周报/月报均全量进入序列化层：周报直接压缩序列化；月报由
    # build_monthly_chat_input 按周公平预算组装（不再 sample_per_day）。
    # 溢出由级联每跳字符预算兜底截断。
    sampled = messages

    settings = svc.get_group_settings(group_id)
    persona = llm_config.personas.get(settings.persona_id) or next(
        iter(llm_config.personas.values()), None
    )
    if persona is None:
        logger.warning(
            "period_report[%s]: no persona available for group %s", period_type, group_id
        )
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
            bot_user_ids=bot_user_ids_from_env(),
            input_char_budget=getattr(cfg, "input_char_budget", None),
            identity_resolver=_identity_resolver_from_svc(svc, group_id),
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
        store.upsert(
            group_id, period_type, period_key, content, model_used,
            run_id=current_usage_run_id(),
        )
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
    """发送单个周期报告到群里并标记已发布；失败时记录尝试次数。"""
    group_id = row["group_id"]
    period_key = row["period_key"]
    try:
        await send(row)
        store.mark_published(group_id, period_type, period_key)
        logger.info(
            "period_report[%s]: published for group %s (%s)",
            period_type, group_id, period_key,
        )
    except Exception as exc:
        record_failure = getattr(store, "record_publish_failure", None)
        attempts: int | None = None
        if callable(record_failure):
            try:
                attempts = record_failure(group_id, period_type, period_key, str(exc))
            except Exception:
                logger.warning(
                    "period_report[%s]: failed to record publish failure for group %s (%s)",
                    period_type, group_id, period_key,
                    exc_info=True,
                )
        logger.warning(
            "period_report[%s]: publish failed for group %s (%s)%s",
            period_type,
            group_id,
            period_key,
            f" (attempt {attempts})" if attempts is not None else "",
            exc_info=True,
        )


async def publish_period_reports_job(
    period_type: str,
    *,
    store,
    enabled_groups,
    send: SendRow,
    max_age_days: int | None = None,
    max_attempts: int = MAX_PUBLISH_ATTEMPTS,
    now: datetime | None = None,
) -> None:
    """定时发布 job：发布近期未发布的周期报告。

    过滤已禁用群、超过补发窗口的过期记录与达到重试上限的记录；
    同群多条记录按 period_key 升序串行发送，不同群之间并发隔离。
    """
    unpublished = store.get_unpublished(period_type)
    if not unpublished:
        return

    current = now if now is not None else datetime.now(tz=_LOCAL_TZ)
    effective_max_age = (
        max_age_days
        if max_age_days is not None
        else (
            WEEKLY_PUBLISH_MAX_AGE_DAYS
            if period_type == PERIOD_WEEKLY
            else MONTHLY_PUBLISH_MAX_AGE_DAYS
        )
    )
    enabled = set(enabled_groups.all_groups())

    by_group: dict[str, list[dict]] = defaultdict(list)
    for row in unpublished:
        group_id = row["group_id"]
        period_key = row["period_key"]
        if group_id not in enabled:
            continue
        attempts = int(row.get("publish_attempts") or 0)
        if attempts >= max_attempts:
            logger.warning(
                "period_report[%s]: skipping group %s (%s), reached max publish attempts (%d/%d)",
                period_type, group_id, period_key, attempts, max_attempts,
            )
            continue
        if _is_period_report_expired(row, current, effective_max_age):
            logger.info(
                "period_report[%s]: skipping expired report for group %s (%s, > %d days)",
                period_type, group_id, period_key, effective_max_age,
            )
            continue
        by_group[group_id].append(row)

    if not by_group:
        return

    async def _publish_group(rows: list[dict]) -> None:
        for row in sorted(rows, key=lambda r: str(r["period_key"])):
            await publish_period_one(row, period_type, store=store, send=send)

    tasks = [_publish_group(rows) for rows in by_group.values()]
    await asyncio.gather(*tasks, return_exceptions=True)
