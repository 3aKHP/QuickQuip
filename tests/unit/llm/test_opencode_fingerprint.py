"""Native Chat wire layout, stable identity and physical-attempt isolation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from importlib.resources import files
import json
import re

import brotli
import httpx
import pytest
import zstandard

from quickquip.llm.client_fingerprints.catalog import (
    FingerprintRuntime, parse_profile, profile_metadata, resolve_profile,
)
from quickquip.llm.client_fingerprints.session_projection import opencode_session_id
from quickquip.llm.config import ProviderConfig
from quickquip.llm.config_document import ConfigError, compile_document, empty_document
from quickquip.llm.epoch import create_epoch_id
from quickquip.llm.provider import LLMProviderError, LLMRequest, RetryPolicy, build_provider_client
from quickquip.llm.provider import base
from quickquip.llm.session import create_session_identity
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall, LLMToolSpec


def config(tmp_path, **changes):
    return ProviderConfig(
        id="test", protocol="openai", base_url="https://example.test/v1",
        api_key_env="PROFILE_TEST_KEY", default_model="glm-5.3-flash", models=["glm-5.3-flash"],
        client_fingerprint="opencode2", stream_enabled=False,
        fingerprint_runtime=FingerprintRuntime(
            resolve_profile("opencode2", "openai"), "", tmp_path,
        ),
        **changes,
    )


def request(**changes):
    values = dict(model="glm-5.3-flash", system_prompt="system", temperature=0.3,
                  max_output_tokens=128, session=create_session_identity(),
                  epoch_id=create_epoch_id(),
                  messages=[LLMConversationMessage("user", "中文")])
    values.update(changes)
    return LLMRequest(**values)


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv("PROFILE_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    seen = []
    replies = []

    async def handler(req):
        seen.append(req)
        if replies:
            return replies.pop(0)
        if json.loads(req.content).get("stream"):
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"},'
                                  '"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw,
    ))
    return seen, replies


def assert_trace(headers):
    trace = headers["traceparent"]
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", trace)
    _, trace_id, span, _ = trace.split("-")
    b3 = headers["b3"].split("-")
    assert b3[:3] == [trace_id, span, "1"]
    assert re.fullmatch(r"[0-9a-f]{16}", b3[3])
    return trace_id, span, b3[3]


@pytest.mark.parametrize("stream", [False, True])
async def test_httpx_native_layout_and_headers(tmp_path, capture, stream):
    seen, _ = capture
    cfg = replace(config(tmp_path), stream_enabled=stream)
    req = request(tools=[LLMToolSpec("z_tool", "desc", {"type": "object"}),
                         LLMToolSpec("a_tool", "desc", {"type": "object"})], allow_tool_calls=True)
    original = deepcopy(req)
    assert (await build_provider_client(cfg).complete(req)).text == "ok"
    wire = seen[0]
    body = json.loads(wire.content)
    keys = ["model", "messages", "tools", "stream"]
    if stream:
        keys.append("stream_options")
    assert list(body) == [*keys, "max_completion_tokens", "temperature", "store"]
    assert body["max_completion_tokens"] == 128 and body["store"] is False
    assert [t["function"]["name"] for t in body["tools"]] == ["z_tool", "a_tool"]
    assert all(t["function"]["strict"] is False for t in body["tools"])
    assert "tool_choice" not in body and "max_tokens" not in body
    assert b'"content":"\xe4\xb8\xad\xe6\x96\x87"' in wire.content
    assert wire.headers["user-agent"] == "opencode/latest/2.0.27/cli"
    assert wire.headers["accept"] == "*/*"
    assert wire.headers["accept-encoding"] == "gzip, deflate, br, zstd"
    assert [n.decode() for n, _ in wire.headers.raw] == [
        "Authorization", "Content-Type", "User-Agent", "b3", "traceparent", "x-opencode-client",
        "x-opencode-project", "x-opencode-session", "x-opencode-session-id", "x-session-affinity",
        "x-session-id", "Connection", "Accept", "Host", "Accept-Encoding", "Content-Length",
    ]
    assert re.fullmatch(r"ses_[0-9a-f]{12}[0-9A-Za-z]{14}", wire.headers["x-opencode-session"])
    assert {wire.headers[n] for n in ("x-opencode-session-id", "x-opencode-session",
            "x-session-id", "x-session-affinity")} == {opencode_session_id(req.session)}
    assert re.fullmatch(r"[0-9a-f]{40}", wire.headers["x-opencode-project"])
    assert not any(n.startswith("x-quickquip-") for n in wire.headers)
    assert "x-parent-session-id" not in wire.headers
    assert "x-opencode-parent-session-id" not in wire.headers
    assert "x-opencode-request" not in wire.headers
    assert_trace(wire.headers)
    assert req == original


async def test_http11_socket_layout_preserves_host_first_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_TEST_KEY", "synthetic-key")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    captured = asyncio.get_running_loop().create_future()

    async def receive(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            names = [line.split(b":", 1)[0].decode() for line in headers.split(b"\r\n")[1:-2]]
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                          if line.lower().startswith(b"content-length:"))
            body = await reader.readexactly(length)
            captured.set_result((names, json.loads(body)))
            response = b'{"choices":[{"message":{"content":"ok"}}]}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Connection: close\r\nContent-Length: " + str(len(response)).encode()
                         + b"\r\n\r\n" + response)
            await writer.drain()
        except Exception as exc:
            if not captured.done():
                captured.set_exception(exc)
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(receive, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        cfg = replace(config(tmp_path), base_url=f"http://127.0.0.1:{port}/v1")
        result = await asyncio.wait_for(build_provider_client(cfg).complete(request()), 5)
        names, body = await asyncio.wait_for(captured, 5)
    assert result.text == "ok" and body["max_completion_tokens"] == 128
    assert names == [
        "Host", "Authorization", "Content-Type", "User-Agent", "b3", "traceparent",
        "x-opencode-client", "x-opencode-project", "x-opencode-session", "x-opencode-session-id",
        "x-session-affinity", "x-session-id", "Connection", "Accept", "Accept-Encoding",
        "Content-Length",
    ]


async def test_invalid_runtime_profile_uses_provider_error(tmp_path, capture):
    seen, _ = capture
    cfg = replace(config(tmp_path), client_fingerprint="missing", fingerprint_runtime=None)
    with pytest.raises(LLMProviderError, match="invalid_profile"):
        await build_provider_client(cfg).complete(request())
    assert not seen


async def test_retry_fallback_recomputes_endpoint_policy_and_span(tmp_path, capture):
    seen, replies = capture
    replies.extend([httpx.Response(503), httpx.Response(503)])
    cfg = config(tmp_path, fallback_urls=["https://api.deepseek.com/v1"])
    client = build_provider_client(cfg, retry_policy=RetryPolicy(2, 0, 0))
    req = request()
    await client.complete(req)
    assert len(seen) == 3
    bodies = [json.loads(w.content) for w in seen]
    assert "max_completion_tokens" in bodies[0] and bodies[0]["store"] is False
    assert bodies[1]["max_tokens"] == 128 and "store" not in bodies[1]
    assert "max_completion_tokens" not in bodies[1]
    assert bodies[2] == bodies[0]
    traces = [assert_trace(w.headers) for w in seen]
    assert len({t[0] for t in traces}) == len({t[2] for t in traces}) == 1
    assert len({t[1] for t in traces}) == 3
    assert {w.headers["x-opencode-session"] for w in seen} == {opencode_session_id(req.session)}


async def test_concurrent_calls_epoch_changes_and_restore(tmp_path, capture):
    seen, _ = capture
    client = build_provider_client(config(tmp_path))
    first, second = request(), request()
    await asyncio.gather(client.complete(first), client.complete(second))
    await client.complete(replace(first, epoch_id=create_epoch_id()))
    restored = replace(first, session=replace(first.session))
    await client.complete(restored)
    ids = [w.headers["x-opencode-session"] for w in seen]
    assert ids[0] == ids[2] == ids[3] != ids[1]
    traces = [assert_trace(w.headers) for w in seen]
    assert len({t[0] for t in traces}) == 1
    assert len({t[1] for t in traces}) == len({t[2] for t in traces}) == 4
    assert len({w.headers["x-opencode-project"] for w in seen}) == 1


async def test_tool_replay_keeps_reasoning_pairing_and_empty_tools(tmp_path, capture):
    seen, _ = capture
    messages = [LLMConversationMessage("assistant", "", tool_calls=[
        LLMToolCall("call-1", "tool", '{"q":"中文"}')], thinking_blocks=[
        {"type": "reasoning", "reasoning_content": "retain this reasoning"}]),
        LLMConversationMessage("tool", "result", tool_call_id="call-1", tool_name="tool")]
    await build_provider_client(config(tmp_path)).complete(request(messages=messages))
    body = json.loads(seen[0].content)
    assistant, tool = body["messages"][1:]
    assert list(assistant) == ["role", "content", "tool_calls", "reasoning_content"]
    assert assistant["content"] is None
    assert assistant["reasoning_content"] == "retain this reasoning"
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"q":"中文"}'
    assert tool == {"role": "tool", "tool_call_id": "call-1", "content": "result"}
    assert body["tools"] == [] and "tool_choice" not in body


@pytest.mark.parametrize("host,max_field,store,strict,tool_stream", [
    ("api.deepseek.com", "max_tokens", False, True, False),
    ("opencode.ai", "max_completion_tokens", False, True, False),
    ("api.moonshot.cn", "max_completion_tokens", False, False, False),
    ("open.bigmodel.cn", "max_tokens", False, True, True),
    ("api.together.xyz", "max_tokens", False, False, False),
    ("example.test", "max_completion_tokens", True, True, False),
])
async def test_source_endpoint_compatibility(tmp_path, capture, host, max_field,
                                           store, strict, tool_stream):
    seen, _ = capture
    cfg = replace(config(tmp_path), base_url=f"https://{host}/v1")
    req = request(tools=[LLMToolSpec("t", "desc", {"type": "object"})], allow_tool_calls=True,
                  tool_choice="required")
    await build_provider_client(cfg).complete(req)
    body = json.loads(seen[0].content)
    assert body[max_field] == 128
    assert ("store" in body) is store
    assert ("strict" in body["tools"][0]["function"]) is strict
    assert ("tool_stream" in body) is tool_stream
    assert body["tool_choice"] == "required"


async def test_explicit_body_and_ua_overrides(tmp_path, capture):
    seen, _ = capture
    cfg = config(tmp_path, user_agent="Custom/1", headers={"User-Agent": "Other/2"},
                 extra_body={"max_tokens": 77, "store": True, "tool_choice": "none"})
    await build_provider_client(cfg).complete(request())
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 77 and "max_completion_tokens" not in body
    assert body["store"] is True and body["tool_choice"] == "none"
    assert seen[0].headers.get_list("user-agent") == ["Custom/1"]


async def test_inline_image_survives_final_projection(tmp_path, capture):
    from io import BytesIO
    from PIL import Image
    from quickquip.llm.tools import LLMInlineImage

    seen, _ = capture
    encoded = BytesIO()
    Image.new("RGB", (4, 4), "red").save(encoded, format="PNG")
    message = LLMConversationMessage("user", "explain this", inline_images=[
        LLMInlineImage(encoded.getvalue(), "image/png", "synthetic image"),
    ])
    await build_provider_client(config(tmp_path)).complete(request(messages=[message]))
    content = json.loads(seen[0].content)["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "text", "text": "explain this"}


@pytest.mark.parametrize("encoding", ["br", "zstd"])
async def test_declared_compression_is_decoded(tmp_path, capture, encoding):
    _, replies = capture
    data = b'{"choices":[{"message":{"content":"decoded"}}]}'
    compressed = brotli.compress(data) if encoding == "br" else zstandard.compress(data)
    replies.append(httpx.Response(200, content=compressed, headers={"content-encoding": encoding}))
    assert (await build_provider_client(config(tmp_path)).complete(request())).text == "decoded"


@pytest.mark.parametrize("name", ["X-Session-Id", "X-OpenCode-Project", "Traceparent", "B3"])
async def test_managed_headers_rejected_before_network(tmp_path, capture, name):
    seen, _ = capture
    cfg = config(tmp_path, headers={name: "manual"})
    with pytest.raises(LLMProviderError, match="profile_owned_header"):
        await build_provider_client(cfg).complete(request())
    assert not seen


async def test_missing_session_and_conflicting_limits_fail_before_network(tmp_path, capture):
    seen, _ = capture
    with pytest.raises(LLMProviderError, match="missing_session_identity"):
        await build_provider_client(config(tmp_path)).complete(request(session=None))
    with pytest.raises(LLMProviderError, match="invalid_field"):
        await build_provider_client(config(tmp_path, extra_body={
            "max_tokens": 1, "max_completion_tokens": 2,
        })).complete(request())
    assert not seen


async def test_stream_failure_fallback_retains_identity_with_new_span(
    tmp_path, capture, monkeypatch,
):
    seen, _ = capture
    client = build_provider_client(replace(config(tmp_path), stream_enabled=True))
    original = client._post_stream_sse

    async def broken_stream(*args):
        await original(*args)
        raise ValueError("simulated stream decoding failure")

    monkeypatch.setattr(client, "_post_stream_sse", broken_stream)
    assert (await client.complete(request())).text == "ok"
    assert len(seen) == 2
    assert [json.loads(w.content)["stream"] for w in seen] == [True, False]
    assert len({w.headers["x-opencode-session"] for w in seen}) == 1
    first, second = [assert_trace(w.headers) for w in seen]
    assert first[0] == second[0] and first[2] == second[2] and first[1] != second[1]


async def test_cancelled_call_restores_context(tmp_path, monkeypatch):
    from quickquip.llm.client_fingerprints.trace_context import current_request

    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def handler(req):
        seen.append(req)
        if len(seen) == 1:
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setenv("PROFILE_TEST_KEY", "synthetic-key")
    monkeypatch.setattr(base, "_schedule_usage_record", lambda *args: None)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(base.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw,
    ))
    client = build_provider_client(config(tmp_path))
    cancelled, next_request = request(), request()
    task = asyncio.create_task(client.complete(cancelled))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ConfigError, match="complete"):
        current_request()
    await client.complete(next_request)
    assert seen[0].headers["x-opencode-session"] != seen[1].headers["x-opencode-session"]
    assert assert_trace(seen[0].headers)[2] != assert_trace(seen[1].headers)[2]


@pytest.mark.parametrize("profile", ["default", "quickquip"])
async def test_other_profiles_keep_existing_compression_and_body(tmp_path, capture, profile):
    seen, _ = capture
    cfg = replace(config(tmp_path), client_fingerprint=profile,
                  fingerprint_runtime=FingerprintRuntime(resolve_profile(profile, "openai"),
                                                         "", tmp_path))
    await build_provider_client(cfg).complete(request())
    assert seen[0].headers["accept-encoding"] == "gzip, deflate"
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 128 and "max_completion_tokens" not in body
    assert "traceparent" not in seen[0].headers and "b3" not in seen[0].headers


def test_selection_and_config_validation(tmp_path):
    doc = empty_document()
    doc["providers"] = [{"id": "test", "protocol": "openai", "base_url": "https://test.invalid/v1",
        "api_key_env": "PROFILE_TEST_KEY", "default_model": "m", "models": [{"model": "m"}],
        "client_fingerprint": "opencode2"}]
    effective = compile_document(doc, config_dir=tmp_path)
    assert effective.providers["test"].client_fingerprint == "opencode2"
    doc["providers"][0]["parameters"] = {"extra_body": None}
    doc["providers"][0]["models"][0]["parameters"] = {"extra_body": None}
    assert compile_document(doc, config_dir=tmp_path).providers["test"].extra_body == {}
    meta = next(p for p in profile_metadata(tmp_path) if p["id"] == "opencode2")
    assert meta["protocols"] == ["openai"]
    doc["providers"][0]["headers"] = {"X-Session-Affinity": "manual"}
    with pytest.raises(ConfigError, match="Dynamic headers"):
        compile_document(doc, config_dir=tmp_path)
    for protocol in ("claude", "gemini", "openai_responses"):
        with pytest.raises(ConfigError):
            resolve_profile("opencode2", protocol)


def test_file_override_changes_body_policy_without_codegen(tmp_path):
    directory = tmp_path / "client_profiles"
    directory.mkdir()
    original = files("quickquip.llm.client_fingerprints").joinpath(
        "defaults/opencode2.toml",
    ).read_text()
    (directory / "opencode2.toml").write_text(original.replace(
        'max_tokens_field = "max_completion_tokens"', 'max_tokens_field = "max_tokens"', 1,
    ))
    profile = resolve_profile("opencode2", "openai", tmp_path)
    assert profile.for_protocol("openai").body.max_tokens_field == "max_tokens"


@pytest.mark.parametrize("before,after", [
    ('max_tokens_field = "max_completion_tokens"', 'max_tokens_field = "bad"'),
    ('supports_store = true', 'supports_store = 1'),
    ('omit_auto_tool_choice = true', 'omit_auto_tool_choice = "true"'),
    ('strategy = "openai-chat-native"', 'strategy = "arbitrary-code"'),
])
def test_invalid_body_file_rejected(before, after):
    content = files("quickquip.llm.client_fingerprints").joinpath(
        "defaults/opencode2.toml",
    ).read_text()
    with pytest.raises(ConfigError):
        parse_profile(content.replace(before, after, 1), "opencode2")
