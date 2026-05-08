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
        self._db: sqlite3.Connection | None = None
        self._closed = False
        self._path = Path(db_path)
        self._recent_random_window_seconds = max(1, int(recent_random_window_seconds))
        self._time = time_func
        self._recent_random_ids: dict[str, list[tuple[int, float]]] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS quotes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id            TEXT NOT NULL,
                quoted_user_id      TEXT NOT NULL DEFAULT '',
                quoted_sender_name  TEXT NOT NULL DEFAULT '',
                content             TEXT NOT NULL,
                saved_by_user_id    TEXT NOT NULL DEFAULT '',
                saved_at            INTEGER NOT NULL,
                group_seq           INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_quotes_group
                ON quotes(group_id, id);
        """)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        try:
            self._db.execute("SELECT group_seq FROM quotes LIMIT 0")
        except sqlite3.OperationalError:
            self._db.execute(
                "ALTER TABLE quotes ADD COLUMN group_seq INTEGER NOT NULL DEFAULT 0"
            )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_group_seq ON quotes(group_id, group_seq)"
        )
        # backfill group_seq for rows that still have 0
        rows = self._db.execute(
            "SELECT id, group_id FROM quotes WHERE group_seq = 0 ORDER BY id"
        ).fetchall()
        if rows:
            from collections import defaultdict
            counters: dict[str, int] = defaultdict(int)
            for row in rows:
                gid = str(row[1])
                counters[gid] += 1
                self._db.execute(
                    "UPDATE quotes SET group_seq = ? WHERE id = ?",
                    (counters[gid], row[0]),
                )

    def add(
        self,
        group_id: str | int,
        quoted_user_id: str | int,
        quoted_sender_name: str,
        content: str,
        saved_by_user_id: str | int,
    ) -> int:
        gid = str(group_id)
        row = self._db.execute(
            "SELECT COALESCE(MAX(group_seq), 0) + 1 FROM quotes WHERE group_id = ?",
            (gid,),
        ).fetchone()
        next_seq = int(row[0]) if row else 1
        cur = self._db.execute(
            "INSERT INTO quotes"
            " (group_id, quoted_user_id, quoted_sender_name, content, saved_by_user_id, saved_at, group_seq)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, str(quoted_user_id), quoted_sender_name, content,
             str(saved_by_user_id), int(self._time()), next_seq),
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
                "SELECT id, group_seq, quoted_sender_name, content, saved_at FROM quotes"
                f" WHERE group_id=? AND id NOT IN ({placeholders})"
                " ORDER BY RANDOM() LIMIT 1",
                (group_key, *recent_ids),
            ).fetchone()

        if row is None:
            if recent_ids:
                self._recent_random_ids.pop(group_key, None)
            row = self._db.execute(
                "SELECT id, group_seq, quoted_sender_name, content, saved_at FROM quotes"
                " WHERE group_id=? ORDER BY RANDOM() LIMIT 1",
                (group_key,),
            ).fetchone()

        if not row:
            return None

        self._remember_random(group_key, int(row[0]))
        return {
            "id": row[0],
            "group_seq": row[1],
            "quoted_sender_name": row[2],
            "content": row[3],
            "saved_at": row[4],
        }

    def clear_recent_random_history(self, group_id: str | int) -> None:
        self._recent_random_ids.pop(str(group_id), None)

    def recent_random_count(self, group_id: str | int) -> int:
        return len(self._recent_ids(str(group_id)))

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

    def count(self, group_id: str | int) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM quotes WHERE group_id=?",
            (str(group_id),),
        ).fetchone()
        return row[0] if row else 0

    def get_by_seq(self, group_id: str | int, seq: int) -> dict | None:
        row = self._db.execute(
            "SELECT id, group_id, quoted_user_id, quoted_sender_name,"
            " content, saved_by_user_id, saved_at, group_seq"
            " FROM quotes WHERE group_id=? AND group_seq=?",
            (str(group_id), int(seq)),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def search(
        self, group_id: str | int, keyword: str,
        offset: int = 0, limit: int = 50,
    ) -> tuple[list[dict], int]:
        gid = str(group_id)
        pattern = f"%{keyword}%"
        rows = self._db.execute(
            "SELECT id, group_id, quoted_user_id, quoted_sender_name,"
            " content, saved_by_user_id, saved_at, group_seq"
            " FROM quotes WHERE group_id=? AND content LIKE ?"
            " ORDER BY id DESC LIMIT ? OFFSET ?",
            (gid, pattern, limit, offset),
        ).fetchall()
        total_row = self._db.execute(
            "SELECT COUNT(*) AS c FROM quotes WHERE group_id=? AND content LIKE ?",
            (gid, pattern),
        ).fetchone()
        return [dict(r) for r in rows], int(total_row["c"]) if total_row else 0

    def delete(self, quote_id: int) -> bool:
        cur = self._db.execute(
            "DELETE FROM quotes WHERE id=?",
            (int(quote_id),),
        )
        self._db.commit()
        return cur.rowcount > 0

    def list_quotes(
        self, group_id: str | int,
        offset: int = 0, limit: int = 50, keyword: str = "",
    ) -> tuple[list[dict], int]:
        gid = str(group_id)
        if keyword:
            return self.search(gid, keyword, offset, limit)
        rows = self._db.execute(
            "SELECT id, group_id, quoted_user_id, quoted_sender_name,"
            " content, saved_by_user_id, saved_at, group_seq"
            " FROM quotes WHERE group_id=?"
            " ORDER BY id DESC LIMIT ? OFFSET ?",
            (gid, limit, offset),
        ).fetchall()
        total_row = self._db.execute(
            "SELECT COUNT(*) AS c FROM quotes WHERE group_id=?",
            (gid,),
        ).fetchone()
        return [dict(r) for r in rows], int(total_row["c"]) if total_row else 0

    def groups(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT group_id, COUNT(*) AS count, MAX(id) AS latest_id"
            " FROM quotes GROUP BY group_id ORDER BY latest_id DESC"
        ).fetchall()
        return [{"group_id": r[0], "count": int(r[1])} for r in rows]
