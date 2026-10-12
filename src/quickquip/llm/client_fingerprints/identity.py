"""Persistent deployment identity and installed client version."""
from __future__ import annotations

from functools import lru_cache
import hashlib
from importlib import metadata
import json
import logging
from pathlib import Path
import re
import uuid

from filelock import FileLock, Timeout

from quickquip.llm.config_durability import durable_write, ensure_directory
from quickquip.llm.config_errors import ConfigError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def client_version() -> str:
    try:
        return metadata.version("quickquip")
    except metadata.PackageNotFoundError:
        logger.warning("QuickQuip package metadata is unavailable; client version is unknown")
        return "unknown"


def load_install_id(data_dir: Path) -> str:
    """Create once under a cross-process lock; never replace damaged existing identity."""
    path = Path(data_dir) / "client_identity.json"
    try:
        ensure_directory(path.parent)
        with FileLock(str(path) + ".lock", timeout=10):
            if not path.exists():
                ident = hashlib.sha256(str(uuid.uuid4()).encode("utf-8")).hexdigest()
                durable_write(path, (json.dumps({"install_id": ident}) + "\n").encode("utf-8"))
            raw = json.loads(path.read_text(encoding="utf-8"))
            ident = raw.get("install_id") if isinstance(raw, dict) else None
            if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{64}", ident):
                raise ValueError("invalid installation identity")
            return ident
    except (OSError, ValueError, UnicodeError, Timeout) as exc:
        raise ConfigError(
            "client_identity_failed", "Cannot load persistent client identity",
        ) from exc
