from __future__ import annotations

from plugins.llm_config import MCPServerConfig
from quickquip.llm.mcp import MCPClientManager


TOOLS = [
    {
        "name": "search_code",
        "description": "Search code across repositories.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_file",
        "description": "Delete a repository file.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_file_contents",
        "description": "Read repository file contents.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def test_mcp_include_tools_filters_by_raw_tool_name():
    manager = MCPClientManager()
    server = MCPServerConfig(
        id="github",
        tool_prefix="github",
        include_tools=["search_code", "get_file_contents"],
    )

    bindings = manager._build_bindings(server, TOOLS)

    assert [binding.tool_name for binding in bindings] == ["search_code", "get_file_contents"]
    assert [binding.alias for binding in bindings] == [
        "mcp_github_search_code",
        "mcp_github_get_file_contents",
    ]


def test_mcp_exclude_tools_filters_by_alias_after_include():
    manager = MCPClientManager()
    server = MCPServerConfig(
        id="github",
        tool_prefix="github",
        include_tools=["search_code", "delete_file", "get_file_contents"],
        exclude_tools=["mcp_github_delete_file"],
    )

    bindings = manager._build_bindings(server, TOOLS)

    assert [binding.tool_name for binding in bindings] == ["search_code", "get_file_contents"]


def test_mcp_allowed_tools_remains_compatible_alias_for_include_tools():
    manager = MCPClientManager()
    server = MCPServerConfig(
        id="github",
        tool_prefix="github",
        allowed_tools=["mcp_github_search_code"],
    )

    bindings = manager._build_bindings(server, TOOLS)

    assert [binding.tool_name for binding in bindings] == ["search_code"]
