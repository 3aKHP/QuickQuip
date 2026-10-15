"""Indexed HTTP text tracing for LLM provider calls."""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from quickquip.llm.session import SessionIdentity
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Iterator
from uuid import uuid4
import logging

from quickquip.common.paths import LLM_TRACE_DB_PATH, LOGS_DIR
from quickquip.llm.provider.media_truncator import (
    MANIFEST_VERSION,
    MediaBlobStore,
    MediaTruncator,
    collect_manifest_shas,
    decode_payload,
    find_manifest_mime,
    resolve_min_bytes,
)


logger = logging.getLogger(__name__)

_TRACE_FLAG_FILE = os.getenv("LLM_TRACE_FLAG_FILE", "")
_TRACE_RETENTION_DAYS = 14
_TRACE_BLOB_DIR_NAME = "trace_blobs"
# GC 保守带：blob 先落盘、引用行后提交，清扫必须避开这个并发窗口。
_TRACE_BLOB_GRACE_SECONDS = 24 * 3600
_LEGACY_TRACE_GLOB = "quickquip_trace_????-??-??.jsonl"
_TRACE_STALE_AFTER = timedelta(hours=1)
_TRACE_STALE_CHECK_INTERVAL_SECONDS = 60
_SQLITE_BUSY_TIMEOUT_MS = 10_000
_SQLITE_BUSY_RETRY_DELAY_SECONDS = 0.1
_SQLITE_BUSY_RETRY_ATTEMPTS = 100
_SQLITE_RETRYABLE_LOCK_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_manifest(raw: str | None) -> dict[str, object] | None:
    """解析落库的 manifest JSON；非法或为空返回 ``None``（视作原样存储）。"""

    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_field_manifests(
    existing_json: str | None,
    additions: dict[str, dict[str, object] | None],
) -> str | None:
    """把新字段的清单并入已有 manifest，避免后写的一次覆盖前一次。

    ``begin_call`` 落 request，``finish_call`` 落 response 与 response_raw，
    三者共用一个 ``media_truncation`` 列，必须合并而非覆盖。全部字段都无
    截断时返回 ``None``——该行就是「原样存储」。
    """

    payload = _parse_manifest(existing_json) or {}
    changed = False
    for field_name, manifest in additions.items():
        if manifest is None:
            continue
        payload[field_name] = manifest
        changed = True
    if not changed:
        return existing_json or None
    payload["v"] = MANIFEST_VERSION
    return json.dumps(payload, ensure_ascii=False)


@dataclass(slots=True)
class TraceCapture:
    """Collect provider call IDs for one explicitly observed operation."""

    force: bool = False
    call_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentLoopTrace:
    """Identify and order all HTTP attempts belonging to one agent loop."""

    loop_id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int = 0


_TRACE_CAPTURE: ContextVar[TraceCapture | None] = ContextVar(
    "quickquip_llm_trace_capture",
    default=None,
)
_AGENT_LOOP_TRACE: ContextVar[AgentLoopTrace | None] = ContextVar(
    "quickquip_llm_agent_loop_trace",
    default=None,
)
_REQUEST_SESSION: ContextVar[SessionIdentity | None] = ContextVar(
    "quickquip_llm_request_session", default=None,
)


@contextmanager
def trace_request_session(identity: SessionIdentity | None) -> Iterator[None]:
    """Bind an explicit request snapshot for tracing, including explicit absence."""
    token = _REQUEST_SESSION.set(identity)
    try:
        yield
    finally:
        _REQUEST_SESSION.reset(token)


@contextmanager
def collect_trace_calls(*, force: bool = False) -> Iterator[list[str]]:
    """Collect call IDs in the current task so diagnostics can load their traces."""

    capture = TraceCapture(force=force)
    token = _TRACE_CAPTURE.set(capture)
    try:
        yield capture.call_ids
    finally:
        _TRACE_CAPTURE.reset(token)


def trace_agent_loop(func):
    """Give all provider calls made by an async agent loop one shared boundary."""

    @wraps(func)
    async def wrapped(*args, **kwargs):
        if _AGENT_LOOP_TRACE.get() is not None:
            return await func(*args, **kwargs)
        token = _AGENT_LOOP_TRACE.set(AgentLoopTrace())
        try:
            return await func(*args, **kwargs)
        finally:
            _AGENT_LOOP_TRACE.reset(token)

    return wrapped


def current_agent_loop_id() -> str | None:
    """Current agent loop id, or ``None`` outside any ``@trace_agent_loop`` boundary.

    跨模块归因的唯一公开入口：不要读取可变的 ``AgentLoopTrace``/``_AGENT_LOOP_TRACE``。
    """
    loop = _AGENT_LOOP_TRACE.get()
    return loop.loop_id if loop is not None else None


def trace_active() -> bool:
    """Return whether global or operation-scoped HTTP tracing is active."""

    capture = _TRACE_CAPTURE.get()
    return bool(
        (capture is not None and capture.force)
        or (_TRACE_FLAG_FILE and os.path.exists(_TRACE_FLAG_FILE))
    )


class LLMTraceStore:
    """Persist indexed LLM HTTP text traces without loading payloads into listings."""

    def __init__(
        self,
        path: str | Path = LLM_TRACE_DB_PATH,
        *,
        legacy_trace_dir: str | Path | None = None,
        blob_dir: str | Path | None = None,
        media_min_bytes: int | None = None,
    ):
        self.path = Path(path)
        self.legacy_trace_dir = (
            Path(legacy_trace_dir)
            if legacy_trace_dir is not None
            else self.path.parent / "logs"
        )
        # blob 库刻意不按天分桶：滚动留存下，全局内容寻址库才能真正做到
        # 跨天严格单副本（issue #291）。min_bytes <= 0 表示截断关闭。
        self.blob_dir = (
            Path(blob_dir)
            if blob_dir is not None
            else self.path.parent / _TRACE_BLOB_DIR_NAME
        )
        self.blob_store = MediaBlobStore(self.blob_dir)
        self.truncator = MediaTruncator(
            self.blob_store,
            min_bytes=resolve_min_bytes() if media_min_bytes is None else media_min_bytes,
        )
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._last_cleanup_date: str | None = None
        self._stale_lock = threading.Lock()
        self._last_stale_check: float | None = None

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
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
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS llm_http_traces (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        call_id          TEXT NOT NULL UNIQUE,
                        agent_loop_id    TEXT NOT NULL,
                        loop_sequence    INTEGER NOT NULL,
                        started_at       TEXT NOT NULL,
                        completed_at     TEXT,
                        provider_id      TEXT NOT NULL,
                        protocol         TEXT NOT NULL,
                        model            TEXT NOT NULL,
                        stream           INTEGER NOT NULL,
                        method           TEXT NOT NULL,
                        url              TEXT NOT NULL,
                        request_headers  TEXT NOT NULL,
                        request_text     TEXT NOT NULL,
                        request_bytes    INTEGER NOT NULL,
                        response_status  INTEGER,
                        response_headers TEXT,
                        response_text    TEXT,
                        response_bytes   INTEGER NOT NULL DEFAULT 0,
                        response_raw_text TEXT,
                        response_raw_bytes INTEGER NOT NULL DEFAULT 0,
                        media_truncation TEXT,
                        duration_ms      REAL,
                        state            TEXT NOT NULL,
                        error_type       TEXT,
                        error_message    TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_llm_http_traces_started
                    ON llm_http_traces(started_at DESC, id DESC);

                    CREATE INDEX IF NOT EXISTS idx_llm_http_traces_provider
                    ON llm_http_traces(provider_id, id DESC);

                    CREATE INDEX IF NOT EXISTS idx_llm_http_traces_state_started
                    ON llm_http_traces(state, started_at);

                    CREATE TABLE IF NOT EXISTS llm_http_trace_events (
                        event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id   INTEGER NOT NULL,
                        state      TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(trace_id) REFERENCES llm_http_traces(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_llm_http_trace_events_trace
                    ON llm_http_trace_events(trace_id, event_id);
                    """
                )
                conn.execute("BEGIN IMMEDIATE")
                event_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(llm_http_trace_events)"
                    ).fetchall()
                }
                if "state" not in event_columns:
                    conn.execute(
                        "ALTER TABLE llm_http_trace_events ADD COLUMN state TEXT"
                    )
                    conn.execute(
                        """
                        UPDATE llm_http_trace_events AS events
                        SET state = CASE
                            WHEN event_id = (
                                SELECT MIN(first_event.event_id)
                                FROM llm_http_trace_events AS first_event
                                WHERE first_event.trace_id = events.trace_id
                            ) THEN 'pending'
                            ELSE COALESCE((
                                SELECT traces.state
                                FROM llm_http_traces AS traces
                                WHERE traces.id = events.trace_id
                            ), 'error')
                        END
                        """
                    )
                trace_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(llm_http_traces)"
                    ).fetchall()
                }
                if "session_id" not in trace_columns:
                    conn.execute("ALTER TABLE llm_http_traces ADD COLUMN session_id TEXT")
                if "agent_loop_id" not in trace_columns:
                    conn.execute(
                        "ALTER TABLE llm_http_traces ADD COLUMN agent_loop_id TEXT"
                    )
                    conn.execute(
                        "UPDATE llm_http_traces SET agent_loop_id = call_id"
                    )
                if "loop_sequence" not in trace_columns:
                    conn.execute(
                        "ALTER TABLE llm_http_traces ADD COLUMN loop_sequence "
                        "INTEGER NOT NULL DEFAULT 1"
                    )
                if "response_raw_text" not in trace_columns:
                    conn.execute(
                        "ALTER TABLE llm_http_traces ADD COLUMN response_raw_text TEXT"
                    )
                if "response_raw_bytes" not in trace_columns:
                    conn.execute(
                        "ALTER TABLE llm_http_traces ADD COLUMN response_raw_bytes "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                if "media_truncation" not in trace_columns:
                    # 旧行保持 NULL，读端视作「原样存储」，天然兼容。
                    conn.execute(
                        "ALTER TABLE llm_http_traces ADD COLUMN media_truncation TEXT"
                    )
            self._schema_ready = True

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": int(row["id"]),
            "call_id": row["call_id"],
            "session_id": row["session_id"],
            "agent_loop_id": row["agent_loop_id"] or row["call_id"],
            "loop_sequence": int(row["loop_sequence"] or 1),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "provider_id": row["provider_id"],
            "protocol": row["protocol"],
            "model": row["model"],
            "stream": bool(row["stream"]),
            "method": row["method"],
            "url": row["url"],
            "request_bytes": int(row["request_bytes"]),
            "response_status": row["response_status"],
            "response_bytes": int(row["response_bytes"]),
            "response_raw_bytes": int(row["response_raw_bytes"] or 0),
            "duration_ms": row["duration_ms"],
            "state": row["state"],
            "error_type": row["error_type"],
            "error_message": row["error_message"],
        }

    def begin_call(
        self,
        *,
        provider_id: str,
        protocol: str,
        model: str,
        stream: bool,
        method: str,
        url: str,
        request_headers: str,
        request_text: str,
        request_bytes: int,
        agent_loop_id: str = "",
        loop_sequence: int = 1,
        session_id: str | None = None,
    ) -> str:
        self._ensure_schema()
        self._cleanup_if_due()
        call_id = uuid4().hex
        # 唯一写入咽喉之一：三个大文本在落库前过一遍截断器，provider 层零改动。
        # request_bytes 仍记原始字节数（等同 full_bytes），语义不变。
        outcome = self.truncator.truncate(request_text)
        manifest_json = _merge_field_manifests(None, {"request": outcome.manifest})
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO llm_http_traces (
                    call_id, agent_loop_id, loop_sequence, started_at,
                    provider_id, protocol, model, stream,
                    method, url, request_headers, request_text, request_bytes, session_id,
                    media_truncation, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    call_id,
                    agent_loop_id or call_id,
                    max(1, int(loop_sequence)),
                    _utc_now(),
                    provider_id,
                    protocol,
                    model,
                    int(stream),
                    method,
                    url,
                    request_headers,
                    outcome.text,
                    request_bytes,
                    session_id,
                    manifest_json,
                ),
            )
            conn.execute(
                """
                INSERT INTO llm_http_trace_events (trace_id, state, created_at)
                VALUES (?, 'pending', ?)
                """,
                (int(cursor.lastrowid), _utc_now()),
            )
        return call_id

    def finish_call(
        self,
        call_id: str,
        *,
        state: str,
        response_status: int | None,
        response_headers: str,
        response_text: str,
        response_bytes: int,
        duration_ms: float,
        error_type: str = "",
        error_message: str = "",
        response_raw_text: str = "",
        response_raw_bytes: int = 0,
    ) -> None:
        self._ensure_schema()
        # 重组响应与原始 SSE 帧各含一份同样的 base64：两处截断后同哈希指向
        # 同一个 blob，这正是「同一次调用双份」膨胀源的坍缩点。
        response_outcome = self.truncator.truncate(response_text or "")
        raw_outcome = self.truncator.truncate(response_raw_text or "")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, media_truncation FROM llm_http_traces WHERE call_id = ?",
                (call_id,),
            ).fetchone()
            if existing is None:
                return
            manifest_json = _merge_field_manifests(
                existing["media_truncation"],
                {
                    "response": response_outcome.manifest,
                    "response_raw": raw_outcome.manifest,
                },
            )
            conn.execute(
                """
                UPDATE llm_http_traces
                SET completed_at = ?, response_status = ?, response_headers = ?,
                    response_text = ?, response_bytes = ?, duration_ms = ?,
                    response_raw_text = ?, response_raw_bytes = ?,
                    media_truncation = ?,
                    state = ?, error_type = ?, error_message = ?
                WHERE call_id = ?
                """,
                (
                    _utc_now(),
                    response_status,
                    response_headers,
                    response_outcome.text,
                    response_bytes,
                    duration_ms,
                    raw_outcome.text or None,
                    response_raw_bytes,
                    manifest_json,
                    state,
                    error_type or None,
                    error_message or None,
                    call_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO llm_http_trace_events (trace_id, state, created_at)
                VALUES (?, ?, ?)
                """,
                (int(existing["id"]), state, _utc_now()),
            )

    def list_calls(
        self,
        *,
        limit: int = 50,
        before_id: int | None = None,
        after_id: int | None = None,
    ) -> list[dict[str, object]]:
        self._ensure_schema()
        self._cleanup_if_due()
        self._expire_stale_pending_if_due()
        limit = max(1, min(int(limit), 200))
        where = ""
        params: list[object] = []
        order = "DESC"
        if before_id is not None:
            where = "WHERE id < ?"
            params.append(int(before_id))
        elif after_id is not None:
            where = "WHERE id > ?"
            params.append(int(after_id))
            order = "ASC"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, call_id, session_id, agent_loop_id, loop_sequence,
                       started_at, completed_at, provider_id, protocol,
                       model, stream, method, url, request_bytes, response_status,
                       response_bytes, response_raw_bytes, duration_ms,
                       state, error_type, error_message
                FROM llm_http_traces
                {where}
                ORDER BY id {order}
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._metadata(row) for row in rows]

    def get_call(self, call_id: str) -> dict[str, object] | None:
        self._ensure_schema()
        self._cleanup_if_due()
        self._expire_stale_pending_if_due()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM llm_http_traces WHERE call_id = ?",
                (call_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **self._metadata(row),
            "request_headers": row["request_headers"],
            "request_text": row["request_text"],
            "response_headers": row["response_headers"] or "",
            "response_text": row["response_text"] or "",
            "response_raw_text": row["response_raw_text"] or "",
            "media_truncation": _parse_manifest(row["media_truncation"]),
        }

    def restore_call(self, call_id: str) -> dict[str, object] | None:
        """按 manifest 回拼字节级原始报文；无清单的行原样返回。

        校验不通过时抛 ``ValueError``——调用方据此判断「存坏了」，而不是把
        残缺内容当成原始报文交付。
        """

        entry = self.get_call(call_id)
        if entry is None:
            return None
        result: dict[str, object] = dict(entry)
        manifest = entry.get("media_truncation")
        if not isinstance(manifest, dict):
            return result
        for field_name, key in (
            ("request_text", "request"),
            ("response_text", "response"),
            ("response_raw_text", "response_raw"),
        ):
            field_manifest = manifest.get(key)
            if not isinstance(field_manifest, dict):
                continue
            try:
                result[field_name] = self.truncator.restore(
                    str(entry[field_name]), field_manifest
                )
            except ValueError:
                logger.exception(
                    "Trace 媒体回拼校验失败：call_id=%s field=%s", call_id, key
                )
                raise
        return result

    def find_blob_mime(self, sha256: str) -> str | None:
        """反查某个 blob 的 mime，供下载端点作 Content-Type。"""

        self._ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT media_truncation FROM llm_http_traces
                WHERE media_truncation LIKE ?
                LIMIT 20
                """,
                (f"%{sha256}%",),
            ).fetchall()
        for row in rows:
            mime = find_manifest_mime(row["media_truncation"], sha256)
            if mime is not None:
                return mime
        return None

    def download_blob(self, sha256: str) -> tuple[bytes, str] | None:
        """取出 blob 并解成二进制；返回 ``(bytes, mime)``，缺失返回 ``None``。"""

        payload = self.blob_store.load(sha256)
        if payload is None:
            return None
        decoded = decode_payload(payload)
        if decoded is None:
            return None
        data, mime = decoded
        resolved = mime or self.find_blob_mime(sha256) or ""
        return data, resolved or "application/octet-stream"

    def list_events(
        self,
        *,
        after_event_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        self._ensure_schema()
        self._cleanup_if_due()
        self._expire_stale_pending_if_due()
        limit = max(1, min(int(limit), 500))
        where = ""
        params: list[object] = []
        order = "DESC"
        if after_event_id is not None:
            where = "WHERE events.event_id > ?"
            params.append(int(after_event_id))
            order = "ASC"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT events.event_id, events.state AS event_state,
                       traces.id, traces.call_id, traces.session_id, traces.agent_loop_id,
                       traces.loop_sequence, traces.started_at, traces.completed_at,
                       traces.provider_id, traces.protocol, traces.model, traces.stream,
                       traces.method, traces.url, traces.request_bytes,
                       traces.response_status, traces.response_bytes,
                       traces.response_raw_bytes, traces.duration_ms,
                       traces.state, traces.error_type, traces.error_message
                FROM llm_http_trace_events AS events
                JOIN llm_http_traces AS traces ON traces.id = events.trace_id
                {where}
                ORDER BY events.event_id {order}
                LIMIT ?
                """,
                params,
            ).fetchall()
        items = []
        for row in rows:
            item = {
                **self._metadata(row),
                "event_id": int(row["event_id"]),
                "state": row["event_state"] or row["state"],
            }
            if item["state"] == "pending":
                item.update(
                    completed_at=None,
                    response_status=None,
                    response_bytes=0,
                    response_raw_bytes=0,
                    duration_ms=None,
                    error_type=None,
                    error_message=None,
                )
            items.append(item)
        return items if order == "ASC" else list(reversed(items))

    def latest_event_id(self) -> int:
        self._ensure_schema()
        self._cleanup_if_due()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(event_id), 0) AS event_id FROM llm_http_trace_events"
            ).fetchone()
        return int(row["event_id"] if row else 0)

    def count_calls(self) -> int:
        self._ensure_schema()
        self._cleanup_if_due()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM llm_http_traces").fetchone()
        return int(row["count"] if row else 0)

    def clear(self) -> int:
        self._ensure_schema()
        with self._connect() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM llm_http_traces").fetchone()[0])
            conn.execute("DELETE FROM llm_http_trace_events")
            conn.execute("DELETE FROM llm_http_traces")
        return count

    def storage_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += Path(f"{self.path}{suffix}").stat().st_size
            except OSError:
                pass
        return total

    def _cleanup_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        if self._last_cleanup_date == today:
            return
        with self._cleanup_lock:
            if self._last_cleanup_date == today:
                return
            retention = timedelta(days=_TRACE_RETENTION_DAYS)
            cutoff = (now - retention).isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    DELETE FROM llm_http_trace_events
                    WHERE trace_id IN (
                        SELECT id FROM llm_http_traces WHERE started_at < ?
                    )
                    """,
                    (cutoff,),
                )
                conn.execute("DELETE FROM llm_http_traces WHERE started_at < ?", (cutoff,))
            self._cleanup_legacy_trace_files((now - retention).timestamp())
            # 先 DELETE 过期行再 sweep：此刻的引用集合才是准确的 mark。
            self._collect_orphaned_blobs()
            self._last_cleanup_date = today

    def _cleanup_legacy_trace_files(self, cutoff_timestamp: float) -> None:
        """Retain the previous JSONL trace format under the same 14-day policy."""

        try:
            paths = list(self.legacy_trace_dir.glob(_LEGACY_TRACE_GLOB))
        except OSError:
            return
        for path in paths:
            try:
                if path.stat().st_mtime < cutoff_timestamp:
                    path.unlink()
            except OSError:
                logger.debug("Failed to clean legacy LLM trace file: %s", path)

    def _collect_orphaned_blobs(self) -> None:
        """mark-sweep 清扫无引用 blob；挂在每日留存清理末尾。

        选扫描式而非引用计数：对任意删除路径（含运维手工清库）免疫，
        不存在计数漂移。24h 保守带规避「blob 已写入、引用行尚未提交」。
        """

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT media_truncation FROM llm_http_traces "
                    "WHERE media_truncation IS NOT NULL"
                ).fetchall()
        except sqlite3.Error:
            logger.exception("LLM trace blob 引用扫描失败")
            return
        referenced: set[str] = set()
        for row in rows:
            referenced |= collect_manifest_shas(row["media_truncation"])
        removed = self.blob_store.collect_orphaned(referenced, _TRACE_BLOB_GRACE_SECONDS)
        if removed:
            logger.info("LLM trace blob GC 已清理 %d 个无引用 blob", removed)

    def _expire_stale_pending_if_due(self) -> None:
        checked_at = time.monotonic()
        if (
            self._last_stale_check is not None
            and checked_at - self._last_stale_check < _TRACE_STALE_CHECK_INTERVAL_SECONDS
        ):
            return
        with self._stale_lock:
            checked_at = time.monotonic()
            if (
                self._last_stale_check is not None
                and checked_at - self._last_stale_check < _TRACE_STALE_CHECK_INTERVAL_SECONDS
            ):
                return
            cutoff = (datetime.now(timezone.utc) - _TRACE_STALE_AFTER).isoformat()
            completed_at = _utc_now()
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT id FROM llm_http_traces
                    WHERE state = 'pending' AND started_at < ?
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    cursor = conn.execute(
                        """
                        UPDATE llm_http_traces
                        SET completed_at = ?, state = 'error',
                            error_type = 'StaleTrace',
                            error_message = 'Trace remained pending for more than one hour'
                        WHERE id = ? AND state = 'pending'
                        """,
                        (completed_at, int(row["id"])),
                    )
                    if cursor.rowcount:
                        conn.execute(
                            """
                            INSERT INTO llm_http_trace_events (trace_id, state, created_at)
                            VALUES (?, 'error', ?)
                            """,
                            (int(row["id"]), completed_at),
                        )
            self._last_stale_check = checked_at


trace_store = LLMTraceStore(legacy_trace_dir=LOGS_DIR)


async def begin_http_trace(**values: object) -> str | None:
    """Start a trace when capture is active and return its call identifier."""

    if not trace_active():
        return None
    identity = _REQUEST_SESSION.get()
    values["session_id"] = identity.id if identity is not None else None
    loop = _AGENT_LOOP_TRACE.get()
    if loop is not None:
        loop.sequence += 1
        values["agent_loop_id"] = loop.loop_id
        values["loop_sequence"] = loop.sequence
    try:
        call_id = await asyncio.to_thread(trace_store.begin_call, **values)
    except (OSError, sqlite3.Error):
        logger.exception("LLM HTTP trace start failed")
        return None
    capture = _TRACE_CAPTURE.get()
    if capture is not None:
        capture.call_ids.append(call_id)
    return call_id


async def finish_http_trace(call_id: str | None, **values: object) -> None:
    """Finish an active trace while keeping storage I/O off the event loop."""

    if call_id is None:
        return
    try:
        await asyncio.to_thread(trace_store.finish_call, call_id, **values)
    except (OSError, sqlite3.Error):
        logger.exception("LLM HTTP trace finish failed: call_id=%s", call_id)
