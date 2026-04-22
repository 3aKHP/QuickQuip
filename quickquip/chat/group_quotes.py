from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class GroupQuoteStore:
    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS quotes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id            TEXT NOT NULL,
                quoted_user_id      TEXT NOT NULL DEFAULT '',
                quoted_sender_name  TEXT NOT NULL DEFAULT '',
                content             TEXT NOT NULL,
                saved_by_user_id    TEXT NOT NULL DEFAULT '',
                saved_at            INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quotes_group
                ON quotes(group_id, id);
        """)
        self._db.commit()

    def add(
        self,
        group_id: str | int,
        quoted_user_id: str | int,
        quoted_sender_name: str,
        content: str,
        saved_by_user_id: str | int,
    ) -> int:
        cur = self._db.execute(
            "INSERT INTO quotes"
            " (group_id, quoted_user_id, quoted_sender_name, content, saved_by_user_id, saved_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (str(group_id), str(quoted_user_id), quoted_sender_name, content,
             str(saved_by_user_id), int(time.time())),
        )
        self._db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def random(self, group_id: str | int) -> dict | None:
        row = self._db.execute(
            "SELECT quoted_sender_name, content, saved_at FROM quotes"
            " WHERE group_id=? ORDER BY RANDOM() LIMIT 1",
            (str(group_id),),
        ).fetchone()
        if not row:
            return None
        return {"quoted_sender_name": row[0], "content": row[1], "saved_at": row[2]}

    def count(self, group_id: str | int) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM quotes WHERE group_id=?",
            (str(group_id),),
        ).fetchone()
        return row[0] if row else 0
