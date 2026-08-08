from __future__ import annotations

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
from quickquip.sts.config import TURMFLUCH_ALIASES, TURMFLUCH_RATE_LIMIT_KEY, TURMFLUCH_RULE_NAME


def register_sts_commands(on_command, Message, MessageSegment) -> None:
    """/turmfluch：把跟随文字/图片/引用提炼成一句「<卡牌或遗物名>了」。"""
    turmfluch_cmd = on_command("turmfluch", aliases=TURMFLUCH_ALIASES, priority=10, block=True)

    @turmfluch_cmd.handle()
    async def _(event):
        if not rate_limiter.allow(TURMFLUCH_RATE_LIMIT_KEY, event.user_id):
            await turmfluch_cmd.finish("尖塔化过于频繁，请稍后再试")

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

        result = await svc.generate_turmfluch_reply(
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
            reason_code="command.turmfluch",
            reason_detail="命令触发：尖塔化（xxx了）",
            rule_name=result.get("rule_name", TURMFLUCH_RULE_NAME),
            chat_type=chat_type,
            group_id=getattr(event, "group_id", ""),
            user_id=event.user_id,
            incoming_message_id=str(getattr(event, "message_id", "") or ""),
            incoming_preview=rendered.text,
            reply_preview=result["reply"],
            llm_used=bool(result.get("llm_used")),
            provider_id=str(result.get("provider_id", "")),
            model=str(result.get("model", "")),
            source="command.turmfluch",
        ):
            await turmfluch_cmd.finish(result["reply"])
