from __future__ import annotations

import logging
from typing import Any

from quickquip.common.sensitive_filter import (
    DEFAULT_OUTPUT_FALLBACK,
    SensitiveFilter,
    get_filter,
    log_hits,
)

logger = logging.getLogger(__name__)

_SINGLE_MESSAGE_APIS = frozenset({"send_msg", "send_group_msg", "send_private_msg"})
_FORWARD_MESSAGE_APIS = frozenset({"send_group_forward_msg", "send_private_forward_msg"})
_GUARDED_APIS = _SINGLE_MESSAGE_APIS | _FORWARD_MESSAGE_APIS
_MAX_EXTRACT_DEPTH = 8

_installed_guard_hooks: set[str] = set()


def _infer_scope(api: str, data: dict[str, Any]) -> str:
    group_id = data.get("group_id")
    if group_id is not None and str(group_id).strip():
        return str(group_id)
    user_id = data.get("user_id")
    if user_id is not None and str(user_id).strip():
        return f"private:{user_id}"
    return f"unknown:{api}"


def _is_text_segment(item: Any) -> bool:
    if isinstance(item, dict):
        return item.get("type") == "text"
    if isinstance(item, (str, list, tuple)):
        return False
    return getattr(item, "type", "") == "text"


def _extract_text_parts(payload: Any, *, _depth: int = 0) -> list[str]:
    """Recursively extract plain text segments from OneBot message payloads."""
    if payload is None or _depth > _MAX_EXTRACT_DEPTH:
        return []
    if isinstance(payload, str):
        return [payload] if payload else []

    if isinstance(payload, dict):
        seg_type = str(payload.get("type", ""))
        seg_data = payload.get("data")
        if not isinstance(seg_data, dict):
            return []
        if seg_type == "text":
            text = seg_data.get("text")
            return [text] if isinstance(text, str) and text else []
        if seg_type == "node":
            return _extract_text_parts(seg_data.get("content"), _depth=_depth + 1)
        return []

    if isinstance(payload, (list, tuple)):
        parts: list[str] = []
        text_buf: list[str] = []
        for item in payload:
            extracted = _extract_text_parts(item, _depth=_depth + 1)
            if _is_text_segment(item):
                text_buf.extend(extracted)
            else:
                if text_buf:
                    parts.append("".join(text_buf))
                    text_buf.clear()
                parts.extend(extracted)
        if text_buf:
            parts.append("".join(text_buf))
        return parts

    seg_type = getattr(payload, "type", None)
    seg_data = getattr(payload, "data", None)
    if isinstance(seg_type, str) and isinstance(seg_data, dict):
        if seg_type == "text":
            text = seg_data.get("text")
            return [text] if isinstance(text, str) and text else []
        if seg_type == "node":
            return _extract_text_parts(seg_data.get("content"), _depth=_depth + 1)
    return []


def _build_safe_message() -> list[dict[str, Any]]:
    return [{"type": "text", "data": {"text": DEFAULT_OUTPUT_FALLBACK}}]


def _build_safe_forward_messages(bot: Any, original_messages: Any) -> list[dict[str, Any]]:
    uin = str(getattr(bot, "self_id", "") or "0")
    name = "Bot"
    if isinstance(original_messages, (list, tuple)) and original_messages:
        first = original_messages[0]
        first_data = (
            first.get("data") if isinstance(first, dict) else getattr(first, "data", None)
        )
        if isinstance(first_data, dict):
            uin = str(first_data.get("uin") or first_data.get("user_id") or uin)
            name = str(first_data.get("name") or first_data.get("nickname") or name)
    return [
        {
            "type": "node",
            "data": {
                "name": name,
                "uin": uin,
                "content": _build_safe_message(),
            },
        }
    ]


def guard_outbound_api_call(
    bot: Any,
    api: str,
    data: dict[str, Any],
    *,
    sensitive_filter: SensitiveFilter | None = None,
) -> bool:
    """Scan outgoing OneBot API payload text; replace with fallback when blocked."""
    if api not in _GUARDED_APIS:
        return False
    sf = sensitive_filter if sensitive_filter is not None else get_filter()
    if not sf.is_loaded:
        return False

    field = "messages" if api in _FORWARD_MESSAGE_APIS else "message"
    try:
        payload = data.get(field)
        parts = _extract_text_parts(payload)
        if not parts:
            return False

        result = sf.scan("\n".join(parts))
        if not result.hits:
            return False

        log_hits(f"outbound_api:{api}", _infer_scope(api, data), result)
        if not result.blocked:
            return False

        # Rebind data[field] without mutating caller-owned Message/list/dict objects.
        if field == "messages":
            data["messages"] = _build_safe_forward_messages(bot, payload)
        else:
            data["message"] = _build_safe_message()
        return True
    except Exception:
        logger.exception("outbound_guard failed on api=%s; failing closed", api)
        if field == "messages":
            data["messages"] = _build_safe_forward_messages(bot, None)
        else:
            data["message"] = _build_safe_message()
        return True


def install_nonebot_outbound_guard(BotClass: type[Any]) -> bool:
    key = f"{BotClass.__module__}.{BotClass.__qualname__}"
    if key in _installed_guard_hooks:
        return False

    @BotClass.on_calling_api
    async def _quickquip_outbound_guard_hook(
        bot: Any, api: str, data: dict[str, Any]
    ) -> None:
        guard_outbound_api_call(bot, api, data)

    _installed_guard_hooks.add(key)
    return True
