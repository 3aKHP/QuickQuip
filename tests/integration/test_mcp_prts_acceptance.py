"""Opt-in, no-provider-cost acceptance against a fixed PRTS MCP deployment."""
from __future__ import annotations

import os

import pytest

from quickquip.llm.config import MCPServerConfig, ProviderConfig
from quickquip.llm.mcp.client import MCPClient
from quickquip.llm.mcp.types import deliver_mcp_tool_result
from quickquip.llm.provider import BaseProviderClient, LLMRequest
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall, LLMToolSpec
from tests.fixtures.provider_fakes import FakeClaudeClient


pytestmark = pytest.mark.network


class _InlineClaudeClient(FakeClaudeClient):
    async def _prepare_image_inputs(self, image_urls, inline_images=None):
        return await BaseProviderClient._prepare_image_inputs(self, image_urls, inline_images)


def _required_environment() -> tuple[str, str, str]:
    if os.getenv("QUICKQUIP_MCP_ACCEPTANCE") != "1":
        pytest.skip("set QUICKQUIP_MCP_ACCEPTANCE=1 to enable fixed-version PRTS MCP acceptance")
    url = os.getenv("QUICKQUIP_MCP_PRTS_URL", "").strip()
    token = os.getenv("QUICKQUIP_MCP_PRTS_TOKEN", "").strip()
    operator = os.getenv("QUICKQUIP_MCP_PRTS_OPERATOR", "").strip()
    if not url or not token or not operator:
        pytest.skip(
            "set QUICKQUIP_MCP_PRTS_URL, QUICKQUIP_MCP_PRTS_TOKEN, and "
            "QUICKQUIP_MCP_PRTS_OPERATOR for fixed-version PRTS MCP acceptance"
        )
    return url, token, operator


async def test_prts_operator_artwork_image_content_reaches_stub_provider():
    url, token, operator = _required_environment()
    client = MCPClient(MCPServerConfig(
        id="prts-2.5.0",
        transport="http",
        url=url,
        headers={"Authorization": f"Bearer {token}"},
    ))
    await client.start()
    try:
        tools = await client.list_tools()
        assert any(item.get("name") == "operator_artwork" for item in tools)

        listed = await client.call_tool(
            "operator_artwork",
            {"operator_name": operator, "action": "list"},
        )
        assert listed.content

        raw_result = await client.call_tool(
            "operator_artwork",
            {"operator_name": operator, "action": "get"},
        )
    finally:
        await client.aclose()

    delivered = deliver_mcp_tool_result(
        raw_result,
        server_id="prts-2.5.0",
        tool_name="operator_artwork",
    )
    assert len(delivered.images) == 1
    assert delivered.images[0].media_type in {"image/png", "image/jpeg", "image/gif", "image/webp"}
    assert delivered.images[0].data
    assert "base64" not in delivered.content.lower()

    provider = _InlineClaudeClient(
        ProviderConfig(
            id="stub-claude",
            protocol="claude",
            base_url="https://example.test/v1",
            api_key_env="UNUSED",
            default_model="stub-model",
            models=["stub-model"],
        ),
        {"content": [{"type": "text", "text": "stub"}]},
    )
    await provider.complete(LLMRequest(
        model="stub-model",
        system_prompt="stub",
        messages=[
            LLMConversationMessage(
                role="assistant",
                tool_calls=[LLMToolCall(
                    id="call_1",
                    name="operator_artwork",
                    arguments_json="{}",
                )],
            ),
            LLMConversationMessage(
                role="tool",
                content=delivered.content,
                tool_call_id="call_1",
                tool_name="operator_artwork",
                inline_images=delivered.images,
            ),
        ],
        temperature=0.0,
        max_output_tokens=16,
        tools=[LLMToolSpec(
            name="operator_artwork",
            description="stub",
            input_schema={"type": "object", "properties": {}},
        )],
        allow_tool_calls=True,
    ))
    tool_result = provider.last_payload["messages"][-1]["content"][0]
    assert tool_result["content"][1]["type"] == "image"
