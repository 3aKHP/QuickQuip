"""MCP binding + execution through LLMService tool loop.

Uses a fake MCPManager sync/execute to avoid spawning real servers.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.llm_mcp import MCPServerStatus, MCPToolBinding
from plugins.llm_runtime import LLMService

from tests.fixtures.configs import write_llm_config_bundle
from tests.fixtures.provider_stubs import StubMCPToolCallingProviderClient


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
