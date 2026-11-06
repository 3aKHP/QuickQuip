"""tool_discovery 的显式点名语义:select: 前缀、裸名快路径、no-op 防抖。"""

from __future__ import annotations

import json

from quickquip.llm.tool_discovery import (
    ToolDiscovery,
    parse_tool_select_query,
    resolve_explicit_tool_names,
)
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tools import LLMToolSpec


def _call(query: str):
    class _Call:
        arguments_json = json.dumps({"query": query})

    return _Call()


def _registry(*names: str) -> ToolRegistry:
    registry = ToolRegistry()

    async def _handler(arguments, context):
        return "stub"

    for name in names:
        registry.register(
            LLMToolSpec(name=name, description=f"{name} 工具", input_schema={"type": "object"}),
            _handler,
        )
    return registry


def _discovery(enabled: list[str], initial: list[str] | None = None, **kwargs):
    registry = _registry(*enabled)
    return ToolDiscovery(
        enabled=True,
        tool_registry=registry,
        tool_search_name="tool_search",
        tool_list_name="tool_list",
        enabled_tool_names=list(enabled),
        initial_tool_names=initial,
        search_limit=5,
        max_loaded_tools=kwargs.get("max_loaded", 12),
        request_tools=[],
    )


def test_parse_tool_select_query():
    assert parse_tool_select_query("select:a,b,c") == ["a", "b", "c"]
    assert parse_tool_select_query("SELECT: A , B ") == ["A", "B"]
    assert parse_tool_select_query("select:") is None
    assert parse_tool_select_query("普通关键词") is None
    assert parse_tool_select_query("") is None


def test_resolve_explicit_names_covers_select_and_bare_name():
    enabled = ["tool_search", "draw_svg", "get_group_stats"]
    assert resolve_explicit_tool_names("select:draw_svg,get_group_stats", enabled) == [
        "draw_svg",
        "get_group_stats",
    ]
    # 裸名快路径 + 大小写规范化到启用名单
    assert resolve_explicit_tool_names("DRAW_SVG", enabled) == ["draw_svg"]
    # 非显式形态返回 None(走关键词搜索)
    assert resolve_explicit_tool_names("画图", enabled) is None


def test_load_from_search_call_select_loads_named_tools():
    discovery = _discovery(
        ["tool_search", "tool_list", "draw_svg", "get_group_stats"],
        initial=["tool_search", "tool_list"],
    )
    loaded = discovery.load_from_search_call(_call("select:draw_svg,get_group_stats"))
    assert loaded == ["draw_svg", "get_group_stats"]
    assert discovery.is_loaded("draw_svg") and discovery.is_loaded("get_group_stats")


def test_load_from_search_call_select_is_idempotent_noop():
    discovery = _discovery(
        ["tool_search", "tool_list", "draw_svg"], initial=["tool_search", "tool_list", "draw_svg"]
    )
    # 已加载工具重复点名:无害 no-op,不报错、不重复入集
    assert discovery.load_from_search_call(_call("select:draw_svg")) == []
    assert discovery.is_loaded("draw_svg")


def test_load_from_search_call_bare_name_fast_path():
    discovery = _discovery(
        ["tool_search", "tool_list", "draw_svg"], initial=["tool_search", "tool_list"]
    )
    assert discovery.load_from_search_call(_call("draw_svg")) == ["draw_svg"]


def test_load_from_search_call_select_respects_max_loaded_cap():
    discovery = _discovery(
        ["tool_search", "a", "b", "c"], initial=["tool_search"], max_loaded=2
    )
    # 上限 2:初始 1 个,select 三个只能装入 1 个
    loaded = discovery.load_from_search_call(_call("select:a,b,c"))
    assert loaded == ["a"]
    assert not discovery.is_loaded("c")


def test_load_from_search_call_keyword_path_unchanged():
    discovery = _discovery(
        ["tool_search", "draw_svg"], initial=["tool_search"]
    )
    # 关键词路径不受影响:按描述命中
    assert discovery.load_from_search_call(_call("draw_svg 工具")) == ["draw_svg"]
