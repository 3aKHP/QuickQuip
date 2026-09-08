from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from quickquip.common.opt_in_groups import OptInGroupSet
from quickquip.common.paths import DAILY_SUMMARIES_DB_PATH

logger = logging.getLogger(__name__)


class DailySummaryStore:
    """SQLite store for persisting generated daily summaries."""

    def __init__(self, db_path: str | Path = DAILY_SUMMARIES_DB_PATH):
        self.db_path = Path(db_path)
        self._unavailable = False
        try:
            self._init_db()
        except sqlite3.Error as exc:
            logger.error("DailySummaryStore 数据库初始化失败 (%s)：%s", self.db_path, exc)
            self._unavailable = True

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id     TEXT NOT NULL,
                    summary_date TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    published_at TEXT DEFAULT NULL,
                    model_used   TEXT,
                    char_count   INTEGER,
                    content      TEXT NOT NULL,
                    UNIQUE(group_id, summary_date)
                )
            """)
            # Migrate: add published_at column if this DB predates it
            try:
                conn.execute("ALTER TABLE summaries ADD COLUMN published_at TEXT DEFAULT NULL")
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.commit()
        finally:
            conn.close()

    def upsert(
        self,
        group_id: int | str,
        summary_date: str,
        content: str,
        model_used: str | None = None,
    ) -> None:
        if self._unavailable:
            raise RuntimeError("每日总结 数据库不可用")
        generated_at = datetime.now(tz=timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO summaries
                    (group_id, summary_date, generated_at, model_used, char_count, content)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id, summary_date) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    model_used   = excluded.model_used,
                    char_count   = excluded.char_count,
                    content      = excluded.content,
                    published_at = NULL
                """,
                (str(group_id), summary_date, generated_at, model_used, len(content), content),
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, group_id: int | str, summary_date: str) -> dict | None:
        if self._unavailable:
            raise RuntimeError("每日总结 数据库不可用")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM summaries WHERE group_id = ? AND summary_date = ?",
                (str(group_id), summary_date),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_unpublished(self) -> list[dict]:
        """Return all summaries that have not yet been published."""
        if self._unavailable:
            raise RuntimeError("每日总结 数据库不可用")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM summaries WHERE published_at IS NULL ORDER BY summary_date, group_id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_published(self, group_id: int | str, summary_date: str) -> None:
        if self._unavailable:
            raise RuntimeError("每日总结 数据库不可用")
        published_at = datetime.now(tz=timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE summaries SET published_at = ? WHERE group_id = ? AND summary_date = ?",
                (published_at, str(group_id), summary_date),
            )
            conn.commit()
        finally:
            conn.close()


class DailySummaryEnabledGroups(OptInGroupSet):
    """Manages the opt-in set of groups with daily_summary enabled (default: off)."""

    log_label = "daily_summary"

    def __init__(self, path: str | Path = "data/daily_summary_groups.json"):
        super().__init__(path)
