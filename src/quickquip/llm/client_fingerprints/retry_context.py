"""Retry-policy index scoped to one dispatch, independent of tracing spans."""
from contextlib import contextmanager
from contextvars import ContextVar

_RETRY_INDEX = ContextVar("fingerprint_retry_index", default=0)


@contextmanager
def retry_context(index: int):
    token = _RETRY_INDEX.set(index)
    try:
        yield
    finally:
        _RETRY_INDEX.reset(token)


def retry_count() -> str:
    return str(_RETRY_INDEX.get())
