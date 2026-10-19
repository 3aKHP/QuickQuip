"""登录限流容量上限/清扫与会话生命周期（绝对过期、哈希落库）测试。"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quickquip.app.web import auth
from quickquip.app.web.session_store import WebAdminSessionStore


@pytest.fixture(autouse=True)
def reset_login_state(monkeypatch):
    monkeypatch.setattr(auth, "_login_fails", {})
    monkeypatch.setattr(auth, "_login_bans", {})
    monkeypatch.setattr(auth, "_login_last_sweep", 0.0)


class TestLoginRateLimitBounds:
    def test_ban_still_triggers_below_cap(self):
        for _ in range(auth._LOGIN_MAX_FAILS):
            auth._record_login_failure("1.2.3.4")
        with pytest.raises(Exception) as exc_info:
            auth._check_login_rate_limit("1.2.3.4")
        assert getattr(exc_info.value, "status_code", None) == 429

    def test_new_key_not_tracked_when_fails_dict_at_cap(self, monkeypatch):
        monkeypatch.setattr(auth, "_LOGIN_TRACK_LIMIT", 2)
        auth._record_login_failure("1.1.1.1")
        auth._record_login_failure("2.2.2.2")
        auth._record_login_failure("3.3.3.3")
        assert set(auth._login_fails) == {"1.1.1.1", "2.2.2.2"}

    def test_sweep_removes_stale_fails_and_expired_bans(self, monkeypatch):
        monkeypatch.setattr(auth, "_LOGIN_SWEEP_INTERVAL", 0)
        now = 1000.0
        auth._login_fails["old"] = [now - auth._LOGIN_WINDOW - 1]
        auth._login_fails["fresh"] = [now - 1]
        auth._login_bans["expired"] = now - 1
        auth._login_bans["active"] = now + 100
        monkeypatch.setattr(auth.time, "monotonic", lambda: now)
        auth._check_login_rate_limit("unrelated")
        assert set(auth._login_fails) == {"fresh"}
        assert set(auth._login_bans) == {"active"}

    def test_sweep_frees_capacity_for_new_keys(self, monkeypatch):
        monkeypatch.setattr(auth, "_LOGIN_TRACK_LIMIT", 1)
        monkeypatch.setattr(auth, "_LOGIN_SWEEP_INTERVAL", 0)
        now = 1000.0
        auth._login_fails["stale"] = [now - auth._LOGIN_WINDOW - 1]
        monkeypatch.setattr(auth.time, "monotonic", lambda: now)
        auth._record_login_failure("new")
        assert set(auth._login_fails) == {"new"}


@pytest.fixture
def client(monkeypatch, tmp_path, config_service):
    monkeypatch.setattr(auth, "get_web_admin_password", lambda: "test-admin-password")
    sessions = WebAdminSessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(auth, "_session_store", lambda: sessions)
    app = FastAPI()
    app.include_router(auth.router, prefix="/ops/api")
    with TestClient(app, headers={"origin": "http://testserver"}) as result:
        result.sessions = sessions
        yield result


def _login(client) -> str:
    response = client.post("/ops/api/auth/login", json={"password": "test-admin-password"})
    assert response.status_code == 200
    return response.cookies[auth.COOKIE_NAME]


def _backdate_created_at(store: WebAdminSessionStore, session_id: str, *, hours: float) -> None:
    created = datetime.now(timezone.utc) - timedelta(hours=hours)
    key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE admin_sessions SET created_at = ? WHERE session_id = ?",
            (created.isoformat(), key),
        )


class TestSessionAbsoluteExpiry:
    def test_session_past_absolute_max_age_is_deleted(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_web_admin_session_ttl_hours", lambda: 24)
        monkeypatch.setattr(auth, "get_web_admin_session_max_age_hours", lambda: 24)
        session_id = _login(client)
        _backdate_created_at(client.sessions, session_id, hours=25)

        response = client.get("/ops/api/auth/me")

        assert response.status_code == 401
        assert client.sessions.get_session(session_id) is None

    def test_sliding_renewal_is_capped_by_absolute_deadline(self, client, monkeypatch):
        monkeypatch.setattr(auth, "get_web_admin_session_ttl_hours", lambda: 24)
        monkeypatch.setattr(auth, "get_web_admin_session_max_age_hours", lambda: 24)
        session_id = _login(client)
        _backdate_created_at(client.sessions, session_id, hours=23.5)

        response = client.get("/ops/api/auth/me")

        assert response.status_code == 200
        expires_at = datetime.fromisoformat(response.json()["expires_at"])
        # 续期结果被绝对寿命截断在 30 分钟附近，而不是完整滑动 24 小时
        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 0 < remaining < 3600


class TestSessionIdHashing:
    def test_db_stores_only_sha256_of_session_id(self, client):
        session_id = _login(client)
        with sqlite3.connect(client.sessions.path) as conn:
            rows = conn.execute("SELECT session_id FROM admin_sessions").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        assert rows[0][0] != session_id

    def test_logout_invalidates_server_side_session(self, client):
        _login(client)
        assert client.post("/ops/api/auth/logout").status_code == 200
        assert client.get("/ops/api/auth/me").status_code == 401
