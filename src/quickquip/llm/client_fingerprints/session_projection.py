"""Stable business Session and deployment projections for client Profiles."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

from quickquip.llm.client_fingerprints.identity import load_install_id
from quickquip.llm.config_errors import ConfigError

if TYPE_CHECKING:
    from quickquip.llm.session import SessionIdentity

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


SESSION_BINDINGS = {
    "opencode_session_id": lambda request, data_dir: opencode_session_id(request.session),
    "project_id": lambda request, data_dir: deployment_project_id(data_dir),
}
