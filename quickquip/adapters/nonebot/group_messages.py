from __future__ import annotations

from quickquip.llm.inputs import extract_llm_input
from quickquip.llm.rendering import render_message_for_llm
from quickquip.app.message_pipeline import (
    get_sender_name,
    llm_service,
    message_deduper,
    rate_limiter,
    recent_messages,
    resolve_reply,
    rule_switch,
    stats_tracker,
)
from quickquip.app.message_pipeline import is_self_message as _is_self_message


def _remember_recent_message(group_id, user_id, sender_name: str, canonical_name: str, rendered_text: str) -> None:
    recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)


def register_message_matcher(on_message, Message, MessageSegment):
    matcher = on_message(priority=60, block=False)

    @matcher.handle()
    async def _(event):
        if _is_self_message(event):
            return

        message = event.get_message()
        text = str(message).strip()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            include_image_placeholder=True,
        )
        rendered_text = rendered_message.text
        sender_name = get_sender_name(event)
        user_id = event.user_id
        group_id = event.group_id
        message_id = getattr(event, "message_id", None)
        identity = llm_service.identities.resolve_user(user_id, sender_name)
        canonical_name = identity.canonical_name

        if message_deduper.is_duplicate(group_id, message_id):
            return

        stats_tracker.record_message(group_id, user_id, sender_name)
        trigger_context = recent_messages.list_recent(group_id, limit=20)

        llm_settings = llm_service.get_group_settings(group_id)
        llm_input = extract_llm_input(
            message,
            event.self_id,
            llm_settings,
            identity_index=llm_service.identities,
            reply=getattr(event, "reply", None),
            is_to_me=bool(getattr(event, "to_me", False)),
        )
        if llm_input is not None and rule_switch.is_enabled(group_id, "llm_chat"):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            if not rate_limiter.allow("llm_chat", user_id):
                return
            result = await llm_service.generate_reply(
                group_id=group_id,
                user_id=user_id,
                sender_name=sender_name,
                prompt=llm_input.prompt,
                image_urls=llm_input.image_urls,
                recent_messages=trigger_context,
                quoted_text=llm_input.quoted_text,
                quoted_image_urls=llm_input.quoted_image_urls,
                quoted_sender_name=llm_input.quoted_sender_name,
                quoted_user_id=llm_input.quoted_user_id,
            )
            stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))
            await matcher.finish(result["reply"])

        result = resolve_reply(
            text,
            user_id=user_id,
            sender_name=sender_name,
            group_id=group_id,
        )
        if not result:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            return
        if not rate_limiter.allow(result["rate_limit_key"], user_id):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            return

        stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))

        if "at_user_id" in result:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            message = Message([
                MessageSegment.at(result["at_user_id"]),
                MessageSegment.text(f" {result['reply']}"),
            ])
            await matcher.finish(message)

        _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text)
        await matcher.finish(result["reply"])

    return matcher
