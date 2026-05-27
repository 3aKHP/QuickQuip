from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quickquip.common.paths import WEB_ADMIN_ACTIONS_DB_PATH


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class WebAdminAction:
    id: str
    action_type: str
    payload: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: str = ""


class WebAdminActionQueue:
    def __init__(self, path: str | Path = WEB_ADMIN_ACTIONS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_admin_actions (
                    id           TEXT PRIMARY KEY,
                    action_type  TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    result_json  TEXT,
                    error        TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_web_admin_actions_status_created
                ON web_admin_actions(status, created_at)
                """
            )

    def _reap_stale_running_locked(self, conn: sqlite3.Connection, timeout_seconds: int = 300) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(1, int(timeout_seconds)))).isoformat()
        cur = conn.execute(
            """
            UPDATE web_admin_actions
            SET status = 'failed', updated_at = ?, error = ?
            WHERE status = 'running' AND updated_at < ?
            """,
            (_utc_now(), "action timed out after bot worker interruption", cutoff),
        )
        return cur.rowcount

    def reap_stale_running(self, timeout_seconds: int = 300) -> int:
        with self._connect() as conn:
            return self._reap_stale_running_locked(conn, timeout_seconds)

    @staticmethod
    def _row_to_action(row: sqlite3.Row) -> WebAdminAction:
        result_json = row["result_json"]
        return WebAdminAction(
            id=row["id"],
            action_type=row["action_type"],
            payload=json.loads(row["payload_json"] or "{}"),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result=json.loads(result_json) if result_json else None,
            error=row["error"] or "",
        )

    def enqueue(self, action_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action_id = uuid.uuid4().hex
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO web_admin_actions
                    (id, action_type, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (
                    action_id,
                    action_type,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return {"id": action_id, "action_type": action_type, "status": "queued"}

    def claim(self, limit: int = 5) -> list[WebAdminAction]:
        limit = max(1, min(int(limit), 20))
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reap_stale_running_locked(conn)
            rows = conn.execute(
                """
                SELECT *
                FROM web_admin_actions
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                conn.executemany(
                    """
                    UPDATE web_admin_actions
                    SET status = 'running', updated_at = ?
                    WHERE id = ? AND status = 'queued'
                    """,
                    [(now, action_id) for action_id in ids],
                )
            conn.commit()
        actions = [self._row_to_action(row) for row in rows]
        for action in actions:
            action.status = "running"
            action.updated_at = now
        return actions

    def complete(self, action_id: str, result: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE web_admin_actions
                SET status = 'succeeded', updated_at = ?, result_json = ?, error = ''
                WHERE id = ?
                """,
                (
                    _utc_now(),
                    json.dumps(result or {}, ensure_ascii=False),
                    action_id,
                ),
            )

    def fail(self, action_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE web_admin_actions
                SET status = 'failed', updated_at = ?, error = ?
                WHERE id = ?
                """,
                (_utc_now(), error[:2000], action_id),
            )

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM web_admin_actions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [asdict(self._row_to_action(row)) for row in rows]


action_queue = WebAdminActionQueue()
