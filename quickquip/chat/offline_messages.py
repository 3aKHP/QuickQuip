from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PendingMessage:
    id: int
    from_user_id: str
    from_sender_name: str
    content: str
    created_at: int


class OfflineMessageStore:
    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
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

    def add(
        self,
        group_id: str | int,
        from_user_id: str | int,
        from_sender_name: str,
        to_user_id: str | int,
        content: str,
    ) -> int:
        cur = self._db.execute(
            "INSERT INTO offline_messages"
            " (group_id, from_user_id, from_sender_name, to_user_id, content, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (str(group_id), str(from_user_id), from_sender_name, str(to_user_id), content, int(time.time())),
        )
        self._db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def pop_pending(self, group_id: str | int, to_user_id: str | int) -> list[PendingMessage]:
        """获取并原子删除该用户在本群的所有待接收留言。"""
        rows = self._db.execute(
            "SELECT id, from_user_id, from_sender_name, content, created_at"
            " FROM offline_messages WHERE group_id=? AND to_user_id=? ORDER BY id",
            (str(group_id), str(to_user_id)),
        ).fetchall()
        if rows:
            ids = [r[0] for r in rows]
            self._db.execute(
                f"DELETE FROM offline_messages WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            self._db.commit()
        return [PendingMessage(r[0], r[1], r[2], r[3], r[4]) for r in rows]

    def retract_latest(self, group_id: str | int, from_user_id: str | int) -> str | None:
        """撤回本用户在本群最新一条未投递留言，返回收件人 user_id；无留言则返回 None。"""
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
        """查询（不消费）该用户的待接收留言列表。"""
        rows = self._db.execute(
            "SELECT id, from_user_id, from_sender_name, content, created_at"
            " FROM offline_messages WHERE group_id=? AND to_user_id=? ORDER BY id",
            (str(group_id), str(to_user_id)),
        ).fetchall()
        return [PendingMessage(r[0], r[1], r[2], r[3], r[4]) for r in rows]
