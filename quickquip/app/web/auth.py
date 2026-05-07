from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hmac
import logging
import threading
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from quickquip.app.web.session_store import WebAdminSessionStore
from quickquip.app.web.settings import (
    get_web_admin_cookie_secure_mode,
    get_web_admin_password,
    get_web_admin_session_db_path,
    get_web_admin_session_ttl_hours,
    load_web_env,
)

load_web_env()

# --- 登录速率限制（H2）---
# 每 IP 最多 5 次失败 / 60 秒；超过后封禁 300 秒
_LOGIN_WINDOW = 60       # 秒
_LOGIN_MAX_FAILS = 5
_LOGIN_BAN_SECONDS = 300

_login_lock = threading.Lock()
_login_fails: dict[str, list[float]] = defaultdict(list)  # ip -> [timestamp, ...]
_login_bans: dict[str, float] = {}                         # ip -> ban_until

router = APIRouter()
logger = logging.getLogger(__name__)


def _check_login_rate_limit(ip: str) -> None:
    """H2: 登录速率限制。超限时抛出 429。"""
    now = time.monotonic()
    with _login_lock:
        ban_until = _login_bans.get(ip, 0)
        if now < ban_until:
            raise HTTPException(status_code=429, detail="too many failed attempts, try later")
        # 清理窗口外的记录
        _login_fails[ip] = [t for t in _login_fails[ip] if now - t < _LOGIN_WINDOW]


def _record_login_failure(ip: str) -> None:
    now = time.monotonic()
    with _login_lock:
        _login_fails[ip].append(now)
        if len(_login_fails[ip]) >= _LOGIN_MAX_FAILS:
            _login_bans[ip] = now + _LOGIN_BAN_SECONDS
            _login_fails[ip] = []
            logger.warning("web admin login: ip=%s banned for %ds", ip, _LOGIN_BAN_SECONDS)


def _clear_login_failures(ip: str) -> None:
    with _login_lock:
        _login_fails.pop(ip, None)
        _login_bans.pop(ip, None)

COOKIE_NAME = "quickquip_admin_session"
COOKIE_PATH = "/ops"


class LoginBody(BaseModel):
    password: str = Field(max_length=4096)


@lru_cache(maxsize=1)
def _session_store() -> WebAdminSessionStore:
    return WebAdminSessionStore(get_web_admin_session_db_path())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl() -> timedelta:
    return timedelta(hours=get_web_admin_session_ttl_hours())


def _format_dt(value: datetime) -> str:
    return value.isoformat()


def _get_client_ip(request: Request) -> str:
    from quickquip.app.web.client_ip import get_client_ip
    return get_client_ip(request)


def _request_scheme(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip()
    return request.url.scheme


def _cookie_secure(request: Request) -> bool:
    mode = get_web_admin_cookie_secure_mode()
    if mode == "true":
        return True
    if mode == "false":
        return False
    return _request_scheme(request) == "https"


def _set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    max_age = int(_session_ttl().total_seconds())
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path=COOKIE_PATH,
    )


def _expected_origin(request: Request) -> tuple[str, str]:
    scheme = _request_scheme(request)
    host = request.headers.get("x-forwarded-host", "") or request.headers.get("host", "")
    if not host:
        host = request.url.netloc
    return scheme, host


def _origin_matches_request(request: Request, value: str) -> bool:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return False
    expected_scheme, expected_host = _expected_origin(request)
    return parsed.scheme == expected_scheme and parsed.netloc == expected_host


def _enforce_same_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    origin = request.headers.get("origin", "").strip()
    if origin:
        if not _origin_matches_request(request, origin):
            raise HTTPException(status_code=403, detail="cross-site request rejected")
        return

    referer = request.headers.get("referer", "").strip()
    if referer:
        if not _origin_matches_request(request, referer):
            raise HTTPException(status_code=403, detail="cross-site request rejected")
        return

    # M4: Origin 和 Referer 都缺失时拒绝，而不是放行
    raise HTTPException(status_code=403, detail="missing origin header")


def require_admin_session(request: Request, response: Response) -> dict[str, str]:
    _enforce_same_origin(request)

    session_id = request.cookies.get(COOKIE_NAME, "").strip()
    if not session_id:
        raise HTTPException(status_code=401, detail="admin login required")

    store = _session_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="admin login required")

    expires_at = _utc_now() + _session_ttl()
    store.touch_session(session_id, expires_at=_format_dt(expires_at))
    _set_session_cookie(response, request, session_id)
    request.state.admin_session = session
    return session


protected_dependencies = [Depends(require_admin_session)]


@router.get("/auth/me")
def get_auth_state(request: Request, response: Response):
    session_id = request.cookies.get(COOKIE_NAME, "").strip()
    if not session_id:
        raise HTTPException(status_code=401, detail="admin login required")

    session = _session_store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="admin login required")

    expires_at = _utc_now() + _session_ttl()
    _session_store().touch_session(session_id, expires_at=_format_dt(expires_at))
    _set_session_cookie(response, request, session_id)
    return {
        "authenticated": True,
        "expires_at": _format_dt(expires_at),
    }


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    _enforce_same_origin(request)
    client_ip = _get_client_ip(request)
    _check_login_rate_limit(client_ip)  # H2: 速率限制检查

    password = get_web_admin_password()
    if not password:
        raise HTTPException(status_code=500, detail="WEB_ADMIN_PASSWORD not configured")
    if not hmac.compare_digest(body.password, password):
        _record_login_failure(client_ip)  # H2: 记录失败
        logger.warning("web admin login failed: ip=%s", client_ip)
        raise HTTPException(status_code=401, detail="invalid password")

    _clear_login_failures(client_ip)  # H2: 登录成功，清除失败记录
    store = _session_store()
    existing_session_id = request.cookies.get(COOKIE_NAME, "").strip()
    if existing_session_id:
        store.delete_session(existing_session_id)

    session = store.create_session(
        expires_at=_format_dt(_utc_now() + _session_ttl()),
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(response, request, session["session_id"])
    logger.info("web admin login succeeded: ip=%s", client_ip)
    return {
        "ok": True,
        "expires_at": session["expires_at"],
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    _enforce_same_origin(request)
    session_id = request.cookies.get(COOKIE_NAME, "").strip()
    if session_id:
        _session_store().delete_session(session_id)
    _clear_session_cookie(response, request)
    return {"ok": True}
