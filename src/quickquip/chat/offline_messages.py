from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingMessage:
    id: int
    from_user_id: str
    from_sender_name: str
    content: str
    created_at: int

    def format_display(self) -> str:
        ts = datetime.fromtimestamp(self.created_at).strftime("%m-%d %H:%M")
        return f"[{self.from_sender_name} {ts}] {self.content}"


class OfflineMessageStore:
    def __init__(self, db_path: str | Path):
        self._db: sqlite3.Connection | None = None
        self._closed = False
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._unavailable = False
        try:
            self._db = sqlite3.connect(str(self._path), check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS offline_messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id        TEXT NOT NULL,
                    from_user_id    TEXT NOT NULL,
                    from_sender_name TEXT NOT NULL DEFAULT '',
                    to_user_id      TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    created_at      INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_om_to
                    ON offline_messages(group_id, to_user_id, id);
                CREATE INDEX IF NOT EXISTS idx_om_from
                    ON offline_messages(group_id, from_user_id, id);
            """)
            self._db.commit()
            # Fast-reject set: (group_id, to_user_id) pairs that have pending rows.
            # Conservative: false positives cause one wasted DELETE RETURNING; false negatives would miss delivery.
            self._pending: set[tuple[str, str]] = {
                (r[0], r[1])
                for r in self._db.execute(
                    "SELECT DISTINCT group_id, to_user_id FROM offline_messages"
                ).fetchall()
            }
        except sqlite3.Error as exc:
            logger.error("OfflineMessageStore 数据库初始化失败 (%s)：%s", self._path, exc)
            self._unavailable = True
            self._pending = set()

    def add(
        self,
        group_id: str | int,
        from_user_id: str | int,
        from_sender_name: str,
        to_user_id: str | int,
        content: str,
    ) -> int:
        if self._unavailable:
            raise RuntimeError("离线消息 数据库不可用")
        g, t = str(group_id), str(to_user_id)
        cur = self._db.execute(
            "INSERT INTO offline_messages"
            " (group_id, from_user_id, from_sender_name, to_user_id, content, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (g, str(from_user_id), from_sender_name, t, content, int(time.time())),
        )
        self._db.commit()
        self._pending.add((g, t))
        return cur.lastrowid  # type: ignore[return-value]

    def pop_pending(self, group_id: str | int, to_user_id: str | int) -> list[PendingMessage]:
        if self._unavailable:
            raise RuntimeError("离线消息 数据库不可用")
        key = (str(group_id), str(to_user_id))
        if key not in self._pending:
            return []
        rows = self._db.execute(
            "DELETE FROM offline_messages WHERE group_id=? AND to_user_id=?"
            " RETURNING id, from_user_id, from_sender_name, content, created_at",
            key,
        ).fetchall()
        self._db.commit()
        self._pending.discard(key)
        return sorted(
            [PendingMessage(r[0], r[1], r[2], r[3], r[4]) for r in rows],
            key=lambda m: m.id,
        )

    def retract_latest(self, group_id: str | int, from_user_id: str | int) -> str | None:
        if self._unavailable:
            raise RuntimeError("离线消息 数据库不可用")
        row = self._db.execute(
            "SELECT id, to_user_id FROM offline_messages"
            " WHERE group_id=? AND from_user_id=? ORDER BY id DESC LIMIT 1",
            (str(group_id), str(from_user_id)),
        ).fetchone()
        if not row:
            return None
        self._db.execute("DELETE FROM offline_messages WHERE id=?", (row[0],))
        self._db.commit()
        return row[1]

    def list_pending_for(self, group_id: str | int, to_user_id: str | int) -> list[PendingMessage]:
        if self._unavailable:
            raise RuntimeError("离线消息 数据库不可用")
        key = (str(group_id), str(to_user_id))
        if key not in self._pending:
            return []
        rows = self._db.execute(
            "SELECT id, from_user_id, from_sender_name, content, created_at"
            " FROM offline_messages WHERE group_id=? AND to_user_id=? ORDER BY id",
            key,
        ).fetchall()
        return [PendingMessage(r[0], r[1], r[2], r[3], r[4]) for r in rows]

    def close(self) -> None:
        if self._closed or self._db is None:
            return
        self._db.close()
        self._db = None
        self._closed = True

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
