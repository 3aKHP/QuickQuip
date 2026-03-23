from __future__ import annotations

from dataclasses import dataclass, field

from plugins.llm_identity import IdentityIndex


@dataclass(slots=True)
class RenderedMessage:
    text: str
    image_urls: list[str] = field(default_factory=list)
    mentioned_bot: bool = False


@dataclass(slots=True)
class RenderedReply:
    text: str
    image_urls: list[str] = field(default_factory=list)
    mentioned_bot: bool = False
    sender_name: str = ""
    user_id: str = ""
    message_id: str = ""


def _get_sender_name(sender) -> str:
    if sender is None:
        return ""
    card = str(getattr(sender, "card", "") or "").strip()
    if card:
        return card
    nickname = str(getattr(sender, "nickname", "") or "").strip()
    if nickname:
        return nickname
    return ""


def render_message_for_llm(
    message,
    *,
    bot_self_id: int | str | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> RenderedMessage:
    if isinstance(message, str):
        return RenderedMessage(text=message.strip())

    segments = list(message)
    if not segments or not any(hasattr(segment, "type") for segment in segments):
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


def render_reply_for_llm(
    reply,
    *,
    bot_self_id: int | str | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> RenderedReply | None:
    if reply is None:
        return None

    reply_message = getattr(reply, "message", None)
    if reply_message is None:
        reply_message = getattr(reply, "raw_message", None)
    rendered = render_message_for_llm(
        reply_message,
        bot_self_id=bot_self_id,
        identity_index=identity_index,
        include_image_placeholder=include_image_placeholder,
    )
    user_id = str(getattr(reply, "user_id", "") or "").strip()
    sender_name = _get_sender_name(getattr(reply, "sender", None))
    if not sender_name:
        sender_name = str(getattr(reply, "nickname", "") or "").strip()
    if not sender_name:
        sender_name = user_id

    return RenderedReply(
        text=rendered.text,
        image_urls=rendered.image_urls,
        mentioned_bot=rendered.mentioned_bot,
        sender_name=sender_name,
        user_id=user_id,
        message_id=str(getattr(reply, "message_id", "") or "").strip(),
    )
