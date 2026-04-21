from __future__ import annotations

from quickquip.llm.inputs import extract_private_llm_input
from quickquip.llm.rendering import render_message_for_llm
from quickquip.adapters.nonebot._forward import extract_forward_content
from quickquip.app.message_pipeline import (
    get_sender_name,
    llm_service,
    message_deduper,
    rate_limiter,
    recent_messages,
)
from quickquip.app.message_pipeline import is_self_message as _is_self_message


def _remember_recent_message(scope_key, user_id, sender_name: str, canonical_name: str, rendered_text: str, message_id: str = "") -> None:
    recent_messages.add_message(scope_key, user_id, sender_name, canonical_name, rendered_text, message_id=message_id)


def register_private_message_matcher(on_message):
    matcher = on_message(priority=60, block=False)

    @matcher.handle()
    async def _(bot, event):
        if getattr(event, "group_id", None) is not None or getattr(event, "message_type", "") == "group":
            return
        if _is_self_message(event):
            return

        message = event.get_message()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            include_image_placeholder=True,
        )
        rendered_text = rendered_message.text
        sender_name = get_sender_name(event)
        user_id = event.user_id
        scope_key = llm_service.build_chat_scope_key(user_id, chat_type="private")
        message_id = str(getattr(event, "message_id", "") or "")
        identity = llm_service.identities.resolve_user(user_id, sender_name)
        canonical_name = identity.canonical_name

        if message_deduper.is_duplicate(scope_key, message_id or None):
            return

        llm_settings = llm_service.get_chat_settings(user_id, chat_type="private")
        if not llm_settings.enabled:
            return
        forward_text, forward_image_urls = await extract_forward_content(
            bot=bot,
            message=message,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            reply=getattr(event, "reply", None),
        )
        llm_input = extract_private_llm_input(
            message,
            event.self_id,
            llm_settings,
            identity_index=llm_service.identities,
            reply=getattr(event, "reply", None),
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
        )

        if llm_input is None:
            return
        _remember_recent_message(scope_key, user_id, sender_name, canonical_name, rendered_text, message_id)
        if not rate_limiter.allow("llm_chat", user_id):
            return

        result = await llm_service.generate_private_reply(
            user_id=user_id,
            sender_name=sender_name,
            prompt=llm_input.prompt,
            image_urls=llm_input.image_urls,
            recent_messages=None,
            quoted_text=llm_input.quoted_text,
            quoted_image_urls=llm_input.quoted_image_urls,
            quoted_sender_name=llm_input.quoted_sender_name,
            quoted_user_id=llm_input.quoted_user_id,
            forward_text=llm_input.forward_text,
            forward_image_urls=llm_input.forward_image_urls,
            message_id=message_id or None,
        )
        resp = await matcher.send(result["reply"])
        sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
        if sent_msg_id:
            llm_service.store.update_last_assistant_message_id(scope_key, sent_msg_id)
        return

    return matcher
