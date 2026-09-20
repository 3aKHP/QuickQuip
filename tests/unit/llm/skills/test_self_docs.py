"""预置 self-docs Skill（skills.example/self-docs）的契约测试。

随 pytest 套件运行，是 CI 中 sync_self_docs_references.py --check 步骤之外的
双保险：走生产 loader（scan_skills）证明运行时真能解析，并强制禁脚本、
资源边界、文档覆盖面与泄漏扫描（与 .redact-ids 名单同源）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from quickquip.llm.skills import (
    MAX_DESCRIPTION_CHARS,
    MAX_RESOURCES_PER_SKILL,
    MAX_SKILL_FILE_BYTES,
    READ_SKILL_RESOURCE_TOOL_NAME,
    SEARCH_SKILL_RESOURCES_TOOL_NAME,
    LoadedSkill,
    scan_skills,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILLS_EXAMPLE_DIR = REPO_ROOT / "skills.example"
SKILL_ROOT = SKILLS_EXAMPLE_DIR / "self-docs"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "ci" / "sync_self_docs_references.py"

MAX_RESOURCE_BYTES = 256 * 1024

_API_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_CHECKOUT_PATH_PATTERN = re.compile(r"(/home/|/Users/|[A-Za-z]:\\Users\\)")


def _load_redact_ids() -> list[str]:
    path = REPO_ROOT / ".redact-ids"
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


@pytest.fixture(scope="module")
def self_docs_skill() -> LoadedSkill:
    skills = {skill.name: skill for skill in scan_skills(SKILLS_EXAMPLE_DIR)}
    assert "self-docs" in skills, "skills.example/self-docs 未能通过生产 loader 加载"
    return skills["self-docs"]


def test_loads_through_production_loader(self_docs_skill: LoadedSkill):
    metadata = self_docs_skill.metadata
    assert metadata.name == "self-docs"
    assert 0 < len(metadata.description) <= MAX_DESCRIPTION_CHARS
    assert self_docs_skill.diagnostics == []
    assert self_docs_skill.body.strip()
    assert SEARCH_SKILL_RESOURCES_TOOL_NAME in self_docs_skill.body
    assert READ_SKILL_RESOURCE_TOOL_NAME in self_docs_skill.body


def test_description_declares_trigger_and_priority(self_docs_skill: LoadedSkill):
    description = self_docs_skill.metadata.description
    assert "当用户" in description
    assert "训练知识" in description


def test_contains_no_scripts(self_docs_skill: LoadedSkill):
    scripts = [r for r in self_docs_skill.resources if r.kind == "script"]
    assert scripts == []
    assert not (SKILL_ROOT / "scripts").exists()


def test_within_resource_bounds(self_docs_skill: LoadedSkill):
    assert len(self_docs_skill.resources) <= MAX_RESOURCES_PER_SKILL
    for resource in self_docs_skill.resources:
        assert resource.size_bytes <= MAX_RESOURCE_BYTES, resource.path
    skill_md_size = (SKILL_ROOT / "SKILL.md").stat().st_size
    assert skill_md_size <= MAX_SKILL_FILE_BYTES


def test_covers_user_admin_dev_and_index(self_docs_skill: LoadedSkill):
    paths = [resource.path for resource in self_docs_skill.resources]
    assert any(path.startswith("references/docs-user-") for path in paths)
    assert any(path.startswith("references/docs-admin-") for path in paths)
    assert any(path.startswith("references/docs-dev-") for path in paths)
    assert "references/index.md" in paths


def test_covers_full_source_allowlist(self_docs_skill: LoadedSkill):
    paths = {resource.path for resource in self_docs_skill.resources}
    expected = {
        "references/root-code_of_conduct.md",
        "references/root-claude.md",
        "references/claude-agents-quickquip-cr-reviewer.md",
        "references/docs-admin-global-admins.md",
        "references/github-issue_template-memo.md",
        "references/github-pull_request_template-release.md",
        "references/github-pull_request_template.md",
        "references/prod.example-readme.md",
    }
    assert expected <= paths
    assert len(paths) == 46


def test_no_leaked_checkout_path_api_key_or_private_id(self_docs_skill: LoadedSkill):
    redact_ids = _load_redact_ids()
    references_dir = SKILL_ROOT / "references"
    for resource in self_docs_skill.resources:
        path = references_dir / resource.path.removeprefix("references/")
        content = path.read_text(encoding="utf-8")
        assert str(REPO_ROOT) not in content, resource.path
        assert not _CHECKOUT_PATH_PATTERN.search(content), resource.path
        for pattern in _API_KEY_PATTERNS:
            assert not pattern.search(content), resource.path
        for private_id in redact_ids:
            assert private_id not in content, resource.path


def test_check_mode_reports_no_drift():
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
