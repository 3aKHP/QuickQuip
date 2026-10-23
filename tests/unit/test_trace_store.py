from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import threading
import time

from quickquip.llm.provider import trace


def _begin(store: trace.LLMTraceStore, *, provider_id: str = "demo") -> str:
    return store.begin_call(
        provider_id=provider_id,
        protocol="openai",
        model="gpt-test",
        stream=True,
        method="POST",
        url="https://llm.example/v1/chat/completions",
        request_headers="authorization: Bearer secret",
        request_text='{"message":"你好"}',
        request_bytes=len('{"message":"你好"}'.encode("utf-8")),
    )


def test_trace_store_lifecycle_metadata_detail_events_and_clear(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call_id = _begin(store)

    pending = store.list_calls()
    assert len(pending) == 1
    assert pending[0]["call_id"] == call_id
    assert pending[0]["agent_loop_id"] == call_id
    assert pending[0]["loop_sequence"] == 1
    assert pending[0]["state"] == "pending"
    assert "request_text" not in pending[0]
    assert "response_text" not in pending[0]

    store.finish_call(
        call_id,
        state="success",
        response_status=200,
        response_headers="content-type: text/event-stream",
        response_text='[\n  {"delta": "你好"}\n]',
        response_bytes=len('[\n  {"delta": "你好"}\n]'.encode("utf-8")),
        response_raw_text='data: {"delta":"你好"}\n\n',
        response_raw_bytes=len('data: {"delta":"你好"}\n\n'.encode("utf-8")),
        duration_ms=12.5,
    )

    detail = store.get_call(call_id)
    assert detail is not None
    assert detail["request_text"] == '{"message":"你好"}'
    assert detail["request_headers"] == "authorization: Bearer secret"
    assert detail["response_text"] == '[\n  {"delta": "你好"}\n]'
    assert detail["response_raw_text"].startswith("data:")
    assert detail["state"] == "success"

    events = store.list_events(after_event_id=0)
    assert [event["state"] for event in events] == ["pending", "success"]
    assert events[0]["event_id"] < events[1]["event_id"]
    assert all("request_text" not in event for event in events)

    assert store.clear() == 1
    assert store.list_calls() == []
    assert store.list_events(after_event_id=0) == []


def test_trace_store_cursor_pagination(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call_ids = [_begin(store, provider_id=f"p{i}") for i in range(3)]

    newest = store.list_calls(limit=2)
    assert [item["call_id"] for item in newest] == list(reversed(call_ids[1:]))
    older = store.list_calls(limit=2, before_id=int(newest[-1]["id"]))
    assert [item["call_id"] for item in older] == [call_ids[0]]
    assert len({item["call_id"] for item in store.list_calls(limit=10)}) == 3


def test_trace_store_migrates_first_release_schema(tmp_path, monkeypatch):
    # started_at 必须落在 14 天保留期内（相对 now 计算），否则行会在访问前被清理
    started = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    path = tmp_path / "trace.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE llm_http_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL UNIQUE,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                provider_id TEXT NOT NULL,
                protocol TEXT NOT NULL,
                model TEXT NOT NULL,
                stream INTEGER NOT NULL,
                method TEXT NOT NULL,
                url TEXT NOT NULL,
                request_headers TEXT NOT NULL,
                request_text TEXT NOT NULL,
                request_bytes INTEGER NOT NULL,
                response_status INTEGER,
                response_headers TEXT,
                response_text TEXT,
                response_bytes INTEGER NOT NULL DEFAULT 0,
                duration_ms REAL,
                state TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT
            );
            CREATE TABLE llm_http_trace_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO llm_http_traces (
                call_id, started_at, provider_id, protocol, model, stream,
                method, url, request_headers, request_text, request_bytes,
                response_bytes, state
            ) VALUES (
                'legacy-call', '{started}', 'p', 'openai',
                'm', 1, 'POST', 'https://llm.example', '', '{{}}', 2, 0, 'pending'
            );
            """
        )

    store = trace.LLMTraceStore(path)
    statements = []
    original_connect = store._connect

    def capture_connect():
        conn = original_connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(store, "_connect", capture_connect)
    detail = store.get_call("legacy-call")

    assert detail is not None
    assert detail["agent_loop_id"] == "legacy-call"
    assert store.restore_call("legacy-call")["media_truncation"] is None
    assert detail["loop_sequence"] == 1
    assert detail["response_raw_text"] == ""
    assert detail["response_raw_bytes"] == 0

    # Explain the actual maintenance SELECT, guarding against payload-table scans.
    pending_query = next(sql for sql in statements
                         if " ".join(sql.split()).startswith("SELECT id FROM llm_http_traces"))
    with sqlite3.connect(path) as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + pending_query).fetchall()
    assert any("COVERING INDEX idx_llm_http_traces_state_started" in row[3] for row in plan)
    assert trace.LLMTraceStore(path).get_call("legacy-call") == detail


def test_trace_store_migration_is_serialized_across_instances(tmp_path):
    path = tmp_path / "trace.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE llm_http_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL UNIQUE,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                provider_id TEXT NOT NULL,
                protocol TEXT NOT NULL,
                model TEXT NOT NULL,
                stream INTEGER NOT NULL,
                method TEXT NOT NULL,
                url TEXT NOT NULL,
                request_headers TEXT NOT NULL,
                request_text TEXT NOT NULL,
                request_bytes INTEGER NOT NULL,
                response_status INTEGER,
                response_headers TEXT,
                response_text TEXT,
                response_bytes INTEGER NOT NULL DEFAULT 0,
                duration_ms REAL,
                state TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT
            );
            CREATE TABLE llm_http_trace_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    ready = threading.Barrier(2)

    def migrate() -> int:
        ready.wait()
        return trace.LLMTraceStore(path).count_calls()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate(), range(2)))

    assert results == [0, 0]
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_http_traces)")}
    assert {"agent_loop_id", "loop_sequence", "response_raw_text"} <= columns


class _RetryingConnection:
    def __init__(self, *, failures: int):
        self.failures = failures
        self.wal_attempts = 0
        self.statements: list[str] = []
        self.errors: list[sqlite3.OperationalError] = []
        self.closed = False
        self.row_factory = None

    def execute(self, statement: str):
        self.statements.append(statement)
        if statement == "PRAGMA journal_mode=WAL":
            self.wal_attempts += 1
            if self.wal_attempts <= self.failures:
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                self.errors.append(error)
                raise error
        return self

    def close(self) -> None:
        self.closed = True


def test_trace_store_retries_wal_setup_with_a_bounded_fast_failure_window(
    monkeypatch, tmp_path
):
    connection = _RetryingConnection(failures=2)
    sleeps: list[float] = []
    monkeypatch.setattr(trace.sqlite3, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(trace.time, "sleep", sleeps.append)

    result = trace.LLMTraceStore(tmp_path / "trace.db")._connect()

    assert result is connection
    assert connection.wal_attempts == 3
    assert sleeps == [trace._SQLITE_BUSY_RETRY_DELAY_SECONDS] * 2
    assert connection.statements[0] == "PRAGMA busy_timeout=0"
    assert connection.statements[-2:] == [
        f"PRAGMA busy_timeout={trace._SQLITE_BUSY_TIMEOUT_MS}",
        "PRAGMA synchronous=NORMAL",
    ]
    assert not connection.closed


def test_trace_store_closes_connection_when_wal_retries_are_exhausted(
    monkeypatch, tmp_path
):
    connection = _RetryingConnection(failures=3)
    monkeypatch.setattr(trace, "_SQLITE_BUSY_RETRY_ATTEMPTS", 3)
    monkeypatch.setattr(trace.sqlite3, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(trace.time, "sleep", lambda _delay: None)

    try:
        trace.LLMTraceStore(tmp_path / "trace.db")._connect()
    except sqlite3.OperationalError as error:
        assert error is connection.errors[-1]
    else:
        raise AssertionError("expected WAL setup to exhaust its retries")

    assert connection.wal_attempts == 3
    assert connection.closed


def test_trace_store_expires_stale_pending_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(trace.time, "monotonic", lambda: 1.0)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call_id = _begin(store)
    fresh_id = _begin(store)
    finished_id = _begin(store)
    store.finish_call(
        finished_id, state="success", response_status=200, response_headers="",
        response_text="{}", response_bytes=2, duration_ms=1.0,
    )
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE llm_http_traces SET started_at = ? WHERE call_id IN (?, ?)",
            ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
             call_id, finished_id),
        )

    calls = {call["call_id"]: call for call in store.list_calls()}

    assert calls[call_id]["state"] == "error"
    assert calls[call_id]["error_type"] == "StaleTrace"
    assert calls[fresh_id]["state"] == "pending"
    assert calls[finished_id]["state"] == "success"
    assert [event["state"] for event in store.list_events()
            if event["call_id"] == call_id] == ["pending", "error"]


def test_trace_store_cleanup_removes_only_expired_legacy_jsonl(tmp_path):
    legacy_dir = tmp_path / "logs"
    legacy_dir.mkdir()
    expired = legacy_dir / "quickquip_trace_2000-01-01.jsonl"
    retained = legacy_dir / "quickquip_trace_2099-01-01.jsonl"
    unrelated = legacy_dir / "quickquip_2000-01-01.log"
    for path in (expired, retained, unrelated):
        path.write_text('{"payload":"sensitive"}\n', encoding="utf-8")

    now = time.time()
    os.utime(expired, (now - 15 * 86400, now - 15 * 86400))
    os.utime(retained, (now - 13 * 86400, now - 13 * 86400))
    os.utime(unrelated, (now - 15 * 86400, now - 15 * 86400))

    store = trace.LLMTraceStore(tmp_path / "trace.db")
    assert store.count_calls() == 0

    assert not expired.exists()
    assert retained.exists()
    assert unrelated.exists()


async def test_forced_capture_records_without_global_flag(monkeypatch, tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    monkeypatch.setattr(trace, "_TRACE_FLAG_FILE", "")

    with trace.collect_trace_calls(force=True) as call_ids:
        call_id = await trace.begin_http_trace(
            provider_id="demo",
            protocol="openai",
            model="m",
            stream=False,
            method="POST",
            url="https://llm.example",
            request_headers="",
            request_text="{}",
            request_bytes=2,
        )
        await trace.finish_http_trace(
            call_id,
            state="success",
            response_status=200,
            response_headers="",
            response_text="{}",
            response_bytes=2,
            duration_ms=1.0,
        )

    assert call_ids == [call_id]
    assert store.get_call(call_id)["state"] == "success"  # type: ignore[index]


def test_context_capture_is_task_local(monkeypatch, tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    monkeypatch.setattr(trace, "_TRACE_FLAG_FILE", "")

    async def capture(provider_id: str) -> tuple[str, list[str]]:
        with trace.collect_trace_calls(force=True) as call_ids:
            call_id = await trace.begin_http_trace(
                provider_id=provider_id,
                protocol="openai",
                model="m",
                stream=False,
                method="POST",
                url="https://llm.example",
                request_headers="",
                request_text="{}",
                request_bytes=2,
            )
            await asyncio.sleep(0)
            return call_id, call_ids  # type: ignore[return-value]

    async def run():
        return await asyncio.gather(capture("a"), capture("b"))

    first, second = asyncio.run(run())
    assert first[1] == [first[0]]
    assert second[1] == [second[0]]
    assert first[0] != second[0]


async def test_agent_loop_groups_http_calls_with_monotonic_sequence(monkeypatch, tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    monkeypatch.setattr(trace, "_TRACE_FLAG_FILE", "")

    @trace.trace_agent_loop
    async def run_loop():
        with trace.collect_trace_calls(force=True) as call_ids:
            for provider_id in ("first", "second"):
                await trace.begin_http_trace(
                    provider_id=provider_id,
                    protocol="openai",
                    model="m",
                    stream=True,
                    method="POST",
                    url="https://llm.example",
                    request_headers="",
                    request_text="{}",
                    request_bytes=2,
                )
            return call_ids

    call_ids = await run_loop()
    details = [store.get_call(call_id) for call_id in call_ids]
    assert all(detail is not None for detail in details)
    assert {detail["agent_loop_id"] for detail in details if detail} == {
        details[0]["agent_loop_id"]  # type: ignore[index]
    }
    assert [detail["loop_sequence"] for detail in details if detail] == [1, 2]


def _begin_media(store, text):
    return store.begin_call(
        provider_id="demo", protocol="openai", model="test", stream=True,
        method="POST", url="https://example.test", request_headers="{}",
        request_text=text, request_bytes=len(text.encode()),
    )


def _finish_media(store, call_id, text):
    store.finish_call(
        call_id, state="success", response_status=200, response_headers="{}",
        response_text=text, response_bytes=len(text.encode()), duration_ms=1,
        response_raw_text="data: " + text + "\n\n",
        response_raw_bytes=len(("data: " + text + "\n\n").encode()),
    )


def test_media_three_field_restore_disable_and_missing_call(tmp_path):
    import json
    import pytest

    store = trace.LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    text = json.dumps({"note": "中文", "image": "A" * 256})
    call_id = _begin_media(store, text)
    _finish_media(store, call_id, text)
    entry = store.get_call(call_id)
    assert set(entry["media_truncation"]) == {"v", "request", "response", "response_raw"}
    assert entry["request_bytes"] == entry["response_bytes"] == len(text.encode())
    assert entry["response_raw_bytes"] == len(("data: " + text + "\n\n").encode())
    assert len(list(store.blob_dir.rglob("*.b64"))) == 1

    disabled = trace.LLMTraceStore(store.path, media_min_bytes=0)
    restored = disabled.restore_call(call_id)
    assert restored["request_text"] == restored["response_text"] == text
    assert restored["response_raw_text"] == "data: " + text + "\n\n"
    plain_id = _begin_media(disabled, text)
    _finish_media(disabled, plain_id, text)
    assert disabled.restore_call(plain_id)["media_truncation"] is None
    assert disabled.get_call(plain_id)["request_text"] == text
    assert disabled.restore_call("missing") is None
    before_events = store.latest_event_id()
    _finish_media(store, "missing", json.dumps({"image": "B" * 256}))
    assert store.latest_event_id() == before_events
    assert len(list(store.blob_dir.rglob("*.b64"))) == 1

    blob = next(store.blob_dir.rglob("*.b64"))
    blob.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError):
        store.restore_call(call_id)
    blob.unlink()
    with pytest.raises(ValueError):
        store.restore_call(call_id)


def test_finish_replacement_removes_stale_response_manifest(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    text = '{"image":"' + "A" * 256 + '"}'
    call_id = _begin_media(store, text)
    _finish_media(store, call_id, text)
    _finish_media(store, call_id, '{"text":"replacement"}')
    restored = store.restore_call(call_id)
    assert restored["request_text"] == text
    assert restored["response_text"] == '{"text":"replacement"}'
    assert set(restored["media_truncation"]) == {"v", "request"}


def _media_writer_process(path, text, ready, start, attempting, result):
    store = trace.LLMTraceStore(path, media_min_bytes=64)
    store._ensure_schema()
    store._last_cleanup_date = datetime.now(timezone.utc).date().isoformat()
    connect = store._connect

    def observe_connect():
        attempting.set()
        return connect()

    store._connect = observe_connect
    ready.set()
    if not start.wait(15):
        raise RuntimeError("writer start timed out")
    result.put(_begin_media(store, text))


def test_gc_and_new_reference_are_coordinated_across_processes(tmp_path, monkeypatch):
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    ready, start, attempting = (ctx.Event() for _ in range(3))
    result = ctx.Queue()
    store = trace.LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    text = '{"image":"' + "A" * 256 + '"}'
    old_call = _begin_media(store, text)
    old_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE llm_http_traces SET started_at=? WHERE call_id=?", (old_time, old_call),
        )
    blob = next(store.blob_dir.rglob("*.b64"))
    old_mtime = time.time() - 3 * 86400
    os.utime(blob, (old_mtime, old_mtime))
    scanned, release = threading.Event(), threading.Event()
    sweep = store.blob_store.collect_orphaned

    def paused_sweep(referenced, grace_seconds):
        assert not referenced
        scanned.set()
        assert release.wait(15)
        return sweep(referenced, grace_seconds)

    monkeypatch.setattr(store.blob_store, "collect_orphaned", paused_sweep)
    writer = ctx.Process(
        target=_media_writer_process,
        args=(store.path, text, ready, start, attempting, result),
    )
    writer.start()
    try:
        assert ready.wait(15)
        store._last_cleanup_date = None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.count_calls)
            try:
                assert scanned.wait(15)
                start.set()
                assert attempting.wait(15)
            finally:
                release.set()
            future.result(timeout=15)
        writer.join(timeout=15)
        assert writer.exitcode == 0
        call_id = result.get(timeout=5)
        assert store.restore_call(call_id)["request_text"] == text
        assert blob.exists()
    finally:
        release.set()
        start.set()
        if writer.is_alive():
            writer.terminate()
        writer.join(timeout=5)
        result.close()


def test_clear_removes_media_and_orphan_downloads(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    call_id = _begin_media(store, '{"image":"' + "A" * 256 + '"}')
    sha = store.get_call(call_id)["media_truncation"]["request"]["splices"][0]["sha256"]
    assert store.download_blob(sha) is not None
    assert store.clear() == 1
    assert store.count_calls() == 0
    assert store.download_blob(sha) is None
    assert not list(store.blob_dir.rglob("*.b64"))
    # 即使失败写入留下无引用文件，也不允许按摘要绕过记录生命周期下载。
    orphan, _ = store.blob_store.store("A" * 256)
    assert store.download_blob(orphan) is None


def test_gc_skips_invalid_manifest_without_deleting_media(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db", media_min_bytes=64)
    call_id = _begin_media(store, '{"image":"' + "A" * 256 + '"}')
    blob = next(store.blob_dir.rglob("*.b64"))
    with store._connect() as conn:
        conn.execute(
            "UPDATE llm_http_traces SET media_truncation=? WHERE call_id=?", ("{broken", call_id),
        )
    store._collect_orphaned_blobs(grace_seconds=0)
    assert blob.exists()
