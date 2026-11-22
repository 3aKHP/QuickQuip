from __future__ import annotations

import pytest
from dataclasses import replace

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest, _detect_stainless_os
from plugins.llm_tools import LLMConversationMessage, LLMToolSpec

from tests.fixtures.provider_fakes import FakeClaudeClient


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id="fake-claude",
        protocol="claude",
        client_fingerprint="legacy-claude",
        base_url="https://example.test/v1",
        api_key_env="ANTHROPIC_API_KEY",
        default_model="claude-test",
        models=["claude-test"],
    )


def _tool_call_request() -> LLMRequest:
    return LLMRequest(
        model="claude-test",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="查一下", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
        tools=[
            LLMToolSpec(
                name="get_identity",
                description="身份查询",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ],
        allow_tool_calls=True,
    )


async def test_claude_tool_use_payload_and_response():
    response_data = {
        "model": "claude-test",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": ""},
            {
                "type": "tool_use",
                "id": "tool_claude_1",
                "name": "get_identity",
                "input": {"query": "哈基镜"},
            },
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    client = FakeClaudeClient(_provider_config(), response_data)
    response = await client.complete(_tool_call_request())

    # Claude's tools payload is flat (no nested "function" wrapper)
    assert client.last_payload["tools"][0]["name"] == "get_identity"
    assert response.tool_calls[0].name == "get_identity"
    # Claude sends input as dict, client serializes to JSON
    assert response.tool_calls[0].arguments_json == '{"query": "哈基镜"}'


async def test_legacy_claude_code_fingerprint_headers():
    """Legacy Claude provider preserves the captured wire-format fingerprint
    captured from a real claude-cli 2.1.150 (external, cli) client on Linux."""
    response_data = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client = FakeClaudeClient(_provider_config(), response_data)
    await client.complete(_tool_call_request())
    headers = client.last_headers

    assert headers["anthropic-version"] == "2023-06-01"
    assert "claude-code-20250219" in headers["anthropic-beta"]
    assert headers["accept"] == "application/json"
    assert headers["accept-encoding"] == "gzip, deflate"
    # Stainless runtime fingerprint marks this as a Node.js SDK client
    assert headers["x-stainless-lang"] == "js"
    assert headers["x-stainless-runtime"] == "node"
    assert headers["x-app"] == "cli"
    assert headers["anthropic-dangerous-direct-browser-access"] == "true"
    # x-stainless-os reflects the host OS (real CC reports the actual OS)
    assert headers["x-stainless-os"] == _detect_stainless_os()
    assert client.last_url.endswith("/messages?beta=true")


async def test_claude_fingerprint_user_override_lowercase():
    """ProviderConfig.headers overrides fingerprint defaults case-insensitively."""
    from dataclasses import replace

    config = replace(
        _provider_config(),
        headers={"anthropic-version": "2025-03-26"},
    )
    response_data = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client = FakeClaudeClient(config, response_data)
    await client.complete(_tool_call_request())

    assert client.last_headers["anthropic-version"] == "2025-03-26"
    # Non-overridden fingerprint headers still applied
    assert client.last_headers["x-app"] == "cli"


async def test_claude_fingerprint_user_override_mixed_case():
    """Mixed-case header keys in config.headers still suppress the matching default."""
    from dataclasses import replace

    config = replace(
        _provider_config(),
        headers={"Anthropic-Version": "2025-03-26"},
    )
    response_data = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client = FakeClaudeClient(config, response_data)
    await client.complete(_tool_call_request())

    # The mixed-case user key should be present and the lowercase default absent
    assert client.last_headers["Anthropic-Version"] == "2025-03-26"
    assert "anthropic-version" not in client.last_headers


async def test_claude_user_agent_no_duplicate():
    """When config.user_agent AND a User-Agent header are both set, only one
    user-agent key survives (regression test for the duplicate-header bug)."""
    from dataclasses import replace

    config = replace(
        _provider_config(),
        user_agent="config-ua-field",
        headers={"User-Agent": "header-ua"},
    )
    response_data = {
        "model": "claude-test",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    client = FakeClaudeClient(config, response_data)
    await client.complete(_tool_call_request())

    ua_keys = [k for k in client.last_headers if k.lower() == "user-agent"]
    assert len(ua_keys) == 1
    assert client.last_headers["user-agent"] == "config-ua-field"


@pytest.mark.parametrize("system, expected", [
    ("Windows", "Windows"), ("Darwin", "MacOS"), ("Linux", "Linux"),
])
def test_detect_stainless_os_matches_platform(monkeypatch, system, expected):
    monkeypatch.setattr("platform.system", lambda: system)
    assert _detect_stainless_os() == expected


async def test_claude_cache_control_ttl_when_configured():
    """cache_ttl='1h' 给所有 cache_control 块加 ttl；空则维持默认 ephemeral（5min）。"""
    request = LLMRequest(
        model="claude-test",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
    )
    base = _provider_config()

    on = FakeClaudeClient(replace(base, prompt_caching=True, cache_ttl="1h"), {"content": []})
    await on.complete(request)
    assert on.last_payload["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    default = FakeClaudeClient(replace(base, prompt_caching=True, cache_ttl=""), {"content": []})
    await default.complete(request)
    assert default.last_payload["system"][-1]["cache_control"] == {"type": "ephemeral"}


async def test_claude_cache_tokens_parsed():
    """cache_creation/cache_read 从 usage 解析；5m/1h 细分求和；thinking 计入 output 无独立字段。"""
    request = LLMRequest(
        model="claude-test",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
    )
    base = _provider_config()

    data = {"model": "claude-test", "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_creation_input_tokens": 80, "cache_read_input_tokens": 200}}
    resp = await FakeClaudeClient(base, data).complete(request)
    assert resp.cache_creation_tokens == 80
    assert resp.cache_read_tokens == 200
    assert resp.thinking_tokens is None

    # 5m/1h 细分求和回退（无顶层 cache_creation_input_tokens 时）
    data2 = {"model": "claude-test", "content": [{"type": "text", "text": "ok"}],
             "usage": {"input_tokens": 100, "output_tokens": 50,
                       "cache_creation": {"ephemeral_5m_input_tokens": 30,
                                         "ephemeral_1h_input_tokens": 50}}}
    resp2 = await FakeClaudeClient(base, data2).complete(request)
    assert resp2.cache_creation_tokens == 80
    assert resp2.cache_read_tokens is None


async def test_claude_stream_cache_tokens_parsed():
    """流式 message_start.usage 的 cache token 解析（stream_enabled 默认 True，生产主路径）。"""
    chunks = [
        {"_sse_event": "message_start", "message": {"model": "claude-test",
            "usage": {"input_tokens": 100, "cache_creation_input_tokens": 80,
                      "cache_read_input_tokens": 200}}},
        {"_sse_event": "message_delta", "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 50}},
    ]
    resp = FakeClaudeClient._assemble_stream_response(chunks, "claude-test")
    assert resp.cache_creation_tokens == 80
    assert resp.cache_read_tokens == 200
    assert resp.output_tokens == 50


async def test_claude_stream_preserves_redacted_thinking():
    """流式组装必须保留 redacted_thinking 块（完整载荷只在 content_block_start，无 delta），
    否则回放 assistant 轮缺块，thinking+tool_use 场景遭上游 400。"""
    chunks = [
        {"_sse_event": "message_start", "message": {"model": "claude-test",
            "usage": {"input_tokens": 10}}},
        {"_sse_event": "content_block_start", "index": 0,
            "content_block": {"type": "redacted_thinking", "data": "sig-abc"}},
        {"_sse_event": "content_block_start", "index": 1,
            "content_block": {"type": "thinking", "thinking": ""}},
        {"_sse_event": "content_block_delta", "index": 1,
            "delta": {"type": "thinking_delta", "thinking": "想一下"}},
        {"_sse_event": "content_block_delta", "index": 1,
            "delta": {"type": "signature_delta", "signature": "sig-1"}},
        {"_sse_event": "content_block_start", "index": 2,
            "content_block": {"type": "text", "text": ""}},
        {"_sse_event": "content_block_delta", "index": 2,
            "delta": {"type": "text_delta", "text": "好的"}},
        {"_sse_event": "message_delta", "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5}},
    ]

    resp = FakeClaudeClient._assemble_stream_response(chunks, "claude-test")

    # 与 buffered _parse_response 同形状，顺序即 wire 顺序
    assert resp.thinking_blocks == [
        {"type": "redacted_thinking", "data": "sig-abc"},
        {"type": "thinking", "thinking": "想一下", "signature": "sig-1"},
    ]
    assert resp.text == "好的"
    assert resp.finish_reason == "end_turn"


async def test_claude_redacted_thinking_round_trips_into_replay():
    """thinking_blocks 里的 redacted_thinking 块原样进入下一轮请求的 assistant content。"""
    request = LLMRequest(
        model="claude-test",
        system_prompt="系统提示",
        messages=[
            LLMConversationMessage(role="user", content="你好", image_urls=[]),
            LLMConversationMessage(
                role="assistant",
                content="上次回复",
                thinking_blocks=[{"type": "redacted_thinking", "data": "sig-abc"}],
            ),
            LLMConversationMessage(role="user", content="继续", image_urls=[]),
        ],
        temperature=0.2,
        max_output_tokens=128,
    )
    client = FakeClaudeClient(
        _provider_config(),
        {"model": "claude-test", "content": [{"type": "text", "text": "ok"}]},
    )

    await client.complete(request)

    assistant_content = client.last_payload["messages"][1]["content"]
    assert assistant_content[0] == {"type": "redacted_thinking", "data": "sig-abc"}
    assert assistant_content[1] == {"type": "text", "text": "上次回复"}


# ── 思考档位（resolve_thinking 接线） ────────────────────────────


def _simple_request(
    model: str, *, effort: str | None = None, temperature: float = 1.0
) -> LLMRequest:
    return LLMRequest(
        model=model,
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=temperature,
        max_output_tokens=64000,
        reasoning_effort=effort,
    )


def _text_body() -> dict:
    return {"model": "m", "content": [{"type": "text", "text": "ok"}]}


async def test_claude_adaptive_effort_on_new_models():
    config = _provider_config()
    config.reasoning_effort = "xhigh"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("claude-opus-4-7"))
    assert client.last_payload["thinking"] == {"type": "adaptive"}
    assert client.last_payload["output_config"] == {"effort": "xhigh"}


async def test_claude_46_clamps_xhigh_to_high():
    config = _provider_config()
    config.reasoning_effort = "xhigh"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("claude-sonnet-4-6"))
    assert client.last_payload["output_config"] == {"effort": "high"}


async def test_claude_legacy_budget_on_45():
    config = _provider_config()
    config.reasoning_effort = "high"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("claude-sonnet-4-5"))
    assert client.last_payload["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert "output_config" not in client.last_payload


async def test_claude_thinking_drops_non_default_temperature():
    config = _provider_config()
    config.reasoning_effort = "high"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("claude-opus-4-7", temperature=0.2))
    assert "temperature" not in client.last_payload
    # 默认温度照常发送（显式 1.0 与上游默认一致）
    client2 = FakeClaudeClient(config, _text_body())
    await client2.complete(_simple_request("claude-opus-4-7", temperature=1.0))
    assert client2.last_payload["temperature"] == 1.0


async def test_claude_non_anthropic_backend_sends_adaptive_thinking_params():
    """非 Claude 家族挂 claude 兼容协议：fail-open 照发 adaptive + effort。"""
    config = _provider_config()
    config.reasoning_effort = "high"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("kimi-for-coding"))
    assert client.last_payload["thinking"] == {"type": "adaptive"}
    assert client.last_payload["output_config"] == {"effort": "high"}


async def test_claude_non_anthropic_backend_drops_non_default_temperature():
    """外族照发即适用 Anthropic 温度契约：非默认 temperature 随思考开启下掉。"""
    config = _provider_config()
    config.reasoning_effort = "high"
    client = FakeClaudeClient(config, _text_body())
    await client.complete(_simple_request("kimi-for-coding", temperature=0.2))
    assert "temperature" not in client.last_payload


async def test_claude_no_effort_sends_nothing():
    client = FakeClaudeClient(_provider_config(), _text_body())
    await client.complete(_simple_request("claude-opus-4-7"))
    assert "thinking" not in client.last_payload


async def test_claude_builtin_search_declared_alone_and_alongside_custom_tools():
    config = _provider_config()
    config.prompt_caching = True

    # 1. Declared alone even when allow_tool_calls=False
    req = _simple_request("claude-sonnet-5-5")
    req.builtin_search = True
    req.allow_tool_calls = False
    client = FakeClaudeClient(config, _text_body())
    await client.complete(req)
    assert client.last_payload["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # 2. Declared alongside custom client tools; cache_control lands on the final tool
    req_with_tools = LLMRequest(
        model="claude-sonnet-5-5",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="查一下")],
        temperature=0.2,
        max_output_tokens=128,
        tools=[
            LLMToolSpec(
                name="get_time",
                description="获取时间",
                input_schema={"type": "object", "properties": {}},
            )
        ],
        allow_tool_calls=True,
        builtin_search=True,
    )
    client2 = FakeClaudeClient(config, _text_body())
    await client2.complete(req_with_tools)
    assert len(client2.last_payload["tools"]) == 2
    assert client2.last_payload["tools"][0]["name"] == "get_time"
    assert "cache_control" not in client2.last_payload["tools"][0]
    assert client2.last_payload["tools"][1] == {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 5,
        "cache_control": {"type": "ephemeral"},
    }


async def test_claude_builtin_search_non_stream_and_stream_parse_and_trace():
    from quickquip.llm.provider.claude import ClaudeProviderClient

    non_stream_body = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "server_tool_use",
                "id": "srvtoolu_1",
                "name": "web_search",
                "input": {"query": "Python 3.13 release"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Python 3.13.18",
                        "url": "https://www.python.org/downloads/release/python-31318/",
                        "encrypted_content": "CIPHER",
                    }
                ],
            },
            {"type": "text", "text": "Latest is Python 3.13."},
            {
                "type": "text",
                "text": "18.",
                "citations": [
                    {
                        "type": "web_search_result_location",
                        "url": "https://www.python.org/downloads/release/python-31318/",
                        "title": "Python 3.13.18",
                        "cited_text": "Python 3.13.18",
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0},
        },
    }
    resp = ClaudeProviderClient._parse_response(non_stream_body, "claude-sonnet-5-5")
    assert resp.text == "Latest is Python 3.13.18."
    assert resp.web_search is not None
    assert resp.web_search.queries == ["Python 3.13 release"]
    assert resp.web_search.link_urls is True
    assert [(s.title, s.url) for s in resp.web_search.sources] == [
        ("Python 3.13.18", "https://www.python.org/downloads/release/python-31318/")
    ]
    # Native replay blocks must not retain bulky server_tool_use / web_search_tool_result.
    assert [b["type"] for b in (resp.native_blocks or [])] == ["text", "text"]

    sse_chunks = [
        {
            "_sse_event": "message_start",
            "message": {
                "id": "msg_2",
                "model": "claude-sonnet-5-5",
                "usage": {"input_tokens": 100},
            },
        },
        {
            "_sse_event": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "server_tool_use",
                "id": "srvtoolu_2",
                "name": "web_search",
                "input": {},
            },
        },
        {
            "_sse_event": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"query": "Python 3.13'},
        },
        {
            "_sse_event": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ' release"}'},
        },
        {
            "_sse_event": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "web_search_tool_result",
                "tool_use_id": "srvtoolu_2",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Python 3.13.18",
                        "url": "https://www.python.org/downloads/release/python-31318/",
                        "encrypted_content": "CIPHER",
                    }
                ],
            },
        },
        {
            "_sse_event": "content_block_start",
            "index": 2,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "_sse_event": "content_block_delta",
            "index": 2,
            "delta": {"type": "text_delta", "text": "Latest is Python 3.13.18."},
        },
        {
            "_sse_event": "content_block_delta",
            "index": 2,
            "delta": {
                "type": "citations_delta",
                "citation": {
                    "type": "web_search_result_location",
                    "url": "https://www.python.org/downloads/release/python-31318/",
                    "title": "Python 3.13.18",
                },
            },
        },
        {
            "_sse_event": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {
                "output_tokens": 20,
                "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0},
            },
        },
    ]
    combined = ClaudeProviderClient._combine_stream_trace(sse_chunks, "claude-sonnet-5-5")
    assert combined["content"][0]["input"] == {"query": "Python 3.13 release"}
    assert combined["content"][1]["type"] == "web_search_tool_result"
    assert len(combined["content"][2]["citations"]) == 1

    stream_resp = ClaudeProviderClient._assemble_stream_response(sse_chunks, "claude-sonnet-5-5")
    assert stream_resp.text == "Latest is Python 3.13.18."
    assert stream_resp.web_search is not None
    assert stream_resp.web_search.queries == ["Python 3.13 release"]
    assert [(s.title, s.url) for s in stream_resp.web_search.sources] == [
        ("Python 3.13.18", "https://www.python.org/downloads/release/python-31318/")
    ]
    assert [b["type"] for b in (stream_resp.native_blocks or [])] == ["text"]


def test_claude_builtin_search_policy_and_config_active():
    from quickquip.llm.config import provider_builtin_search_active
    from quickquip.llm.search_policy import resolve_search_mode

    cfg = _provider_config()
    cfg.builtin_search = True
    assert provider_builtin_search_active(cfg) is True
    assert (
        resolve_search_mode(cfg, tools_allowed=True, local_search_enabled=True)
        == "claude_web_search"
    )
    assert (
        resolve_search_mode(cfg, tools_allowed=False, local_search_enabled=False)
        == "claude_web_search"
    )
