"""Request-scoped context and coherent tracing for physical HTTP attempts."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
import os
import secrets
from typing import TYPE_CHECKING

from quickquip.llm.config_errors import ConfigError

if TYPE_CHECKING:
    from quickquip.llm.provider.base import LLMRequest


@dataclass(frozen=True, slots=True)
class FingerprintCall:
    request: LLMRequest
    trace_id: str
    parent_span: str


_CALL: ContextVar[FingerprintCall | None] = ContextVar("fingerprint_call", default=None)


@lru_cache(maxsize=1)
def _process_trace(pid: int) -> str:
    # PID is part of the cache key so a fork never inherits the parent's trace identity.
    return secrets.token_hex(16)


@contextmanager
def request_context(request: LLMRequest, *, tracing: bool):
    call = FingerprintCall(
        request, _process_trace(os.getpid()) if tracing else "",
        secrets.token_hex(8) if tracing else "",
    )
    token = _CALL.set(call)
    try:
        yield
    finally:
        _CALL.reset(token)


def current_request() -> LLMRequest:
    call = _CALL.get()
    if call is None:
        raise ConfigError("missing_request_context", "Profile requires complete() request context")
    return call.request


ATTEMPT_BINDINGS = {
    "traceparent": lambda call, span: f"00-{call.trace_id}-{span}-01",
    "b3": lambda call, span: f"{call.trace_id}-{span}-1-{call.parent_span}",
}


def attempt_bindings() -> dict[str, str]:
    call = _CALL.get()
    if call is None or not call.trace_id:
        raise ConfigError("missing_request_context", "Profile requires HTTP trace context")
    span = secrets.token_hex(8)
    return {source: build(call, span) for source, build in ATTEMPT_BINDINGS.items()}
