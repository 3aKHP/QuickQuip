"""Stable client Session projections and isolated HTTP trace identities."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import secrets
from typing import TYPE_CHECKING
import uuid

from quickquip.llm.client_fingerprints.identity import load_install_id
from quickquip.llm.config_errors import ConfigError

if TYPE_CHECKING:
    from quickquip.llm.provider.base import LLMRequest
    from quickquip.llm.session import SessionIdentity

SESSION_BINDINGS = ("opencode_session_id", "project_id")
ATTEMPT_BINDINGS = ("b3", "traceparent")
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def opencode_session_id(session: SessionIdentity | None) -> str:
    """Project a persisted business identity into OpenCode's descending ID shape."""
    try:
        if session is None:
            raise ValueError("missing session")
        ident = uuid.UUID(session.id)
        if session.created_at.tzinfo is None:
            raise ValueError("missing timezone")
        milliseconds = int(session.created_at.timestamp() * 1000)
        if milliseconds < 0:
            raise ValueError("invalid creation time")
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ConfigError(
            "missing_session_identity", "Profile requires a business Session",
        ) from None
    prefix = (~((milliseconds << 12) | 1)) & ((1 << 48) - 1)
    digest = hashlib.sha256(f"quickquip:opencode-session:v1:{ident}".encode()).digest()
    return f"ses_{prefix:012x}" + "".join(_BASE62[b % 62] for b in digest[:14])


def deployment_project_id(data_dir: Path) -> str:
    """One opaque project per deployment, independent of host paths and chat IDs."""
    install = load_install_id(data_dir)
    return hashlib.sha1(
        f"quickquip:client-project:v1:{install}".encode(), usedforsecurity=False,
    ).hexdigest()


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


def attempt_bindings() -> dict[str, str]:
    call = _CALL.get()
    if call is None or not call.trace_id:
        raise ConfigError("missing_request_context", "Profile requires HTTP trace context")
    span = secrets.token_hex(8)
    return {
        "traceparent": f"00-{call.trace_id}-{span}-01",
        "b3": f"{call.trace_id}-{span}-1-{call.parent_span}",
    }
