from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider import BaseProviderClient, trace
from quickquip.llm.provider import base as provider_base


def _config(**overrides) -> ProviderConfig:
    values = {
        "id": "test",
        "protocol": "openai",
        "base_url": "https://primary.example/v1",
        "api_key_env": "TEST_KEY",
        "default_model": "m",
        "models": ["m"],
    }
    values.update(overrides)
    return ProviderConfig(**values)


class _FakeClient:
    def __init__(self, responses: list[httpx.Response], sent: list[dict[str, object]], **kwargs):
        self._responses = responses
        self._sent = sent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url: str, **kwargs):
        self._sent.append({"url": url, **kwargs})
        return self._responses.pop(0)


def _response(status: int, text: str) -> httpx.Response:
    request = httpx.Request("POST", "https://llm.example")
    return httpx.Response(
        status,
        text=text,
        headers={"content-type": "application/json; charset=utf-8"},
        request=request,
    )


async def test_non_stream_trace_keeps_sent_body_and_original_response_text(
    monkeypatch, tmp_path
):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    sent: list[dict[str, object]] = []
    original = '{\n  "answer": "你好",\n  "order": 1\n}\n'
    responses = [_response(200, original)]
    monkeypatch.setattr(
        provider_base.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(responses, sent, **kwargs),
    )
    client = BaseProviderClient(_config())
    payload = {"model": "m", "messages": [{"role": "user", "content": "你好"}]}

    with trace.collect_trace_calls(force=True) as call_ids:
        result = await client._post_json(
            "https://primary.example/v1/chat/completions",
            {"authorization": "Bearer secret"},
            payload,
        )

    assert result == {"answer": "你好", "order": 1}
    assert len(call_ids) == 1
    detail = store.get_call(call_ids[0])
    assert detail is not None
    assert sent[0]["content"] == detail["request_text"].encode("utf-8")
    assert json.loads(detail["request_text"]) == payload
    assert detail["response_text"] == original
    assert detail["response_bytes"] == len(original.encode("utf-8"))


async def test_http_fallback_attempts_are_separate_correlated_calls(
    monkeypatch, tmp_path
):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    sent: list[dict[str, object]] = []
    responses = [
        _response(503, '{"error":"unavailable"}'),
        _response(200, '{"ok":true}'),
    ]
    monkeypatch.setattr(
        provider_base.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(responses, sent, **kwargs),
    )
    client = BaseProviderClient(
        _config(fallback_urls=["https://fallback.example/v1"])
    )

    with trace.collect_trace_calls(force=True) as call_ids:
        result = await client._post_json_with_fallback(
            "https://primary.example/v1/chat/completions",
            {},
            {"model": "m"},
        )

    assert result == {"ok": True}
    assert len(call_ids) == 2
    first = store.get_call(call_ids[0])
    second = store.get_call(call_ids[1])
    assert first is not None and second is not None
    assert first["state"] == "error"
    assert first["response_status"] == 503
    assert first["url"].startswith("https://primary.example/")
    assert second["state"] == "success"
    assert second["response_status"] == 200
    assert second["url"].startswith("https://fallback.example/")
    assert first["call_id"] != second["call_id"]


async def test_non_stream_cancellation_finishes_pending_trace(monkeypatch, tmp_path):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    started = asyncio.Event()
    never = asyncio.Event()

    class BlockingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url: str, **kwargs):
            started.set()
            await never.wait()

    monkeypatch.setattr(provider_base.httpx, "AsyncClient", BlockingClient)
    client = BaseProviderClient(_config())

    with trace.collect_trace_calls(force=True) as call_ids:
        task = asyncio.create_task(
            client._post_json(
                "https://primary.example/v1/chat/completions",
                {},
                {"model": "m"},
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    detail = store.get_call(call_ids[0])
    assert detail is not None
    assert detail["state"] == "error"
    assert detail["error_type"] == "CancelledError"
