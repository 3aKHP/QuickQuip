"""self-docs 关键词检索集成测试（验收映射「关键词检索可用」后半）。

用生产 loader 加载真实的 skills.example/self-docs 生成物，直接调用
search_skill_resources / read_skill_resource，验证关键词型问题（命令名、
配置键、报错术语）命中正确 reference，并走通 SKILL.md 指引的
「search 命中行号 → read 行区间」工作流。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import pytest

from quickquip.llm.skills import (
    LoadedSkill,
    SkillActivationState,
    read_skill_resource,
    scan_skills,
    search_skill_resources,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_EXAMPLE_DIR = REPO_ROOT / "skills.example"
_SCOPE = "self-docs-search-test"
_RESOURCE_MAX_BYTES = 65536


@pytest.fixture(scope="module")
def activated() -> tuple[Mapping[str, LoadedSkill], SkillActivationState]:
    skills = {skill.name: skill for skill in scan_skills(SKILLS_EXAMPLE_DIR)}
    skill = skills["self-docs"]
    state = SkillActivationState()
    state.record(_SCOPE, skill.name, skill.body_sha256)
    return {skill.name: skill}, state


def _search(activated, query: str) -> str:
    skills, state = activated
    result = search_skill_resources(
        skill_name="self-docs",
        query=query,
        skills=skills,
        state=state,
        scope=_SCOPE,
    )
    assert isinstance(result, str)
    return result


def test_command_name_hits_group_commands(activated):
    result = _search(activated, "/quote")
    assert "references/docs-user-group-commands.md:" in result


def test_config_key_hits_skills_admin_page(activated):
    result = _search(activated, "catalog_max_bytes")
    assert "references/docs-admin-skills.md:" in result


def test_error_term_hits_migration_troubleshooting(activated):
    result = _search(activated, "掉线")
    assert "references/docs-admin-migration-napcat-to-llbot.md:" in result


def test_search_hit_line_number_guides_ranged_read(activated):
    result = _search(activated, "/quote search")
    match = re.search(r"references/docs-user-group-commands\.md:(\d+):", result)
    assert match, result
    line = int(match.group(1))

    skills, state = activated
    read = read_skill_resource(
        skill_name="self-docs",
        path="references/docs-user-group-commands.md",
        skills=skills,
        state=state,
        scope=_SCOPE,
        max_bytes=_RESOURCE_MAX_BYTES,
        start_line=max(1, line - 2),
        end_line=line + 2,
    )
    assert isinstance(read, str)
    assert "/quote search" in read
    assert "[第 " in read


def test_oversized_reference_reads_truncated_front_section(activated):
    skills, state = activated
    read = read_skill_resource(
        skill_name="self-docs",
        path="references/root-changelog.md",
        skills=skills,
        state=state,
        scope=_SCOPE,
        max_bytes=_RESOURCE_MAX_BYTES,
    )
    assert isinstance(read, str)
    assert "[已截断" in read
