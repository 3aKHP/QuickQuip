"""Codex identity and cache bindings through actual Responses HTTP dispatch."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from importlib.resources import files
import json

import httpx
from httpx import AsyncClient as HTTPXClient
import pytest

from quickquip.llm.client_fingerprints.catalog import (
    FingerprintRuntime, parse_profile, profile_metadata, resolve_profile,
)
from quickquip.llm.config import ProviderConfig
from quickquip.llm.config_document import ConfigError, compile_document, empty_document
from quickquip.llm.epoch import create_epoch_id
from quickquip.llm.provider import LLMProviderError, LLMRequest, RetryPolicy, build_provider_client
from quickquip.llm.provider import base
from quickquip.llm.session import create_session_identity
from quickquip.llm.tools import LLMConversationMessage, LLMToolSpec
from tests.fixtures.stream_chunks import RESPONSES_TEXT_CHUNKS

SUCCESS = RESPONSES_TEXT_CHUNKS[-1]["response"]


def config(tmp_path, **changes):
    values = dict(
        id="test", protocol="openai_responses", base_url="https://example.test/v1",
        api_key_env="CODEX_TEST_KEY", default_model="gpt-test", models=["gpt-test"],
        client_fingerprint="codex", stream_enabled=False,
        fingerprint_runtime=FingerprintRuntime(resolve_profile("codex", "openai_responses"),
                                               "", tmp_path),
    )
    values.update(changes)
    return ProviderConfig(**values)


def request(**changes):
    values = dict(
        model="gpt-test", system_prompt="business prompt", temperature=0.2,
        max_output_tokens=128, session=create_session_identity(), epoch_id=create_epoch_id(),
        messages=[LLMConversationMessage("user", "中文")],
    )
    values.update(changes)
    return LLMRequest(**values)


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv("CODEX_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    seen, replies = [], []

    async def handler(req):
        seen.append(req)
        if replies:
            return replies.pop(0)
        if json.loads(req.content).get("stream"):
            return httpx.Response(200, text="".join(
                "data: " + json.dumps(chunk) + "\n\n" for chunk in RESPONSES_TEXT_CHUNKS
            ))
        return httpx.Response(200, json=SUCCESS)

    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: HTTPXClient(
        transport=httpx.MockTransport(handler), **kw,
    ))
    return seen, replies


def assert_identity(wire, expected):
    assert {wire.headers[k] for k in ("session-id", "thread-id", "x-client-request-id")} == {
        expected,
    }
    assert json.loads(wire.content)["prompt_cache_key"] == expected


@pytest.mark.parametrize("stream", [False, True])
async def test_identity_and_business_payload_survive_dispatch(tmp_path, capture, stream):
    seen, _ = capture
    req = request(tools=[LLMToolSpec("lookup", "desc", {"type": "object"})],
                  allow_tool_calls=True, tool_choice="required", reasoning_effort="high")
    original = deepcopy(req)
    cfg = config(tmp_path, stream_enabled=stream, extra_body={"metadata": {"custom": "keep"}})
    assert (await build_provider_client(cfg).complete(req)).text == "你好，世界"
    wire = seen[0]
    assert_identity(wire, req.session.id)
    assert wire.headers["user-agent"] == (
        "codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)"
    )
    assert wire.headers["originator"] == "codex-tui"
    assert wire.headers["accept-encoding"] == "gzip, deflate"
    if stream:
        assert wire.headers["accept"] == "text/event-stream"
    assert not any(k.startswith(("x-quickquip-", "x-codex-")) for k in wire.headers)
    assert "b3" not in wire.headers and "traceparent" not in wire.headers
    body = json.loads(wire.content)
    assert body["stream"] is stream and body["store"] is False
    assert body["instructions"] == "business prompt"
    assert body["max_output_tokens"] == 128 and body["temperature"] == 0.2
    assert body["tools"] == [{"type": "function", "name": "lookup", "description": "desc",
                              "parameters": {"type": "object"}}]
    assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is True
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["metadata"] == {"custom": "keep"} and "client_metadata" not in body
    assert req == original and not (tmp_path / "client_identity.json").exists()


async def test_epoch_restore_and_new_session_lifecycles(tmp_path, capture):
    seen, _ = capture
    client = build_provider_client(config(tmp_path))
    first = request()
    for req in (first, replace(first, epoch_id=create_epoch_id()),
                replace(first, session=replace(first.session)), request()):
        await client.complete(req)
    for wire in seen[:3]:
        assert_identity(wire, first.session.id)
    assert seen[3].headers["session-id"] != first.session.id
    assert_identity(seen[3], seen[3].headers["session-id"])


async def test_native_tool_reasoning_phase_and_image_replay_are_preserved(tmp_path, capture):
    from io import BytesIO
    from PIL import Image
    from quickquip.llm.tools import LLMInlineImage

    seen, _ = capture
    image = BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    native = [
        {"type": "reasoning", "id": "rs_1", "summary": [],
         "encrypted_content": "synthetic-cipher"},
        {"type": "message", "role": "assistant", "phase": "commentary",
         "content": [{"type": "output_text", "text": "checking"}]},
        {"type": "function_call", "call_id": "call_1", "name": "lookup", "arguments": "{}"},
    ]
    req = request(messages=[LLMConversationMessage("user", "question"),
        LLMConversationMessage("assistant", "", native_content=native),
        LLMConversationMessage("tool", "result", tool_call_id="call_1", inline_images=[
            LLMInlineImage(image.getvalue(), "image/png", "synthetic")])])
    original = deepcopy(req)
    await build_provider_client(config(tmp_path)).complete(req)
    body = json.loads(seen[0].content)
    assert body["input"][1:4] == native
    assert body["input"][4] == {
        "type": "function_call_output", "call_id": "call_1", "output": "result",
    }
    assert body["input"][5]["content"][0]["image_url"].startswith("data:image/png;base64,")
    assert req == original
    assert_identity(seen[0], req.session.id)


async def test_overlapping_calls_keep_their_own_cache_identity(tmp_path, capture, monkeypatch):
    seen, _ = capture
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(req):
        seen.append(req)
        if len(seen) == 2:
            entered.set()
        await release.wait()
        return httpx.Response(200, json=SUCCESS)

    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: HTTPXClient(
        transport=httpx.MockTransport(handler), **kw,
    ))
    client = build_provider_client(config(tmp_path))
    first, second = request(), request()
    tasks = [asyncio.create_task(client.complete(req)) for req in (first, second)]
    try:
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert_identity(seen[0], first.session.id)
    assert_identity(seen[1], second.session.id)


async def test_retry_and_backup_keep_identity(tmp_path, capture):
    seen, replies = capture
    replies.extend([httpx.Response(503), httpx.Response(503)])
    cfg = config(tmp_path, fallback_urls=["https://backup.test/v1"])
    client = build_provider_client(cfg, retry_policy=RetryPolicy(2, 0, 0))
    req = request()
    await client.complete(req)
    assert len(seen) == 3 and seen[1].url.host == "backup.test"
    for wire in seen:
        assert_identity(wire, req.session.id)


async def test_stream_fallback_keeps_identity(tmp_path, capture, monkeypatch):
    seen, _ = capture
    req = request()
    client = build_provider_client(config(tmp_path, stream_enabled=True))
    original = client._post_stream_sse

    async def broken_stream(*args):
        await original(*args)
        raise ValueError("simulated decode failure")

    monkeypatch.setattr(client, "_post_stream_sse", broken_stream)
    await client.complete(req)
    assert [json.loads(w.content)["stream"] for w in seen] == [True, False]
    for wire in seen:
        assert_identity(wire, req.session.id)


async def test_history_degrade_keeps_identity_and_phase(tmp_path, capture):
    seen, replies = capture
    items = [{"type": "reasoning", "id": "rs_old", "summary": [],
              "encrypted_content": "synthetic-cipher"},
             {"type": "message", "role": "assistant", "phase": "final_answer",
              "content": [{"type": "output_text", "text": "old"}]}]
    req = request(messages=[LLMConversationMessage("user", "old question"),
        LLMConversationMessage("assistant", "old", native_content=items),
        LLMConversationMessage("user", "new question")])
    replies.append(httpx.Response(400))
    await build_provider_client(config(tmp_path)).complete(req)
    assert len(seen) == 2
    first, second = [json.loads(w.content)["input"] for w in seen]
    assert any(i.get("type") == "reasoning" for i in first)
    assert not any(i.get("type") == "reasoning" for i in second)
    assert next(i for i in second if i.get("role") == "assistant")["phase"] == "final_answer"
    for wire in seen:
        assert_identity(wire, req.session.id)


@pytest.mark.parametrize("headers,extra_body", [
    ({"Session-ID": "manual"}, {}), ({"Thread-ID": "manual"}, {}),
    ({"X-Client-Request-Id": "manual"}, {}), ({}, {"prompt_cache_key": None}),
    ({}, {"prompt_cache_key": "manual"}),
])
async def test_runtime_rejects_managed_overrides_before_network(tmp_path, capture,
                                                            headers, extra_body):
    seen, _ = capture
    with pytest.raises(LLMProviderError, match="profile_owned"):
        await build_provider_client(config(tmp_path, headers=headers,
                                           extra_body=extra_body)).complete(request())
    assert not seen


@pytest.mark.parametrize("session", [None, replace(create_session_identity(), id="invalid")])
async def test_invalid_session_fails_before_network(tmp_path, capture, session):
    seen, _ = capture
    with pytest.raises(LLMProviderError, match="missing_session_identity"):
        await build_provider_client(config(tmp_path)).complete(request(session=session))
    assert not seen


def document():
    doc = empty_document()
    doc["providers"] = [{"id": "test", "protocol": "openai_responses",
        "base_url": "https://example.test/v1", "api_key_env": "CODEX_TEST_KEY",
        "default_model": "gpt-test", "models": [{"model": "gpt-test"}],
        "client_fingerprint": "codex"}]
    return doc


@pytest.mark.parametrize("level", ["provider", "model"])
@pytest.mark.parametrize("value", [None, "manual"])
def test_config_rejects_cache_overrides_at_both_levels(tmp_path, level, value):
    doc = document()
    target = doc["providers"][0]
    if level == "model":
        target = target["models"][0]
    target["parameters"] = {"extra_body": {"prompt_cache_key": value}}
    with pytest.raises(ConfigError, match="Dynamic Body"):
        compile_document(doc, config_dir=tmp_path)


@pytest.mark.parametrize("placement", ["authorization", "api_key", "nested_cache_key"])
def test_cache_exception_does_not_admit_credentials(tmp_path, placement):
    doc = document()
    provider = doc["providers"][0]
    if placement == "authorization":
        provider["headers"] = {"Authorization": "synthetic-secret"}
    else:
        extra = ({"api_key": "synthetic-secret"} if placement == "api_key" else
                 {"metadata": {"prompt_cache_key": "synthetic-secret"}})
        provider["parameters"] = {"extra_body": extra}
    with pytest.raises(ConfigError) as exc:
        compile_document(doc, config_dir=tmp_path)
    assert exc.value.code == "literal_secret"


async def test_file_binding_removal_allows_manual_cache_and_ua(tmp_path, capture):
    seen, _ = capture
    original = files("quickquip.llm.client_fingerprints").joinpath(
        "defaults/codex.toml",
    ).read_text()
    directory = tmp_path / "client_profiles"
    directory.mkdir()
    (directory / "codex.toml").write_text(original.replace(
        'prompt_cache_key = "business_session_id"', '',
    ).replace('originator = "codex-tui"', 'originator = "custom"'))
    profile = resolve_profile("codex", "openai_responses", tmp_path)
    doc = document()
    doc["providers"][0]["parameters"] = {"extra_body": {"prompt_cache_key": "manual"}}
    assert compile_document(doc, config_dir=tmp_path).providers["test"].extra_body == {
        "prompt_cache_key": "manual",
    }
    cfg = config(tmp_path, user_agent="Custom/1", headers={"User-Agent": "Other/2"},
        extra_body={"prompt_cache_key": "manual"},
        fingerprint_runtime=FingerprintRuntime(profile, "", tmp_path))
    await build_provider_client(cfg).complete(request())
    assert json.loads(seen[0].content)["prompt_cache_key"] == "manual"
    assert seen[0].headers["user-agent"] == "Custom/1"
    assert seen[0].headers["originator"] == "custom"


def test_selection_and_protocol_filter(tmp_path):
    compiled = compile_document(document(), config_dir=tmp_path)
    assert compiled.providers["test"].client_fingerprint == "codex"
    assert next(p for p in profile_metadata(tmp_path) if p["id"] == "codex")["protocols"] == [
        "openai_responses",
    ]
    for protocol in ("openai", "claude", "gemini"):
        with pytest.raises(ConfigError):
            resolve_profile("codex", protocol)


@pytest.mark.parametrize("replacement", [
    'prompt_cache_key = "opencode_session_id"', 'prompt_cache_key = 1',
    'unknown = "business_session_id"',
])
def test_invalid_body_bindings_rejected(replacement):
    original = files("quickquip.llm.client_fingerprints").joinpath(
        "defaults/codex.toml",
    ).read_text()
    with pytest.raises(ConfigError):
        parse_profile(original.replace('prompt_cache_key = "business_session_id"', replacement),
                      "codex")


def test_body_bindings_cannot_be_applied_to_chat():
    with pytest.raises(ConfigError):
        parse_profile('''format_version = 1
id = "custom"
label = "Custom"
[protocols.openai.body_bindings]
prompt_cache_key = "business_session_id"
''', "custom")
