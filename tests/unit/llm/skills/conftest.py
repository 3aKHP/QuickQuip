"""skills 域测试共享的 skill 目录构造助手。"""
from __future__ import annotations

from pathlib import Path

import pytest

from quickquip.llm.skills import LoadedSkill, SkillActivationState, scan_skills


def skill_markdown(
    name: str,
    description: str,
    *,
    body: str = "",
    frontmatter_extra: str = "",
) -> str:
    extra = f"{frontmatter_extra}\n" if frontmatter_extra else ""
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra}"
        "---\n"
        f"{body}"
    )


def write_skill(
    catalog_dir: Path,
    name: str,
    description: str = "测试用 skill。",
    *,
    body: str = "",
    frontmatter_extra: str = "",
    files: dict[str, str | bytes] | None = None,
) -> Path:
    """在 catalog_dir 下写一个合法 skill 目录，返回 skill 根。"""
    root = catalog_dir / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        skill_markdown(name, description, body=body, frontmatter_extra=frontmatter_extra),
        encoding="utf-8",
    )
    for relative, content in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def make_skill(tmp_path):
    """返回 (catalog_dir, writer)；writer 即 write_skill 绑定到该 catalog_dir。"""

    catalog_dir = tmp_path / "skills"
    catalog_dir.mkdir()

    def _writer(name: str, description: str = "测试用 skill。", **kwargs) -> Path:
        return write_skill(catalog_dir, name, description, **kwargs)

    return catalog_dir, _writer


def load_single(catalog_dir: Path, name: str) -> LoadedSkill:
    skills = {skill.name: skill for skill in scan_skills(catalog_dir)}
    return skills[name]


@pytest.fixture
def activation_state() -> SkillActivationState:
    return SkillActivationState()
