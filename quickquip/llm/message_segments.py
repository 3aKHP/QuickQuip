from __future__ import annotations

from collections.abc import Iterable

from quickquip.llm.identity import IdentityIndex


def normalize_bot_self_ids(
    bot_self_id: int | str | None = None,
    bot_self_ids: Iterable[int | str] | None = None,
) -> set[str]:
    ids: set[str] = set()
    if bot_self_ids is not None:
        for item in bot_self_ids:
            key = str(item).strip()
            if key:
                ids.add(key)
    if bot_self_id is not None:
        key = str(bot_self_id).strip()
        if key:
            ids.add(key)
    return ids


def _segment_type_and_data(segment) -> tuple[str, dict[str, object]]:
    segment_type = getattr(segment, "type", None)
    data = getattr(segment, "data", None)
    if segment_type is None and isinstance(segment, dict):
        segment_type = segment.get("type", "")
    if data is None and isinstance(segment, dict):
        data = segment.get("data", {})
    return str(segment_type or ""), dict(data or {})


def message_has_segments(message) -> bool:
    try:
        segments = list(message)
    except TypeError:
        return False
    return bool(segments and any(hasattr(segment, "type") or isinstance(segment, dict) for segment in segments))


def render_segment_leaf(
    segment,
    *,
    bot_self_ids: Iterable[int | str] | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> tuple[str, list[str], bool]:
    bot_keys = normalize_bot_self_ids(bot_self_ids=bot_self_ids)
    identities = identity_index or IdentityIndex()
    segment_type, data = _segment_type_and_data(segment)

    if segment_type == "at":
        qq = str(data.get("qq", "")).strip()
        if qq and qq in bot_keys:
            return "", [], True
        if qq:
            return identities.render_mention(qq), [], False
        return "", [], False

    if segment_type == "text":
        return str(data.get("text", "")), [], False

    if segment_type == "image":
        url = str(data.get("url", "")).strip()
        file_value = str(data.get("file", "")).strip()
        image_urls: list[str] = []
        if url:
            image_urls.append(url)
        elif file_value.startswith("http://") or file_value.startswith("https://"):
            image_urls.append(file_value)
        text = "[图片]" if include_image_placeholder else ""
        return text, image_urls, False

    if segment_type == "forward" and include_image_placeholder:
        return "[合并转发消息]", [], False

    return "", [], False
