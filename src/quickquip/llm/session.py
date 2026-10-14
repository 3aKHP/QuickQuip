"""Business-owned session identities and the client projection input contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, InitVar
from datetime import datetime, timezone
from uuid import uuid4
from threading import Lock


class SessionModelProjection:
    """First-use model anchors, owned by the continuing business interaction."""

    def __init__(self, persist: Callable[[str, str], str] | None = None):
        self._persist = persist
        self._models: dict[str, str] = {}
        self._lock = Lock()

    def get_or_bind_model(self, client: str, model: str) -> str:
        with self._lock:
            if self._persist is not None:
                # The store also fences late requests against session transitions.
                return self._persist(client, model)
            return self._models.setdefault(client, model)


class _SessionProjectionOwner:
    # Runtime behavior stays outside the identity's serialized dataclass fields.
    __slots__ = ("_model_projection",)

    @property
    def model_projection(self) -> SessionModelProjection:
        return self._model_projection


@dataclass(frozen=True, slots=True)
class SessionIdentity(_SessionProjectionOwner):
    """Immutable identity of one continuing chat or independent operation."""

    id: str
    created_at: datetime
    projection: InitVar[SessionModelProjection | None] = None

    def __post_init__(self, projection):
        object.__setattr__(self, "_model_projection", projection or SessionModelProjection())

    def __deepcopy__(self, memo):
        # A copied request still belongs to the same immutable business identity.
        memo[id(self)] = self
        return self


SessionProjector = Callable[[SessionIdentity], str]


def create_session_identity() -> SessionIdentity:
    """Allocate at the business entrypoint, once per new interaction."""
    return SessionIdentity(str(uuid4()), datetime.now(timezone.utc))


class SessionStoreError(RuntimeError):
    """A persistent chat identity could not be safely read or changed."""


class SessionInvalidated(RuntimeError):
    """The captured chat session or its write generation is no longer current."""
