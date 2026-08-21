from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import time
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.common.opt_in_groups import OptInGroupSet
from quickquip.common.paths import DAILY_MESSAGES_DIR, DAILY_SUMMARIES_DB_PATH

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)


def _safe_group_id(group_id: int | str) -> str:
    """Return a filesystem-safe, digit-only group ID string.

    QQ group IDs are always positive integers. Accepting anything else
    would allow path traversal (e.g. group_id = "../../etc").
    """
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id (must be all digits): {group_id!r}")
    return s


class DailyMessageCollector:
    """Appends chat messages to per-group per-date JSONL files for daily summarization."""

    def __init__(self, base_dir: str | Path = DAILY_MESSAGES_DIR):
        self.base_dir = Path(base_dir)

    def _file_path(self, group_id: int | str, calendar_date: date) -> Path:
        return self.base_dir / _safe_group_id(group_id) / f"{calendar_date.isoformat()}.jsonl"

    def record(
        self,
        group_id: int | str,
        sender_name: str,
        text: str,
        ts: float | None = None,
        user_id: int | str | None = None,
    ) -> None:
        if not text.strip():
            return
        ts_val = ts if ts is not None else time()
        local_date = datetime.fromtimestamp(ts_val, tz=_LOCAL_TZ).date()
        path = self._file_path(group_id, local_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sender": sender_name, "text": text, "ts": ts_val}
        if user_id is not None:
            payload["user_id"] = str(user_id)
        line = json.dumps(payload, ensure_ascii=False)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            logger.warning("daily_summary: failed to write message for group %s", group_id)

    def read_window(self, group_id: int | str, start_ts: float, end_ts: float) -> list[dict]:
        """Return all messages in [start_ts, end_ts) sorted by timestamp."""
        start_dt = datetime.fromtimestamp(start_ts, tz=_LOCAL_TZ)
        end_dt = datetime.fromtimestamp(end_ts, tz=_LOCAL_TZ)

        dates_to_check: list[date] = []
        current = start_dt.date()
        while current <= end_dt.date():
            dates_to_check.append(current)
            current += timedelta(days=1)

        messages: list[dict] = []
        for d in dates_to_check:
            path = self._file_path(group_id, d)
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            entry = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        ts_val = float(entry.get("ts", 0))
                        if start_ts <= ts_val < end_ts:
                            messages.append(entry)
            except OSError:
                logger.warning("daily_summary: could not read %s", path)

        messages.sort(key=lambda x: float(x.get("ts", 0)))
        return messages

    def read_all(self, group_id: int | str) -> list[dict]:
        """Return all persisted messages for a group sorted by timestamp."""
        group_dir = self.base_dir / _safe_group_id(group_id)
        if not group_dir.exists():
            return []

        messages: list[dict] = []
        for path in sorted(group_dir.glob("*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            entry = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        messages.append(entry)
            except OSError:
                logger.warning("daily_summary: could not read %s", path)

        messages.sort(key=lambda x: float(x.get("ts", 0)))
        return messages

    def delete_date_file(self, group_id: int | str, calendar_date: date) -> None:
        path = self._file_path(group_id, calendar_date)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("daily_summary: could not delete %s", path)


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
