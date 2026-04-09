from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import time
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)


class DailyMessageCollector:
    """Appends chat messages to per-group per-date JSONL files for daily summarization."""

    def __init__(self, base_dir: str | Path = "data/daily_msgs"):
        self.base_dir = Path(base_dir)

    def _file_path(self, group_id: int | str, calendar_date: date) -> Path:
        return self.base_dir / str(group_id) / f"{calendar_date.isoformat()}.jsonl"

    def record(self, group_id: int | str, sender_name: str, text: str, ts: float | None = None) -> None:
        if not text.strip():
            return
        ts_val = ts if ts is not None else time()
        local_date = datetime.fromtimestamp(ts_val, tz=_LOCAL_TZ).date()
        path = self._file_path(group_id, local_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"sender": sender_name, "text": text, "ts": ts_val}, ensure_ascii=False)
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

    def delete_date_file(self, group_id: int | str, calendar_date: date) -> None:
        path = self._file_path(group_id, calendar_date)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("daily_summary: could not delete %s", path)


class DailySummaryStore:
    """SQLite store for persisting generated daily summaries."""

    def __init__(self, db_path: str | Path = "data/daily_summaries.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id     TEXT NOT NULL,
                    summary_date TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    model_used   TEXT,
                    char_count   INTEGER,
                    content      TEXT NOT NULL,
                    UNIQUE(group_id, summary_date)
                )
            """)
            conn.commit()

    def upsert(
        self,
        group_id: int | str,
        summary_date: str,
        content: str,
        model_used: str | None = None,
    ) -> None:
        generated_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO summaries (group_id, summary_date, generated_at, model_used, char_count, content)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id, summary_date) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    model_used   = excluded.model_used,
                    char_count   = excluded.char_count,
                    content      = excluded.content
                """,
                (str(group_id), summary_date, generated_at, model_used, len(content), content),
            )
            conn.commit()

    def get(self, group_id: int | str, summary_date: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE group_id = ? AND summary_date = ?",
                (str(group_id), summary_date),
            ).fetchone()
        return dict(row) if row else None


class DailySummaryEnabledGroups:
    """Manages the opt-in set of groups with daily_summary enabled (default: off)."""

    def __init__(self, path: str | Path = "data/daily_summary_groups.json"):
        self.path = Path(path)
        self._groups: set[str] = set()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._groups = {str(g) for g in data.get("enabled", [])}
        except (OSError, json.JSONDecodeError):
            self._groups = set()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump({"enabled": sorted(self._groups)}, f, ensure_ascii=False, indent=2)

    def add(self, group_id: int | str) -> None:
        self._groups.add(str(group_id))
        self.save()

    def remove(self, group_id: int | str) -> None:
        self._groups.discard(str(group_id))
        self.save()

    def contains(self, group_id: int | str) -> bool:
        return str(group_id) in self._groups

    def all_groups(self) -> list[str]:
        return sorted(self._groups)
