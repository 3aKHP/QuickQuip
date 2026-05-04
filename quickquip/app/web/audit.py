import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request

logger = logging.getLogger(__name__)


class AuditLogger:
    """SQLite-backed audit log for web admin mutations.

    All log() calls are wrapped in try/except — audit failures NEVER block
    the main operation.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        return conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        operator TEXT NOT NULL,
                        action TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        summary_before TEXT,
                        summary_after TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_target_type ON audit_log(target_type)"
                )
        except Exception:
            logger.exception("audit_logger: failed to initialise database")

    def log(
        self,
        request: Request,
        action: str,
        target_type: str,
        target_id: str,
        summary_before: dict[str, Any] | None = None,
        summary_after: dict[str, Any] | None = None,
    ) -> None:
        """Record an audit entry. Failures are caught and logged — never raised."""
        try:
            operator = request.client.host if request.client else "unknown"
            timestamp = datetime.now(timezone.utc).isoformat()
            before_json = json.dumps(summary_before, ensure_ascii=False) if summary_before else None
            after_json = json.dumps(summary_after, ensure_ascii=False) if summary_after else None

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log (timestamp, operator, action, target_type, target_id,
                                           summary_before, summary_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (timestamp, operator, action, target_type, target_id, before_json, after_json),
                )
        except Exception:
            logger.exception(
                "audit_logger: failed to record entry action=%s target_type=%s target_id=%s",
                action,
                target_type,
                target_id,
            )

    def query(
        self,
        page: int = 1,
        limit: int = 50,
        action: str | None = None,
        target_type: str | None = None,
        operator: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Query audit entries with filtering and pagination.

        Returns (items: list[dict], total: int). Items are ordered by
        timestamp DESC.
        """
        try:
            where_clauses: list[str] = []
            params: list[Any] = []

            if action:
                where_clauses.append("action = ?")
                params.append(action)

            if target_type:
                where_clauses.append("target_type = ?")
                params.append(target_type)

            if operator:
                where_clauses.append("operator = ?")
                params.append(operator)

            if since:
                where_clauses.append("timestamp >= ?")
                params.append(since)

            if until:
                where_clauses.append("timestamp <= ?")
                params.append(until)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            with self._connect() as conn:
                total_row = conn.execute(
                    f"SELECT COUNT(*) FROM audit_log {where_sql}", params
                ).fetchone()
                total = total_row[0] if total_row else 0

                page = max(1, page)
                limit = max(1, min(limit, 200))
                offset = (page - 1) * limit

                rows = conn.execute(
                    f"""
                    SELECT id, timestamp, operator, action, target_type, target_id,
                           summary_before, summary_after
                    FROM audit_log
                    {where_sql}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()

            items: list[dict[str, Any]] = []
            for row in rows:
                entry = dict(row)
                # Parse JSON summary fields for convenience
                for key in ("summary_before", "summary_after"):
                    if entry.get(key):
                        try:
                            entry[key] = json.loads(entry[key])
                        except (json.JSONDecodeError, TypeError):
                            pass
                items.append(entry)

            return items, total
        except Exception:
            logger.exception("audit_logger: query failed")
            return [], 0


# Module-level singleton
audit_logger = AuditLogger(Path(__file__).parent.parent.parent.parent / "data" / "audit.db")
