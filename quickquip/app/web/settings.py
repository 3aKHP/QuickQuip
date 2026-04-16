from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_ENV_LOADED = False


def load_web_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / "dev/.env", override=True)
    _ENV_LOADED = True


def get_web_admin_password() -> str:
    load_web_env()
    return os.environ.get("WEB_ADMIN_PASSWORD", "")


def get_web_admin_session_ttl_hours() -> int:
    load_web_env()
    raw = os.environ.get("WEB_ADMIN_SESSION_TTL_HOURS", "168").strip()
    try:
        value = int(raw)
    except ValueError:
        return 168
    return min(max(value, 1), 24 * 365)


def get_web_admin_cookie_secure_mode() -> str:
    load_web_env()
    raw = os.environ.get("WEB_ADMIN_COOKIE_SECURE", "auto").strip().lower()
    if raw in {"true", "false", "auto"}:
        return raw
    return "auto"


def get_web_admin_session_db_path() -> Path:
    return PROJECT_ROOT / "data" / "web_admin_sessions.db"
