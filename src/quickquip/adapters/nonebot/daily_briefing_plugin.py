from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except (ModuleNotFoundError, ValueError):
    nonebot = None
    scheduler = None

from quickquip.app.message_pipeline import (
    RULE_SWITCH_PATH,
    daily_briefing_enabled_groups,
    _ensure_llm_bindings,
    get_llm_service,
    daily_collector,
    rule_switch,
    wordcloud_collector,
)
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.adapters.nonebot._safe_send import send_group_text
from quickquip.adapters.nonebot._scheduling import (
    cron_to_hhmm,
    mark_triggered,
    on_cooldown,
    parse_cron,
)
from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.chat.daily_briefing import (
    BriefingPeriod,
    NullBriefingNewsProvider,
    build_briefing_context,
    build_fallback_briefing,
    default_period_for_now,
    normalize_period,
)
from quickquip.llm.briefing import generate_daily_briefing

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
_RULE_NAME = "daily_briefing"
_NEWS_PROVIDER = NullBriefingNewsProvider()
_PERIOD_LABELS = {"morning": "早报", "noon": "午报", "evening": "晚报"}
_last_manual_trigger: dict[str, float] = {}


def _on_cooldown(group_id: int | str) -> bool:
    return on_cooldown(_last_manual_trigger, group_id)


def _mark_triggered(group_id: int | str) -> None:
    mark_triggered(_last_manual_trigger, group_id)


def _is_group_enabled(group_id: int | str) -> bool:
    return (
        daily_briefing_enabled_groups.contains(group_id)
        and rule_switch.is_enabled(group_id, _RULE_NAME)
    )


async def _render_briefing(group_id: str, period: BriefingPeriod) -> tuple[str, str]:
    _ensure_llm_bindings()
    svc = get_llm_service()
    now = datetime.now(tz=_LOCAL_TZ)
    briefing_cfg = svc.config.daily_briefing
    context = await build_briefing_context(
        group_id=group_id,
        period=period,
        now=now,
        daily_collector=daily_collector,
        wordcloud_collector=wordcloud_collector,
        briefing_config=briefing_cfg,
        news_provider=_NEWS_PROVIDER,
    )
    fallback_text = build_fallback_briefing(context)

    if svc.config.load_error:
        return fallback_text, "fallback"

    settings = svc.get_group_settings(group_id)
    persona = svc.config.personas.get(settings.persona_id) or next(
        iter(svc.config.personas.values()),
        None,
    )
    if persona is None:
        return fallback_text, "fallback"

    if context.message_count < briefing_cfg.min_messages_for_llm:
        return fallback_text, "fallback"

    try:
        content, model_used = await generate_daily_briefing(
            context=context,
            persona=persona,
            group_id=group_id,
            briefing_config=briefing_cfg,
            llm_config=svc.config,
            default_provider_id=settings.provider_id,
            default_model=settings.model,
        )
        return content, model_used
    except Exception:
        logger.exception("daily_briefing: generation failed for group %s (%s)", group_id, period)
        return fallback_text, "fallback"


async def _send_one(bot, group_id: str, period: str) -> None:
    if not rule_switch.is_enabled(group_id, _RULE_NAME):
        return
    content, model_used = await _render_briefing(group_id, period)
    try:
        with bot_action_trace(
            trigger_kind="scheduled",
            reason_code=f"daily_briefing.{period}",
            reason_detail=f"定时发送每日播报：{period}",
            rule_name=_RULE_NAME,
            chat_type="group",
            group_id=group_id,
            reply_preview=content,
            llm_used=model_used != "fallback",
            model=model_used,
            source="daily_briefing.scheduled",
        ):
            await send_group_text(bot, int(group_id), content)
        logger.info(
            "daily_briefing: sent to group %s (%s via %s)",
            group_id,
            period,
            model_used,
        )
    except Exception:
        logger.warning(
            "daily_briefing: send failed for group %s (%s)",
            group_id,
            period,
            exc_info=True,
        )


async def send_daily_briefing_now(
    group_id: int | str,
    period: BriefingPeriod | None = None,
    bot=None,
    before_generate=None,
) -> dict[str, object]:
    group_key = str(group_id)
    if period is not None:
        normalized_period = normalize_period(period)
        if normalized_period is None:
            raise ValueError("period must be morning, noon, or evening")
        period = normalized_period
    if not _is_group_enabled(group_key):
        raise RuntimeError("daily briefing is not enabled for this group")
    if _on_cooldown(group_key):
        raise RuntimeError("briefing generation is on cooldown")

    _mark_triggered(group_key)
    selected_period = period or default_period_for_now(datetime.now(tz=_LOCAL_TZ))
    if bot is None:
        if nonebot is None:
            raise RuntimeError("bot runtime is not available")
        bot = nonebot.get_bot()
    if before_generate is not None:
        await before_generate(selected_period)
    content, model_used = await _render_briefing(group_key, selected_period)
    with bot_action_trace(
        trigger_kind="command",
        reason_code=f"command.briefing.now.{selected_period}",
        reason_detail=f"命令触发：立即发送每日播报 {selected_period}",
        rule_name=_RULE_NAME,
        chat_type="group",
        group_id=group_key,
        reply_preview=content,
        llm_used=model_used != "fallback",
        model=model_used,
        source="daily_briefing.manual",
    ):
        await send_group_text(bot, int(group_key), content)
    return {"period": selected_period, "model_used": model_used, "char_count": len(content)}


async def _job_send_period(period: str) -> None:
    if nonebot is None:
        return
    try:
        bot = nonebot.get_bot()
    except Exception:
        logger.warning("daily_briefing: bot not available at %s time", period)
        return

    enabled_groups = [
        gid
        for gid in daily_briefing_enabled_groups.all_groups()
        if rule_switch.is_enabled(gid, _RULE_NAME)
    ]
    if not enabled_groups:
        return

    tasks = [_send_one(bot, gid, period) for gid in enabled_groups]
    await asyncio.gather(*tasks, return_exceptions=True)


def _register_scheduler_jobs() -> None:
    _ensure_llm_bindings()
    svc = get_llm_service()
    if not scheduler:
        return
    cfg = svc.config.daily_briefing
    if not cfg.enabled:
        return

    from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

    periods = ["morning", "noon", "evening"]
    for period in periods:
        job_id = f"daily_briefing_{period}"

        async def _wrapped_send(p=period, jid=job_id):
            try:
                await _job_send_period(p)
                try:
                    record_job_result(jid, True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result(jid, False, str(exc)[:500])
                except Exception:
                    pass
                raise

        scheduler.add_job(
            _wrapped_send,
            "cron",
            id=job_id,
            name=job_id,
            replace_existing=True,
            **parse_cron(getattr(cfg, f"{period}_cron"), fallback_hour="8"),
        )
    logger.info(
        "daily_briefing: jobs registered (morning=%s, noon=%s, evening=%s)",
        cfg.morning_cron,
        cfg.noon_cron,
        cfg.evening_cron,
    )


def register_daily_briefing_commands(on_command) -> None:
    briefing_cmd = on_command("briefing", priority=10, block=True)

    @briefing_cmd.handle()
    async def _(event):
        if getattr(event, "group_id", None) is None:
            await briefing_cmd.finish("该命令仅支持群聊")

        _ensure_llm_bindings()
        svc = get_llm_service()

        group_id = event.group_id
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "briefing").strip()
        tokens = [item for item in args.split() if item]
        action = tokens[0].lower() if tokens else "status"
        cfg = svc.config.daily_briefing

        if action in {"on", "开启", "启用"}:
            if not _is_admin(event):
                await briefing_cmd.finish("仅管理员可执行此操作")
            if not cfg.enabled:
                await briefing_cmd.finish(
                    "每日播报全局未开启，请先在 config/llm.toml 的 [daily_briefing] 中设置 enabled = true。"
                )
            daily_briefing_enabled_groups.add(group_id)
            rule_switch.enable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            await briefing_cmd.finish(
                "本群每日播报已开启。"
                f" 早报 { cron_to_hhmm(cfg.morning_cron) }，"
                f" 午报 { cron_to_hhmm(cfg.noon_cron) }，"
                f" 晚报 { cron_to_hhmm(cfg.evening_cron) }。"
            )

        if action in {"off", "关闭", "禁用"}:
            if not _is_admin(event):
                await briefing_cmd.finish("仅管理员可执行此操作")
            daily_briefing_enabled_groups.remove(group_id)
            rule_switch.disable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            await briefing_cmd.finish("本群每日播报已关闭。")

        if action in {"status", "状态", ""}:
            enabled = _is_group_enabled(group_id)
            await briefing_cmd.finish(
                "每日播报状态\n"
                f"全局开关：{'ON' if cfg.enabled else 'OFF'}\n"
                f"本群开关：{'已开启 ✓' if enabled else '已关闭'}\n"
                f"早报：{cron_to_hhmm(cfg.morning_cron)}\n"
                f"午报：{cron_to_hhmm(cfg.noon_cron)}\n"
                f"晚报：{cron_to_hhmm(cfg.evening_cron)}"
            )

        if action in {"now", "立即", "测试"}:
            if not _is_admin(event):
                await briefing_cmd.finish("仅管理员可执行此操作")
            period = normalize_period(tokens[1]) if len(tokens) >= 2 else None
            if period is None:
                period = default_period_for_now(datetime.now(tz=_LOCAL_TZ))
            try:
                await send_daily_briefing_now(
                    group_id,
                    period,
                    before_generate=lambda selected_period: briefing_cmd.send(f"正在生成{_PERIOD_LABELS[selected_period]}，请稍候……"),
                )
            except RuntimeError as exc:
                message = str(exc)
                if message == "daily briefing is not enabled for this group":
                    await briefing_cmd.finish("本群未开启每日播报，请先使用 /briefing on 开启。")
                if message == "briefing generation is on cooldown":
                    await briefing_cmd.finish("操作过于频繁，请稍后再试（每分钟限一次）。")
                raise
            await briefing_cmd.finish()

        await briefing_cmd.finish(
            "用法：/briefing on|off|status|now [morning|noon|evening]\n"
            "  on     — 开启本群每日播报（管理员）\n"
            "  off    — 关闭本群每日播报（管理员）\n"
            "  now    — 立即测试一条播报，默认按当前时段（管理员，每分钟限一次）\n"
            "  status — 查看当前状态"
        )


def setup(on_command) -> None:
    _register_scheduler_jobs()
    register_daily_briefing_commands(on_command)
