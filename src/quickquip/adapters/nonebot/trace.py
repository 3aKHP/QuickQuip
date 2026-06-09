from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from quickquip.common.bot_action_trace import bot_action_trace, current_bot_action_trace


def _chat_type(event: Any) -> str:
    if getattr(event, "message_type", "") == "private" or getattr(event, "group_id", None) is None:
        return "private"
    return "group"


def _chat_ids(event: Any) -> tuple[str, str]:
    group_id = getattr(event, "group_id", "")
    user_id = getattr(event, "user_id", "")
    return str(group_id or ""), str(user_id or "")


def _message_preview(event: Any) -> str:
    try:
        return str(event.get_message()).strip()
    except Exception:
        return ""


def _message_id(event: Any) -> str:
    return str(getattr(event, "message_id", "") or "")


def traced_on_command(on_command: Callable[..., Any]) -> Callable[..., Any]:
    def _wrapped_on_command(name: str, *args: Any, **kwargs: Any) -> Any:
        matcher = on_command(name, *args, **kwargs)
        return _TracedMatcherProxy(matcher, name)

    return _wrapped_on_command


class _TracedMatcherProxy:
    def __init__(self, matcher: Any, command_name: str):
        self._matcher = matcher
        self._command_name = command_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._matcher, name)

    def handle(self, *handle_args: Any, **handle_kwargs: Any):
        decorator = self._matcher.handle(*handle_args, **handle_kwargs)
        command_name = self._command_name

        def _decorate(func):
            @wraps(func)
            async def _wrapped(*func_args: Any, **func_kwargs: Any):
                event = _extract_event(func_args, func_kwargs)
                if event is None or current_bot_action_trace() is not None:
                    return await func(*func_args, **func_kwargs)
                group_id, user_id = _chat_ids(event)
                with bot_action_trace(
                    trigger_kind="command",
                    reason_code=f"command.{command_name}",
                    reason_detail=f"命令触发：/{command_name}",
                    rule_name=f"command_{command_name}",
                    chat_type=_chat_type(event),
                    group_id=group_id,
                    user_id=user_id,
                    incoming_message_id=_message_id(event),
                    incoming_preview=_message_preview(event),
                    source="nonebot.command",
                ):
                    return await func(*func_args, **func_kwargs)

            return decorator(_wrapped)

        return _decorate


def _extract_event(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if "event" in kwargs:
        return kwargs["event"]
    for item in args:
        if hasattr(item, "get_message") or hasattr(item, "message_type"):
            return item
    return None
