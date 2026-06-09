from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sqlite3

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebAdminSessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._unavailable = False
        try:
            self._ensure_schema()
        except sqlite3.Error as exc:
            logger.error("WebAdminSessionStore 数据库初始化失败 (%s)：%s", self.path, exc)
            self._unavailable = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    client_ip TEXT,
                    user_agent TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires_at
                ON admin_sessions(expires_at);
                """
            )

    def purge_expired_sessions(self, *, now: str | None = None) -> int:
        if self._unavailable:
            raise RuntimeError("Web管理会话 数据库不可用")
        threshold = now or _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?",
                (threshold,),
            )
            return int(cursor.rowcount)

    def create_session(
        self,
        *,
        expires_at: str,
        client_ip: str = "",
        user_agent: str = "",
    ) -> dict[str, str]:
        if self._unavailable:
            raise RuntimeError("Web管理会话 数据库不可用")
        self.purge_expired_sessions()
        session_id = secrets.token_urlsafe(32)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions (session_id, created_at, expires_at, last_seen_at, client_ip, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    now,
                    expires_at,
                    now,
                    client_ip or None,
                    user_agent or None,
                ),
            )
        return {
            "session_id": session_id,
            "created_at": now,
            "expires_at": expires_at,
            "last_seen_at": now,
        }

    def get_session(self, session_id: str) -> dict[str, str] | None:
        if self._unavailable:
            raise RuntimeError("Web管理会话 数据库不可用")
        self.purge_expired_sessions()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, created_at, expires_at, last_seen_at, client_ip, user_agent
                FROM admin_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def touch_session(self, session_id: str, *, expires_at: str) -> bool:
        if self._unavailable:
            raise RuntimeError("Web管理会话 数据库不可用")
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE admin_sessions
                SET expires_at = ?, last_seen_at = ?
                WHERE session_id = ?
                """,
                (expires_at, now, session_id),
            )
            return int(cursor.rowcount) > 0

    def delete_session(self, session_id: str) -> bool:
        if self._unavailable:
            raise RuntimeError("Web管理会话 数据库不可用")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM admin_sessions WHERE session_id = ?",
                (session_id,),
            )
            return int(cursor.rowcount) > 0
