from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_id, _chat_type
from quickquip.adapters.nonebot.command_parts._parsing import _strip_leading_command_token
from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    get_llm_service,
    rate_limiter,
    stats_tracker,
)
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.llm.rendering import render_message_for_llm, render_reply_for_llm
from quickquip.sts.config import (
    DEFECTIFY_ALIASES,
    DEFECTIFY_RATE_LIMIT_KEY,
    DEFECTIFY_RULE_NAME,
    TURMFLUCH_ALIASES,
    TURMFLUCH_RATE_LIMIT_KEY,
    TURMFLUCH_RULE_NAME,
)


@dataclass(frozen=True, slots=True)
class _StsCommandSpec:
    """命令型 STS 公式入口的差异点束；处理器骨架见 :func:`_register_sts_command`。

    ``generate_reply`` 接收 ``LLMService`` 实例并返回其 ``generate_*_reply``
    绑定方法——两个方法的签名一致，由骨架以统一关键字参数调用。
    """

    name: str
    aliases: frozenset[str]
    rate_limit_key: str
    rate_limit_reply: str
    reason_detail: str
    rule_name: str
    generate_reply: Callable[[Any], Callable[..., Awaitable[dict[str, Any]]]]


def _register_sts_command(on_command, spec: _StsCommandSpec) -> None:
    """注册「渲染输入 → 单发 LLM → 上报」形态的 STS 公式命令。

    渲染、引用消息提取、触发统计与 bot_action_trace 上报只写一次；
    turmfluch / defectify 各自仅传入差异点（分层风格同
    llm/single_shot.py 的 CommandSingleShotSpec）。
    """
    cmd = on_command(spec.name, aliases=spec.aliases, priority=10, block=True)
    reason_code = f"command.{spec.name}"

    @cmd.handle()
    async def _(event):
        if not rate_limiter.allow(spec.rate_limit_key, event.user_id):
            await cmd.finish(spec.rate_limit_reply)

        _ensure_llm_bindings()
        svc = get_llm_service()

        rendered = render_message_for_llm(
            event.get_message(),
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
        )
        rendered_reply = render_reply_for_llm(
            getattr(event, "reply", None),
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=True,
        )
        prompt = _strip_leading_command_token(rendered.text)
        quoted_text = "" if rendered_reply is None else rendered_reply.text
        quoted_image_urls = [] if rendered_reply is None else rendered_reply.image_urls
        quoted_sender_name = "" if rendered_reply is None else rendered_reply.sender_name
        quoted_user_id = "" if rendered_reply is None else rendered_reply.user_id
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        generate_reply = spec.generate_reply(svc)
        result = await generate_reply(
            chat_id=chat_id,
            chat_type=chat_type,
            prompt=prompt,
            image_urls=rendered.image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )
        if chat_type == "group":
            stats_tracker.record_trigger(event.group_id, result.get("rule_name", "unknown"))
        with bot_action_trace(
            trigger_kind="command",
            reason_code=reason_code,
            reason_detail=spec.reason_detail,
            rule_name=result.get("rule_name", spec.rule_name),
            chat_type=chat_type,
            group_id=getattr(event, "group_id", ""),
            user_id=event.user_id,
            incoming_message_id=str(getattr(event, "message_id", "") or ""),
            incoming_preview=rendered.text,
            reply_preview=result["reply"],
            llm_used=bool(result.get("llm_used")),
            provider_id=str(result.get("provider_id", "")),
            model=str(result.get("model", "")),
            source=reason_code,
        ):
            await cmd.finish(result["reply"])


def register_sts_commands(on_command, Message, MessageSegment) -> None:
    """/turmfluch：把跟随文字/图片/引用提炼成一句「<卡牌或遗物名>了」。

    /defectify（别名 /故障化）：把跟随文字/图片/引用转写成读音贴近
    「故障机器人」的五字梗。两命令共用同一处理器骨架，仅差异点不同。
    """
    _register_sts_command(
        on_command,
        _StsCommandSpec(
            name="turmfluch",
            aliases=TURMFLUCH_ALIASES,
            rate_limit_key=TURMFLUCH_RATE_LIMIT_KEY,
            rate_limit_reply="尖塔化过于频繁，请稍后再试",
            reason_detail="命令触发：尖塔化（xxx了）",
            rule_name=TURMFLUCH_RULE_NAME,
            generate_reply=lambda svc: svc.generate_turmfluch_reply,
        ),
    )
    _register_sts_command(
        on_command,
        _StsCommandSpec(
            name="defectify",
            aliases=DEFECTIFY_ALIASES,
            rate_limit_key=DEFECTIFY_RATE_LIMIT_KEY,
            rate_limit_reply="转写过于频繁，请稍后再试",
            reason_detail="命令触发：故障化转写",
            rule_name=DEFECTIFY_RULE_NAME,
            generate_reply=lambda svc: svc.generate_defectify_reply,
        ),
    )
