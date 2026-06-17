"""Pure utility functions for NoneBot event inspection.

Extracted from ``app/message_pipeline.py`` — these helpers take a NoneBot
``Event`` and extract sender/admin/self info or strip command prefixes.
They depend only on duck-typed event attributes (``sender``, ``user_id``,
``self_id``) and carry no QuickQuip-internal state, so they belong in the
``common`` layer rather than the ``app`` assembly module.

``message_pipeline`` re-exports them for backward compatibility; downstream
modules should gradually switch to importing directly from here.
"""
from __future__ import annotations


def get_sender_name(event) -> str:
    sender = getattr(event, "sender", None)
    if sender:
        if getattr(sender, "card", None):
            return sender.card
        if getattr(sender, "nickname", None):
            return sender.nickname
    return str(event.user_id)


def is_admin(event) -> bool:
    sender = getattr(event, "sender", None)
    if sender:
        role = getattr(sender, "role", None)
        if role in ("admin", "owner"):
            return True
    return False


def is_self_message(event) -> bool:
    return str(getattr(event, "user_id", "")) == str(getattr(event, "self_id", ""))


def strip_command_name(text: str, command_name: str) -> str:
    normalized = text.strip()
    prefixes = (f"/{command_name}", f"!{command_name}", command_name)
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return normalized[len(prefix):].strip()
    return normalized
