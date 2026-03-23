from __future__ import annotations

from dataclasses import dataclass, field

from plugins.llm_identity import IdentityIndex


@dataclass(slots=True)
class RenderedMessage:
    text: str
    image_urls: list[str] = field(default_factory=list)
    mentioned_bot: bool = False


def render_message_for_llm(
    message,
    *,
    bot_self_id: int | str | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> RenderedMessage:
    segments = list(message)
    if not segments:
        return RenderedMessage(text=str(message).strip())

    plain_parts: list[str] = []
    image_urls: list[str] = []
    mentioned_bot = False
    bot_key = "" if bot_self_id is None else str(bot_self_id)
    identities = identity_index or IdentityIndex()

    for segment in segments:
        segment_type = getattr(segment, "type", "")
        data = getattr(segment, "data", {})
        if segment_type == "at":
            qq = str(data.get("qq", "")).strip()
            if qq and qq == bot_key:
                mentioned_bot = True
                continue
            if qq:
                plain_parts.append(identities.render_mention(qq))
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
            if include_image_placeholder:
                plain_parts.append("[图片]")

    return RenderedMessage(
        text="".join(plain_parts).strip(),
        image_urls=image_urls,
        mentioned_bot=mentioned_bot,
    )
