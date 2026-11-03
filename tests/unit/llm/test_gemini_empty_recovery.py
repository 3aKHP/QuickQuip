"""GenerateContent's opt-in correction preserves generation state and bounds calls."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider import GeminiProviderClient, LLMProviderError, LLMRequest, trace
from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.usage import drain_usage_tasks
from tests.fixtures.client_fingerprints import protocol_only_config


def _body(*, text=None, finish="MAX_TOKENS", token="opaque-token", usage=True):
    parts = [{"text": "thinking", "thought": True, "thoughtSignature": "signed-thought"}]
    if text is not None:
        parts.append({"text": text})
    candidate = {"content": {"role": "model", "parts": parts}, "finishReason": finish}
    if token is not None:
        candidate["continuationToken"] = token
    result = {"candidates": [candidate]}
    if usage:
        result["usageMetadata"] = {
            "promptTokenCount": 30, "candidatesTokenCount": 1,
            "thoughtsTokenCount": 15, "cachedContentTokenCount": 20,
        }
    return result


def _request():
    return LLMRequest(
        model="vertex/gemini-test", system_prompt="system",
        messages=[LLMConversationMessage(role="user", content="question")],
        temperature=0.2, max_output_tokens=16,
    )


@pytest.fixture
async def metering(monkeypatch):
    records = []

    async def record(client, request, response, started, stream_used, state, *args):
        records.append((state, deepcopy(response)))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", record)
    yield records
    await drain_usage_tasks()


@pytest.fixture
def transport(monkeypatch):
    sent = []
    original = httpx.AsyncClient

    def install(responses, *, stream=False, enabled=True, single_dispatch=False, **config):
        async def handle(request):
            sent.append((str(request.url), json.loads(request.content)))
            item = responses.pop(0)
            if callable(item):
                return await item(request)
            if isinstance(item, int):
                return httpx.Response(item, text="unavailable")
            if stream:
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    text="data: " + json.dumps(item) + "\n\n",
                )
            return httpx.Response(200, json=item)

        monkeypatch.setattr(
            "quickquip.llm.provider.base.httpx.AsyncClient",
            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
        )
        provider = protocol_only_config(ProviderConfig(
            id="test", protocol="gemini", base_url="https://primary.test/v1beta",
            api_key_env="TEST_KEY", default_model="vertex/gemini-test",
            models=["vertex/gemini-test"], stream_enabled=stream,
            gemini_empty_response_recovery=enabled, retry_base_delay=0,
            **config,
        ))
        client = GeminiProviderClient(provider, single_dispatch=single_dispatch)
        monkeypatch.setattr(client, "_get_api_key", lambda: "test-key")
        return client

    return install, sent


@pytest.mark.parametrize("stream", [False, True])
async def test_recovery_preserves_prompt_signed_parts_usage_and_physical_traces(
    transport, metering, monkeypatch, tmp_path, stream,
):
    install, sent = transport
    first = _body()
    second = {
        "candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": "answer"}]},
        }],
        "usageMetadata": {
            "promptTokenCount": 46, "candidatesTokenCount": 5,
            "thoughtsTokenCount": 2, "cachedContentTokenCount": 30,
        },
    }
    client = install([first, second], stream=stream)
    store = trace.LLMTraceStore(tmp_path / "trace.db")
    monkeypatch.setattr(trace, "trace_store", store)
    with trace.collect_trace_calls(force=True) as call_ids:
        response = await client.complete(_request())
    await drain_usage_tasks()

    assert len(sent) == len(call_ids) == 2
    original_payload = sent[0][1]
    expected = deepcopy(original_payload)
    expected["continuationToken"] = "opaque-token"
    expected["generationConfig"]["maxOutputTokens"] = 32
    assert sent[1] == (sent[0][0], expected)
    assert response.text == "answer" and response.finish_reason == "STOP"
    assert response.native_blocks == [
        first["candidates"][0]["content"]["parts"][0], {"text": "answer"},
    ]
    assert (response.input_tokens, response.output_tokens) == (76, 6)
    assert (response.thinking_tokens, response.cache_read_tokens) == (17, 50)
    assert len(metering) == 1 and metering[0][0] == "ok"
    assert metering[0][1].input_tokens == 76
    for call_id, (_, payload) in zip(call_ids, sent, strict=True):
        assert json.loads(store.get_call(call_id)["request_text"]) == payload


@pytest.mark.parametrize("case", [
    "disabled", "text", "no_token", "stop", "safety", "continuation",
    "tool", "image", "audio", "cap", "single_dispatch",
])
async def test_recovery_gate_does_not_continue_other_results(transport, metering, case):
    install, sent = transport
    body = _body()
    candidate = body["candidates"][0]
    options = {}
    if case == "disabled":
        options["enabled"] = False
    elif case == "text":
        candidate["content"]["parts"].append({"text": "partial answer"})
    elif case == "no_token":
        del candidate["continuationToken"]
    elif case in ("stop", "safety", "continuation"):
        candidate["finishReason"] = case.upper()
    elif case == "tool":
        candidate["content"]["parts"].append({"functionCall": {"name": "tool", "args": {}}})
    elif case in ("image", "audio"):
        candidate["content"]["parts"].append({"inlineData": {
            "mimeType": "image/png" if case == "image" else "audio/wav", "data": "YQ==",
        }})
    elif case == "cap":
        options["gemini_empty_response_recovery_max_output_tokens"] = 16
    elif case == "single_dispatch":
        options["single_dispatch"] = True
    await install([body], **options).complete(_request())
    assert len(sent) == 1


async def test_recovery_caps_expansion_and_never_recurses(transport, metering):
    install, sent = transport
    client = install([_body(text="  "), _body(token="next-token")],
                     gemini_empty_response_recovery_max_output_tokens=20)
    response = await client.complete(_request())
    assert len(sent) == 2
    assert sent[1][1]["generationConfig"]["maxOutputTokens"] == 20
    assert response.text == "" and response.finish_reason == "MAX_TOKENS"


async def test_missing_recovery_usage_does_not_count_initial_usage_twice(transport, metering):
    install, _sent = transport
    client = install([_body(), _body(text="answer", finish="STOP", usage=False)])
    response = await client.complete(_request())
    assert response.input_tokens == 30 and response.thinking_tokens == 15


@pytest.mark.parametrize("stream", [False, True])
async def test_recovery_keeps_unsigned_and_signed_thought_parts_separate(
    transport, metering, stream,
):
    install, _sent = transport
    first = _body()
    del first["candidates"][0]["content"]["parts"][0]["thoughtSignature"]
    second = _body(text="answer", finish="STOP")
    second["candidates"][0]["content"]["parts"][0]["text"] = "later thought"
    client = install([first, second], stream=stream)
    response = await client.complete(_request())
    assert response.native_blocks == (
        first["candidates"][0]["content"]["parts"]
        + second["candidates"][0]["content"]["parts"]
    )
    assert response.thinking_blocks[1]["part"]["text"] == "later thought"
    assert response.thinking_blocks[1]["part"]["thoughtSignature"] == "signed-thought"


@pytest.mark.parametrize("stream", [False, True])
async def test_recovery_with_no_candidate_preserves_its_reported_usage(
    transport, metering, stream,
):
    install, sent = transport
    second = {
        "promptFeedback": {"blockReason": "SAFETY"},
        "usageMetadata": {"promptTokenCount": 40, "cachedContentTokenCount": 25},
    }
    client = install([_body(), second], stream=stream)
    with pytest.raises(LLMProviderError, match="补正"):
        await client.complete(_request())
    await drain_usage_tasks()
    assert len(sent) == 2
    assert [state for state, _ in metering] == ["ok", "error"]
    assert metering[0][1].input_tokens == 70
    assert metering[0][1].cache_read_tokens == 45
    assert metering[0][1].thinking_tokens == 15


@pytest.mark.parametrize("stream", [False, True])
async def test_failed_correction_does_not_replay_or_fallback_and_keeps_spent_usage(
    transport, metering, stream,
):
    install, sent = transport
    client = install(
        [503, _body(), 503], stream=stream, fallback_urls=["https://backup.test/v1beta"],
    )
    with pytest.raises(LLMProviderError, match="补正"):
        await client.complete(_request())
    await drain_usage_tasks()
    assert len(sent) == 3
    assert "backup.test" in sent[1][0] and sent[2][0] == sent[1][0]
    assert [state for state, _ in metering] == ["ok", "error"]
    assert metering[0][1].thinking_tokens == 15


async def test_cancellation_during_correction_keeps_usage_and_stops_calls(transport, metering):
    install, sent = transport
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=_body(text="answer", finish="STOP"))

    task = asyncio.create_task(install([_body(), block]).complete(_request()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    await drain_usage_tasks()
    assert len(sent) == 2
    assert [state for state, _ in metering] == ["ok", "cancelled"]
    assert metering[0][1].input_tokens == 30


@pytest.mark.parametrize("stream", [False, True])
async def test_correction_has_a_total_timeout_without_restarting(transport, metering, stream):
    install, sent = transport

    async def block(request):
        await asyncio.Event().wait()

    client = install([_body(), block], stream=stream, timeout_seconds=0.01)
    with pytest.raises(LLMProviderError, match="补正"):
        await asyncio.wait_for(client.complete(_request()), timeout=1)
    await drain_usage_tasks()
    assert len(sent) == 2
    assert [state for state, _ in metering] == ["ok", "error"]
    assert metering[0][1].thinking_tokens == 15
