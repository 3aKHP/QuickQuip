from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedLLMInput:
    prompt: str
    image_urls: list[str] = field(default_factory=list)


def extract_llm_input(message, bot_self_id: int | str, settings) -> ExtractedLLMInput | None:
    segments = list(message)
    plain_parts: list[str] = []
    image_urls: list[str] = []
    mentioned_bot = False
    bot_key = str(bot_self_id)

    if not segments:
        text = str(message).strip()
        if settings.allow_prefix and text.startswith(settings.trigger_prefix):
            return ExtractedLLMInput(prompt=text[len(settings.trigger_prefix):].strip())
        return None

    for segment in segments:
        segment_type = getattr(segment, "type", "")
        data = getattr(segment, "data", {})
        if segment_type == "at":
            if str(data.get("qq", "")) == bot_key:
                mentioned_bot = True
                continue
            plain_parts.append(f"@{data.get('qq', '')}")
            continue
        if segment_type == "text":
            plain_parts.append(str(data.get("text", "")))
            continue
        if segment_type == "image":
            url = str(data.get("url", "")).strip()
            file_value = str(data.get("file", "")).strip()
            if url:
                image_urls.append(url)
            elif file_value.startswith("http://") or file_value.startswith("https://"):
                image_urls.append(file_value)

    normalized = "".join(plain_parts).strip()
    if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
        return ExtractedLLMInput(
            prompt=normalized[len(settings.trigger_prefix):].strip(),
            image_urls=image_urls,
        )
    if settings.allow_at and mentioned_bot:
        if settings.allow_prefix and normalized.startswith(settings.trigger_prefix):
            normalized = normalized[len(settings.trigger_prefix):].strip()
        return ExtractedLLMInput(prompt=normalized.strip(), image_urls=image_urls)
    return None


def extract_llm_prompt(message, bot_self_id: int | str, settings) -> str | None:
    extracted = extract_llm_input(message, bot_self_id, settings)
    if extracted is None:
        return None
    return extracted.prompt
