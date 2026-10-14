"""Persistent deployment identity and installed client version."""
from __future__ import annotations

from functools import lru_cache
import hashlib
from importlib import metadata
import json
import logging
from pathlib import Path
import re
import secrets
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


def normalize_device_id(value: str, location="settings.runtime.claude_code_device_id") -> str:
    if not isinstance(value, str):
        raise ConfigError("invalid_field", "Device identity must be a string", location)
    value = value.strip().lower()
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ConfigError("invalid_field", "Device identity requires 64 hexadecimal characters",
                          location)
    return value


def load_claude_device_id(data_dir: Path, override: str = "") -> str:
    """One persistent random CC identity; explicit settings do not touch the automatic value."""
    override = normalize_device_id(override)
    if override:
        return override
    load_install_id(data_dir)
    path = Path(data_dir) / "client_identity.json"
    try:
        with FileLock(str(path) + ".lock", timeout=10):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw.get("install_id", "")),
            ):
                raise ValueError("invalid installation identity")
            if "claude_code_device_id" not in raw:
                raw["claude_code_device_id"] = secrets.token_hex(32)
                durable_write(path, (json.dumps(raw) + "\n").encode("utf-8"))
            value = raw["claude_code_device_id"]
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("invalid CC identity")
            return value
    except (OSError, ValueError, UnicodeError, Timeout) as exc:
        raise ConfigError("client_identity_failed",
                          "Cannot load persistent CC device identity") from exc


def normalize_gemini_install_id(value: str, location="settings.runtime.gemini_cli_install_id"):
    if not isinstance(value, str):
        raise ConfigError("invalid_field", "Installation identity must be a string", location)
    value = value.strip()
    if not value:
        return ""
    try:
        ident = uuid.UUID(value)
        if ident.version != 4:
            raise ValueError("not UUIDv4")
    except ValueError:
        raise ConfigError("invalid_field", "Installation identity requires UUIDv4",
                          location) from None
    return str(ident)


def load_gemini_install_id(data_dir: Path, override: str = "") -> str:
    """Preserve the independent automatic identity when an administrator overrides it."""
    override = normalize_gemini_install_id(override)
    if override:
        return override
    load_install_id(data_dir)
    path = Path(data_dir) / "client_identity.json"
    try:
        with FileLock(str(path) + ".lock", timeout=10):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw.get("install_id", "")),
            ):
                raise ValueError("invalid installation identity")
            if "gemini_cli_install_id" not in raw:
                raw["gemini_cli_install_id"] = str(uuid.uuid4())
                durable_write(path, (json.dumps(raw) + "\n").encode("utf-8"))
            value = normalize_gemini_install_id(raw["gemini_cli_install_id"])
            if not value:
                raise ValueError("empty Gemini installation identity")
            return value
    except (OSError, ValueError, UnicodeError, Timeout, ConfigError) as exc:
        raise ConfigError("client_identity_failed",
                          "Cannot load persistent Gemini installation identity") from exc
