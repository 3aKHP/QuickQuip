from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "sync_self_docs_references.py"

SKILL_MD = (
    "---\n"
    "name: self-docs\n"
    "description: 测试用 self-docs。\n"
    "---\n"
    "\n"
    "| 主题 | Reference |\n"
    "| --- | --- |\n"
    "| 概览 | `references/root-readme.md` |\n"
    "| 命令 | `references/docs-user-commands.md` |\n"
    "| 配置 | `references/docs-admin-skills.md` |\n"
    "| PR 模板 | `references/github-pull_request_template.md` |\n"
    "| 索引 | `references/index.md` |\n"
)

EXTRA_FILES = {
    ".claude/agents/quickquip-cr-reviewer.md": "# CR 评审\n\n按 `git diff` 评审。\n",
    ".github/ISSUE_TEMPLATE/memo.md": "# Memo 模板\n",
    ".github/PULL_REQUEST_TEMPLATE/release.md": "# Release 模板\n",
    ".github/pull_request_template.md": "# PR 模板\n",
    "prod.example/README.md": "# 生产模板\n\n复制为 `prod/`。\n",
}


def _make_repo(root: Path) -> None:
    (root / "docs" / "user").mkdir(parents=True)
    (root / "docs" / "admin").mkdir(parents=True)
    (root / "README.md").write_text("# Demo\n\n参见 `config.toml`。\n", encoding="utf-8")
    (root / "docs" / "user" / "commands.md").write_text(
        "# 命令速查\n\n`/quote` 收藏语录。\n", encoding="utf-8"
    )
    (root / "docs" / "admin" / "skills.md").write_text(
        "# Skill 系统\n\n`catalog_max_bytes` 控制预算。\n", encoding="utf-8"
    )
    for relative, content in EXTRA_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    skill_root = root / "skills.example" / "self-docs"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
    )


def test_write_then_check_roundtrip(tmp_path: Path):
    _make_repo(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    references = tmp_path / "skills.example" / "self-docs" / "references"
    names = sorted(path.name for path in references.iterdir())
    assert names == [
        "claude-agents-quickquip-cr-reviewer.md",
        "docs-admin-skills.md",
        "docs-user-commands.md",
        "github-issue_template-memo.md",
        "github-pull_request_template-release.md",
        "github-pull_request_template.md",
        "index.md",
        "prod.example-readme.md",
        "root-readme.md",
    ]

    readme = (references / "root-readme.md").read_text(encoding="utf-8")
    assert readme.startswith("<!-- Generated from README.md; do not edit -->\n\n# Demo")

    cr = (references / "claude-agents-quickquip-cr-reviewer.md").read_text(encoding="utf-8")
    assert cr.startswith(
        "<!-- Generated from .claude/agents/quickquip-cr-reviewer.md; do not edit -->"
    )
    prod = (references / "prod.example-readme.md").read_text(encoding="utf-8")
    assert prod.startswith("<!-- Generated from prod.example/README.md; do not edit -->")

    index = (references / "index.md").read_text(encoding="utf-8")
    assert index.startswith("<!-- Generated index; do not edit.")
    assert "关键词：/quote" in index
    assert "关键词：catalog_max_bytes" in index
    assert "命令速查" in index

    check = _run(tmp_path, "--check")
    assert check.returncode == 0, check.stderr


def test_missing_extra_source_file_fails(tmp_path: Path):
    _make_repo(tmp_path)
    (tmp_path / ".github" / "pull_request_template.md").unlink()
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "缺失" in result.stderr
    assert ".github/pull_request_template.md" in result.stderr


def test_write_sweeps_stale_staging_dirs(tmp_path: Path):
    """历史中断残留的任意 pid 暂存/旧目录在 write 前被清扫。"""
    _make_repo(tmp_path)
    skill_root = tmp_path / "skills.example" / "self-docs"
    for name in (".references-staging-999", ".references-old-999"):
        leftover = skill_root / name
        leftover.mkdir()
        (leftover / "junk.md").write_text("残留\n", encoding="utf-8")

    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (skill_root / "references").is_dir()
    remaining = [
        path.name
        for path in skill_root.iterdir()
        if path.name.startswith((".references-staging-", ".references-old-"))
    ]
    assert remaining == []


def test_check_detects_changed_and_extra_and_missing(tmp_path: Path):
    _make_repo(tmp_path)
    assert _run(tmp_path).returncode == 0
    references = tmp_path / "skills.example" / "self-docs" / "references"

    (tmp_path / "docs" / "user" / "commands.md").write_text(
        "# 命令速查\n\n内容变了。\n", encoding="utf-8"
    )
    (references / "stray.md").write_text("多余文件\n", encoding="utf-8")
    (references / "root-readme.md").unlink()

    check = _run(tmp_path, "--check")
    assert check.returncode == 1
    assert "changed: references/docs-user-commands.md" in check.stderr
    assert "extra: references/stray.md" in check.stderr
    assert "missing: references/root-readme.md" in check.stderr


def test_rejects_nul_bytes_in_source(tmp_path: Path):
    _make_repo(tmp_path)
    (tmp_path / "docs" / "user" / "commands.md").write_bytes(b"# hi\n\n\x00binary\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "NUL" in result.stderr


def test_rejects_resource_name_collision(tmp_path: Path):
    _make_repo(tmp_path)
    (tmp_path / "docs" / "user" / "a-b.md").write_text("# AB\n", encoding="utf-8")
    nested = tmp_path / "docs" / "user" / "a"
    nested.mkdir()
    (nested / "b.md").write_text("# AB nested\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "docs-user-a-b.md" in result.stderr
    assert "冲突" in result.stderr


def test_rejects_routing_reference_not_generated(tmp_path: Path):
    _make_repo(tmp_path)
    skill_md = tmp_path / "skills.example" / "self-docs" / "SKILL.md"
    skill_md.write_text(SKILL_MD + "| 幽灵 | `references/docs-user-ghost.md` |\n", encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "references/docs-user-ghost.md" in result.stderr
    assert "不在生成的资源集中" in result.stderr


def test_rejects_invalid_utf8_in_source(tmp_path: Path):
    _make_repo(tmp_path)
    (tmp_path / "docs" / "user" / "commands.md").write_bytes(b"# hi\n\n\xff\xfe\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "UTF-8" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Windows 创建符号链接需要特权")
def test_rejects_symlink_in_source(tmp_path: Path):
    _make_repo(tmp_path)
    target = tmp_path / "docs" / "user" / "commands.md"
    link = tmp_path / "docs" / "user" / "linked.md"
    link.symlink_to(target)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "符号链接" in result.stderr
