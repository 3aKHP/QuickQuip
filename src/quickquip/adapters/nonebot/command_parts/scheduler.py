from __future__ import annotations

import logging

from quickquip.adapters.nonebot.command_parts._chat_utils import _is_private_chat
from quickquip.chat.scheduled_messages import ScheduledMessageStore
from quickquip.common.event_utils import is_admin as _is_admin
from quickquip.common.event_utils import strip_command_name as _strip_command_name

logger = logging.getLogger(__name__)

scheduled_message_store = ScheduledMessageStore()

_MESSAGE_PREVIEW_LIMIT = 20

_USAGE = (
    "定时消息命令用法：\n"
    "/schedule list — 查看本群定时消息\n"
    "/schedule add [llm] [once] <cron 5段> <消息> — 添加定时消息\n"
    "  llm：内容为 LLM 任务指令；once：一次性任务（触发后自动删除）\n"
    "  cron 周字段 0=周一…6=周日（不支持 7）；按北京时间（Asia/Shanghai）触发\n"
    "  如 /schedule add 0 9 * * * 早安\n"
    "  如 /schedule add llm once 0 19 5 9 * 提醒大家今晚看KPL\n"
    "/schedule del <id> — 删除定时消息\n"
    "/schedule on <id> — 启用定时消息\n"
    "/schedule off <id> — 停用定时消息"
)


def _reload_jobs() -> None:
    """重注册定时消息 job，失败只记 log 不影响命令回复。"""
    try:
        from quickquip.adapters.nonebot.scheduler_plugin import reload_scheduled_message_jobs

        reload_scheduled_message_jobs(store=scheduled_message_store)
    except Exception:
        logger.warning("schedule: reload scheduled message jobs failed", exc_info=True)


def _message_preview(text: str) -> str:
    if len(text) <= _MESSAGE_PREVIEW_LIMIT:
        return text
    return text[:_MESSAGE_PREVIEW_LIMIT] + "…"


def _parse_add_flags(rest: str) -> tuple[str, bool, str]:
    """剥离 add 的可选前导标记（llm / once，顺序任意），返回 (kind, recurring, 剩余文本)。"""
    kind = "text"
    recurring = True
    while True:
        head, _, tail = rest.partition(" ")
        flag = head.lower()
        if flag == "llm":
            kind = "llm"
        elif flag == "once":
            recurring = False
        else:
            break
        rest = tail.strip()
    return kind, recurring, rest


def register_scheduler_commands(on_command, Message, MessageSegment) -> None:
    schedule_cmd = on_command("schedule", aliases={"定时"}, priority=10, block=True)

    @schedule_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await schedule_cmd.finish("私聊不支持 /schedule")
        if not _is_admin(event):
            await schedule_cmd.finish("仅管理员可执行此操作")
        group_id = str(event.group_id)
        text = str(event.get_message()).strip()
        args = _strip_command_name(_strip_command_name(text, "schedule"), "定时").strip()
        tokens = args.split()
        sub = tokens[0].lower() if tokens else ""

        if sub == "list":
            jobs = [j for j in scheduled_message_store.list() if group_id in j.group_ids]
            if not jobs:
                await schedule_cmd.finish("本群暂无定时消息")
            lines = ["本群定时消息："]
            for job in jobs:
                status = "启用" if job.enabled else "停用"
                tags = f"[{status}]"
                if job.kind == "llm":
                    tags += " [LLM]"
                if not job.recurring:
                    tags += " [一次性]"
                lines.append(f"- {job.id} {tags} {job.cron}：{_message_preview(job.message)}")
            await schedule_cmd.finish("\n".join(lines))

        if sub == "add":
            parts1 = args.split(maxsplit=1)
            rest = parts1[1].strip() if len(parts1) > 1 else ""
            kind, recurring, rest = _parse_add_flags(rest)
            parts = rest.split(maxsplit=5)
            if len(parts) < 6:
                await schedule_cmd.finish("用法：/schedule add [llm] [once] <cron 5段> <消息>，例如 /schedule add 0 9 * * * 早安")
            cron = " ".join(parts[:5])
            message = parts[5]
            try:
                job = scheduled_message_store.add(
                    cron=cron,
                    group_ids=[group_id],
                    message=message,
                    origin="command",
                    kind=kind,
                    recurring=recurring,
                )
            except ValueError as exc:
                await schedule_cmd.finish(str(exc))
            _reload_jobs()
            await schedule_cmd.finish(f"已添加定时消息：{job.id}\ncron：{job.cron}")

        if sub in ("del", "on", "off"):
            job_id = tokens[1] if len(tokens) > 1 else ""
            if not job_id:
                await schedule_cmd.finish(f"用法：/schedule {sub} <id>")
            job = scheduled_message_store.get(job_id)
            if job is None or group_id not in job.group_ids:
                await schedule_cmd.finish(f"未找到属于本群的任务：{job_id}")

            if sub == "del":
                scheduled_message_store.remove(job_id)
                _reload_jobs()
                await schedule_cmd.finish(f"已删除定时消息：{job_id}")

            enabled = sub == "on"
            if job.enabled == enabled:
                status = "启用" if enabled else "停用"
                await schedule_cmd.finish(f"任务 {job_id} 已是{status}状态")
            scheduled_message_store.set_enabled(job_id, enabled)
            _reload_jobs()
            action = "启用" if enabled else "停用"
            await schedule_cmd.finish(f"已{action}定时消息：{job_id}")

        await schedule_cmd.finish(_USAGE)
