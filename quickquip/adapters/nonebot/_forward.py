from __future__ import annotations

import logging

from quickquip.llm.rendering import render_message_for_llm

logger = logging.getLogger(__name__)


def _get_field(obj, key: str, default: str = "") -> str:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return str(obj.get(key, default) or default)
    return str(getattr(obj, key, default) or default)


def _find_forward_id(message) -> str:
    try:
        segments = list(message)
    except TypeError:
        return ""
    for segment in segments:
        segment_type = getattr(segment, "type", None)
        if segment_type is None and isinstance(segment, dict):
            segment_type = segment.get("type", "")
        if str(segment_type or "") != "forward":
            continue
        data = getattr(segment, "data", None)
        if data is None and isinstance(segment, dict):
            data = segment.get("data", {})
        forward_id = str(_get_field(data, "id")).strip()
        if forward_id:
            return forward_id
    return ""


async def extract_forward_content(bot, message, bot_self_id, identity_index=None, *, reply=None):
    forward_id = _find_forward_id(message)
    if not forward_id and reply is not None:
        reply_message = getattr(reply, "message", None)
        if reply_message is None:
            reply_message = getattr(reply, "raw_message", None)
        if reply_message is not None:
            forward_id = _find_forward_id(reply_message)

    if not forward_id:
        return "", []

    try:
        result = await bot.call_api("get_forward_msg", message_id=forward_id)
    except Exception:
        logger.warning("Failed to fetch forward message id=%s", forward_id, exc_info=True)
        return "", []

    messages = []
    if isinstance(result, dict):
        messages = result.get("messages", [])
    elif hasattr(result, "messages"):
        messages = result.messages

    if not messages:
        return "", []

    lines = []
    image_urls = []
    for idx, item in enumerate(messages, 1):
        sender = item.get("sender", {}) if isinstance(item, dict) else getattr(item, "sender", {})
        sender_name = _get_field(sender, "card") or _get_field(sender, "nickname")
        user_id = _get_field(sender, "user_id")

        if isinstance(item, dict):
            content = item.get("content", item.get("message", []))
        else:
            content = getattr(item, "content", getattr(item, "message", []))

        rendered = render_message_for_llm(
            content,
            bot_self_id=bot_self_id,
            identity_index=identity_index,
            include_image_placeholder=True,
        )

        speaker = sender_name or user_id or "未知"
        speaker_label = f"{speaker}（QQ {user_id}）" if user_id else speaker

        line_text = rendered.text.strip()
        if line_text:
            lines.append(f"{idx}. {speaker_label}：{line_text}")
        else:
            lines.append(f"{idx}. {speaker_label}")

        image_urls.extend(rendered.image_urls)

    return "\n".join(lines), image_urls
