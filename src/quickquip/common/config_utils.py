from __future__ import annotations

import os
import re
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_EXPANSION_ENVIRONMENT: ContextVar[Mapping[str, str] | None] = ContextVar(
    "configuration_expansion_environment", default=None
)


@contextmanager
def expansion_environment(environment: Mapping[str, str]):
    """Resolve configuration references against a supplied environment in this context."""
    token = _EXPANSION_ENVIRONMENT.set(environment)
    try:
        yield
    finally:
        _EXPANSION_ENVIRONMENT.reset(token)


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _expand_env_string(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        environment = _EXPANSION_ENVIRONMENT.get()
        resolved = os.getenv(key) if environment is None else environment.get(key)
        if resolved is None:
            return default or ""
        return resolved

    return _ENV_PATTERN.sub(_replace, value)


def expand_env_value(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env_string(value)
    if isinstance(value, list):
        return [expand_env_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): expand_env_value(item) for key, item in value.items()}
    return value
