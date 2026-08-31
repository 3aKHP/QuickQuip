from __future__ import annotations

import logging

from quickquip.llm.config import ProviderConfig, ToolsConfig, load_llm_config
from quickquip.llm.service_parts.constants import DEFAULT_ENABLED_TOOLS
from quickquip.llm.service_parts.tools import ToolMixin
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tools import LLMToolSpec, ToolExecutionContext

_BUILTIN_TOOLS = [*DEFAULT_ENABLED_TOOLS, "draw_svg"]

_MINIMAL_SPEC = {"type": "object", "properties": {}}


class _FakeHost(ToolMixin):
    """只满足 _get_enabled_tool_names 依赖的最小宿主。"""

    def __init__(
        self,
        tools: ToolsConfig,
        mcp_names: set[str],
        providers: dict[str, ProviderConfig] | None = None,
    ) -> None:
        # 与真实 LLMConfig 对齐：providers 恒存在（默认空 dict），生产代码
        # 直接访问 self.config.providers，无需 getattr 兜底。
        self.config = type("Cfg", (), {"tools": tools, "providers": providers or {}})()
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


# ---------------------------------------------------------------------------
# builtin_search 与 search_web 的会话级互斥
# ---------------------------------------------------------------------------

def _gemini_provider(builtin: bool = True) -> ProviderConfig:
    return ProviderConfig(
        id="gemini-main",
        protocol="gemini",
        base_url="https://example.test/v1beta",
        api_key_env="GEMINI_KEY",
        default_model="gemini-x",
        models=["gemini-x"],
        builtin_search=builtin,
    )


def _openai_provider(builtin: bool = True) -> ProviderConfig:
    return ProviderConfig(
        id="openai-main",
        protocol="openai",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_KEY",
        default_model="gpt-x",
        models=["gpt-x"],
        builtin_search=builtin,
    )


def test_builtin_search_provider_session_removes_search_web():
    host = _FakeHost(_tools([]), set(), providers={"gemini-main": _gemini_provider()})

    names = host._get_enabled_tool_names(provider_id="gemini-main")

    assert "search_web" not in names
    assert "get_identity" in names  # 其余工具不受影响


def test_builtin_search_mutual_exclusion_is_provider_scoped():
    host = _FakeHost(_tools([]), set(), providers={"gemini-main": _gemini_provider()})

    # 不传 provider_id（默认视图）与指向其他 provider 的会话不受影响
    assert "search_web" in host._get_enabled_tool_names()
    assert "search_web" in host._get_enabled_tool_names(provider_id="someone-else")


def test_builtin_search_inactive_provider_keeps_search_web():
    host = _FakeHost(_tools([]), set(), providers={"gemini-main": _gemini_provider(builtin=False)})

    assert "search_web" in host._get_enabled_tool_names(provider_id="gemini-main")


def test_builtin_search_on_non_gemini_protocol_is_inert():
    # openai provider 误配 builtin_search = true：请求级与互斥层均不生效
    host = _FakeHost(_tools([]), set(), providers={"openai-main": _openai_provider(builtin=True)})

    assert "search_web" in host._get_enabled_tool_names(provider_id="openai-main")


def test_builtin_search_removes_search_web_in_replace_mode():
    host = _FakeHost(
        _tools(["search_web", "get_identity"], mode="replace"),
        set(),
        providers={"gemini-main": _gemini_provider()},
    )

    names = host._get_enabled_tool_names(provider_id="gemini-main")

    assert "search_web" not in names
    assert names == ["get_identity"]


def test_builtin_search_removes_search_web_from_always_loaded():
    host = _FakeHost(_tools([]), set(), providers={"gemini-main": _gemini_provider()})

    always = host._get_always_loaded_tool_names(provider_id="gemini-main")

    assert "search_web" not in always
    assert "tool_search" in always


async def test_tool_search_view_excludes_search_web_for_builtin_session():
    """tool_search 处理器视图与主链路一致：内置搜索会话搜不到 search_web。"""
    host = _FakeHost(
        ToolsConfig(enabled=[]),
        set(),
        providers={"gemini-main": _gemini_provider()},
    )
    # 最小宿主注册的 search_web 描述为空，补一个可按关键词命中的注册
    host.tool_registry.register(
        LLMToolSpec(
            name="search_web",
            description="联网搜索",
            input_schema=_MINIMAL_SPEC,
        ),
        lambda arguments, context: "",
        category="search",
        keywords=["联网", "搜索"],
    )

    def _context(provider_id: str) -> ToolExecutionContext:
        return ToolExecutionContext(
            group_id=1001,
            user_id=2002,
            sender_name="tester",
            provider_id=provider_id,
            model="gemini-x",
            chat_scope="1001",
        )

    default_view = await host._tool_search_tools({"query": "联网 搜索"}, _context("someone-else"))
    builtin_view = await host._tool_search_tools({"query": "联网 搜索"}, _context("gemini-main"))

    assert "search_web" in default_view
    assert "search_web" not in builtin_view
