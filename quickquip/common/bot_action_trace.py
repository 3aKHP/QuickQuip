from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import json
import logging
from time import time
from typing import Any, Iterator
from uuid import uuid4

try:
    from loguru import logger as _logger
except ModuleNotFoundError:
    _logger = logging.getLogger(__name__)


_TRACE_MARK = "BOT_ACTION_TRACE"
_PREVIEW_LIMIT = 120


@dataclass(frozen=True, slots=True)
class BotActionTrace:
    trace_id: str
    trigger_kind: str = "unknown"
    reason_code: str = "unknown.unattributed"
    reason_detail: str = ""
    rule_name: str = ""
    chat_type: str = ""
    group_id: str = ""
    user_id: str = ""
    incoming_message_id: str = ""
    incoming_preview: str = ""
    reply_preview: str = ""
    llm_used: bool = False
    provider_id: str = ""
    model: str = ""
    source: str = ""


_current_trace: ContextVar[BotActionTrace | None] = ContextVar("quickquip_bot_action_trace", default=None)
_installed_api_hooks: set[str] = set()


def current_bot_action_trace() -> BotActionTrace | None:
    return _current_trace.get()


def _coerce(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    text = _coerce(value).replace("\r", "\\r").replace("\n", "\\n").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _message_types(message: Any) -> list[str]:
    if message is None:
        return []
    if isinstance(message, str):
        return ["text"] if message else []
    try:
        return [str(getattr(seg, "type", "")) for seg in message if getattr(seg, "type", "")]
    except TypeError:
        return [type(message).__name__]


def _infer_chat_fields(api: str, data: dict[str, Any], trace: BotActionTrace | None) -> tuple[str, str, str]:
    chat_type = trace.chat_type if trace else ""
    group_id = trace.group_id if trace else ""
    user_id = trace.user_id if trace else ""

    if not group_id and data.get("group_id") is not None:
        group_id = _coerce(data.get("group_id"))
    if not user_id and data.get("user_id") is not None:
        user_id = _coerce(data.get("user_id"))
    if not chat_type:
        if data.get("message_type") in {"group", "private"}:
            chat_type = _coerce(data.get("message_type"))
        elif group_id:
            chat_type = "group"
        elif user_id:
            chat_type = "private"
        elif api.startswith("send_group"):
            chat_type = "group"
        elif api.startswith("send_private"):
            chat_type = "private"
    return chat_type, group_id, user_id


def _sent_message_id(result: Any) -> str:
    if isinstance(result, dict):
        return _coerce(result.get("message_id"))
    return ""


def build_bot_action_trace_payload(
    *,
    api: str,
    data: dict[str, Any],
    result: Any = None,
    exception: Exception | None = None,
    trace: BotActionTrace | None = None,
) -> dict[str, Any]:
    active = trace or current_bot_action_trace()
    coverage_gap = active is None
    if active is None:
        active = BotActionTrace(
            trace_id=uuid4().hex,
            trigger_kind="unknown",
            reason_code="unknown.unattributed",
            reason_detail="no bot action trace context was set",
        )

    message = data.get("message")
    chat_type, group_id, user_id = _infer_chat_fields(api, data, active)
    reply_preview = active.reply_preview or _preview(message)

    return {
        "trace_id": active.trace_id,
        "trigger_kind": active.trigger_kind,
        "reason_code": active.reason_code,
        "reason_detail": active.reason_detail,
        "rule_name": active.rule_name,
        "chat_type": chat_type,
        "group_id": group_id,
        "user_id": user_id,
        "incoming_message_id": active.incoming_message_id,
        "incoming_preview": active.incoming_preview,
        "api": api,
        "outcome": "failed" if exception else "sent",
        "error": "" if exception is None else f"{type(exception).__name__}: {_preview(exception, 240)}",
        "sent_message_id": "" if exception else _sent_message_id(result),
        "message_types": _message_types(message),
        "reply_preview": reply_preview,
        "llm_used": active.llm_used,
        "provider_id": active.provider_id,
        "model": active.model,
        "source": active.source,
        "coverage_gap": coverage_gap,
        "ts": time(),
    }


def log_bot_action_trace(
    *,
    api: str,
    data: dict[str, Any],
    result: Any = None,
    exception: Exception | None = None,
    trace: BotActionTrace | None = None,
) -> dict[str, Any]:
    payload = build_bot_action_trace_payload(
        api=api,
        data=data,
        result=result,
        exception=exception,
        trace=trace,
    )
    _logger.info(f"{_TRACE_MARK} {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
    return payload


@contextmanager
def bot_action_trace(
    *,
    trigger_kind: str,
    reason_code: str,
    reason_detail: str = "",
    rule_name: str = "",
    chat_type: str = "",
    group_id: int | str | None = None,
    user_id: int | str | None = None,
    incoming_message_id: int | str | None = None,
    incoming_preview: str = "",
    reply_preview: str = "",
    llm_used: bool = False,
    provider_id: str = "",
    model: str = "",
    source: str = "",
) -> Iterator[BotActionTrace]:
    parent = current_bot_action_trace()
    trace_id = parent.trace_id if parent else uuid4().hex
    next_trace = BotActionTrace(
        trace_id=trace_id,
        trigger_kind=trigger_kind,
        reason_code=reason_code,
        reason_detail=reason_detail,
        rule_name=rule_name,
        chat_type=chat_type,
        group_id=_coerce(group_id),
        user_id=_coerce(user_id),
        incoming_message_id=_coerce(incoming_message_id),
        incoming_preview=_preview(incoming_preview),
        reply_preview=_preview(reply_preview),
        llm_used=llm_used,
        provider_id=provider_id,
        model=model,
        source=source,
    )
    token = _current_trace.set(next_trace)
    try:
        yield next_trace
    finally:
        _current_trace.reset(token)


@contextmanager
def overlay_bot_action_trace(**updates: Any) -> Iterator[BotActionTrace]:
    parent = current_bot_action_trace()
    if parent is None:
        with bot_action_trace(
            trigger_kind=updates.pop("trigger_kind", "unknown"),
            reason_code=updates.pop("reason_code", "unknown.unattributed"),
            **updates,
        ) as trace:
            yield trace
        return

    normalized = {
        key: _coerce(value) if key in {"group_id", "user_id", "incoming_message_id"} else value
        for key, value in updates.items()
    }
    if "incoming_preview" in normalized:
        normalized["incoming_preview"] = _preview(normalized["incoming_preview"])
    if "reply_preview" in normalized:
        normalized["reply_preview"] = _preview(normalized["reply_preview"])
    token = _current_trace.set(replace(parent, **normalized))
    try:
        yield _current_trace.get()  # type: ignore[misc]
    finally:
        _current_trace.reset(token)


def install_nonebot_api_trace_hook(BotClass: type[Any]) -> bool:
    key = f"{BotClass.__module__}.{BotClass.__qualname__}"
    if key in _installed_api_hooks:
        return False

    @BotClass.on_called_api
    async def _quickquip_bot_action_trace_hook(bot, exception, api: str, data: dict[str, Any], result: Any) -> None:
        if not _is_action_api(api):
            return
        log_bot_action_trace(api=api, data=data, result=result, exception=exception)

    _installed_api_hooks.add(key)
    return True


def _is_action_api(api: str) -> bool:
    return api in {
        "send_msg",
        "send_group_msg",
        "send_private_msg",
        "send_group_forward_msg",
        "send_private_forward_msg",
        "delete_msg",
    } or api.startswith("set_group_")
