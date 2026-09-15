"""SkillsToolMixin 接缝：注册、惰性注册、catalog 块、format_skill_list。"""
from __future__ import annotations

from types import SimpleNamespace

from quickquip.llm.tools import ToolExecutionContext

from tests.fixtures.configs import MIN_LLM_CONFIG_TOML, write_llm_config_bundle
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
