from __future__ import annotations

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
    get_web_admin_session_max_age_hours,
    get_web_admin_session_ttl_hours,
    load_web_env,
)

load_web_env()

# --- 登录速率限制（H2）---
# 每 IP 最多 5 次失败 / 60 秒；超过后封禁 300 秒。
# 两个字典均有容量上限并周期性清扫过期键，伪造来源无法让它们无界增长；
# 容量占满时逐出最旧的键为新键腾位——限流跟踪不会因满载出现真空，
# 被逐出的代价只是对应来源的失败计数或封禁提前结束。
_LOGIN_WINDOW = 60       # 秒
_LOGIN_MAX_FAILS = 5
_LOGIN_BAN_SECONDS = 300
_LOGIN_TRACK_LIMIT = 4096
_LOGIN_SWEEP_INTERVAL = 60  # 秒

_login_lock = threading.Lock()
_login_fails: dict[str, list[float]] = {}   # ip -> [timestamp, ...]
_login_bans: dict[str, float] = {}          # ip -> ban_until
_login_last_sweep = 0.0

router = APIRouter()
logger = logging.getLogger(__name__)


def _sweep_login_state(now: float) -> None:
    """清扫窗口外的失败记录与已过期的封禁。调用方须持有 _login_lock。"""
    global _login_last_sweep
    if now - _login_last_sweep < _LOGIN_SWEEP_INTERVAL:
        return
    _login_last_sweep = now
    for ip in [
        ip
        for ip, stamps in _login_fails.items()
        if all(now - t >= _LOGIN_WINDOW for t in stamps)
    ]:
        _login_fails.pop(ip, None)
    for ip in [ip for ip, ban_until in _login_bans.items() if now >= ban_until]:
        _login_bans.pop(ip, None)


def _check_login_rate_limit(ip: str) -> None:
    """H2: 登录速率限制。超限时抛出 429。"""
    now = time.monotonic()
    with _login_lock:
        _sweep_login_state(now)
        ban_until = _login_bans.get(ip, 0)
        if now < ban_until:
            raise HTTPException(status_code=429, detail="too many failed attempts, try later")
        # 清理窗口外的记录
        fails = _login_fails.get(ip)
        if fails is not None:
            _login_fails[ip] = [t for t in fails if now - t < _LOGIN_WINDOW]


def _record_login_failure(ip: str) -> None:
    now = time.monotonic()
    with _login_lock:
        _sweep_login_state(now)
        fails = _login_fails.get(ip)
        if fails is None:
            if len(_login_fails) >= _LOGIN_TRACK_LIMIT:
                # 逐出最旧键而非拒收新来源：拒收会让满载后的新来源完全不受限流
                # （dict 保持插入序，首键即最旧）
                _login_fails.pop(next(iter(_login_fails)))
            fails = []
            _login_fails[ip] = fails
        fails.append(now)
        if len(fails) >= _LOGIN_MAX_FAILS:
            if len(_login_bans) >= _LOGIN_TRACK_LIMIT:
                _login_bans.pop(next(iter(_login_bans)))
            _login_bans[ip] = now + _LOGIN_BAN_SECONDS
            _login_fails.pop(ip, None)
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


def _session_max_age() -> timedelta:
    return timedelta(hours=get_web_admin_session_max_age_hours())


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


def _set_session_cookie(
    response: Response, request: Request, session_id: str, *, max_age: int
) -> None:
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


def _load_fresh_session(request: Request, response: Response) -> tuple[dict[str, str], datetime]:
    """读取会话并滑动续期；续期以 created_at + 绝对寿命为上界，超过即删除并要求重新登录。"""
    session_id = request.cookies.get(COOKIE_NAME, "").strip()
    if not session_id:
        raise HTTPException(status_code=401, detail="admin login required")

    store = _session_store()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="admin login required")

    now = _utc_now()
    try:
        created_at = datetime.fromisoformat(session["created_at"])
    except (KeyError, ValueError):
        # 存储行损坏时按失效处理，不为来源不明的会话重置绝对寿命
        store.delete_session(session_id)
        raise HTTPException(status_code=401, detail="session invalid, please login again") from None
    absolute_deadline = created_at + _session_max_age()
    if absolute_deadline <= now:
        store.delete_session(session_id)
        raise HTTPException(status_code=401, detail="session expired, please login again")

    expires_at = min(now + _session_ttl(), absolute_deadline)
    store.touch_session(session_id, expires_at=_format_dt(expires_at))
    _set_session_cookie(
        response, request, session_id,
        max_age=max(1, int((expires_at - now).total_seconds())),
    )
    request.state.admin_session = session
    return session, expires_at


def require_admin_session(request: Request, response: Response) -> dict[str, str]:
    _enforce_same_origin(request)
    session, _ = _load_fresh_session(request, response)
    return session


protected_dependencies = [Depends(require_admin_session)]


@router.get("/auth/me")
def get_auth_state(request: Request, response: Response):
    _, expires_at = _load_fresh_session(request, response)
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

    now = _utc_now()
    expires_at = now + min(_session_ttl(), _session_max_age())
    session = store.create_session(
        expires_at=_format_dt(expires_at),
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_session_cookie(
        response, request, session["session_id"],
        max_age=max(1, int((expires_at - now).total_seconds())),
    )
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
