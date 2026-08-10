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

logger = logging.getLogger(__name__)

_USAGE_RETENTION_DAYS = 90
_SQLITE_BUSY_TIMEOUT_MS = 10_000
_SQLITE_BUSY_RETRY_DELAY_SECONDS = 0.1
_SQLITE_BUSY_RETRY_ATTEMPTS = 100
_SQLITE_RETRYABLE_LOCK_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                        output_tokens         INTEGER,
                        cache_creation_tokens INTEGER,
                        cache_read_tokens     INTEGER,
                        thinking_tokens       INTEGER,
                        cost_usd              REAL NOT NULL DEFAULT 0.0,
                        priced                INTEGER NOT NULL DEFAULT 0,
                        state                 TEXT NOT NULL DEFAULT 'ok',
                        error_message         TEXT
                    );
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
