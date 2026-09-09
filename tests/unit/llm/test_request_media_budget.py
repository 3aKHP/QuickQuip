"""Validate media limits on complete wire payloads for every provider protocol."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider import ClaudeProviderClient, GeminiProviderClient, OpenAIProviderClient
from quickquip.llm.provider.base import LLMImageInput, LLMProviderError, LLMRequest
from quickquip.llm.tools import LLMConversationMessage, LLMInlineImage, LLMToolCall


def _png(color: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), (color, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def _image(data: bytes, label: str = "image") -> LLMInlineImage:
    return LLMInlineImage(data=data, media_type="image/png", source_label=label)


def _request(messages: list[LLMConversationMessage]) -> LLMRequest:
    return LLMRequest(model="test", system_prompt="test", messages=messages,
                      temperature=0.7, max_output_tokens=100)


def _payload_images(value):
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            yield base64.b64decode(value["image_url"]["url"].split(",", 1)[1])
            return
        if value.get("type") == "image" and value.get("source", {}).get("type") == "base64":
            yield base64.b64decode(value["source"]["data"])
            return
        for key, child in value.items():
            if key in {"inline_data", "inlineData"}:
                yield base64.b64decode(child["data"])
            else:
                yield from _payload_images(child)
    elif isinstance(value, list):
        for child in value:
            yield from _payload_images(child)


@pytest.fixture(params=[("openai", OpenAIProviderClient), ("claude", ClaudeProviderClient), ("gemini", GeminiProviderClient)])
def client(request, monkeypatch):
    protocol, client_type = request.param
    config = ProviderConfig(id="review", protocol=protocol, base_url="https://example.test/v1",
                            api_key_env="TEST_MEDIA_KEY", default_model="test", models=["test"])
    monkeypatch.setenv("TEST_MEDIA_KEY", "synthetic-key")
    return client_type(config)


async def test_whole_request_budget_prioritizes_current_user(client):
    old, current = _png(1), _png(2)
    client.config = replace(client.config, max_inline_media_bytes=len(current) + 1)
    request = _request([
        LLMConversationMessage(role="user", content="earlier", inline_images=[_image(old)]),
        LLMConversationMessage(role="assistant", content="reply"),
        LLMConversationMessage(role="user", content="current", inline_images=[_image(current)]),
    ])
    for _ in range(2):  # each retry/next call receives its own budget
        _, _, payload = await client._build_request_parts(request)
        assert list(_payload_images(payload)) == [current]
    assert request.messages[0].inline_images[0].data == old


async def test_same_content_dedupes_across_user_and_tool_batches(client, monkeypatch):
    raw = _png(1)
    url = "https://example.test/current.png"
    async def download(_):
        return LLMImageInput(url, "image/png", base64.b64encode(raw).decode("ascii"))
    monkeypatch.setattr(client, "_download_image", download)
    calls = [LLMToolCall(id=f"t{i}", name="look", arguments_json="{}") for i in range(3)]
    request = _request([
        LLMConversationMessage(role="user", content="look", image_urls=[url]),
        LLMConversationMessage(role="assistant", tool_calls=calls[:2]),
        *[LLMConversationMessage(role="tool", content="result", tool_call_id=call.id,
                                  tool_name=call.name, inline_images=[_image(raw)]) for call in calls[:2]],
        LLMConversationMessage(role="assistant", tool_calls=calls[2:]),
        LLMConversationMessage(role="tool", content="result", tool_call_id="t2",
                               tool_name="look", inline_images=[_image(raw)]),
    ])
    _, _, payload = await client._build_request_parts(request)
    assert list(_payload_images(payload)) == [raw]
    # Every protocol still carries the complete tool-result batch.
    if client.config.protocol == "openai":
        ids = [msg["tool_call_id"] for msg in payload["messages"] if msg["role"] == "tool"]
    elif client.config.protocol == "claude":
        ids = [block["tool_use_id"] for msg in payload["messages"] if isinstance(msg["content"], list)
               for block in msg["content"] if block["type"] == "tool_result"]
    else:
        ids = [part["functionResponse"]["id"] for msg in payload["contents"] for part in msg["parts"]
               if "functionResponse" in part]
    assert ids == ["t0", "t1", "t2"]


async def test_budget_stops_later_tool_batches_after_current_overflows(client):
    current = _png(1)
    client.config = replace(client.config, max_inline_media_bytes=len(current) - 1)
    request = _request([
        LLMConversationMessage(role="user", content="current", inline_images=[_image(current)]),
        LLMConversationMessage(role="assistant", tool_calls=[LLMToolCall("t1", "look", "{}")]),
        LLMConversationMessage(role="tool", content="result", tool_name="look", tool_call_id="t1",
                               inline_images=[_image(b"tiny")]),
    ])
    _, _, payload = await client._build_request_parts(request)
    assert list(_payload_images(payload)) == []


async def test_unlimited_budget_still_dedupes_and_ignores_failed_tool_images(client):
    a, b, error_image = _png(1), _png(2), _png(3)
    client.config = replace(client.config, max_inline_media_bytes=0)
    request = _request([
        LLMConversationMessage(role="user", content="old", inline_images=[_image(a)]),
        LLMConversationMessage(role="user", content="current", inline_images=[_image(a), _image(b)]),
        LLMConversationMessage(role="assistant", tool_calls=[LLMToolCall("t1", "look", "{}")]),
        LLMConversationMessage(role="tool", content="failed", tool_name="look", tool_call_id="t1",
                               is_tool_error=True, inline_images=[_image(error_image)]),
    ])
    _, _, payload = await client._build_request_parts(request)
    assert list(_payload_images(payload)) == [a, b]


async def test_concurrent_requests_have_independent_budgets(client, monkeypatch):
    raw = _png(1)
    client.config = replace(client.config, max_inline_media_bytes=len(raw))
    async def download(url):
        await asyncio.sleep(0)
        return LLMImageInput(url, "image/png", base64.b64encode(raw).decode("ascii"))
    monkeypatch.setattr(client, "_download_image", download)
    request = _request([LLMConversationMessage(role="user", content="image", image_urls=["https://example.test/a.png"])])
    results = await asyncio.gather(client._build_request_parts(request), client._build_request_parts(request))
    assert [list(_payload_images(payload)) for _, _, payload in results] == [[raw], [raw]]


async def test_cancelled_preparation_does_not_leak_budget(client, monkeypatch):
    raw = _png(1)
    ready = asyncio.Event()
    async def cancelled_download(url):
        ready.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(client, "_download_image", cancelled_download)
    request = _request([LLMConversationMessage(role="user", content="image", image_urls=["https://example.test/a.png"])])
    task = asyncio.create_task(client._build_request_parts(request))
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async def good_download(url):
        return LLMImageInput(url, "image/png", base64.b64encode(raw).decode("ascii"))
    monkeypatch.setattr(client, "_download_image", good_download)
    _, _, payload = await client._build_request_parts(request)
    assert list(_payload_images(payload)) == [raw]


async def test_failed_url_does_not_consume_other_message_budget(client, monkeypatch):
    raw = _png(1)
    client.config = replace(client.config, max_inline_media_bytes=len(raw))
    async def failed_download(url):
        raise LLMProviderError("HTTP 404", status_code=404)
    monkeypatch.setattr(client, "_download_image", failed_download)
    request = _request([
        LLMConversationMessage(role="user", content="old", inline_images=[_image(raw)]),
        LLMConversationMessage(role="user", content="new", image_urls=["https://example.test/missing.png"]),
    ])
    _, _, payload = await client._build_request_parts(request)
    assert list(_payload_images(payload)) == [raw]
