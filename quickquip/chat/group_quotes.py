from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path


class GroupQuoteStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        recent_random_window_seconds: int = 600,
        time_func: Callable[[], float] = time.time,
    ):
        self._path = Path(db_path)
        self._recent_random_window_seconds = max(1, int(recent_random_window_seconds))
        self._time = time_func
        self._recent_random_ids: dict[str, list[tuple[int, float]]] = {}
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
             str(saved_by_user_id), int(self._time())),
        )
        self._db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def _remember_random(self, group_id: str, quote_id: int) -> None:
        now = self._time()
        cutoff = now - self._recent_random_window_seconds
        recent = [
            (item_id, ts)
            for item_id, ts in self._recent_random_ids.get(group_id, [])
            if ts >= cutoff
        ]
        recent.append((quote_id, now))
        self._recent_random_ids[group_id] = recent

    def _recent_ids(self, group_id: str) -> set[int]:
        now = self._time()
        cutoff = now - self._recent_random_window_seconds
        recent = [
            (item_id, ts)
            for item_id, ts in self._recent_random_ids.get(group_id, [])
            if ts >= cutoff
        ]
        if recent:
            self._recent_random_ids[group_id] = recent
        else:
            self._recent_random_ids.pop(group_id, None)
        return {item_id for item_id, _ in recent}

    def random(self, group_id: str | int) -> dict | None:
        group_key = str(group_id)
        recent_ids = self._recent_ids(group_key)
        row = None
        if recent_ids:
            placeholders = ",".join("?" for _ in recent_ids)
            row = self._db.execute(
                "SELECT id, quoted_sender_name, content, saved_at FROM quotes"
                f" WHERE group_id=? AND id NOT IN ({placeholders})"
                " ORDER BY RANDOM() LIMIT 1",
                (group_key, *recent_ids),
            ).fetchone()

        if row is None:
            if recent_ids:
                self._recent_random_ids.pop(group_key, None)
            row = self._db.execute(
                "SELECT id, quoted_sender_name, content, saved_at FROM quotes"
                " WHERE group_id=? ORDER BY RANDOM() LIMIT 1",
                (group_key,),
            ).fetchone()

        if not row:
            return None

        self._remember_random(group_key, int(row[0]))
        return {
            "id": row[0],
            "quoted_sender_name": row[1],
            "content": row[2],
            "saved_at": row[3],
        }

    def clear_recent_random_history(self, group_id: str | int) -> None:
        self._recent_random_ids.pop(str(group_id), None)

    def recent_random_count(self, group_id: str | int) -> int:
        return len(self._recent_ids(str(group_id)))

    def close(self) -> None:
        self._db.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def count(self, group_id: str | int) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM quotes WHERE group_id=?",
            (str(group_id),),
        ).fetchone()
        return row[0] if row else 0
