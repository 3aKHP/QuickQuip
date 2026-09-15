"""SkillsToolMixin 接缝：注册、惰性注册、catalog 块、format_skill_list。"""
from __future__ import annotations

from types import SimpleNamespace

from quickquip.common.sensitive_filter import SensitiveFilter
from quickquip.llm.epoch import EpochKey
from quickquip.llm.tools import ToolExecutionContext

from tests.fixtures.configs import MIN_LLM_CONFIG_TOML, write_llm_config_bundle
from tests.fixtures.sensitive_filter import make_sensitive_filter
from tests.unit.llm.skills.conftest import write_skill
from plugins.llm_runtime import LLMService

_TOOL_NAMES = (
    "activate_skill",
    "read_skill_resource",
    "search_skill_resources",
    "run_skill_script",
)


def _service(tmp_path, skills_toml: str) -> LLMService:
    bundle = write_llm_config_bundle(
        tmp_path, config_toml=f"{MIN_LLM_CONFIG_TOML}\n{skills_toml}"
    )
    return LLMService(**bundle)


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        group_id=1001,
        user_id=2002,
        sender_name="测试",
        provider_id="openai-main",
        model="gpt-test",
        chat_type="group",
    )


def test_empty_catalog_dir_registers_nothing(tmp_path):
    catalog = tmp_path / "skills"
    catalog.mkdir()
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    for name in _TOOL_NAMES:
        assert not svc.tool_registry.has_tool(name)
    assert svc._skills_catalog_block(provider=None, model="gpt-test") == ""


def test_nonempty_catalog_registers_at_startup(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。", body="正文\n")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    for name in _TOOL_NAMES:
        assert svc.tool_registry.has_tool(name)
    block = svc._skills_catalog_block(provider=None, model="gpt-test")
    assert '<skill_catalog hash="' in block
    assert "- demo: 演示。" in block
    # activate 的 name enum 即当前名单
    (spec,) = svc.tool_registry.get_specs(["activate_skill"])
    assert spec.input_schema["properties"]["name"]["enum"] == ["demo"]


def test_hot_deploy_registers_lazily(tmp_path):
    catalog = tmp_path / "skills"
    catalog.mkdir()
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    assert not svc.tool_registry.has_tool("activate_skill")
    write_skill(catalog, "late", "热部署。")
    block = svc._skills_catalog_block(provider=None, model="gpt-test")
    assert "- late: 热部署。" in block
    for name in _TOOL_NAMES:
        assert svc.tool_registry.has_tool(name)


def test_prepare_for_turn_registers_before_specs(tmp_path):
    """prepare_skill_catalog_for_turn：specs 计算前的生产入口（一轮一次扫描）。

    热部署当轮：prepare 返回渲染块并完成惰性注册，随后计算的 enabled tool
    specs 即含 4 个 skill 工具（广告面零滞后）。
    """
    catalog = tmp_path / "skills"
    catalog.mkdir()
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    assert svc.prepare_skill_catalog_for_turn(provider=None, model="gpt-test") == ""
    write_skill(catalog, "late", "热部署。")
    block = svc.prepare_skill_catalog_for_turn(provider=None, model="gpt-test")
    assert "- late: 热部署。" in block
    spec_names = [spec.name for spec in svc._get_enabled_tool_specs()]
    for name in _TOOL_NAMES:
        assert name in spec_names


def test_enum_refreshes_when_catalog_changes(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "aaa", "一。")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    assert svc._skill_registered_names == ["aaa"]
    write_skill(catalog, "bbb", "二。")
    svc._skills_catalog_block(provider=None, model="gpt-test")
    assert svc._skill_registered_names == ["aaa", "bbb"]
    (spec,) = svc.tool_registry.get_specs(["activate_skill"])
    assert spec.input_schema["properties"]["name"]["enum"] == ["aaa", "bbb"]


def test_disabled_skills_everything_off(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。")
    svc = _service(tmp_path, f'[skills]\nenabled = false\ncatalog_dir = "{catalog}"\n')
    for name in _TOOL_NAMES:
        assert not svc.tool_registry.has_tool(name)
    assert svc._skills_catalog_block(provider=None, model="gpt-test") == ""
    # handler fail-closed
    result = svc._tool_activate_skill({"name": "demo"}, _context())
    assert result.is_error
    assert "未启用" in result.content


def test_catalog_block_budget_uses_context_window(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    provider = SimpleNamespace(model_context_windows={"gpt-test": 1_000_000})
    block = svc._skills_catalog_block(provider=provider, model="gpt-test")
    assert '<skill_catalog hash="' in block


def test_emptied_catalog_block_disappears_and_handler_fails_closed(tmp_path):
    catalog = tmp_path / "skills"
    root = write_skill(catalog, "demo", "演示。", body="正文\n")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    assert svc._skills_catalog_block(provider=None, model="gpt-test") != ""
    # 目录清空：块消失；handler 对不存在的名字 fail-closed（不抛异常）
    for child in root.iterdir():
        child.unlink()
    root.rmdir()
    assert svc._skills_catalog_block(provider=None, model="gpt-test") == ""
    result = svc._tool_activate_skill({"name": "demo"}, _context())
    assert result.is_error
    assert "未安装" in result.content


def test_activate_handler_records_activation(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。", body="正文内容\n")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    result = svc._tool_activate_skill({"name": "demo"}, _context())
    assert isinstance(result, str)
    assert 'status="activated"' in result
    scope = svc.build_chat_scope_key(1001, "group")
    assert svc._skill_activations.is_active(scope, "demo")


def test_format_skill_list(tmp_path):
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    text = svc.format_skill_list(1001, chat_type="group")
    assert "已安装 Skill（1）：" in text
    assert "- demo：演示。" in text
    assert "当前会话已激活：（无）" in text
    # 激活后反映到列表
    scope = svc.build_chat_scope_key(1001, "group")
    svc._skill_activations.record(scope, "demo", "h")
    assert "当前会话已激活：demo" in svc.format_skill_list(1001, chat_type="group")


def test_format_skill_list_disabled(tmp_path):
    svc = _service(tmp_path, "[skills]\nenabled = false\n")
    assert "未启用" in svc.format_skill_list(1001, chat_type="group")


def test_format_skill_list_empty_catalog(tmp_path):
    catalog = tmp_path / "skills"
    catalog.mkdir()
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    assert "当前未安装任何 Skill" in svc.format_skill_list(1001, chat_type="group")


def test_clear_context_clears_activations(tmp_path):
    """清空会话上下文后激活登记同步作废：重新激活重新注入正文。"""
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。", body="正文内容\n")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    ctx = _context()
    first = svc._tool_activate_skill({"name": "demo"}, ctx)
    assert 'status="activated"' in first
    again = svc._tool_activate_skill({"name": "demo"}, ctx)
    assert 'status="already-active"' in again

    svc.clear_context(1001, chat_type="group")
    scope = svc.build_chat_scope_key(1001, "group")
    assert not svc._skill_activations.is_active(scope, "demo")
    third = svc._tool_activate_skill({"name": "demo"}, ctx)
    assert 'status="activated"' in third
    assert "正文内容" in third


def test_epoch_advance_clears_activations(tmp_path, monkeypatch):
    """锚点推进（冷场/触顶/行数兜底）时激活注入可能出窗，登记同步清。"""
    catalog = tmp_path / "skills"
    write_skill(catalog, "demo", "演示。", body="正文内容\n")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    scope = svc.build_chat_scope_key(1001, "group")
    svc._skill_activations.record(scope, "demo", "h")

    provider = svc.config.providers["openai-main"]
    epoch_key = EpochKey(
        scope_key=scope, provider_id=provider.id, model="gpt-test"
    )
    epoch_params = svc.config.resolve_epoch_params(provider)

    def _load():
        return svc._load_scrubbed_history_and_participants(
            chat_id=1001,
            chat_type="group",
            scope_key=scope,
            settings=svc.get_chat_settings(1001),
            sensitive=SensitiveFilter.empty(),
            user_id=2002,
            sender_name="测试",
            recent_messages=[],
            message_id=None,
            quoted_sender_name="",
            quoted_user_id="",
            epoch_key=epoch_key,
            epoch_params=epoch_params,
        )

    # 未推进：登记保留
    monkeypatch.setattr(svc._epochs, "maybe_advance", lambda *a, **k: None)
    _load()
    assert svc._skill_activations.is_active(scope, "demo")

    # 发生推进：登记清空
    monkeypatch.setattr(svc._epochs, "maybe_advance", lambda *a, **k: object())
    _load()
    assert not svc._skill_activations.is_active(scope, "demo")


def test_catalog_drops_blocked_descriptions(tmp_path, monkeypatch):
    """description 命中拦截词：整只 skill 从 catalog 块、enum 与激活面同步消失。"""
    catalog = tmp_path / "skills"
    write_skill(catalog, "clean", "正常描述。")
    write_skill(catalog, "dirty", "含 blocked 词。")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    sensitive = make_sensitive_filter(tmp_path, "block")
    monkeypatch.setattr(
        "quickquip.llm.service_parts.skills._get_sensitive_filter", lambda: sensitive
    )

    block = svc.prepare_skill_catalog_for_turn(provider=None, model="gpt-test")
    assert "- clean: 正常描述。" in block
    assert "dirty" not in block
    (spec,) = svc.tool_registry.get_specs(["activate_skill"])
    assert spec.input_schema["properties"]["name"]["enum"] == ["clean"]
    result = svc._tool_activate_skill({"name": "dirty"}, _context())
    assert result.is_error
    assert "未安装" in result.content


def test_catalog_descriptions_kept_when_filter_not_loaded(tmp_path, monkeypatch):
    catalog = tmp_path / "skills"
    write_skill(catalog, "dirty", "含 blocked 词。")
    svc = _service(tmp_path, f'[skills]\ncatalog_dir = "{catalog}"\n')
    monkeypatch.setattr(
        "quickquip.llm.service_parts.skills._get_sensitive_filter",
        lambda: SensitiveFilter.empty(),
    )
    block = svc.prepare_skill_catalog_for_turn(provider=None, model="gpt-test")
    assert "- dirty: 含 blocked 词。" in block
