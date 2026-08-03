from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
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


def test_trace_store_cursor_pagination_and_concurrent_calls(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call_ids = [_begin(store, provider_id=f"p{i}") for i in range(3)]

    newest = store.list_calls(limit=2)
    assert [item["call_id"] for item in newest] == list(reversed(call_ids[1:]))
    older = store.list_calls(limit=2, before_id=int(newest[-1]["id"]))
    assert [item["call_id"] for item in older] == [call_ids[0]]
    assert len({item["call_id"] for item in store.list_calls(limit=10)}) == 3


def test_trace_store_migrates_first_release_schema(tmp_path):
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
            INSERT INTO llm_http_traces (
                call_id, started_at, provider_id, protocol, model, stream,
                method, url, request_headers, request_text, request_bytes,
                response_bytes, state
            ) VALUES (
                'legacy-call', '2026-08-03T00:00:00+00:00', 'p', 'openai',
                'm', 1, 'POST', 'https://llm.example', '', '{}', 2, 0, 'pending'
            );
            """
        )

    store = trace.LLMTraceStore(path)
    detail = store.get_call("legacy-call")

    assert detail is not None
    assert detail["agent_loop_id"] == "legacy-call"
    assert detail["loop_sequence"] == 1
    assert detail["response_raw_text"] == ""
    assert detail["response_raw_bytes"] == 0


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


def test_trace_store_expires_stale_pending_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(trace.time, "monotonic", lambda: 1.0)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call_id = _begin(store)
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE llm_http_traces SET started_at = ? WHERE call_id = ?",
            ("2000-01-01T00:00:00+00:00", call_id),
        )

    calls = store.list_calls()

    assert calls[0]["state"] == "error"
    assert calls[0]["error_type"] == "StaleTrace"
    assert [event["state"] for event in store.list_events()] == ["pending", "error"]


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
