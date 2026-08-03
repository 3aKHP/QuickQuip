"""SSE stream parsing in BaseProviderClient._post_stream_sse.

These tests feed constructed SSE text through the real _post_stream_sse by
monkeypatching httpx.AsyncClient.stream to return a fake streaming response,
verifying the SSE line-parsing semantics ([DONE] termination, multi-line data
space-join, _sse_event injection, CRLF handling) survive the urllib→httpx
migration.
"""
from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMProviderError, OpenAIProviderClient
from quickquip.llm.provider import trace


def _make_config(**overrides) -> ProviderConfig:
    defaults = dict(
        id="test",
        protocol="openai",
        base_url="http://test",
        api_key_env="TEST_KEY",
        default_model="m",
        models=["m"],
        stream_enabled=True,
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class _FakeStreamResponse:
    """Mimics the subset of httpx.Response used by _post_stream_sse."""

    def __init__(self, chunks: list[str], status_code: int = 200, error_body: str = ""):
        self._chunks = chunks
        self.status_code = status_code
        self.text = error_body
        self.headers = httpx.Headers({"content-type": "text/event-stream"})
        self.request = MagicMock()

    async def aread(self) -> None:
        """Simulate httpx Response.aread(): materializes the body into .text."""
        # In the real httpx, aread() reads the stream into .content/.text. The
        # fake's error_body is already set; this is a no-op marker so production
        # code's `await response.aread()` works before raise_for_status().
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=self.request, response=self  # type: ignore[arg-type]
            )

    async def aiter_text(self) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


def _patch_stream(
    monkeypatch,
    lines: list[str],
    status_code: int = 200,
    error_body: str = "",
):
    """Monkeypatch httpx.AsyncClient.stream to return a fake SSE response.

    httpx 0.28's stream() is a *synchronous* method returning an async context
    manager, so the fake must also be a plain function returning the context.
    """
    response = _FakeStreamResponse(
        ["\n".join(lines)], status_code=status_code, error_body=error_body
    )

    def fake_stream(self, method, url, **kwargs):
        return _FakeStreamContext(response)

    # AsyncClient.stream is a bound method; patch on the class.
    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    return response


@pytest.fixture
def client():
    return OpenAIProviderClient(_make_config())


async def test_sse_done_marker_terminates(client, monkeypatch):
    """[DONE] on a data line stops collection immediately."""
    lines = [
        'data: {"choices":[{"delta":{"content":"hi"}}]}',
        "",
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"should-not-appear"}}]}',
        "",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    # Only the first event was collected; the [DONE] line broke the loop.
    assert len(events) == 1
    assert events[0]["choices"][0]["delta"]["content"] == "hi"


async def test_sse_multi_data_space_join(client, monkeypatch):
    """Multiple consecutive data: lines before a blank line are joined with a space."""
    lines = [
        'data: {"part":',
        'data: "merged"}',
        "",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    assert len(events) == 1
    assert events[0] == {"part": "merged"}


async def test_sse_event_name_injection(client, monkeypatch):
    """The event: field is carried into the parsed dict as _sse_event."""
    lines = [
        "event: content_block_delta",
        'data: {"type":"content_block_delta"}',
        "",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    assert len(events) == 1
    assert events[0]["_sse_event"] == "content_block_delta"


async def test_sse_crlf_line_endings(client, monkeypatch):
    """Lines terminated with \r\n are stripped correctly (aiter_lines drops \n,
    the parser rstrips the remaining \r)."""
    # aiter_lines() strips \n; we simulate \r\n by including \r here.
    lines = [
        "event: ping\r",
        'data: {"ok":true}\r',
        "\r",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    assert len(events) == 1
    assert events[0]["_sse_event"] == "ping"
    assert events[0]["ok"] is True


async def test_sse_invalid_json_silently_dropped(client, monkeypatch):
    """A data block whose joined content is not valid JSON is skipped, not raised."""
    lines = [
        "data: {not valid json}",
        "",
        'data: {"valid":true}',
        "",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    assert len(events) == 1
    assert events[0] == {"valid": True}


async def test_sse_blank_line_without_data_no_event(client, monkeypatch):
    """An empty event boundary with no accumulated data produces no event."""
    lines = [
        "",
        'data: {"only":"one"}',
        "",
    ]
    _patch_stream(monkeypatch, lines)
    events = await client._post_stream_sse("http://x", {}, {})
    assert len(events) == 1


async def test_sse_accept_header_lowercased(client, monkeypatch):
    """The injected SSE accept header uses lowercase 'accept' (not 'Accept')."""
    captured: dict = {}

    def fake_stream(self, method, url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        return _FakeStreamContext(_FakeStreamResponse([""]))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    await client._post_stream_sse("http://x", {"content-type": "application/json"}, {})
    assert captured["headers"]["accept"] == "text/event-stream"


async def test_sse_http_error_mapped(client, monkeypatch):
    """A 4xx/5xx response becomes LLMProviderError with 'HTTP ' prefix (fallback contract).

    Regression guard: streamed error bodies must be read (via aread) before
    raise_for_status so exc.response.text is accessible; otherwise httpx raises
    ResponseNotRead and the error message is lost.
    """
    _patch_stream(
        monkeypatch, [], status_code=429, error_body='{"error":"rate limited"}'
    )
    with pytest.raises(LLMProviderError) as exc_info:
        await client._post_stream_sse("http://x", {}, {})
    msg = str(exc_info.value)
    assert msg.startswith("HTTP 429")
    assert "rate limited" in msg  # error body was read and surfaced


async def test_stream_trace_is_one_complete_combined_json_document(
    client, monkeypatch, tmp_path
):
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    captured: dict[str, object] = {}
    chunks = [
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n',
        "data: [DONE]\n\n",
    ]

    def fake_stream(self, method, url, **kwargs):
        captured["body"] = kwargs["content"]
        return _FakeStreamContext(_FakeStreamResponse(chunks))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    payload = {"model": "m", "messages": [{"role": "user", "content": "你好"}]}

    with trace.collect_trace_calls(force=True) as call_ids:
        await client._post_stream_sse("http://x", {}, payload)

    assert len(call_ids) == 1
    detail = store.get_call(call_ids[0])
    assert detail is not None
    assert detail["request_text"].encode("utf-8") == captured["body"]
    assert json.loads(detail["request_text"]) == payload
    combined = json.loads(detail["response_text"])
    assert combined["object"] == "chat.completion"
    assert combined["choices"][0]["message"]["content"] == "你好"
    assert not isinstance(combined, list)
    assert "data:" not in detail["response_text"]
    assert "data:" in detail["response_raw_text"]
    assert detail["response_raw_bytes"] == len(detail["response_raw_text"].encode("utf-8"))
    assert detail["state"] == "success"
