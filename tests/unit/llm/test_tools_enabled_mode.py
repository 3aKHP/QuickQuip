from __future__ import annotations

import logging

from quickquip.llm.config import ToolsConfig, load_llm_config
from quickquip.llm.service_parts.constants import DEFAULT_ENABLED_TOOLS
from quickquip.llm.service_parts.tools import ToolMixin
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tools import LLMToolSpec

_BUILTIN_TOOLS = [*DEFAULT_ENABLED_TOOLS, "draw_svg"]

_MINIMAL_SPEC = {"type": "object", "properties": {}}


class _FakeHost(ToolMixin):
    """只满足 _get_enabled_tool_names 依赖的最小宿主。"""

    def __init__(self, tools: ToolsConfig, mcp_names: set[str]) -> None:
        self.config = type("Cfg", (), {"tools": tools})()
        self._mcp_tool_names = mcp_names
        self.tool_registry = ToolRegistry()
        for name in [*_BUILTIN_TOOLS, *sorted(mcp_names)]:
            self.tool_registry.register(
                LLMToolSpec(name=name, description="", input_schema=_MINIMAL_SPEC),
                lambda arguments, context: "",
            )


def _tools(enabled: list[str], mode: str = "append") -> ToolsConfig:
    return ToolsConfig(enabled=enabled, enabled_mode=mode)


def test_empty_enabled_keeps_default_plus_mcp():
    host = _FakeHost(_tools([]), {"mcp_a", "mcp_b"})
    names = host._get_enabled_tool_names()
    assert set(DEFAULT_ENABLED_TOOLS) <= set(names)
    assert {"mcp_a", "mcp_b"} <= set(names)


def test_append_mode_unions_defaults_mcp_and_extras():
    host = _FakeHost(_tools(["draw_svg", "search_web"]), {"mcp_a"})
    names = host._get_enabled_tool_names()
    assert set(DEFAULT_ENABLED_TOOLS) <= set(names)
    assert "mcp_a" in names
    assert "draw_svg" in names
    assert names.count("search_web") == 1  # 去重保序


def test_replace_mode_filters_exactly():
    host = _FakeHost(_tools(["search_web", "mcp_a"], mode="replace"), {"mcp_a", "mcp_b"})
    names = host._get_enabled_tool_names()
    assert names == ["search_web", "mcp_a"]


def test_private_chat_filters_unavailable_tools():
    host = _FakeHost(_tools(["draw_svg"]), set())
    names = host._get_enabled_tool_names(chat_type="private")
    assert "get_group_stats" not in names
    assert "get_rule_status" not in names
    assert "draw_svg" in names


def test_unknown_tool_names_dropped():
    host = _FakeHost(_tools(["draw_svg", "no_such_tool"], mode="replace"), set())
    assert host._get_enabled_tool_names() == ["draw_svg"]


def test_config_parses_enabled_mode(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        '[tools]\nenabled = ["draw_svg"]\nenabled_mode = "replace"\n',
        encoding="utf-8",
    )
    loaded = load_llm_config(config_path)
    assert loaded.tools.enabled == ["draw_svg"]
    assert loaded.tools.enabled_mode == "replace"


def test_config_enabled_mode_defaults_to_append(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled = []\n', encoding="utf-8")
    loaded = load_llm_config(config_path)
    assert loaded.tools.enabled_mode == "append"


def test_config_invalid_enabled_mode_falls_back_to_append(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled_mode = "merge"\n', encoding="utf-8")
    loaded = load_llm_config(config_path)
    assert loaded.tools.enabled_mode == "append"


def test_config_warns_when_enabled_nonempty_without_mode(tmp_path, caplog):
    """升级部署语义提示：enabled 非空且未显式设置 enabled_mode 时告警（append 默认）。"""
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled = ["draw_svg"]\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        loaded = load_llm_config(config_path)
    assert loaded.tools.enabled == ["draw_svg"]
    assert any("enabled_mode" in record.message for record in caplog.records)


def test_config_no_append_semantics_warning_with_explicit_mode(tmp_path, caplog):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled = ["draw_svg"]\nenabled_mode = "append"\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        load_llm_config(config_path)
    assert not any("enabled_mode" in record.message for record in caplog.records)


def test_config_no_append_semantics_warning_when_enabled_empty(tmp_path, caplog):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled = []\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        load_llm_config(config_path)
    assert not any("enabled_mode" in record.message for record in caplog.records)
