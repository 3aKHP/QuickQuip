from __future__ import annotations

from dataclasses import dataclass, field

from quickquip.llm.identity import IdentityIndex
from quickquip.llm.rendering import render_message_for_llm, render_reply_for_llm


@dataclass(slots=True)
class ExtractedLLMInput:
    prompt: str
    image_urls: list[str] = field(default_factory=list)
    quoted_text: str = ""
    quoted_image_urls: list[str] = field(default_factory=list)
    quoted_sender_name: str = ""
    quoted_user_id: str = ""


def extract_llm_input(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
    *,
    reply=None,
    is_to_me: bool = False,
) -> ExtractedLLMInput | None:
    rendered = render_message_for_llm(
        message,
        bot_self_id=bot_self_id,
        identity_index=identity_index,
    )
    rendered_reply = render_reply_for_llm(
        reply,
        bot_self_id=bot_self_id,
        identity_index=identity_index,
        include_image_placeholder=True,
    )
    segments = list(message)

    extracted_reply = {
        "quoted_text": "" if rendered_reply is None else rendered_reply.text,
        "quoted_image_urls": [] if rendered_reply is None else rendered_reply.image_urls,
        "quoted_sender_name": "" if rendered_reply is None else rendered_reply.sender_name,
        "quoted_user_id": "" if rendered_reply is None else rendered_reply.user_id,
    }

    if not segments:
        text = rendered.text
        if settings.allow_prefix and text.startswith(settings.trigger_prefix):
            return ExtractedLLMInput(
                prompt=text[len(settings.trigger_prefix):].strip(),
                **extracted_reply,
            )
        if settings.allow_at and is_to_me:
            return ExtractedLLMInput(prompt=text.strip(), **extracted_reply)
        return None

    normalized = rendered.text
    if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
        return ExtractedLLMInput(
            prompt=normalized[len(settings.trigger_prefix):].strip(),
            image_urls=rendered.image_urls,
            **extracted_reply,
        )
    if settings.allow_at and (rendered.mentioned_bot or is_to_me):
        if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
            normalized = normalized[len(settings.trigger_prefix):].strip()
        return ExtractedLLMInput(
            prompt=normalized.strip(),
            image_urls=rendered.image_urls,
            **extracted_reply,
        )
    return None


def extract_llm_prompt(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
    *,
    reply=None,
    is_to_me: bool = False,
) -> str | None:
    extracted = extract_llm_input(
        message,
        bot_self_id,
        settings,
        identity_index=identity_index,
        reply=reply,
        is_to_me=is_to_me,
    )
    if extracted is None:
        return None
    return extracted.prompt
