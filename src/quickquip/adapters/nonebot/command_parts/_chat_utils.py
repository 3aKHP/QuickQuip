from __future__ import annotations

from quickquip.common.event_utils import is_admin as _is_admin


def _is_private_chat(event) -> bool:
    return getattr(event, "message_type", "") == "private" or getattr(event, "group_id", None) is None


def _chat_type(event) -> str:
    return "private" if _is_private_chat(event) else "group"


def _chat_id(event):
    if _is_private_chat(event):
        return event.user_id
    return event.group_id


def _scope_key(event) -> str:
    chat_id = _chat_id(event)
    return f"private:{chat_id}" if _is_private_chat(event) else str(chat_id)


def _chat_label(event) -> str:
    return "当前私聊" if _is_private_chat(event) else "本群"


def _allow_scope_management(event) -> bool:
    return _is_private_chat(event) or _is_admin(event)
