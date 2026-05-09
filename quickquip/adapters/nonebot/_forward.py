from __future__ import annotations

from collections.abc import Iterable
import logging

from quickquip.llm.message_segments import (
    message_has_segments,
    normalize_bot_self_ids,
    render_segment_leaf,
    segment_type_and_data,
)
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.prompting import format_participant_label

logger = logging.getLogger(__name__)

MAX_FORWARD_DEPTH = 8


def _get_field(obj, key: str, default: str = "") -> str:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return str(obj.get(key, default) or default)
    return str(getattr(obj, key, default) or default)
def _message_segments(message) -> list[object]:
    try:
        segments = list(message)
    except TypeError:
        return []
    if not message_has_segments(message):
        return []
    return segments


def _extract_forward_payload(message) -> tuple[str, list[object]]:
    for segment in _message_segments(message):
        segment_type, data = segment_type_and_data(segment)
        if segment_type != "forward":
            continue
        forward_id = str(_get_field(data, "id")).strip()
        nested_nodes = data.get("content") or []
        if nested_nodes and isinstance(nested_nodes, list):
            return forward_id, nested_nodes
        return forward_id, []
    return "", []


def _format_forward_sender(sender_name: str, user_id: str, *, bot_keys: set[str], identities: IdentityIndex) -> str:
    normalized_user_id = user_id.strip()
    if normalized_user_id and normalized_user_id in bot_keys:
        return f"机器人（QQ {normalized_user_id}）"
    match = identities.resolve_user(normalized_user_id, sender_name)
    return format_participant_label(
        user_id=normalized_user_id,
        sender_name=sender_name,
        canonical_name=match.canonical_name,
        include_unregistered_note=True,
    )


async def _render_forward_nodes(
    bot,
    nodes: list[object],
    *,
    bot_keys: set[str],
    identity_index: IdentityIndex,
    include_image_placeholder: bool,
    depth: int,
    visited_forward_ids: set[str],
) -> tuple[str, list[str]]:
    if depth >= MAX_FORWARD_DEPTH:
        return "[合并转发内容过深，已截断]", []

    lines: list[str] = []
    image_urls: list[str] = []

    for idx, item in enumerate(nodes, 1):
        sender = item.get("sender", {}) if isinstance(item, dict) else getattr(item, "sender", {})
        sender_name = _get_field(sender, "card") or _get_field(sender, "nickname")
        user_id = _get_field(sender, "user_id")

        if isinstance(item, dict):
            content = item.get("content", item.get("message", []))
        else:
            content = getattr(item, "content", getattr(item, "message", []))

        rendered_text, rendered_images = await _render_forward_content(
            bot,
            content,
            bot_keys=bot_keys,
            identity_index=identity_index,
            include_image_placeholder=include_image_placeholder,
            depth=depth + 1,
            visited_forward_ids=visited_forward_ids,
        )

        speaker_label = _format_forward_sender(
            sender_name,
            user_id,
            bot_keys=bot_keys,
            identities=identity_index,
        )

        if rendered_text:
            lines.append(f"{idx}. {speaker_label}：{rendered_text}")
        else:
            lines.append(f"{idx}. {speaker_label}")
        image_urls.extend(rendered_images)

    return "\n".join(lines), image_urls


async def _render_forward_content(
    bot,
    content,
    *,
    bot_keys: set[str],
    identity_index: IdentityIndex,
    include_image_placeholder: bool,
    depth: int,
    visited_forward_ids: set[str],
) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content.strip(), []

    segments = _message_segments(content)
    if not segments:
        return str(content).strip(), []

    plain_parts: list[str] = []
    image_urls: list[str] = []

    for segment in segments:
        segment_type, data = segment_type_and_data(segment)

        if segment_type == "forward":
            nested_id = str(_get_field(data, "id")).strip()
            nested_nodes = data.get("content") or []

            nested_text = ""
            nested_images: list[str] = []
            if nested_nodes and isinstance(nested_nodes, list):
                next_visited = visited_forward_ids | ({nested_id} if nested_id else set())
                nested_text, nested_images = await _render_forward_nodes(
                    bot,
                    nested_nodes,
                    bot_keys=bot_keys,
                    identity_index=identity_index,
                    include_image_placeholder=include_image_placeholder,
                    depth=depth + 1,
                    visited_forward_ids=next_visited,
                )
            elif nested_id:
                if nested_id in visited_forward_ids:
                    nested_text = "[循环转发已跳过]"
                elif depth >= MAX_FORWARD_DEPTH:
                    nested_text = "[合并转发内容过深，已截断]"
                else:
                    try:
                        result = await bot.call_api("get_forward_msg", message_id=nested_id)
                    except Exception:
                        logger.warning("Failed to fetch nested forward message id=%s", nested_id, exc_info=True)
                        nested_text = ""
                    else:
                        nested_nodes = []
                        if isinstance(result, dict):
                            nested_nodes = result.get("messages", [])
                        elif hasattr(result, "messages"):
                            nested_nodes = result.messages
                        if nested_nodes:
                            nested_text, nested_images = await _render_forward_nodes(
                                bot,
                                list(nested_nodes),
                                bot_keys=bot_keys,
                                identity_index=identity_index,
                                include_image_placeholder=include_image_placeholder,
                                depth=depth + 1,
                                visited_forward_ids=visited_forward_ids | {nested_id},
                            )

            if nested_text:
                if plain_parts and not plain_parts[-1].endswith("\n"):
                    plain_parts.append("\n")
                plain_parts.append(nested_text)
            elif include_image_placeholder:
                plain_parts.append("[合并转发消息]")

            if nested_images:
                image_urls.extend(nested_images)
            continue

        text, segment_images, _ = render_segment_leaf(
            segment,
            bot_self_ids=bot_keys,
            identity_index=identity_index,
            include_image_placeholder=include_image_placeholder,
        )
        if text:
            plain_parts.append(text)
        if segment_images:
            image_urls.extend(segment_images)

    return "".join(plain_parts).strip(), image_urls


async def extract_forward_content(
    bot,
    message,
    bot_self_id,
    identity_index=None,
    *,
    bot_self_ids: Iterable[int | str] | None = None,
    reply=None,
):
    bot_keys = normalize_bot_self_ids(bot_self_id=bot_self_id, bot_self_ids=bot_self_ids)
    identities = identity_index or IdentityIndex()

    forward_id, raw_nodes = _extract_forward_payload(message)
    if not forward_id and not raw_nodes and reply is not None:
        for candidate in (getattr(reply, "message", None), getattr(reply, "raw_message", None)):
            if candidate is None:
                continue
            forward_id, raw_nodes = _extract_forward_payload(candidate)
            if forward_id or raw_nodes:
                break

    if not forward_id and not raw_nodes:
        return "", []

    if not raw_nodes and forward_id:
        try:
            result = await bot.call_api("get_forward_msg", message_id=forward_id)
        except Exception:
            logger.warning("Failed to fetch forward message id=%s", forward_id, exc_info=True)
            return "", []
        if isinstance(result, dict):
            raw_nodes = result.get("messages", [])
        elif hasattr(result, "messages"):
            raw_nodes = result.messages

    if not raw_nodes:
        return "", []

    return await _render_forward_nodes(
        bot,
        list(raw_nodes),
        bot_keys=bot_keys,
        identity_index=identities,
        include_image_placeholder=True,
        depth=0,
        visited_forward_ids={forward_id} if forward_id else set(),
    )
