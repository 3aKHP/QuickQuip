"""activate_skill 工具与资源面激活门（tools/activate.py）。"""
from __future__ import annotations

from quickquip.llm.skills import (
    ACTIVATE_SKILL_TOOL_NAME,
    SkillActivationState,
    activate_skill,
    build_activate_skill_spec,
    require_active_skill,
    scan_skills,
)
from quickquip.llm.tools import LLMToolOutput


def _skills_by_name(catalog_dir):
    return {skill.name: skill for skill in scan_skills(catalog_dir)}


def test_spec_name_enum_matches_catalog_names():
    spec = build_activate_skill_spec(["alpha", "beta"])
    assert spec.name == ACTIVATE_SKILL_TOOL_NAME == "activate_skill"
    schema = spec.input_schema
    assert schema["properties"]["name"]["enum"] == ["alpha", "beta"]
    assert schema["required"] == ["name"]


def test_activate_unknown_name_fails_closed(make_skill):
    catalog_dir, writer = make_skill
    writer("demo")
    skills = _skills_by_name(catalog_dir)
    result = activate_skill(
        name="ghost", skills=skills, state=SkillActivationState(), scope="s1"
    )
    assert isinstance(result, LLMToolOutput)
    assert result.is_error
    assert '未安装名为 "ghost" 的 Skill' in result.content
    assert "demo" in result.content  # 可用名单提示


def test_activate_injects_body_and_records_state(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", body="正文内容。\n")
    skills = _skills_by_name(catalog_dir)
    state = SkillActivationState()
    result = activate_skill(name="demo", skills=skills, state=state, scope="s1")
    assert isinstance(result, str)
    assert 'status="activated"' in result
    assert "正文内容。" in result
    assert state.is_active("s1", "demo")


def test_activate_duplicate_returns_short_form(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", body="正文不重复。\n")
    skills = _skills_by_name(catalog_dir)
    state = SkillActivationState()
    activate_skill(name="demo", skills=skills, state=state, scope="s1")
    second = activate_skill(name="demo", skills=skills, state=state, scope="s1")
    assert isinstance(second, str)
    assert 'status="already-active"' in second
    assert "正文不重复。" not in second


def test_activate_reinjects_after_content_change(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", body="v1 正文\n")
    state = SkillActivationState()
    first = activate_skill(
        name="demo", skills=_skills_by_name(catalog_dir), state=state, scope="s1"
    )
    assert "v1 正文" in first
    # 正文变化 → hash 变化 → 再次激活重新注入新正文
    writer("demo", body="v2 正文\n")
    second = activate_skill(
        name="demo", skills=_skills_by_name(catalog_dir), state=state, scope="s1"
    )
    assert 'status="activated"' in second
    assert "v2 正文" in second


def test_activate_scopes_are_isolated(make_skill):
    catalog_dir, writer = make_skill
    writer("demo", body="正文\n")
    skills = _skills_by_name(catalog_dir)
    state = SkillActivationState()
    activate_skill(name="demo", skills=skills, state=state, scope="s1")
    other_scope = activate_skill(name="demo", skills=skills, state=state, scope="s2")
    # 另一会话首次激活仍注入完整正文
    assert 'status="activated"' in other_scope


def test_require_active_skill_gates(make_skill):
    catalog_dir, writer = make_skill
    writer("demo")
    skills = _skills_by_name(catalog_dir)
    state = SkillActivationState()

    missing = require_active_skill("ghost", skills=skills, state=state, scope="s1")
    assert isinstance(missing, LLMToolOutput) and missing.is_error
    assert "未安装" in missing.content

    inactive = require_active_skill("demo", skills=skills, state=state, scope="s1")
    assert isinstance(inactive, LLMToolOutput) and inactive.is_error
    assert 'activate_skill("demo")' in inactive.content

    state.record("s1", "demo", skills["demo"].body_sha256)
    resolved = require_active_skill("demo", skills=skills, state=state, scope="s1")
    assert resolved is skills["demo"]
