"""Business-owned session identities and the client projection input contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Immutable identity of one continuing chat or independent operation."""

    id: str
    created_at: datetime


SessionProjector = Callable[[SessionIdentity], str]


def create_session_identity() -> SessionIdentity:
    """Allocate at the business entrypoint, once per new interaction."""
    return SessionIdentity(str(uuid4()), datetime.now(timezone.utc))


class SessionStoreError(RuntimeError):
    """A persistent chat identity could not be safely read or changed."""


class SessionInvalidated(RuntimeError):
    """The captured chat session or its write generation is no longer current."""
