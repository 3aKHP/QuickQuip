from __future__ import annotations

from quickquip.llm.inputs import extract_private_llm_input
from quickquip.llm.rendering import render_message_for_llm
from quickquip.adapters.nonebot._forward import extract_forward_content
from quickquip.adapters.nonebot.voice import append_voice_transcripts, transcribe_message_records
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    get_llm_service,
    get_sender_name,
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

        _ensure_llm_bindings()
        svc = get_llm_service()

        message = event.get_message()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=True,
        )
        sender_name = get_sender_name(event)
        user_id = event.user_id
        scope_key = svc.build_chat_scope_key(user_id, chat_type="private")
        message_id = str(getattr(event, "message_id", "") or "")
        identity = svc.identities.resolve_user(user_id, sender_name)
        canonical_name = identity.canonical_name

        if message_deduper.is_duplicate(scope_key, message_id or None):
            return

        llm_settings = svc.get_chat_settings(user_id, chat_type="private")
        if not llm_settings.enabled:
            return

        voice_transcripts = await transcribe_message_records(bot, message)
        voice_text = append_voice_transcripts("", voice_transcripts)
        rendered_text = append_voice_transcripts(rendered_message.text, voice_transcripts)

        forward_text, forward_image_urls = await extract_forward_content(
            bot=bot,
            message=message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            reply=getattr(event, "reply", None),
        )
        llm_input = extract_private_llm_input(
            message,
            event.self_id,
            llm_settings,
            identity_index=svc.identities,
            bot_self_ids={event.self_id},
            reply=getattr(event, "reply", None),
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
            voice_text=voice_text,
        )

        if llm_input is None:
            return
        _remember_recent_message(scope_key, user_id, sender_name, canonical_name, rendered_text, message_id)
        if not rate_limiter.allow("llm_chat", user_id):
            return

        result = await svc.generate_private_reply(
            user_id=user_id,
            sender_name=sender_name,
            prompt=llm_input.prompt,
            image_urls=llm_input.image_urls,
            recent_messages=None,
            quoted_text=llm_input.quoted_text,
            quoted_image_urls=llm_input.quoted_image_urls,
            quoted_sender_name=llm_input.quoted_sender_name,
            quoted_user_id=llm_input.quoted_user_id,
            quoted_is_bot_self=llm_input.quoted_is_bot_self,
            forward_text=llm_input.forward_text,
            forward_image_urls=llm_input.forward_image_urls,
            voice_text=llm_input.voice_text,
            message_id=message_id or None,
        )
        trigger_source = llm_input.trigger_source or "private_message"
        with bot_action_trace(
            trigger_kind="explicit_llm",
            reason_code=f"llm_chat.{trigger_source}",
            reason_detail=f"私聊 LLM 触发：{trigger_source}",
            rule_name=result.get("rule_name", "llm_chat"),
            chat_type="private",
            user_id=user_id,
            incoming_message_id=message_id,
            incoming_preview=rendered_text,
            reply_preview=result["reply"],
            llm_used=bool(result.get("llm_used")),
            provider_id=str(result.get("provider_id", "")),
            model=str(result.get("model", "")),
            source="private_message.llm",
        ):
            resp = await matcher.send(result["reply"])
        sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
        if sent_msg_id:
            svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
        return

    return matcher
