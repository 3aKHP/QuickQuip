from __future__ import annotations

from quickquip.chat.festival import get_active_festival, get_festival_greeting

__all__ = ["format_greeting_message"]


def format_greeting_message() -> str | None:
    """Format a decorated festival greeting message for group sending.

    Returns a message like 【春节】新春快乐！给大家拜年啦，...
    or None when no festival is active.
    """
    festival = get_active_festival()
    if festival is None:
        return None
    greeting = get_festival_greeting()
    if greeting is None:
        return None
    return f"【{festival.name}】{greeting}"
