from __future__ import annotations

import logging

from quickquip.llm.config import LLMConfig, ProviderConfig, ToolsConfig, load_llm_config
from quickquip.llm.history_tools import HISTORY_TOOLS
from quickquip.llm.service_parts.constants import DEFAULT_ENABLED_TOOLS
from quickquip.llm.service_parts.tools import ToolMixin
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tools import LLMToolSpec, ToolExecutionContext

# #72 后默认面含群历史工具，但历史双开关未开时被 _get_enabled_tool_names
# 过滤；「完整默认面」断言需以 history_enabled=True 调用，其余场景按
# 关闭口径 = DEFAULT_ENABLED_TOOLS − HISTORY_TOOLS。
DEFAULT_FACE_HISTORY_OFF = [n for n in DEFAULT_ENABLED_TOOLS if n not in HISTORY_TOOLS]

_BUILTIN_TOOLS = [*DEFAULT_ENABLED_TOOLS, "draw_svg", "get_group_stats", "get_rule_status"]

_MINIMAL_SPEC = {"type": "object", "properties": {}}


class _FakeHost(ToolMixin):
    """只满足 _get_enabled_tool_names 依赖的最小宿主。"""

    def __init__(
        self,
        tools: ToolsConfig,
        mcp_names: set[str],
        providers: dict[str, ProviderConfig] | None = None,
    ) -> None:
        self.config = LLMConfig(tools=tools, providers=providers or {})
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
    # 历史双开关默认关：默认面按关闭口径裁剪
    assert set(DEFAULT_FACE_HISTORY_OFF) <= set(names)
    assert {"mcp_a", "mcp_b"} <= set(names)
    # 双开后完整默认面可见
    assert set(DEFAULT_ENABLED_TOOLS) <= set(
        host._get_enabled_tool_names(history_enabled=True)
    )
    assert not set(HISTORY_TOOLS) & set(names)


def test_append_mode_unions_defaults_mcp_and_extras():
    host = _FakeHost(_tools(["draw_svg", "search_web"]), {"mcp_a"})
    names = host._get_enabled_tool_names()
    assert set(DEFAULT_FACE_HISTORY_OFF) <= set(names)
    assert "mcp_a" in names
    assert "draw_svg" in names
    assert names.count("search_web") == 1  # 去重保序


def test_replace_mode_filters_exactly():
    host = _FakeHost(_tools(["search_web", "mcp_a"], mode="replace"), {"mcp_a", "mcp_b"})
    names = host._get_enabled_tool_names()
    assert names == ["search_web", "mcp_a"]


def test_demoted_tools_require_opt_in():
    """get_group_stats/get_rule_status 已移出默认面，opt-in 后才可用。"""
    host = _FakeHost(_tools([]), set())
    names = host._get_enabled_tool_names()
    assert "get_group_stats" not in names
    assert "get_rule_status" not in names

    opted_in = _FakeHost(_tools(["get_group_stats"]), set())
    assert "get_group_stats" in opted_in._get_enabled_tool_names()


def test_private_chat_filters_unavailable_tools():
    host = _FakeHost(_tools(["draw_svg", "get_group_stats"]), set())
    assert "get_group_stats" in host._get_enabled_tool_names()
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
    config_path.write_text(
        '[tools]\nenabled = ["draw_svg"]\nenabled_mode = "append"\n', encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        load_llm_config(config_path)
    assert not any("enabled_mode" in record.message for record in caplog.records)


def test_config_no_append_semantics_warning_when_enabled_empty(tmp_path, caplog):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\nenabled = []\n', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.config"):
        load_llm_config(config_path)
    assert not any("enabled_mode" in record.message for record in caplog.records)


def _register_heavy_tool(host, name: str = "heavy_tool") -> None:
    host.tool_registry.register(
        LLMToolSpec(
            name=name,
            description="重型描述" * 400,  # ~1600 字符,token 估算远超体量线
            input_schema=_MINIMAL_SPEC,
        ),
        lambda arguments, context: "",
    )


def test_auto_discovery_triggers_on_heavy_schemas():
    """体量控线:个数控线不触发时,少量重型 schema 仍开启 auto 发现。"""
    host = _FakeHost(_tools(["heavy_tool"]), set())
    host.config.tools.discovery_min_tools = 99  # 隔离个数控线
    host.config.tools.discovery_min_schema_tokens = 500
    _register_heavy_tool(host)

    assert host._is_tool_discovery_enabled() is True


def test_auto_discovery_schema_line_disabled_at_zero():
    host = _FakeHost(_tools(["heavy_tool"]), set())
    host.config.tools.discovery_min_tools = 99
    host.config.tools.discovery_min_schema_tokens = 0
    _register_heavy_tool(host)

    assert host._is_tool_discovery_enabled() is False


def test_auto_discovery_count_line_still_governs_lightweight_face():
    """轻量默认面(5 个可延迟、schema 极小)不触発体量线,维持原 auto 边界。"""
    host = _FakeHost(_tools([]), set())
    host.config.runtime.tool_calling_enabled = True

    assert host._is_tool_discovery_enabled() is False
    assert host._get_deferred_tool_names() == []


async def test_real_builtin_deferred_face_stays_under_schema_threshold(llm_service):
    """真实内置默认面的可延迟 schema 总量必须对体量线留足余量——
    内置工具描述增肥导致默认面静默翻转 discovery 时,此测试报警。"""
    from quickquip.llm.service_parts.constants import (
        DEFAULT_ALWAYS_LOADED_TOOLS,
        DEFAULT_ENABLED_TOOLS,
    )
    from quickquip.llm.tool_registry import estimate_spec_tokens

    deferred = [
        name
        for name in DEFAULT_ENABLED_TOOLS
        if name not in DEFAULT_ALWAYS_LOADED_TOOLS
        and llm_service.tool_registry.has_tool(name)
    ]
    assert deferred  # fixture 至少注册了非 skill 延迟面
    total = sum(
        estimate_spec_tokens(spec)
        for spec in llm_service.tool_registry.get_specs(deferred)
    )
    threshold = llm_service.config.tools.discovery_min_schema_tokens
    assert total < threshold * 0.5, (
        f"内置默认面可延迟 schema {total} tok 已超过体量线 {threshold} 的一半,"
        "继续增肥会翻转默认部署的 auto 发现边界"
    )


def test_config_parses_discovery_schema_tokens(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text('[tools]\ndiscovery_min_schema_tokens = 800\n', encoding="utf-8")
    loaded = load_llm_config(config_path)
    assert loaded.tools.discovery_min_schema_tokens == 800


def test_discovery_schema_tokens_default():
    assert ToolsConfig().discovery_min_schema_tokens == 2000


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


def _ctx(provider_id: str = "p") -> ToolExecutionContext:
    return ToolExecutionContext(
        group_id=1001,
        user_id=2002,
        sender_name="tester",
        provider_id=provider_id,
        model="m",
        chat_scope="1001",
    )


def test_get_deferred_tool_names_requires_discovery():
    # auto 模式下默认面可延迟数(5)未过阈值 → 关闭 → 无公告名单
    off = _FakeHost(_tools([]), set())
    assert off._get_deferred_tool_names() == []

    on = _FakeHost(ToolsConfig(enabled=[], discovery_mode="on"), set())
    on.config.runtime.tool_calling_enabled = True
    names = on._get_deferred_tool_names()
    # 常驻面与元工具不在公告名单;延迟面技能三件套在
    assert "get_identity" not in names
    assert "tool_search" not in names and "tool_list" not in names
    assert {"read_skill_resource", "search_skill_resources", "run_skill_script"} <= set(names)


def test_get_deferred_tool_names_gated_by_tool_calling_switch():
    """工具总闸关闭时模型面前无工具,公告必须同闸关闭。"""
    gated = _FakeHost(ToolsConfig(enabled=[], discovery_mode="on"), set())
    gated.config.runtime.tool_calling_enabled = False
    assert gated._get_deferred_tool_names() == []


async def test_tool_search_select_reports_available_and_missing():
    host = _FakeHost(_tools(["draw_svg", "get_group_stats"]), set())

    text = await host._tool_search_tools(
        {"query": "select:draw_svg,get_identity,no_such_tool"}, _ctx()
    )

    assert "draw_svg" in text and "将于下一轮可用" in text
    assert "get_identity" in text and "已常驻" in text
    assert "no_such_tool" in text and "未找到" in text


async def test_tool_search_bare_tool_name_loads_without_select():
    host = _FakeHost(_tools(["draw_svg"]), set())

    text = await host._tool_search_tools({"query": "draw_svg"}, _ctx())

    assert "draw_svg" in text and "将于下一轮可用" in text


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
