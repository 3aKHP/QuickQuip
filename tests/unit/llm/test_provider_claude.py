from __future__ import annotations

import platform
from dataclasses import replace

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest, _detect_stainless_os
from plugins.llm_tools import LLMConversationMessage, LLMToolSpec

from tests.fixtures.provider_fakes import FakeClaudeClient


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id="fake-claude",
        protocol="claude",
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


async def test_claude_code_fingerprint_headers():
    """Default Claude provider emits the full Claude Code wire-format fingerprint
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

    assert headers["user-agent"] == "claude-cli/2.1.150 (external, cli)"
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


async def test_detect_stainless_os_matches_platform():
    """_detect_stainless_os returns a sensible value for the current host."""
    detected = _detect_stainless_os()
    system = platform.system()
    if system == "Windows":
        assert detected == "Windows"
    elif system == "Darwin":
        assert detected == "MacOS"
    else:
        assert detected == system


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
                       "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 50}}}
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
