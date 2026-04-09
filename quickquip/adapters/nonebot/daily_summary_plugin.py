from __future__ import annotations

import logging
from datetime import datetime, timedelta
from time import time
from zoneinfo import ZoneInfo

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except ModuleNotFoundError:
    nonebot = None
    scheduler = None

from quickquip.app.message_pipeline import (
    RULE_SWITCH_PATH,
    llm_service,
    rule_switch,
    stats_tracker,
)
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.daily_summary import (
    DailyMessageCollector,
    DailySummaryEnabledGroups,
    DailySummaryStore,
)
from quickquip.llm.summarize import generate_daily_summary

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
_RULE_NAME = "daily_summary"
_MANUAL_COOLDOWN_SECONDS = 60

# Module-level singletons
collector = DailyMessageCollector()
store = DailySummaryStore()
enabled_groups = DailySummaryEnabledGroups()

# Per-group manual trigger cooldown
_last_manual_trigger: dict[str, float] = {}


def _on_cooldown(group_id: int | str) -> bool:
    last = _last_manual_trigger.get(str(group_id))
    return last is not None and time() - last < _MANUAL_COOLDOWN_SECONDS


def _mark_triggered(group_id: int | str) -> None:
    _last_manual_trigger[str(group_id)] = time()


def record_group_message(group_id: int | str, sender_name: str, rendered_text: str) -> None:
    """Record a message for daily summary collection. No-op if group is not opted in."""
    if not enabled_groups.contains(group_id):
        return
    collector.record(group_id, sender_name, rendered_text)


async def _generate_and_store(
    group_id: str,
    start_ts: float,
    end_ts: float,
    date_label: str,
    summary_date: str,
) -> str | None:
    """Generate summary for a group window and persist it. Returns content or None."""
    messages = collector.read_window(group_id, start_ts, end_ts)
    llm_config = llm_service.config
    daily_config = llm_config.daily_summary

    if len(messages) < daily_config.min_messages:
        logger.info(
            "daily_summary: group %s has %d messages (< %d), skipping",
            group_id, len(messages), daily_config.min_messages,
        )
        return None

    settings = llm_service.get_group_settings(group_id)
    persona = llm_config.personas.get(settings.persona_id) or next(
        iter(llm_config.personas.values()), None
    )
    if persona is None:
        logger.warning("daily_summary: no persona available for group %s", group_id)
        return None

    gs = stats_tracker.get_stats(group_id)
    name_table: dict[str, str] = dict(gs.user_names) if gs and gs.user_names else {}

    try:
        content, model_used = await generate_daily_summary(
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
        store.upsert(group_id, summary_date, content, model_used)
        return content
    except Exception:
        logger.exception("daily_summary: generation failed for group %s", group_id)
        return None


async def _job_generate_summaries() -> None:
    """06:00 scheduled job: generate summaries for the previous 06:00–06:00 window."""
    now = datetime.now(tz=_LOCAL_TZ)
    today_06 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    yesterday_06 = today_06 - timedelta(days=1)

    start_ts = yesterday_06.timestamp()
    end_ts = today_06.timestamp()
    summary_date = yesterday_06.date().isoformat()
    date_label = yesterday_06.strftime("%Y年%m月%d日 06:00 至 ") + today_06.strftime("%m月%d日 06:00")

    for group_id in enabled_groups.all_groups():
        content = await _generate_and_store(group_id, start_ts, end_ts, date_label, summary_date)
        if content is not None:
            # Delete the raw message files spanning this window
            collector.delete_date_file(group_id, yesterday_06.date())
            # Also clean up the day before in case of lingering files
            collector.delete_date_file(group_id, (yesterday_06 - timedelta(days=1)).date())


async def _job_publish_summaries() -> None:
    """12:00 scheduled job: publish stored summaries to their respective groups."""
    if nonebot is None:
        return
    try:
        bot = nonebot.get_bot()
    except Exception:
        logger.warning("daily_summary: bot not available at publish time")
        return

    now = datetime.now(tz=_LOCAL_TZ)
    today_06 = now.replace(hour=6, minute=0, second=0, microsecond=0)
    summary_date = (today_06 - timedelta(days=1)).date().isoformat()

    for group_id in enabled_groups.all_groups():
        row = store.get(group_id, summary_date)
        if row is None:
            continue
        try:
            await bot.send_group_msg(group_id=int(group_id), message=row["content"])
            logger.info("daily_summary: published for group %s (%s)", group_id, summary_date)
        except Exception:
            logger.warning(
                "daily_summary: publish failed for group %s", group_id, exc_info=True
            )


def _parse_cron(cron_expr: str) -> dict[str, str]:
    parts = cron_expr.split()
    if len(parts) != 5:
        return {"minute": "0", "hour": "6", "day": "*", "month": "*", "day_of_week": "*"}
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _register_scheduler_jobs() -> None:
    if not scheduler:
        return
    daily_cfg = llm_service.config.daily_summary
    if not daily_cfg.enabled:
        return

    scheduler.add_job(
        _job_generate_summaries,
        "cron",
        id="daily_summary_generate",
        replace_existing=True,
        **_parse_cron(daily_cfg.generate_cron),
    )
    scheduler.add_job(
        _job_publish_summaries,
        "cron",
        id="daily_summary_publish",
        replace_existing=True,
        **_parse_cron(daily_cfg.publish_cron),
    )
    logger.info(
        "daily_summary: jobs registered (generate=%s, publish=%s)",
        daily_cfg.generate_cron,
        daily_cfg.publish_cron,
    )


def register_daily_summary_commands(on_command) -> None:
    summary_cmd = on_command("summary", priority=10, block=True)

    @summary_cmd.handle()
    async def _(event):
        if getattr(event, "group_id", None) is None:
            await summary_cmd.finish("该命令仅支持群聊")

        group_id = event.group_id
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "summary").lower()

        # ── /summary on ──────────────────────────────────────────────
        if args in {"on", "开启", "启用"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            enabled_groups.add(group_id)
            rule_switch.enable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            await summary_cmd.finish(
                "本群每日总结已开启。"
                f"将于每日 {llm_service.config.daily_summary.generate_cron.split()[1]}:00 生成、"
                f"{llm_service.config.daily_summary.publish_cron.split()[1]}:00 发布。"
            )

        # ── /summary off ─────────────────────────────────────────────
        if args in {"off", "关闭", "禁用"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            enabled_groups.remove(group_id)
            rule_switch.disable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            await summary_cmd.finish("本群每日总结已关闭。")

        # ── /summary status ──────────────────────────────────────────
        if args in {"status", "状态", ""}:
            is_on = enabled_groups.contains(group_id)
            await summary_cmd.finish(f"本群每日总结：{'已开启 ✓' if is_on else '已关闭'}")

        # ── /summary now ─────────────────────────────────────────────
        if args in {"now", "立即", "生成"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            if not enabled_groups.contains(group_id):
                await summary_cmd.finish("本群未开启每日总结，请先使用 /summary on 开启。")
            if _on_cooldown(group_id):
                await summary_cmd.finish("操作过于频繁，请稍后再试（每分钟限一次）。")
            _mark_triggered(group_id)

            now = datetime.now(tz=_LOCAL_TZ)
            yesterday = now.date() - timedelta(days=1)
            start_dt = now.replace(
                year=yesterday.year, month=yesterday.month, day=yesterday.day,
                hour=6, minute=0, second=0, microsecond=0,
            )
            start_ts = start_dt.timestamp()
            end_ts = now.timestamp()
            date_label = (
                start_dt.strftime("%Y年%m月%d日 06:00")
                + " 至 "
                + now.strftime("%m月%d日 %H:%M")
            )

            await summary_cmd.send("正在生成总结，请稍候……")

            messages = collector.read_window(str(group_id), start_ts, end_ts)
            llm_config = llm_service.config
            daily_config = llm_config.daily_summary

            if len(messages) < daily_config.min_messages:
                await summary_cmd.finish(
                    f"当前窗口消息数不足（{len(messages)} 条，"
                    f"至少需要 {daily_config.min_messages} 条），无法生成总结。"
                )

            settings = llm_service.get_group_settings(group_id)
            persona = llm_config.personas.get(settings.persona_id) or next(
                iter(llm_config.personas.values()), None
            )
            if persona is None:
                await summary_cmd.finish("无可用人格配置，无法生成总结。")

            gs = stats_tracker.get_stats(group_id)
            name_table: dict[str, str] = dict(gs.user_names) if gs and gs.user_names else {}

            try:
                content, model_used = await generate_daily_summary(
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
                await summary_cmd.finish(content)
            except Exception as exc:
                await summary_cmd.finish(f"总结生成失败：{exc}")

        await summary_cmd.finish(
            "用法：/summary on|off|status|now\n"
            "  on   — 开启本群每日总结（管理员）\n"
            "  off  — 关闭本群每日总结（管理员）\n"
            "  now  — 立即生成前一天06:00至今的总结（管理员，每分钟限一次）\n"
            "  status — 查看当前状态"
        )


def setup(on_command) -> None:
    """Register scheduler jobs and commands. Call at plugin load time."""
    _register_scheduler_jobs()
    register_daily_summary_commands(on_command)
