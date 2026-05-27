from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from time import time
from zoneinfo import ZoneInfo

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except (ModuleNotFoundError, ValueError):
    # ValueError is raised by nonebot_plugin_apscheduler when NoneBot is not
    # yet initialized (e.g. during tests that import outside a bot context).
    nonebot = None
    scheduler = None

from quickquip.app.message_pipeline import (
    RULE_SWITCH_PATH,
    daily_collector,
    _ensure_llm_bindings,
    get_llm_service,
    daily_enabled_groups,
    daily_store,
    rule_switch,
    stats_tracker,
)
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.adapters.nonebot.long_messages import send_long_group_message
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.llm.summarize import generate_daily_summary

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
_RULE_NAME = "daily_summary"
_MANUAL_COOLDOWN_SECONDS = 60

# Per-group manual trigger cooldown: group_id -> last trigger timestamp.
# asyncio is single-threaded; the check-then-mark sequence has no await
# in between, so it is atomically safe within the event loop.
_last_manual_trigger: dict[str, float] = {}

async def _send_long_message(bot, group_id: int, content: str) -> None:
    await send_long_group_message(
        bot,
        group_id,
        content,
        node_name="群聊日报",
        log_name="daily_summary",
    )


def _on_cooldown(group_id: int | str) -> bool:
    last = _last_manual_trigger.get(str(group_id))
    return last is not None and time() - last < _MANUAL_COOLDOWN_SECONDS


def _mark_triggered(group_id: int | str) -> None:
    _last_manual_trigger[str(group_id)] = time()


def _cron_to_hhmm(cron_expr: str) -> str:
    """Convert a 5-field cron expression to an HH:MM display string.

    Returns the first hour:minute that matches (handles simple numeric fields).
    Falls back to the raw expression if fields are not plain integers.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        return cron_expr
    minute_field, hour_field = parts[0], parts[1]
    try:
        return f"{int(hour_field):02d}:{int(minute_field):02d}"
    except ValueError:
        return f"{hour_field}:{minute_field}"


async def _run_generation(
    group_id: str,
    start_ts: float,
    end_ts: float,
    date_label: str,
) -> tuple[str, str] | None:
    """Core generation logic shared by the scheduled job and the manual command.

    Returns (content, model_used) on success, None if skipped or failed.
    Does NOT persist to the store — callers decide what to do with the result.
    """
    _ensure_llm_bindings()
    svc = get_llm_service()

    messages = daily_collector.read_window(group_id, start_ts, end_ts)
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


async def _generate_one(
    group_id: str,
    start_ts: float,
    end_ts: float,
    date_label: str,
    summary_date: str,
) -> None:
    """Generate and persist a summary for one group. Used by the scheduled job."""
    result = await _run_generation(group_id, start_ts, end_ts, date_label)
    if result is not None:
        content, model_used = result
        daily_store.upsert(group_id, summary_date, content, model_used)


async def send_daily_summary_now(group_id: int | str, bot=None, before_generate=None) -> dict[str, object]:
    group_key = str(group_id)
    if not daily_enabled_groups.contains(group_key):
        raise RuntimeError("daily summary is not enabled for this group")
    if _on_cooldown(group_key):
        raise RuntimeError("summary generation is on cooldown")

    _mark_triggered(group_key)
    _ensure_llm_bindings()
    svc = get_llm_service()
    now = datetime.now(tz=_LOCAL_TZ)
    yesterday = now.date() - timedelta(days=1)
    start_dt = now.replace(
        year=yesterday.year,
        month=yesterday.month,
        day=yesterday.day,
        hour=6,
        minute=0,
        second=0,
        microsecond=0,
    )
    date_label = (
        start_dt.strftime("%Y年%m月%d日 06:00")
        + " 至 "
        + now.strftime("%m月%d日 %H:%M")
    )
    if before_generate is not None:
        await before_generate()
    messages = daily_collector.read_window(group_key, start_dt.timestamp(), now.timestamp())
    min_messages = svc.config.daily_summary.min_messages
    if len(messages) < min_messages:
        raise RuntimeError(f"not enough messages: {len(messages)}/{min_messages}")
    result = await _run_generation(group_key, start_dt.timestamp(), now.timestamp(), date_label)
    if result is None:
        raise RuntimeError("summary generation skipped or failed")

    content, model_used = result
    if bot is None:
        if nonebot is None:
            raise RuntimeError("bot runtime is not available")
        bot = nonebot.get_bot()
    with bot_action_trace(
        trigger_kind="command",
        reason_code="command.summary.now",
        reason_detail="命令触发：立即生成并发送每日总结",
        rule_name=_RULE_NAME,
        chat_type="group",
        group_id=group_key,
        reply_preview=content,
        llm_used=model_used != "fallback",
        model=model_used,
        source="daily_summary.manual",
    ):
        await _send_long_message(bot, int(group_key), content)
    return {"model_used": model_used, "char_count": len(content)}


async def _job_generate_summaries() -> None:
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
        _generate_one(gid, start_ts, end_ts, date_label, summary_date)
        for gid in daily_enabled_groups.all_groups()
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _publish_one(bot, row: dict) -> None:
    """Send one summary to its group; mark published and clean up raw files on success."""
    group_id = row["group_id"]
    summary_date = row["summary_date"]
    try:
        with bot_action_trace(
            trigger_kind="scheduled",
            reason_code="daily_summary.publish",
            reason_detail=f"定时发布每日总结：{summary_date}",
            rule_name=_RULE_NAME,
            chat_type="group",
            group_id=group_id,
            reply_preview=row["content"],
            model=str(row.get("model_used", "")),
            source="daily_summary.scheduled_publish",
        ):
            await _send_long_message(bot, int(group_id), row["content"])
        daily_store.mark_published(group_id, summary_date)
        # Delete JSONL files only after confirmed delivery; covers the two dates in the window
        import datetime as _dt
        d = _dt.date.fromisoformat(summary_date)
        daily_collector.delete_date_file(group_id, d)
        daily_collector.delete_date_file(group_id, d - timedelta(days=1))
        logger.info("daily_summary: published for group %s (%s)", group_id, summary_date)
    except Exception:
        logger.warning(
            "daily_summary: publish failed for group %s (%s)", group_id, summary_date,
            exc_info=True,
        )


async def _job_publish_summaries() -> None:
    """12:00 scheduled job: publish all unpublished summaries."""
    if nonebot is None:
        return
    try:
        bot = nonebot.get_bot()
    except Exception:
        logger.warning("daily_summary: bot not available at publish time")
        return

    unpublished = daily_store.get_unpublished()
    if not unpublished:
        return

    # Only publish for groups that are still enabled
    enabled = set(daily_enabled_groups.all_groups())
    tasks = [
        _publish_one(bot, row)
        for row in unpublished
        if row["group_id"] in enabled
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


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
    _ensure_llm_bindings()
    svc = get_llm_service()
    if not scheduler:
        return
    daily_cfg = svc.config.daily_summary
    if not daily_cfg.enabled:
        return

    from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

    async def _wrapped_generate():
        try:
            await _job_generate_summaries()
            try:
                record_job_result("daily_summary_generate", True)
            except Exception:
                pass
        except Exception as exc:
            try:
                record_job_result("daily_summary_generate", False, str(exc)[:500])
            except Exception:
                pass
            raise

    async def _wrapped_publish():
        try:
            await _job_publish_summaries()
            try:
                record_job_result("daily_summary_publish", True)
            except Exception:
                pass
        except Exception as exc:
            try:
                record_job_result("daily_summary_publish", False, str(exc)[:500])
            except Exception:
                pass
            raise

    scheduler.add_job(
        _wrapped_generate,
        "cron",
        id="daily_summary_generate",
        replace_existing=True,
        **_parse_cron(daily_cfg.generate_cron),
    )
    scheduler.add_job(
        _wrapped_publish,
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

        _ensure_llm_bindings()
        svc = get_llm_service()

        group_id = event.group_id
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "summary").lower()

        # ── /summary on ──────────────────────────────────────────────
        if args in {"on", "开启", "启用"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            daily_enabled_groups.add(group_id)
            rule_switch.enable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            cfg = svc.config.daily_summary
            gen_time = _cron_to_hhmm(cfg.generate_cron)
            pub_time = _cron_to_hhmm(cfg.publish_cron)
            await summary_cmd.finish(
                f"本群每日总结已开启。将于每日 {gen_time} 生成、{pub_time} 发布。"
            )

        # ── /summary off ─────────────────────────────────────────────
        elif args in {"off", "关闭", "禁用"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            daily_enabled_groups.remove(group_id)
            rule_switch.disable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            await summary_cmd.finish("本群每日总结已关闭。")

        # ── /summary status ──────────────────────────────────────────
        elif args in {"status", "状态", ""}:
            is_on = daily_enabled_groups.contains(group_id)
            await summary_cmd.finish(f"本群每日总结：{'已开启 ✓' if is_on else '已关闭'}")

        # ── /summary now ─────────────────────────────────────────────
        # Window: [yesterday 06:00, now), regardless of trigger time.
        elif args in {"now", "立即", "生成"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            try:
                await send_daily_summary_now(group_id, before_generate=lambda: summary_cmd.send("正在生成总结，请稍候……"))
            except RuntimeError as exc:
                message = str(exc)
                if message == "daily summary is not enabled for this group":
                    await summary_cmd.finish("本群未开启每日总结，请先使用 /summary on 开启。")
                if message == "summary generation is on cooldown":
                    await summary_cmd.finish("操作过于频繁，请稍后再试（每分钟限一次）。")
                if message.startswith("not enough messages:"):
                    counts = message.removeprefix("not enough messages:").strip()
                    current, minimum = counts.split("/", 1)
                    await summary_cmd.finish(
                        f"当前窗口消息数不足（{current} 条，"
                        f"至少需要 {minimum} 条），无法生成总结。"
                    )
                if message == "summary generation skipped or failed":
                    await summary_cmd.finish("总结生成失败，请查看日志。")
                raise
            await summary_cmd.finish()

        # ── unknown subcommand ────────────────────────────────────────
        else:
            await summary_cmd.finish(
                "用法：/summary on|off|status|now\n"
                "  on     — 开启本群每日总结（管理员）\n"
                "  off    — 关闭本群每日总结（管理员）\n"
                "  now    — 立即生成前一天06:00至今的总结，不入库（管理员，每分钟限一次）\n"
                "  status — 查看当前状态"
            )


def setup(on_command) -> None:
    """Register scheduler jobs and commands. Call at plugin load time."""
    _register_scheduler_jobs()
    register_daily_summary_commands(on_command)
