"""MCP binding + execution through LLMService tool loop.

Uses a fake MCPManager sync/execute to avoid spawning real servers.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.llm_mcp import MCPServerStatus, MCPToolBinding
from plugins.llm_runtime import LLMService
from quickquip.llm.mcp.types import _format_tool_result

from tests.fixtures.configs import write_llm_config_bundle
from tests.fixtures.provider_stubs import (
    StubMCPDiscoveryProviderClient,
    StubMCPListLoadProviderClient,
    StubMCPToolCallingProviderClient,
)


MCP_CONFIG_TOML = textwrap.dedent(
    """
    [runtime]
    enabled = true
    default_provider = "openai-main"
    default_persona = "default"
    history_limit = 6
    history_max_messages_per_group = 8
    memory_limit = 3
    memory_max_items_per_group = 20
    max_prompt_chars = 1000
    tool_calling_enabled = true
    tool_max_rounds = 2
    tool_max_calls_per_round = 3

    [triggers]
    default_prefix = "/ai"
    allow_prefix = true
    allow_at = true
    empty_prompt_reply = "empty"

    [tools]
    enabled = []

    [mcp]
    enabled = true

    [[mcp.servers]]
    id = "fake"
    transport = "stdio"
    command = "python"
    args = ["fake_mcp_server.py"]
    timeout_seconds = 10

    [[personas]]
    id = "default"
    display_name = "默认人格"
    system_prompt = "你是测试人格。"
    style_prompt = "短一点。"

    [[providers]]
    id = "openai-main"
    protocol = "openai"
    base_url = "https://example.test/v1"
    api_key_env = "OPENAI_API_KEY"
    default_model = "gpt-test"
    models = ["gpt-test"]
    timeout_seconds = 30
    temperature = 0.5
    max_output_tokens = 256
    """
).strip()


@pytest.fixture
async def mcp_service(tmp_path: Path):
    paths = write_llm_config_bundle(tmp_path, config_toml=MCP_CONFIG_TOML)
    service = LLMService(**paths)

    async def fake_sync(_config, force_pull=False):
        binding = MCPToolBinding(
            alias="mcp_fake_echo_text",
            server_id="fake",
            tool_name="echo_text",
            description="回显输入文本。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
        service.mcp_manager._statuses = {
            "fake": MCPServerStatus(
                id="fake",
                transport="stdio",
                enabled=True,
                connected=True,
                tool_count=1,
                detail="fake-mcp 1.0.0",
            )
        }
        service.mcp_manager._bindings = {binding.alias: binding}
        return [binding]

    async def fake_execute(alias, arguments, context):
        _ = alias, context
        return f"echo::{arguments['text']}"

    service.mcp_manager.sync = fake_sync
    service.mcp_manager.execute = fake_execute

    await service.startup()
    yield service
    await service.shutdown()


async def test_mcp_status_reports_connection(mcp_service):
    status = mcp_service.format_mcp_status()
    assert "连接数：1/1" in status
    assert "工具数：1" in status

    current = mcp_service.format_current(2001)
    assert "MCP：ON (1/1，1 tools)" in current
    assert "mcp_fake_echo_text" in current


async def test_mcp_tool_call_executed_in_loop(mcp_service, patch_provider_builder):
    stub = StubMCPToolCallingProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await mcp_service.generate_reply(
        group_id=2001,
        user_id=2002,
        sender_name="测试用户",
        prompt="帮我走 MCP 工具",
        recent_messages=[],
    )

    assert result["reply"] == "echo::云端 DOOD"
    assert len(stub.requests) == 2
    round2 = stub.requests[-1]
    assert round2.messages[-2].tool_calls[0].name == "mcp_fake_echo_text"
    assert round2.messages[-1].role == "tool"
    assert round2.messages[-1].tool_name == "mcp_fake_echo_text"
    assert round2.messages[-1].content == "echo::云端 DOOD"


async def test_mcp_non_text_result_reaches_provider_only_as_safe_notice(
    mcp_service,
    patch_provider_builder,
):
    image_sentinel = "MCP_PROVIDER_IMAGE_SECRET_73b0"
    resource_sentinel = "MCP_PROVIDER_RESOURCE_SECRET_1ac4"
    stub = StubMCPToolCallingProviderClient()
    patch_provider_builder(lambda provider: stub)

    async def fake_execute(alias, arguments, context):
        _ = alias, arguments, context
        return _format_tool_result(
            {"content": [
                {"type": "text", "text": "safe MCP text"},
                {"type": "image", "data": image_sentinel, "mimeType": "image/png"},
                {"type": "resource", "resource": {
                    "uri": f"https://example.test/data?token={resource_sentinel}",
                    "text": resource_sentinel,
                }},
            ]}
        ).content

    mcp_service.mcp_manager.execute = fake_execute
    await mcp_service.generate_reply(
        group_id=2001,
        user_id=2002,
        sender_name="测试用户",
        prompt="帮我走 MCP 工具",
        recent_messages=[],
    )

    provider_text = "\n".join(message.content for message in stub.requests[-1].messages)
    assert "safe MCP text" in provider_text
    assert "尚未交付的图片项" in provider_text
    assert "resource 项" in provider_text
    assert image_sentinel not in provider_text
    assert resource_sentinel not in provider_text


async def test_mcp_tool_discovery_loads_deferred_tool(mcp_service, patch_provider_builder):
    mcp_service.config.tools.discovery_mode = "on"
    mcp_service.config.tools.always_loaded = [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "search_web",
    ]
    stub = StubMCPDiscoveryProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await mcp_service.generate_reply(
        group_id=2001,
        user_id=2002,
        sender_name="测试用户",
        prompt="帮我找能回显文本的 MCP 工具，然后调用它",
        recent_messages=[],
    )

    assert result["reply"] == "echo::云端 DOOD"
    assert len(stub.requests) == 3
    assert "mcp_fake_echo_text" not in {tool.name for tool in stub.requests[0].tools}
    assert "tool_search" in {tool.name for tool in stub.requests[0].tools}
    assert "tool_list" in {tool.name for tool in stub.requests[0].tools}
    assert "mcp_fake_echo_text" in {tool.name for tool in stub.requests[1].tools}
    assert stub.requests[1].messages[-1].tool_name == "tool_search"
    assert "mcp_fake_echo_text" in stub.requests[1].messages[-1].content
    assert stub.requests[2].messages[-1].tool_name == "mcp_fake_echo_text"


async def test_mcp_tool_list_can_load_deferred_tool(mcp_service, patch_provider_builder):
    mcp_service.config.tools.discovery_mode = "on"
    mcp_service.config.tools.always_loaded = [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "search_web",
    ]
    stub = StubMCPListLoadProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await mcp_service.generate_reply(
        group_id=2001,
        user_id=2002,
        sender_name="测试用户",
        prompt="如果搜索不到，就列出工具并加载回显文本工具",
        recent_messages=[],
    )

    assert result["reply"] == "echo::云端 DOOD"
    assert len(stub.requests) == 5
    assert "mcp_fake_echo_text" not in {tool.name for tool in stub.requests[0].tools}
    assert stub.requests[1].messages[-1].tool_name == "tool_list"
    assert "mcp:fake" in stub.requests[1].messages[-1].content
    assert "mcp_fake_echo_text" in stub.requests[2].messages[-1].content
    assert "mcp_fake_echo_text" in stub.requests[3].messages[-1].content
    assert "mcp_fake_echo_text" in {tool.name for tool in stub.requests[3].tools}
    assert stub.requests[4].messages[-1].tool_name == "mcp_fake_echo_text"
