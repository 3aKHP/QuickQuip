"""Persistent LLM usage/cost metering store (always-on, decoupled from trace).

每次 ``complete()`` 落一行（成功/错误/取消皆记），**不存请求/响应正文**——
与 ``trace.py`` 的 debug-only 全正文 trace 一刀切：trace=调试、14 天、标志门控；
usage=常驻计量、90 天、永不被标志门控。两者唯一共享面是 ``LLMResponse``。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quickquip.common.paths import LLM_USAGE_DB_PATH

logger = logging.getLogger(__name__)

_USAGE_RETENTION_DAYS = 90
_SQLITE_BUSY_TIMEOUT_MS = 10_000
_SQLITE_BUSY_RETRY_DELAY_SECONDS = 0.1
_SQLITE_BUSY_RETRY_ATTEMPTS = 100
_SQLITE_RETRYABLE_LOCK_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def window_start(range_days: int) -> datetime:
    """趋势网格起点，同时作为同 range 汇总/明细查询的统一下界。

    1d：当前整点 - 23h（24 个小时桶）；多天：UTC 今天 - (N-1) 的零点
    （N 个日历日桶）。summary/timeline/events 共用该起点，保证趋势合计
    与总成本卡片口径一致。
    """
    now = datetime.now(timezone.utc)
    if range_days <= 1:
        return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    start_date = now.date() - timedelta(days=range_days - 1)
    return datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)


class LLMUsageStore:
    """SQLite WAL store for LLM usage/cost events. 克隆 trace.py 的连接/保留机械。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._last_cleanup_date: str | None = None

    def connect(self) -> sqlite3.Connection:
        """打开一个 WAL 连接（row_factory=Row）；调用方用 ``with`` 包裹。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=0")
            for attempt in range(_SQLITE_BUSY_RETRY_ATTEMPTS):
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as error:
                    error_code = getattr(error, "sqlite_errorcode", None)
                    if (
                        error_code is None
                        or error_code & 0xFF not in _SQLITE_RETRYABLE_LOCK_CODES
                        or attempt == _SQLITE_BUSY_RETRY_ATTEMPTS - 1
                    ):
                        raise
                    time.sleep(_SQLITE_BUSY_RETRY_DELAY_SECONDS)
            conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            conn.close()
            raise
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return conn

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self.connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS llm_usage_events (
                        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts                    TEXT NOT NULL,
                        provider_id           TEXT NOT NULL,
                        protocol              TEXT NOT NULL,
                        model                 TEXT NOT NULL,
                        feature               TEXT,
                        group_id              TEXT,
                        persona_id            TEXT,
                        agent_loop_id         TEXT,
                        stream                INTEGER NOT NULL,
                        duration_ms           REAL,
                        input_tokens          INTEGER,
                        fresh_input_tokens    INTEGER,
                        total_tokens          INTEGER,
                        input_token_semantics TEXT,
                        output_tokens         INTEGER,
                        cache_creation_tokens INTEGER,
                        cache_read_tokens     INTEGER,
                        thinking_tokens       INTEGER,
                        cost_usd              REAL NOT NULL DEFAULT 0.0,
                        input_cost_usd        REAL NOT NULL DEFAULT 0.0,
                        output_cost_usd       REAL NOT NULL DEFAULT 0.0,
                        cache_read_cost_usd   REAL NOT NULL DEFAULT 0.0,
                        cache_creation_cost_usd REAL NOT NULL DEFAULT 0.0,
                        pricing_model         TEXT,
                        pricing_source        TEXT,
                        pricing_confidence    TEXT,
                        priced                INTEGER NOT NULL DEFAULT 0,
                        state                 TEXT NOT NULL DEFAULT 'ok',
                        error_message         TEXT
                    );
                    """
                )
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(llm_usage_events)")
                }
                migrations = {
                    "feature": "TEXT",
                    "group_id": "TEXT",
                    "persona_id": "TEXT",
                    "agent_loop_id": "TEXT",
                    "duration_ms": "REAL",
                    "fresh_input_tokens": "INTEGER",
                    "total_tokens": "INTEGER",
                    "input_token_semantics": "TEXT",
                    "input_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "output_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "cache_read_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "cache_creation_cost_usd": "REAL NOT NULL DEFAULT 0.0",
                    "pricing_model": "TEXT",
                    "pricing_source": "TEXT",
                    "pricing_confidence": "TEXT",
                }
                for name, definition in migrations.items():
                    if name not in columns:
                        conn.execute(f"ALTER TABLE llm_usage_events ADD COLUMN {name} {definition}")
                conn.executescript(
                    """
                    CREATE INDEX IF NOT EXISTS idx_usage_ts       ON llm_usage_events(ts DESC, id DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_provider ON llm_usage_events(provider_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_feature  ON llm_usage_events(feature, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_group    ON llm_usage_events(group_id, ts DESC);
                    CREATE INDEX IF NOT EXISTS idx_usage_model    ON llm_usage_events(model, ts DESC);
                    """
                )
            self._schema_ready = True

    def record(self, row: dict) -> None:
        """落一行用量（ts 自动补 UTC now）。row 的键须是表列子集。"""
        self._ensure_schema()
        self._cleanup_if_due()
        full = {"ts": _utc_now(), **row}
        cols = list(full.keys())
        placeholders = ", ".join("?" for _ in cols)
        with self.connect() as conn:
            conn.execute(
                f"INSERT INTO llm_usage_events ({', '.join(cols)}) VALUES ({placeholders})",
                list(full.values()),
            )

    def summary(self, cutoff: str, **filters: str | None) -> dict:
        """聚合用量/成本（仅 state='ok' 行计入金额；error/cancelled 单独计数）。"""
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._fresh_input_expr()} ELSE 0 END), 0) AS fresh_input, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN output_tokens ELSE 0 END), 0) AS output, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cache_read_tokens ELSE 0 END), 0) AS cache_read, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cache_creation_tokens ELSE 0 END), 0) AS cache_creation, "
                f"COUNT(*) AS calls, COALESCE(SUM(CASE WHEN state = 'ok' THEN 1 ELSE 0 END), 0) AS successes, "
                f"COALESCE(AVG(duration_ms), 0) AS avg_duration "
                f"FROM llm_usage_events WHERE {where}",
                params,
            ).fetchone()
            unpriced = conn.execute(
                f"SELECT COUNT(*) AS c, COALESCE(SUM({self._total_tokens_expr()}), 0) AS t "
                f"FROM llm_usage_events WHERE {where} AND priced = 0 AND state = 'ok'",
                params,
            ).fetchone()
            states = conn.execute(
                f"SELECT state, COUNT(*) AS c FROM llm_usage_events WHERE {where} GROUP BY state",
                params,
            ).fetchall()
            state_counts = {r["state"]: r["c"] for r in states}
            input_total = total["fresh_input"] + total["cache_read"] + total["cache_creation"]
            return {
                "total_cost": round(total["cost"], 6),
                "total_tokens": total["tokens"],
                "total_fresh_input_tokens": total["fresh_input"],
                "total_output_tokens": total["output"],
                "total_cache_read_tokens": total["cache_read"],
                "total_cache_creation_tokens": total["cache_creation"],
                "request_count": total["calls"],
                "success_count": total["successes"],
                "total_calls": total["successes"],
                "success_rate": round((total["successes"] or 0) / total["calls"], 4) if total["calls"] else 0.0,
                "average_duration_ms": round(total["avg_duration"], 2),
                "cache_hit_rate": round(total["cache_read"] / input_total, 4) if input_total else 0.0,
                "by_provider": self._group_by(conn, "provider_id", where, params),
                "by_feature": self._group_by(conn, "feature", where, params),
                "by_model": self._group_by(conn, "model", where, params),
                "by_group": self._group_by(conn, "group_id", where, params),
                "unpriced_calls_count": unpriced["c"],
                "unpriced_tokens_total": unpriced["t"],
                "error_count": state_counts.get("error", 0),
                "cancelled_count": state_counts.get("cancelled", 0),
                "bounds_note": "总成本为下界：不含失败/超时/未定价调用",
            }

    def timeline(
        self,
        cutoff: str,
        *,
        range_days: int | None = None,
        metric: str = "cost",
        **filters: str | None,
    ) -> list[dict]:
        if metric not in {"cost", "tokens", "requests", "errors", "duration"}:
            raise ValueError("unsupported metric")
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        fill_buckets = range_days is not None
        effective_days = range_days or 7
        aligned_start = window_start(effective_days)
        if effective_days <= 1:
            bucket_expr = "strftime('%Y-%m-%dT%H:00:00Z', ts)"
            step = timedelta(hours=1)
            start = aligned_start
            fmt = "%Y-%m-%dT%H:00:00Z"
        else:
            bucket_expr = "strftime('%Y-%m-%d', ts)"
            step = timedelta(days=1)
            start = aligned_start.date()
            fmt = "%Y-%m-%d"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {bucket_expr} AS d, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
                f"COALESCE(SUM(CASE WHEN state = 'ok' THEN {self._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
                f"COUNT(*) AS requests, SUM(CASE WHEN state = 'error' THEN 1 ELSE 0 END) AS errors, "
                f"COALESCE(AVG(duration_ms), 0) AS duration "
                f"FROM llm_usage_events WHERE {where} GROUP BY d ORDER BY d",
                params,
            ).fetchall()
        indexed = {r["d"]: r for r in rows}
        result = []
        cursor = start
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) if effective_days <= 1 else datetime.now(timezone.utc).date()
        if not fill_buckets:
            return [
                {"date": r["d"], "cost": round(r["cost"], 6), "tokens": r["tokens"],
                 "requests": r["requests"], "errors": r["errors"], "duration": round(r["duration"], 2),
                 "value": self._timeline_value(r, metric)}
                for r in rows
            ]
        while cursor <= end:
            key = cursor.strftime(fmt)
            row = indexed.get(key)
            result.append({
                "date": key,
                "cost": round(row["cost"], 6) if row else 0.0,
                "tokens": row["tokens"] if row else 0,
                "requests": row["requests"] if row else 0,
                "errors": row["errors"] if row else 0,
                "duration": round(row["duration"], 2) if row else 0.0,
                "value": self._timeline_value(row, metric),
            })
            cursor += step
        return result

    @staticmethod
    def _group_by(conn, col: str, where: str, params: list[object]) -> list[dict]:
        """按某列聚合 cost/calls（仅 state='ok'）。col 受控（非用户输入）。"""
        rows = conn.execute(
            f"SELECT {col} AS k, COALESCE(SUM(CASE WHEN state = 'ok' THEN cost_usd ELSE 0 END), 0) AS cost, "
            f"COUNT(*) AS calls, COALESCE(SUM(CASE WHEN state = 'ok' THEN {LLMUsageStore._total_tokens_expr()} ELSE 0 END), 0) AS tokens, "
            f"SUM(CASE WHEN state = 'error' THEN 1 ELSE 0 END) AS errors "
            f"FROM llm_usage_events WHERE {where} GROUP BY {col} "
            f"ORDER BY cost DESC",
            params,
        ).fetchall()
        return [
            {"key": r["k"] if r["k"] is not None else "(未归因)", "cost": round(r["cost"], 6), "calls": r["calls"], "tokens": r["tokens"], "errors": r["errors"]}
            for r in rows
        ]

    @staticmethod
    def _total_tokens_expr() -> str:
        return "COALESCE(total_tokens, CASE WHEN input_token_semantics = 'exclusive' OR (input_token_semantics IS NULL AND protocol = 'claude') THEN COALESCE(input_tokens, 0) + COALESCE(cache_read_tokens, 0) + COALESCE(cache_creation_tokens, 0) ELSE COALESCE(input_tokens, 0) END + COALESCE(output_tokens, 0))"

    @staticmethod
    def _fresh_input_expr() -> str:
        return "COALESCE(fresh_input_tokens, CASE WHEN input_token_semantics = 'exclusive' OR (input_token_semantics IS NULL AND protocol = 'claude') THEN COALESCE(input_tokens, 0) ELSE MAX(0, COALESCE(input_tokens, 0) - COALESCE(cache_read_tokens, 0) - COALESCE(cache_creation_tokens, 0)) END)"

    @staticmethod
    def _timeline_value(row: sqlite3.Row | None, metric: str) -> float | int:
        if row is None:
            return 0.0 if metric in {"cost", "duration"} else 0
        return {
            "cost": round(row["cost"], 6),
            "tokens": row["tokens"],
            "requests": row["requests"],
            "errors": row["errors"],
            "duration": round(row["duration"], 2),
        }[metric]

    @staticmethod
    def _where(cutoff: str, filters: dict[str, str | None]) -> tuple[str, list[object]]:
        clauses = ["ts >= ?"]
        params: list[object] = [cutoff]
        for key in ("provider_id", "model", "feature", "group_id", "state"):
            value = filters.get(key)
            if value:
                clauses.append(f"{key} = ?")
                params.append(value)
        return " AND ".join(clauses), params

    def events(
        self,
        *,
        cutoff: str,
        limit: int = 50,
        cursor: int | None = None,
        **filters: str | None,
    ) -> dict:
        self._ensure_schema()
        where, params = self._where(cutoff, filters)
        if cursor is not None:
            where += " AND id < ?"
            params.append(cursor)
        limit = max(1, min(limit, 100))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM llm_usage_events WHERE {where} ORDER BY id DESC LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return {"items": [dict(row) for row in rows], "next_cursor": str(rows[-1]["id"]) if has_more and rows else None}

    def event(self, event_id: int) -> dict | None:
        self._ensure_schema()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM llm_usage_events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def _cleanup_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        if self._last_cleanup_date == today:
            return
        with self._cleanup_lock:
            if self._last_cleanup_date == today:
                return
            cutoff = (now - timedelta(days=_USAGE_RETENTION_DAYS)).isoformat()
            with self.connect() as conn:
                conn.execute("DELETE FROM llm_usage_events WHERE ts < ?", (cutoff,))
            self._last_cleanup_date = today

    def storage_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += Path(f"{self.path}{suffix}").stat().st_size
            except OSError:
                pass
        return total

    def close(self) -> None:
        """每次操作开/关连接，无持久连接需关。"""


usage_store = LLMUsageStore(LLM_USAGE_DB_PATH)
