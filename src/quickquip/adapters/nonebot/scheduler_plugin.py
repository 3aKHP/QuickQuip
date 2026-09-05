import logging
from datetime import datetime

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except (ModuleNotFoundError, ValueError):
    # 未安装插件或 NoneBot driver 尚未初始化（如测试环境）时优雅降级
    nonebot = None
    scheduler = None

try:
    # 与 scheduler 分开导入：onebot 适配器在 driver 未初始化时也可用（测试环境）
    from nonebot.adapters.onebot.v11 import Message, MessageSegment
except (ModuleNotFoundError, ValueError):
    Message = MessageSegment = None

try:
    from apscheduler.jobstores.base import JobLookupError
except ImportError:  # pragma: no cover - apscheduler 随 nonebot-plugin-apscheduler 安装
    class JobLookupError(Exception):
        pass

from quickquip.adapters.nonebot import cron_status_sync
from quickquip.adapters.nonebot._llm_reply import build_llm_reply_message
from quickquip.adapters.nonebot._safe_send import send_group_text
from quickquip.adapters.nonebot._scheduling import parse_cron
from quickquip.chat.scheduled_messages import ScheduledMessage, ScheduledMessageStore
from quickquip.common.bot_action_trace import bot_action_trace

logger = logging.getLogger(__name__)

# ── Job result tracking ──────────────────────────────────────────────────────

_job_run_results: dict[str, dict] = {}


def record_job_result(job_id: str, success: bool, error: str | None = None):
    """Record the last run result of a scheduled job. Best-effort only."""
    _job_run_results[job_id] = {
        "last_run": datetime.now().astimezone().isoformat(),
        "last_status": "ok" if success else "error",
        "last_error": error[:500] if error else None,
    }


def get_job_results() -> dict:
    """Return a shallow copy of all recorded job results."""
    return dict(_job_run_results)


# ── Job registration ─────────────────────────────────────────────────────────

_JOB_ID_PREFIX = "scheduled_msg_"
_LLM_RULE_NAME = "scheduled_message_llm"


def _build_llm_task_prompt(job: ScheduledMessage) -> str:
    """llm 类任务的信封式 prompt：合成 user 消息，标注这是定时触发。

    与 awakening 的【内部触发说明】信封同一模式；合成消息以 user 角色进入
    对话（参考 Claude Code Cron：定时触发的 prompt 入队为用户消息而非工具结果）。
    """
    return (
        "【内部触发说明】这是群友之前设置的定时任务，现在到点自动触发。"
        "请按照【任务指令】执行，以你平时在群里说话的语气自然地发出内容；"
        "不要在回复里提及这条说明本身。\n"
        f"【任务指令】{job.message}"
    )


async def _fire_llm_task(bot, job: ScheduledMessage, group_id: str, job_id: str) -> None:
    """llm 类任务单群触发：LLM 生成 → 安全外发（敏感词过滤在 generate_reply 内部）。"""
    from quickquip.app.message_pipeline import (
        _ensure_llm_bindings,
        get_llm_service,
        rule_switch,
    )
    from quickquip.chat.awakening import _is_group_llm_enabled

    if not rule_switch.is_enabled(group_id, _LLM_RULE_NAME):
        logger.info("scheduled_msg: llm job %s skipped in group %s (rule disabled)", job.id, group_id)
        return
    _ensure_llm_bindings()
    svc = get_llm_service()
    if not _is_group_llm_enabled(svc, group_id):
        logger.info("scheduled_msg: llm job %s skipped in group %s (group LLM disabled)", job.id, group_id)
        return

    result = await svc.generate_reply(
        group_id=group_id,
        user_id="scheduled_timer",
        sender_name="定时任务",
        prompt=_build_llm_task_prompt(job),
        image_urls=[],
        include_recent_images=True,
        # 合成配对行：落库结构化摘要（任务指令为管理端配置文本，同轮 prompt
        # 已过输入扫描），消除 history 里的 assistant 孤行；不抽记忆
        raw_user_text=f"【定时消息】按 {job.cron} 发送：{job.message[:60]}",
        store_user_message=True,
        trigger_auto_memory=False,
        message_id=None,
    )
    reply_text = str(result.get("reply") or "").strip()
    if not reply_text:
        return
    message = build_llm_reply_message(result, Message, MessageSegment)
    with bot_action_trace(
        trigger_kind="scheduled",
        reason_code="scheduled_message_llm",
        reason_detail=f"定时任务触发（LLM）：{job_id}",
        rule_name=_LLM_RULE_NAME,
        chat_type="group",
        group_id=group_id,
        reply_preview=reply_text[:100],
        source="scheduler.scheduled_message",
    ):
        await bot.send_group_msg(group_id=int(group_id), message=message)


async def _fire_text_task(bot, job: ScheduledMessage, group_id: str, job_id: str) -> None:
    """text 类任务单群触发：固定文案原样发出。"""
    with bot_action_trace(
        trigger_kind="scheduled",
        reason_code="scheduled_message",
        reason_detail=f"定时消息触发：{job_id}",
        rule_name="scheduled_message",
        chat_type="group",
        group_id=group_id,
        reply_preview=job.message,
        source="scheduler.scheduled_message",
    ):
        await send_group_text(bot, int(group_id), job.message)


def _make_send_task(job: ScheduledMessage, bot_getter, store: ScheduledMessageStore):
    job_id = f"{_JOB_ID_PREFIX}{job.id}"

    def _consume_one_shot() -> None:
        """一次性任务触发后自动删除（存储 + 调度器）。"""
        if job.recurring:
            return
        try:
            store.remove(job.id)
        except Exception:
            logger.warning("scheduled_msg: failed to remove one-shot job %s", job.id, exc_info=True)
        try:
            if scheduler:
                scheduler.remove_job(job_id)
        except JobLookupError:
            pass  # job 已不在调度器中（如 reload 先行清理），属正常
        except Exception:
            # 存储已删但调度器残留会导致下个 tick 重复触发，必须留下告警
            logger.warning(
                "scheduled_msg: failed to remove APScheduler job %s", job_id, exc_info=True
            )

    async def _send():
        fired = False
        try:
            try:
                bot = bot_getter()
            except Exception:
                logger.warning("scheduled_msg: bot not available, skipping")
                return
            for gid in job.group_ids:
                try:
                    if job.kind == "llm":
                        await _fire_llm_task(bot, job, gid, job_id)
                    else:
                        await _fire_text_task(bot, job, gid, job_id)
                except Exception:
                    logger.warning("scheduled_msg: failed to send to group %s", gid, exc_info=True)
            fired = True
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
        finally:
            # bot 不可用而跳过的不算触发，一次性任务保留到下次
            if fired:
                _consume_one_shot()

    return _send


def reload_scheduled_message_jobs(store: ScheduledMessageStore | None = None) -> int:
    """重读任务存储并重新注册所有定时消息 job，返回已注册数量。

    斜杠命令 / LLM 工具变更后直接调用（同进程即时生效）；
    Web Admin 写入后通过 ``scheduler_reload`` 管理动作间接触发。
    """
    if not scheduler:
        return 0
    store = store or ScheduledMessageStore()
    for existing in scheduler.get_jobs():
        if existing.id.startswith(_JOB_ID_PREFIX):
            scheduler.remove_job(existing.id)
    if nonebot is None:
        return 0
    bot_getter = nonebot.get_bot
    count = 0
    for job in store.list():
        if not job.enabled:
            continue
        try:
            cron_kwargs = parse_cron(job.cron, fallback_hour="0")
            scheduler.add_job(
                _make_send_task(job, bot_getter, store),
                "cron",
                id=f"{_JOB_ID_PREFIX}{job.id}",
                replace_existing=True,
                **cron_kwargs,
            )
            count += 1
        except Exception:
            logger.warning("scheduled_msg: failed to register job %s", job.id, exc_info=True)
    logger.info("scheduled_msg: %d job(s) registered", count)
    return count


reload_scheduled_message_jobs()


# ── Festival check ────────────────────────────────────────────────────────────


def _register_festival_job() -> None:
    if not scheduler:
        return
    if nonebot is None:
        return

    from quickquip.chat.festival import check_today_festival, get_festival_greeting
    from quickquip.app.message_pipeline import daily_enabled_groups

    bot_getter = nonebot.get_bot

    async def _check_and_greet() -> None:
        try:
            festival = check_today_festival()
            if festival is None:
                record_job_result("festival_check", True)
                return

            greeting = get_festival_greeting()
            if not greeting:
                record_job_result("festival_check", True)
                return

            try:
                bot = bot_getter()
            except Exception:
                logger.warning("festival_check: bot not available, skipping greeting")
                record_job_result("festival_check", False, "bot not available")
                return

            full_greeting = f"【{festival.name}】{greeting}"
            for gid in daily_enabled_groups.all_groups():
                try:
                    with bot_action_trace(
                        trigger_kind="scheduled",
                        reason_code="festival_greeting",
                        reason_detail=f"节日问候触发：{festival.name}",
                        rule_name="festival_greeting",
                        chat_type="group",
                        group_id=gid,
                        reply_preview=full_greeting,
                        source="scheduler.festival_greeting",
                    ):
                        await send_group_text(bot, int(gid), full_greeting)
                except Exception:
                    logger.warning(
                        "festival_check: failed to send greeting to group %s",
                        gid, exc_info=True,
                    )
            record_job_result("festival_check", True)
        except Exception as exc:
            try:
                record_job_result("festival_check", False, str(exc)[:500])
            except Exception:
                pass
            raise

    scheduler.add_job(
        _check_and_greet,
        "cron",
        id="festival_check",
        replace_existing=True,
        hour="1",
        minute="0",
    )
    logger.info("festival_check: job registered (daily at 01:00)")


_register_festival_job()


# 跨进程状态同步：bot 进程每 30 秒把调度器快照落盘，web-admin 定时任务页读文件。
# 重启恢复（#200）：落盘注册前把上次快照里的执行结果灌回内存表。
# - 必须原地更新：_job_run_results 的 dict 引用已被 sync 闭包捕获，rebind 会让
#   record_job_result 写新 dict 而 sync 仍序列化旧空 dict，恢复整体静默失效
# - 不按当前已注册 job 剪枝：模块加载时 daily_summary 等任务尚未注册，剪枝会
#   误删活任务记录；陈旧 id 由 sync 的 get_jobs() 驱动序列化在首 tick 自动清除
# - 门控在 scheduler 可用环境（bot 进程）执行：pytest / web 进程不读真实文件
if scheduler and nonebot is not None:
    for _restored_id, _restored_entry in cron_status_sync.load_job_results().items():
        _job_run_results[_restored_id] = _restored_entry
    if _job_run_results:
        logger.info("scheduler: restored last-run results for %d job(s)", len(_job_run_results))
    cron_status_sync.register_cron_status_sync(scheduler, _job_run_results)
