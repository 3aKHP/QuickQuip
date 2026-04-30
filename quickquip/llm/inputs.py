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
    forward_text: str = ""
    forward_image_urls: list[str] = field(default_factory=list)
    voice_text: str = ""


def extract_llm_input(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
    *,
    reply=None,
    is_to_me: bool = False,
    forward_text: str = "",
    forward_image_urls: list[str] | None = None,
    voice_text: str = "",
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

    forward_kwargs = {
        "forward_text": forward_text,
        "forward_image_urls": list(forward_image_urls or []),
        "voice_text": voice_text.strip(),
    }

    if not segments:
        text = rendered.text
        if settings.allow_prefix and text.startswith(settings.trigger_prefix):
            return ExtractedLLMInput(
                prompt=text[len(settings.trigger_prefix):].strip(),
                **extracted_reply,
                **forward_kwargs,
            )
        if settings.allow_at and is_to_me:
            return ExtractedLLMInput(prompt=text.strip(), **extracted_reply, **forward_kwargs)
        return None

    normalized = rendered.text
    if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
        return ExtractedLLMInput(
            prompt=normalized[len(settings.trigger_prefix):].strip(),
            image_urls=rendered.image_urls,
            **extracted_reply,
            **forward_kwargs,
        )
    if settings.allow_at and (rendered.mentioned_bot or is_to_me):
        if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
            normalized = normalized[len(settings.trigger_prefix):].strip()
        return ExtractedLLMInput(
            prompt=normalized.strip(),
            image_urls=rendered.image_urls,
            **extracted_reply,
            **forward_kwargs,
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


def extract_private_llm_input(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
    *,
    reply=None,
    forward_text: str = "",
    forward_image_urls: list[str] | None = None,
    voice_text: str = "",
) -> ExtractedLLMInput | None:
    extracted = extract_llm_input(
        message,
        bot_self_id,
        settings,
        identity_index=identity_index,
        reply=reply,
        is_to_me=False,
        forward_text=forward_text,
        forward_image_urls=forward_image_urls,
        voice_text=voice_text,
    )
    if extracted is not None:
        return extracted

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

    prompt = rendered.text.strip()
    quoted_text = "" if rendered_reply is None else rendered_reply.text
    quoted_image_urls = [] if rendered_reply is None else rendered_reply.image_urls
    quoted_sender_name = "" if rendered_reply is None else rendered_reply.sender_name
    quoted_user_id = "" if rendered_reply is None else rendered_reply.user_id

    has_any_content = (
        prompt or rendered.image_urls
        or quoted_text.strip() or quoted_image_urls
        or forward_text.strip() or forward_image_urls
        or voice_text.strip()
    )
    if not has_any_content:
        return None

    return ExtractedLLMInput(
        prompt=prompt,
        image_urls=rendered.image_urls,
        quoted_text=quoted_text,
        quoted_image_urls=quoted_image_urls,
        quoted_sender_name=quoted_sender_name,
        quoted_user_id=quoted_user_id,
        forward_text=forward_text,
        forward_image_urls=list(forward_image_urls or []),
        voice_text=voice_text.strip(),
    )
