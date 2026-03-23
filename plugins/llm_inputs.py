from __future__ import annotations

from dataclasses import dataclass, field

from plugins.llm_identity import IdentityIndex
from plugins.message_rendering import render_message_for_llm


@dataclass(slots=True)
class ExtractedLLMInput:
    prompt: str
    image_urls: list[str] = field(default_factory=list)


def extract_llm_input(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
) -> ExtractedLLMInput | None:
    rendered = render_message_for_llm(
        message,
        bot_self_id=bot_self_id,
        identity_index=identity_index,
    )
    segments = list(message)

    if not segments:
        text = rendered.text
        if settings.allow_prefix and text.startswith(settings.trigger_prefix):
            return ExtractedLLMInput(prompt=text[len(settings.trigger_prefix):].strip())
        return None

    normalized = rendered.text
    if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
        return ExtractedLLMInput(
            prompt=normalized[len(settings.trigger_prefix):].strip(),
            image_urls=rendered.image_urls,
        )
    if settings.allow_at and rendered.mentioned_bot:
        if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
            normalized = normalized[len(settings.trigger_prefix):].strip()
        return ExtractedLLMInput(prompt=normalized.strip(), image_urls=rendered.image_urls)
    return None


def extract_llm_prompt(
    message,
    bot_self_id: int | str,
    settings,
    identity_index: IdentityIndex | None = None,
) -> str | None:
    extracted = extract_llm_input(message, bot_self_id, settings, identity_index=identity_index)
    if extracted is None:
        return None
    return extracted.prompt
