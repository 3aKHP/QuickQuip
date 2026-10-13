from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider import LLMRequest, RetryPolicy, build_provider_client
from quickquip.llm.provider import base, trace
from quickquip.llm.session import create_session_identity
from quickquip.llm.tools import LLMConversationMessage


def _config(protocol="openai", **overrides):
    return ProviderConfig(
        client_fingerprint="legacy-claude" if protocol == "claude" else "default",
        id="test", protocol=protocol, base_url="https://example.test/v1",
        api_key_env="SESSION_TEST_KEY", default_model="m", models=["m"],
        stream_enabled=False, **overrides,
    )


def _request(session=None):
    return LLMRequest(
        model="m", system_prompt="system", messages=[LLMConversationMessage("user", "hello")],
        temperature=1.0, max_output_tokens=256, session=session,
    )


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
async def test_session_snapshot_does_not_change_wire_request(protocol, monkeypatch):
    monkeypatch.setenv("SESSION_TEST_KEY", "synthetic-key")
    client = build_provider_client(_config(protocol))
    original = _request()
    baseline = await client._build_request_parts(original)
    with_identity = await client._build_request_parts(
        replace(original, session=create_session_identity()),
    )
    assert with_identity == baseline


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
async def test_real_protocol_transport_trace_carries_identity(protocol, monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    bodies = {
        "openai": {"model": "m", "choices": [{"message": {"content": "ok"}}]},
        "claude": {"model": "m", "content": [{"type": "text", "text": "ok"}]},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        "openai_responses": {
            "id": "resp-test", "status": "completed",
            "output": [{"id": "msg-test", "type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}]}],
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=bodies[protocol]))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        base.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    identity = create_session_identity()
    with trace.collect_trace_calls(force=True) as calls:
        response = await build_provider_client(_config(protocol)).complete(_request(identity))
    assert response.text == "ok"
    assert len(calls) == 1
    assert store.list_calls()[0]["session_id"] == identity.id
    assert store.get_call(calls[0])["session_id"] == identity.id
    assert all(event["session_id"] == identity.id for event in store.list_events())


async def test_shared_client_concurrent_calls_do_not_cross_trace_identities(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    release = asyncio.Event()
    seen = []

    async def handler(request):
        seen.append(request)
        if len(seen) == 2:
            release.set()
        await asyncio.wait_for(release.wait(), 5)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        base.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    first, second = create_session_identity(), create_session_identity()
    client = build_provider_client(_config())
    with trace.collect_trace_calls(force=True):
        await asyncio.gather(client.complete(_request(first)), client.complete(_request(second)))
    assert {row["session_id"] for row in store.list_calls()} == {first.id, second.id}


async def test_retry_keeps_session_and_absent_session_masks_parent_context(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSION_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    responses = [429, 200, 200]

    def handler(request):
        status = responses.pop(0)
        body = {"choices": [{"message": {"content": "ok"}}]}
        return httpx.Response(status, json=body)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        base.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    parent, identity = create_session_identity(), create_session_identity()
    client = build_provider_client(_config(), retry_policy=RetryPolicy(2, 0, 0))
    with trace.collect_trace_calls(force=True), trace.trace_request_session(parent):
        await client.complete(_request(identity))
        assert trace._REQUEST_SESSION.get() == parent
        await client.complete(_request())
        assert trace._REQUEST_SESSION.get() == parent
    assert trace._REQUEST_SESSION.get() is None
    rows = list(reversed(store.list_calls()))
    assert [row["session_id"] for row in rows] == [identity.id, identity.id, None]


def test_trace_legacy_rows_stay_without_session(tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    call = store.begin_call(
        provider_id="p", protocol="openai", model="m", stream=False, method="POST",
        url="https://example.test", request_headers="", request_text="{}", request_bytes=2,
    )
    with store._connect() as conn:
        conn.execute("ALTER TABLE llm_http_traces DROP COLUMN session_id")
    upgraded = trace.LLMTraceStore(store.path)
    assert upgraded.get_call(call)["session_id"] is None
    assert upgraded.list_calls()[0]["session_id"] is None
