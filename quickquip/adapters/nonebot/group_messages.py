from __future__ import annotations

from quickquip.llm.inputs import extract_llm_input
from quickquip.llm.rendering import render_message_for_llm
from quickquip.adapters.nonebot._forward import extract_forward_content
from quickquip.adapters.nonebot.voice import append_voice_transcripts, transcribe_message_records
from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    awakening_state,
    get_llm_service,
    get_sender_name,
    message_deduper,
    offline_message_store,
    rate_limiter,
    recent_messages,
    record_group_message,
    record_wordcloud_message,
    resolve_reply,
    rule_switch,
    stats_tracker,
)
from quickquip.app.message_pipeline import is_self_message as _is_self_message


def _remember_recent_message(group_id, user_id, sender_name: str, canonical_name: str, rendered_text: str, message_id: str = "") -> None:
    recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id=message_id)


def register_message_matcher(on_message, Message, MessageSegment):
    matcher = on_message(priority=60, block=False)

    @matcher.handle()
    async def _(bot, event):
        if getattr(event, "group_id", None) is None or getattr(event, "message_type", "") == "private":
            return
        if _is_self_message(event):
            return

        _ensure_llm_bindings()
        svc = get_llm_service()

        message = event.get_message()
        text = str(message).strip()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=True,
        )
        sender_name = get_sender_name(event)
        user_id = event.user_id
        group_id = event.group_id
        message_id = str(getattr(event, "message_id", "") or "")
        identity = svc.identities.resolve_user(user_id, sender_name)
        canonical_name = identity.canonical_name

        if message_deduper.is_duplicate(group_id, message_id or None):
            return

        voice_transcripts = await transcribe_message_records(bot, message)
        voice_text = append_voice_transcripts("", voice_transcripts)
        rendered_text = append_voice_transcripts(rendered_message.text, voice_transcripts)

        stats_tracker.record_message(group_id, user_id, sender_name)
        record_group_message(group_id, user_id, sender_name, rendered_text)
        record_wordcloud_message(group_id, sender_name, rendered_text)
        awakening_state.record_message(group_id, user_id)

        pending = offline_message_store.pop_pending(group_id, user_id)
        if pending:
            lines = [f"有 {len(pending)} 条留言捎给你："]
            for m in pending:
                lines.append(m.format_display())
            await bot.send(event, Message([
                MessageSegment.at(user_id),
                MessageSegment.text(" " + "\n".join(lines)),
            ]))

        trigger_context = recent_messages.list_recent(group_id, limit=20)

        llm_settings = svc.get_group_settings(group_id)
        forward_text, forward_image_urls = await extract_forward_content(
            bot=bot,
            message=message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            reply=getattr(event, "reply", None),
        )
        llm_input = extract_llm_input(
            message,
            event.self_id,
            llm_settings,
            identity_index=svc.identities,
            bot_self_ids={event.self_id},
            reply=getattr(event, "reply", None),
            is_to_me=bool(getattr(event, "to_me", False)),
            forward_text=forward_text,
            forward_image_urls=forward_image_urls,
            voice_text=voice_text,
        )
        if llm_input is not None and rule_switch.is_enabled(group_id, "llm_chat"):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
            if not rate_limiter.allow("llm_chat", user_id):
                return
            result = await svc.generate_reply(
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
                quoted_is_bot_self=llm_input.quoted_is_bot_self,
                forward_text=llm_input.forward_text,
                forward_image_urls=llm_input.forward_image_urls,
                voice_text=llm_input.voice_text,
                message_id=message_id or None,
            )
            stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))
            awakening_state.bot_messages.add(group_id, result["reply"])
            resp = await matcher.send(result["reply"])
            sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
            if sent_msg_id:
                scope_key = str(group_id)
                svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
            return

        from quickquip.chat.awakening import check_awakening_triggers

        awakening_result = await check_awakening_triggers(
            group_id, user_id, text, llm_settings, svc,
        )
        if awakening_result and rule_switch.is_enabled(group_id, awakening_result.rule_name):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
            if not rate_limiter.allow(awakening_result.rule_name, user_id):
                return
            trigger_context = recent_messages.list_recent(group_id, limit=20)
            result = await svc.generate_reply(
                group_id=group_id,
                user_id=user_id,
                sender_name=sender_name,
                prompt=awakening_result.prompt,
                image_urls=[],
                recent_messages=trigger_context,
                message_id=message_id or None,
            )
            stats_tracker.record_trigger(group_id, awakening_result.rule_name)
            awakening_state.bot_messages.add(group_id, result["reply"])
            resp = await matcher.send(result["reply"])
            sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
            if sent_msg_id:
                scope_key = str(group_id)
                svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
            awakening_state.mark_awakened(group_id, user_id)
            return

        result = await resolve_reply(
            text,
            user_id=user_id,
            sender_name=sender_name,
            group_id=group_id,
            recent_context=trigger_context,
        )
        if not result:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
            return
        if not rate_limiter.allow(result["rate_limit_key"], user_id, group_id=group_id):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
            return

        stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))

        if "at_user_id" in result:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
            message = Message([
                MessageSegment.at(result["at_user_id"]),
                MessageSegment.text(f" {result['reply']}"),
            ])
            await matcher.finish(message)

        _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id)
        await matcher.finish(result["reply"])

    return matcher
