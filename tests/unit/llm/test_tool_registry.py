from __future__ import annotations

from plugins.llm_tool_registry import ToolRegistry
from plugins.llm_tools import LLMToolSpec


async def _noop_handler(arguments, context):
    _ = arguments, context
    return "ok"


def test_search_manifest_scores_name_description_and_arguments():
    registry = ToolRegistry()
    registry.register(
        LLMToolSpec(
            name="mcp_github_search_code",
            description="Search code across GitHub repositories.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "perPage": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        _noop_handler,
        source="mcp:github",
        category="mcp:github",
        keywords=["repo", "code"],
    )
    registry.register(
        LLMToolSpec(
            name="get_identity",
            description="查询群友身份。",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        _noop_handler,
        category="identity",
    )

    matches = registry.search_manifest("GitHub code query", limit=3)

    assert matches[0].name == "mcp_github_search_code"
    assert matches[0].argument_names == ["query", "perPage"]


def test_search_manifest_respects_enabled_excluded_category_and_limit():
    registry = ToolRegistry()
    for index in range(3):
        registry.register(
            LLMToolSpec(
                name=f"mcp_github_tool_{index}",
                description="GitHub repository helper.",
                input_schema={"type": "object", "properties": {}},
            ),
            _noop_handler,
            source="mcp:github",
            category="mcp:github",
        )
    registry.register(
        LLMToolSpec(
            name="mcp_weather_tool",
            description="Weather helper.",
            input_schema={"type": "object", "properties": {}},
        ),
        _noop_handler,
        source="mcp:weather",
        category="mcp:weather",
    )

    matches = registry.search_manifest(
        "GitHub",
        enabled_names=["mcp_github_tool_0", "mcp_github_tool_1", "mcp_weather_tool"],
        exclude_names=["mcp_github_tool_0"],
        category="github",
        limit=1,
    )

    assert [item.name for item in matches] == ["mcp_github_tool_1"]


def test_list_groups_and_manifest_page():
    registry = ToolRegistry()
    for index in range(3):
        registry.register(
            LLMToolSpec(
                name=f"mcp_github_tool_{index}",
                description="GitHub helper.",
                input_schema={"type": "object", "properties": {}},
            ),
            _noop_handler,
            source="mcp:github",
            category="mcp:github",
        )
    registry.register(
        LLMToolSpec(
            name="search_web",
            description="Search web.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        _noop_handler,
        category="search",
    )

    groups = registry.list_groups()
    assert [(item["name"], item["tool_count"]) for item in groups] == [
        ("mcp:github", 3),
        ("search", 1),
    ]

    entries, total = registry.list_manifest_page(group="github", page=2, limit=2)
    assert total == 3
    assert [item.name for item in entries] == ["mcp_github_tool_2"]
