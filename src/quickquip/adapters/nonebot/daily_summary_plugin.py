from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
    wordcloud_collector,
    weekly_enabled_groups,
    monthly_enabled_groups,
    period_store,
)
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.chat import summary_jobs
from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.period_report import (
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    compute_period_window,
)
from quickquip.adapters.nonebot._scheduling import (
    cron_to_hhmm,
    mark_triggered,
    on_cooldown,
    parse_cron,
)
from quickquip.adapters.nonebot.long_messages import send_long_group_message
from quickquip.common.bot_action_trace import bot_action_trace

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
_RULE_NAME = "daily_summary"

# Per-group manual trigger cooldown: group_id -> last trigger timestamp.
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
    return on_cooldown(_last_manual_trigger, group_id)


def _mark_triggered(group_id: int | str) -> None:
    mark_triggered(_last_manual_trigger, group_id)


# 周报/月报手动触发冷却：独立于每日总结，避免同群两类"立即生成"互相阻挡。
_last_period_manual_trigger: dict[str, float] = {}


def _on_period_cooldown(group_id: int | str) -> bool:
    return on_cooldown(_last_period_manual_trigger, group_id)


def _mark_period_triggered(group_id: int | str) -> None:
    mark_triggered(_last_period_manual_trigger, group_id)


class DailySummaryNotEnabledError(RuntimeError):
    """群未开启每日总结。"""


class DailySummaryCooldownError(RuntimeError):
    """命令触发过于频繁（冷却中）。"""


class DailySummaryInsufficientMessagesError(RuntimeError):
    """窗口内消息数不足，无法生成每日总结。携带 current/minimum 供调用方渲染文案。"""

    def __init__(self, current: int, minimum: int) -> None:
        self.current = current
        self.minimum = minimum
        super().__init__(f"not enough messages: {current}/{minimum}")


class DailySummaryGenerationFailedError(RuntimeError):
    """每日总结生成失败或被跳过（LLM 失败、persona 缺失等）。"""


async def send_daily_summary_now(group_id: int | str, bot=None, before_generate=None) -> dict[str, object]:
    group_key = str(group_id)
    if not daily_enabled_groups.contains(group_key):
        raise DailySummaryNotEnabledError("daily summary is not enabled for this group")
    if _on_cooldown(group_key):
        raise DailySummaryCooldownError("summary generation is on cooldown")

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
        raise DailySummaryInsufficientMessagesError(len(messages), min_messages)
    result = await summary_jobs.run_summary_generation(
        group_key, start_dt.timestamp(), now.timestamp(), date_label,
        svc=svc, collector=daily_collector, stats_tracker=stats_tracker,
    )
    if result is None:
        raise DailySummaryGenerationFailedError("summary generation skipped or failed")

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
    _ensure_llm_bindings()
    await summary_jobs.generate_summaries_job(
        svc=get_llm_service(),
        collector=daily_collector,
        store=daily_store,
        enabled_groups=daily_enabled_groups,
        stats_tracker=stats_tracker,
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

    async def _send(row: dict) -> None:
        group_id = row["group_id"]
        with bot_action_trace(
            trigger_kind="scheduled",
            reason_code="daily_summary.publish",
            reason_detail=f"定时发布每日总结：{row['summary_date']}",
            rule_name=_RULE_NAME,
            chat_type="group",
            group_id=group_id,
            reply_preview=row["content"],
            llm_used=str(row.get("model_used", "")) != "fallback",
            model=str(row.get("model_used", "")),
            source="daily_summary.scheduled_publish",
        ):
            await _send_long_message(bot, int(group_id), row["content"])

    await summary_jobs.publish_summaries_job(
        store=daily_store,
        collector=daily_collector,
        enabled_groups=daily_enabled_groups,
        send=_send,
    )


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
        name="daily_summary_generate",
        replace_existing=True,
        **parse_cron(daily_cfg.generate_cron, fallback_hour="6"),
    )
    scheduler.add_job(
        _wrapped_publish,
        "cron",
        id="daily_summary_publish",
        name="daily_summary_publish",
        replace_existing=True,
        **parse_cron(daily_cfg.publish_cron, fallback_hour="6"),
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

        # ── /summary weekly|monthly ... 子命令分发 ──────────────────
        # 周期报告子命令独立解析，不与日报 on/off/status/now 冲突。
        if args.split(None, 1)[:1] and args.split(None, 1)[0] in {"weekly", "monthly", "周报", "月报"}:
            handled = await _handle_period_subcommand(args, group_id, summary_cmd, event)
            if handled:
                return

        # ── /summary on ──────────────────────────────────────────────
        if args in {"on", "开启", "启用"}:
            if not _is_admin(event):
                await summary_cmd.finish("仅管理员可执行此操作")
            daily_enabled_groups.add(group_id)
            rule_switch.enable(group_id, _RULE_NAME)
            rule_switch.save(RULE_SWITCH_PATH)
            cfg = svc.config.daily_summary
            gen_time = cron_to_hhmm(cfg.generate_cron)
            pub_time = cron_to_hhmm(cfg.publish_cron)
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
            except DailySummaryNotEnabledError:
                await summary_cmd.finish("本群未开启每日总结，请先使用 /summary on 开启。")
            except DailySummaryCooldownError:
                await summary_cmd.finish("操作过于频繁，请稍后再试（每分钟限一次）。")
            except DailySummaryInsufficientMessagesError as exc:
                await summary_cmd.finish(
                    f"当前窗口消息数不足（{exc.current} 条，"
                    f"至少需要 {exc.minimum} 条），无法生成总结。"
                )
            except DailySummaryGenerationFailedError:
                await summary_cmd.finish("总结生成失败，请查看日志。")
            await summary_cmd.finish()

        # ── unknown subcommand ────────────────────────────────────────
        else:
            await summary_cmd.finish(
                "用法：/summary [on|off|status|now|weekly ...|monthly ...]\n"
                "  on     — 开启本群每日总结（管理员）\n"
                "  off    — 关闭本群每日总结（管理员）\n"
                "  now    — 立即生成前一天06:00至今的总结，不入库（管理员，每分钟限一次）\n"
                "  status — 查看当前状态\n"
                "  weekly  on|off|status|now — 群周报（每周一自动生成上周回顾）\n"
                "  monthly on|off|status|now — 群月报（每月1日自动生成上月回顾）"
            )


def setup(on_command) -> None:
    """Register scheduler jobs and commands. Call at plugin load time."""
    _register_scheduler_jobs()
    _register_period_jobs()
    register_daily_summary_commands(on_command)


# ── 群周报 / 群月报 ──────────────────────────────────────────────────────
# 数据源复用 wordcloud_collector（always-on），分天采样后调 generate_period_report。
# 与日报共享 LLM 级联校验骨架，但 prompt、period 标识、消息格式化（带日期前缀）独立。

_PERIOD_RULE_NAMES = {"weekly": "weekly_report", "monthly": "monthly_report"}


def _period_enabled_groups(period_type: str):
    """按 period_type 返回对应的 enabled groups 实例（duck-typed，具备 add/remove/contains/all_groups）。"""
    if period_type == PERIOD_WEEKLY:
        return weekly_enabled_groups
    if period_type == PERIOD_MONTHLY:
        return monthly_enabled_groups
    raise ValueError(f"未知 period_type: {period_type!r}")


async def _job_generate_period_reports(period_type: str) -> None:
    """定时生成 job：为所有启用群生成上一个完整周期的周期报告。"""
    _ensure_llm_bindings()
    await summary_jobs.generate_period_reports_job(
        period_type,
        svc=get_llm_service(),
        collector=wordcloud_collector,
        store=period_store,
        enabled_groups=_period_enabled_groups(period_type),
        stats_tracker=stats_tracker,
    )


async def _job_publish_period_reports(period_type: str) -> None:
    """定时发布 job：把所有未发布的周期报告发出去。"""
    if nonebot is None:
        return
    try:
        bot = nonebot.get_bot()
    except Exception:
        logger.warning("period_report[%s]: bot not available at publish time", period_type)
        return

    node_name = "群周报" if period_type == PERIOD_WEEKLY else "群月报"

    async def _send(row: dict) -> None:
        group_id = row["group_id"]
        with bot_action_trace(
            trigger_kind="scheduled",
            reason_code=f"period_report.publish.{period_type}",
            reason_detail=f"定时发布{node_name}：{row['period_key']}",
            rule_name=_PERIOD_RULE_NAMES[period_type],
            chat_type="group",
            group_id=group_id,
            reply_preview=row["content"],
            llm_used=str(row.get("model_used", "")) != "fallback",
            model=str(row.get("model_used", "")),
            source=f"period_report.scheduled_publish.{period_type}",
        ):
            await send_long_group_message(
                bot, int(group_id), row["content"],
                node_name=node_name,
                log_name=f"period_report_{period_type}",
            )

    await summary_jobs.publish_period_reports_job(
        period_type,
        store=period_store,
        enabled_groups=_period_enabled_groups(period_type),
        send=_send,
    )


def _register_period_jobs() -> None:
    """注册周报/月报的生成与发布 job。各自独立 enabled 开关。"""
    if not scheduler:
        return
    _ensure_llm_bindings()
    svc = get_llm_service()
    from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

    def _make_wrapped(job_id: str, coro_factory):
        async def _wrapped():
            try:
                await coro_factory()
                try:
                    record_job_result(job_id, True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result(job_id, False, str(exc)[:500])
                except Exception:
                    pass
                raise
        return _wrapped

    for period_type, cfg in (
        (PERIOD_WEEKLY, svc.config.weekly_report),
        (PERIOD_MONTHLY, svc.config.monthly_report),
    ):
        if not cfg.enabled:
            continue
        gen_id = f"{period_type}_report_generate"
        pub_id = f"{period_type}_report_publish"
        scheduler.add_job(
            _make_wrapped(gen_id, lambda pt=period_type: _job_generate_period_reports(pt)),
            "cron", id=gen_id, name=gen_id, replace_existing=True, **parse_cron(cfg.generate_cron, fallback_hour="6"),
        )
        scheduler.add_job(
            _make_wrapped(pub_id, lambda pt=period_type: _job_publish_period_reports(pt)),
            "cron", id=pub_id, name=pub_id, replace_existing=True, **parse_cron(cfg.publish_cron, fallback_hour="6"),
        )
        logger.info(
            "period_report[%s]: jobs registered (generate=%s, publish=%s)",
            period_type, cfg.generate_cron, cfg.publish_cron,
        )


class PeriodReportNotEnabledError(RuntimeError):
    """群未开启该周期报告。"""


class PeriodReportCooldownError(RuntimeError):
    """命令触发过于频繁（冷却中）。"""


class PeriodReportGenerationFailedError(RuntimeError):
    """周期报告生成失败或被跳过（消息不足、LLM 失败等）。"""


async def send_period_report_now(
    group_id: int | str, period_type: str, bot=None, before_generate=None
) -> dict[str, object]:
    """命令触发的立即生成 + 发送（不入库）。"""
    group_key = str(group_id)
    enabled = _period_enabled_groups(period_type)
    if not enabled.contains(group_key):
        raise PeriodReportNotEnabledError(f"{period_type} report is not enabled for this group")
    if _on_period_cooldown(group_key):
        raise PeriodReportCooldownError("generation is on cooldown")
    _mark_period_triggered(group_key)

    if before_generate is not None:
        await before_generate()

    now = datetime.now(tz=_LOCAL_TZ)
    start_ts, end_ts, _, period_label = compute_period_window(period_type, now)
    _ensure_llm_bindings()
    result = await summary_jobs.run_period_generation(
        group_key, period_type, start_ts, end_ts, period_label,
        svc=get_llm_service(), collector=wordcloud_collector, stats_tracker=stats_tracker,
    )
    if result is None:
        raise PeriodReportGenerationFailedError("period report generation skipped or failed")

    content, model_used = result
    if bot is None:
        if nonebot is None:
            raise RuntimeError("bot runtime is not available")
        bot = nonebot.get_bot()
    node_name = "群周报" if period_type == PERIOD_WEEKLY else "群月报"
    with bot_action_trace(
        trigger_kind="command",
        reason_code=f"command.summary.{period_type}.now",
        reason_detail=f"命令触发：立即生成并发送{node_name}",
        rule_name=_PERIOD_RULE_NAMES[period_type],
        chat_type="group",
        group_id=group_key,
        reply_preview=content,
        llm_used=model_used != "fallback",
        model=model_used,
        source=f"period_report.manual.{period_type}",
    ):
        await send_long_group_message(
            bot, int(group_key), content,
            node_name=node_name,
            log_name=f"period_report_{period_type}",
        )
    return {"model_used": model_used, "char_count": len(content)}


async def _handle_period_subcommand(
    args: str, group_id, summary_cmd, event,
) -> bool:
    """处理 /summary weekly|monthly 子命令。返回 True 表示已处理（调用方应 return）。"""
    parts = args.split(None, 1)
    if not parts:
        return False
    head = parts[0]
    if head not in {"weekly", "monthly", "周报", "月报"}:
        return False

    period_type = PERIOD_WEEKLY if head in {"weekly", "周报"} else PERIOD_MONTHLY
    kind_word = "周报" if period_type == PERIOD_WEEKLY else "月报"
    sub = parts[1].strip() if len(parts) > 1 else ""
    enabled = _period_enabled_groups(period_type)
    _ensure_llm_bindings()
    svc = get_llm_service()

    if sub in {"on", "开启", "启用"}:
        if not _is_admin(event):
            await summary_cmd.finish("仅管理员可执行此操作")
        enabled.add(group_id)
        cfg = svc.config.weekly_report if period_type == PERIOD_WEEKLY else svc.config.monthly_report
        gen_time = cron_to_hhmm(cfg.generate_cron)
        pub_time = cron_to_hhmm(cfg.publish_cron)
        await summary_cmd.finish(f"本群{kind_word}已开启。将于每周期 {gen_time} 生成，每天 {pub_time} 发布（未发布的报告会自动补发）。")
        return True

    if sub in {"off", "关闭", "禁用"}:
        if not _is_admin(event):
            await summary_cmd.finish("仅管理员可执行此操作")
        enabled.remove(group_id)
        await summary_cmd.finish(f"本群{kind_word}已关闭。")
        return True

    if sub in {"status", "状态", ""}:
        is_on = enabled.contains(group_id)
        await summary_cmd.finish(f"本群{kind_word}：{'已开启 ✓' if is_on else '已关闭'}")
        return True

    if sub in {"now", "立即", "生成"}:
        if not _is_admin(event):
            await summary_cmd.finish("仅管理员可执行此操作")
        try:
            await send_period_report_now(
                group_id, period_type,
                before_generate=lambda: summary_cmd.send(f"正在生成{kind_word}，请稍候……"),
            )
        except PeriodReportNotEnabledError:
            await summary_cmd.finish(f"本群未开启{kind_word}，请先使用 /summary {head} on 开启。")
        except PeriodReportCooldownError:
            await summary_cmd.finish("操作过于频繁，请稍后再试（每分钟限一次）。")
        except PeriodReportGenerationFailedError:
            await summary_cmd.finish(f"{kind_word}生成失败，请查看日志。")
        await summary_cmd.finish()
        return True

    await summary_cmd.finish(
        f"用法：/summary {head} on|off|status|now\n"
        f"  on     — 开启本群{kind_word}（管理员）\n"
        f"  off    — 关闭本群{kind_word}（管理员）\n"
        f"  now    — 立即生成上一周期的{kind_word}并发送（管理员，每分钟限一次）\n"
        f"  status — 查看当前状态"
    )
    return True
