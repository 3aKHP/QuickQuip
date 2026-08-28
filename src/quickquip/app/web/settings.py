from __future__ import annotations

import os
from pathlib import Path

from quickquip.common.env import load_project_env_files
from quickquip.common.paths import WEB_ADMIN_SESSIONS_DB_PATH

def load_web_env() -> None:
    load_project_env_files()


DEFAULT_WEB_ADMIN_HOST = "127.0.0.1"
DEFAULT_WEB_ADMIN_PORT = 5104


def get_web_admin_host() -> str:
    """WEB_ADMIN_HOST（.env），缺省/空白回退默认。web_api 与 webview_launcher 同源。"""
    load_web_env()
    return os.environ.get("WEB_ADMIN_HOST", DEFAULT_WEB_ADMIN_HOST).strip() or DEFAULT_WEB_ADMIN_HOST


def get_web_admin_port() -> int:
    """WEB_ADMIN_PORT（.env），非法值回退默认并收敛到 1-65535。"""
    load_web_env()
    raw = os.environ.get("WEB_ADMIN_PORT", str(DEFAULT_WEB_ADMIN_PORT)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WEB_ADMIN_PORT
    return min(max(value, 1), 65535)


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
    return WEB_ADMIN_SESSIONS_DB_PATH
