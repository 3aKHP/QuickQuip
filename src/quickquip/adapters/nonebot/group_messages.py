from __future__ import annotations

from quickquip.llm.inputs import extract_llm_input
from quickquip.llm.rendering import render_message_for_llm
from quickquip.adapters.nonebot._forward import extract_forward_content
from quickquip.adapters.nonebot._llm_reply import build_llm_reply_message
from quickquip.adapters.nonebot.voice import append_voice_transcripts, transcribe_message_records
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.chat.repeat_detector import RepeatAction
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


def _remember_recent_message(group_id, user_id, sender_name: str, canonical_name: str, rendered_text: str, message_id: str = "", image_urls: list[str] | None = None) -> None:
    recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id=message_id, image_urls=image_urls)


def _result_reason(result: dict) -> str:
    if result.get("trigger_reason"):
        return str(result["trigger_reason"])
    rule_name = str(result.get("rule_name", "unknown"))
    kind = str(result.get("trigger_kind", "rule"))
    return f"{kind} 触发：{rule_name}"


def _trim_last_content_unit(message):
    trimmed = message.copy()
    while trimmed:
        last_segment = trimmed[-1]
        if getattr(last_segment, "type", "") != "text":
            trimmed.pop()
            break
        text = str(getattr(last_segment, "data", {}).get("text", ""))
        if not text:
            trimmed.pop()
            continue
        remaining = text[:-1]
        if remaining:
            last_segment.data["text"] = remaining
        else:
            trimmed.pop()
        break
    return trimmed or None


def _build_rule_reply_message(result: dict, incoming_message, Message, MessageSegment):
    repeat_action = result.get("repeat_action")
    if repeat_action == RepeatAction.COPY_ORIGINAL:
        return incoming_message.copy()
    if repeat_action == RepeatAction.TRIM_LAST:
        return _trim_last_content_unit(incoming_message)
    if "at_user_id" in result:
        return Message([
            MessageSegment.at(result["at_user_id"]),
            MessageSegment.text(f" {result['reply']}"),
        ])
    return result["reply"]


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
        repeat_fingerprint = str(message).strip()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=True,
        )
        rule_text = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=False,
        ).text
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
        passive_trigger_text = rendered_text

        stats_tracker.record_message(group_id, user_id, sender_name)
        record_group_message(group_id, user_id, sender_name, rendered_text)
        record_wordcloud_message(group_id, sender_name, rendered_text)
        awakening_state.record_message(group_id, user_id)

        pending = offline_message_store.pop_pending(group_id, user_id)
        if pending:
            lines = [f"有 {len(pending)} 条留言捎给你："]
            for m in pending:
                lines.append(m.format_display())
            reply_message = Message([
                MessageSegment.at(user_id),
                MessageSegment.text(" " + "\n".join(lines)),
            ])
            with bot_action_trace(
                trigger_kind="offline_delivery",
                reason_code="offline_message.delivery",
                reason_detail=f"离线留言投递：{len(pending)} 条",
                rule_name="offline_message_delivery",
                chat_type="group",
                group_id=group_id,
                user_id=user_id,
                incoming_message_id=message_id,
                incoming_preview=rendered_text,
                reply_preview=reply_message,
                source="group_message.pending_offline_messages",
            ):
                await bot.send(event, reply_message)

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
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
            if not rate_limiter.allow("llm_chat", user_id):
                return
            result = await svc.generate_reply(
                group_id=group_id,
                user_id=user_id,
                sender_name=sender_name,
                prompt=llm_input.prompt,
                image_urls=llm_input.image_urls,
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
            if bool(result.get("llm_used")):
                awakening_state.mark_awakened(group_id, user_id, source="explicit_llm")
            trigger_source = llm_input.trigger_source or "explicit"
            with bot_action_trace(
                trigger_kind="explicit_llm",
                reason_code=f"llm_chat.{trigger_source}",
                reason_detail=f"显式 LLM 触发：{trigger_source}",
                rule_name=result.get("rule_name", "llm_chat"),
                chat_type="group",
                group_id=group_id,
                user_id=user_id,
                incoming_message_id=message_id,
                incoming_preview=rendered_text,
                reply_preview=result["reply"],
                llm_used=bool(result.get("llm_used")),
                provider_id=str(result.get("provider_id", "")),
                model=str(result.get("model", "")),
                source="group_message.explicit_llm",
            ):
                resp = await matcher.send(build_llm_reply_message(result, Message, MessageSegment))
            sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
            if sent_msg_id:
                scope_key = str(group_id)
                svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
            return

        from quickquip.chat.awakening import (
            allows_recent_images,
            build_awakening_prompt,
            build_passive_trigger_raw_user_text,
            check_awakening_triggers,
            select_passive_trigger_image_urls,
        )

        awakening_result = await check_awakening_triggers(
            group_id,
            user_id,
            passive_trigger_text,
            llm_settings,
            svc,
            rule_enabled=lambda rule_name: rule_switch.is_enabled(group_id, rule_name),
            rate_available=lambda rule_name: rate_limiter.can_allow(rule_name, user_id, group_id=group_id),
        )
        if awakening_result and rule_switch.is_enabled(group_id, awakening_result.rule_name):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
            if not rate_limiter.allow(awakening_result.rule_name, user_id, group_id=group_id):
                return
            # trigger_context was captured before the current message was stored,
            # so the passive prompt's user text stays the only copy of it.
            passive_image_urls = select_passive_trigger_image_urls(
                awakening_result,
                rendered_message.image_urls,
            )
            result = await svc.generate_reply(
                group_id=group_id,
                user_id=user_id,
                sender_name=sender_name,
                prompt=build_awakening_prompt(awakening_result, passive_image_urls),
                image_urls=passive_image_urls,
                include_recent_images=allows_recent_images(awakening_result.rule_name),
                raw_user_text=build_passive_trigger_raw_user_text(awakening_result, passive_image_urls),
                message_id=message_id or None,
            )
            stats_tracker.record_trigger(group_id, awakening_result.rule_name)
            awakening_state.bot_messages.add(group_id, result["reply"])
            with bot_action_trace(
                trigger_kind="awakening",
                reason_code=awakening_result.rule_name,
                reason_detail=awakening_result.trigger_reason,
                rule_name=awakening_result.rule_name,
                chat_type="group",
                group_id=group_id,
                user_id=user_id,
                incoming_message_id=message_id,
                incoming_preview=rendered_text,
                reply_preview=result["reply"],
                llm_used=bool(result.get("llm_used")),
                provider_id=str(result.get("provider_id", "")),
                model=str(result.get("model", "")),
                source="group_message.awakening",
            ):
                resp = await matcher.send(build_llm_reply_message(result, Message, MessageSegment))
            sent_msg_id = str(resp.get("message_id", "")) if isinstance(resp, dict) else ""
            if sent_msg_id:
                scope_key = str(group_id)
                svc.store.update_last_assistant_message_id(scope_key, sent_msg_id)
            return

        result = await resolve_reply(
            rule_text,
            user_id=user_id,
            sender_name=sender_name,
            group_id=group_id,
            recent_context=trigger_context,
            repeat_fingerprint=repeat_fingerprint,
        )
        if not result:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
            return
        reply_message = _build_rule_reply_message(
            result,
            message,
            Message,
            MessageSegment,
        )
        if reply_message is None:
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
            return
        if not rate_limiter.allow(result["rate_limit_key"], user_id, group_id=group_id):
            _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
            return

        stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))

        _remember_recent_message(group_id, user_id, sender_name, canonical_name, rendered_text, message_id, image_urls=rendered_message.image_urls)
        with bot_action_trace(
            trigger_kind=str(result.get("trigger_kind", "rule")),
            reason_code=str(result.get("reason_code", result.get("rule_name", "unknown"))),
            reason_detail=_result_reason(result),
            rule_name=str(result.get("rule_name", "unknown")),
            chat_type="group",
            group_id=group_id,
            user_id=user_id,
            incoming_message_id=message_id,
            incoming_preview=rendered_text,
            reply_preview=reply_message,
            source="group_message.rule_reply",
        ):
            await matcher.finish(reply_message)

    return matcher
