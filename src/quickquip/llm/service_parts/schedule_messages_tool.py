"""manage_scheduled_messages 工具：LLM 管理当前群的定时消息任务。

从 tools.py 拆出的独立 mixin——后者已超文件长度预警线，新工具不再堆入。
MRO 契约：本 mixin 只依赖宿主（LLMService）的 ``tool_registry`` 属性。
"""

from __future__ import annotations

import logging

from quickquip.chat.scheduled_messages import ScheduledMessage, ScheduledMessageStore
from quickquip.llm.tools import LLMToolSpec, ToolExecutionContext

logger = logging.getLogger(__name__)

SCHEDULE_MESSAGES_TOOL_NAME = "manage_scheduled_messages"

_ACTIONS = ("list", "create", "set_enabled", "delete")

SCHEDULE_MESSAGES_TOOL_SPEC = LLMToolSpec(
    name=SCHEDULE_MESSAGES_TOOL_NAME,
    description=(
        "管理当前群的定时消息任务（创建后机器人会按 cron 周期自动在群里发消息）。"
        "cron 为 5 段式：分 时 日 月 周，按北京时间（Asia/Shanghai）执行，"
        "周字段 0=周一…6=周日（不支持 7），"
        "例如 \"0 9 * * *\" 表示每天 09:00。"
        "任务有两种 kind：\"text\" 为固定文案，到点原样发送 message；"
        "\"llm\" 为任务指令，到点把 message 作为指令交给你生成内容后发群——"
        "提醒某人做某事、或需要结合群聊动态生成的内容应使用 llm 类。"
        "创建一次性任务（如\"今晚七点提醒我\"）时设 recurring=false，"
        "并把 cron 的分/时/日/月钉到具体日期值（周字段用 *），"
        "当轮用户消息开头的【轮次上下文】中提供了当前北京时间与星期，请据此推算日/月字段；"
        "一次性任务触发后会自动删除。"
        "操作前请先用 action=\"list\" 查看当前群已有任务；"
        "set_enabled / delete 需要先从 list 结果中取得任务 id（job_id）。"
        "任务只作用于当前群，不能跨群操作。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "list 列出任务 / create 创建 / set_enabled 启停 / delete 删除",
            },
            "cron": {
                "type": "string",
                "description": "5 段 cron 表达式（分 时 日 月 周），action=create 时必填",
            },
            "message": {
                "type": "string",
                "description": "定时发送的内容（text 类为固定文案，llm 类为任务指令），action=create 时必填",
            },
            "kind": {
                "type": "string",
                "enum": ["text", "llm"],
                "description": "任务类型：text 固定文案（默认）/ llm 任务指令，action=create 时可选",
            },
            "recurring": {
                "type": "boolean",
                "description": "是否周期重复（默认 true）；false 为一次性任务，触发后自动删除，action=create 时可选",
            },
            "enabled": {
                "type": "boolean",
                "description": "action=create 时的初始启用状态（默认 true）；action=set_enabled 时的目标状态",
            },
            "job_id": {
                "type": "string",
                "description": "任务 id，action=set_enabled / delete 时必填",
            },
        },
        "required": ["action"],
    },
)


def _format_job_summary(job: ScheduledMessage) -> str:
    """单行任务摘要：id（状态，类型，周期标记，cron）：内容。"""
    state = "启用" if job.enabled else "停用"
    kind_label = "LLM 任务" if job.kind == "llm" else "固定文案"
    recurrence = "周期" if job.recurring else "一次性"
    return f"{job.id}（{state}，{kind_label}，{recurrence}，cron：{job.cron}）：{job.message}"


def _reload_scheduled_message_jobs() -> None:
    """变更后重注册调度任务；失败只记日志，不影响工具结果。

    必须 lazy import：LLM service 模块不能在 import 时依赖 nonebot 适配层。
    """
    try:
        from quickquip.adapters.nonebot.scheduler_plugin import (
            reload_scheduled_message_jobs,
        )

        reload_scheduled_message_jobs()
    except Exception:
        logger.warning("manage_scheduled_messages: 重注册定时任务失败", exc_info=True)


class ScheduleMessagesToolMixin:
    def register_schedule_messages_tool(self) -> None:
        self.tool_registry.register(
            SCHEDULE_MESSAGES_TOOL_SPEC,
            self._tool_manage_scheduled_messages,
            category="schedule",
            keywords=["定时", "提醒", "每天", "闹钟", "定时消息", "schedule", "cron"],
        )

    async def _tool_manage_scheduled_messages(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> str:
        if context.chat_type != "group":
            return "该工具仅支持群聊。"
        action = str(arguments.get("action", "")).strip()
        group_id = str(context.group_id)
        store = ScheduledMessageStore()

        if action == "list":
            jobs = [job for job in store.list() if group_id in job.group_ids]
            if not jobs:
                return "当前群没有定时消息任务。"
            lines = ["当前群定时消息任务："]
            for job in jobs:
                lines.append(f"- {_format_job_summary(job)}")
            return "\n".join(lines)

        if action == "create":
            cron = str(arguments.get("cron", "")).strip()
            message = str(arguments.get("message", "")).strip()
            if not cron or not message:
                return "create 需要提供 cron 和 message。"
            enabled = bool(arguments.get("enabled", True))
            # 未知 kind 值由 store.add 归一为 "text"（与存储层容错风格一致）
            kind = str(arguments.get("kind", "text")).strip() or "text"
            recurring = bool(arguments.get("recurring", True))
            try:
                job = store.add(
                    cron=cron,
                    group_ids=[group_id],
                    message=message,
                    enabled=enabled,
                    origin="llm",
                    kind=kind,
                    recurring=recurring,
                )
            except ValueError as exc:
                return f"创建定时消息失败：{exc}"
            _reload_scheduled_message_jobs()
            return f"已创建定时消息任务 {_format_job_summary(job)}"

        if action in ("set_enabled", "delete"):
            job_id = str(arguments.get("job_id", "")).strip()
            if not job_id:
                return f"{action} 需要提供 job_id。"
            job = store.get(job_id)
            if job is None or group_id not in job.group_ids:
                return f"当前群不存在定时消息任务 {job_id}。"
            if action == "set_enabled":
                enabled = arguments.get("enabled")
                if enabled is None:
                    return "set_enabled 需要提供 enabled 布尔值（true 启用 / false 停用）。"
                store.set_enabled(job_id, bool(enabled))
                _reload_scheduled_message_jobs()
                state = "启用" if enabled else "停用"
                return f"已将定时消息任务 {job_id} {state}。"
            store.remove(job_id)
            _reload_scheduled_message_jobs()
            return f"已删除定时消息任务 {job_id}。"

        return "未知 action。可用 action：list、create、set_enabled、delete。"
