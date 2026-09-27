"""预置 Skill 同步脚本的三态报告、备份覆盖与退出码。"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from quickquip.llm.skills import scan_skills

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "sync_preset_skills.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_preset_skills", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _pair(tmp_path):
    skills_dir = tmp_path / "skills"
    example_dir = tmp_path / "skills.example"
    skills_dir.mkdir()
    example_dir.mkdir()
    return skills_dir, example_dir


def _run(module, monkeypatch, argv: list[str]):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), *argv])
    return module.main()


def test_check_all_current_exits_zero(tmp_path, monkeypatch, capsys):
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "alpha", {"SKILL.md": "v1", "references/a.md": "参考"})
    _write(skills_dir / "alpha", {"SKILL.md": "v1", "references/a.md": "参考"})
    code = _run(
        module,
        monkeypatch,
        ["--check", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    )
    assert code == 0
    assert "全部一致" in capsys.readouterr().out


def test_check_reports_missing_and_diverged(tmp_path, monkeypatch, capsys):
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "alpha", {"SKILL.md": "v2"})
    _write(example_dir / "beta", {"SKILL.md": "v1"})
    _write(skills_dir / "alpha", {"SKILL.md": "v1"})
    _write(skills_dir / "local-only", {"SKILL.md": "自建"})
    code = _run(
        module,
        monkeypatch,
        ["--check", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    )
    assert code == 1
    output = capsys.readouterr().out
    assert "diverged  alpha" in output
    assert "missing   beta" in output
    assert "local-only" in output
    assert "--apply" in output


def test_apply_installs_missing_and_backs_up_diverged(tmp_path, monkeypatch, capsys):
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "alpha", {"SKILL.md": "v2", "references/a.md": "新参考"})
    _write(example_dir / "beta", {"SKILL.md": "v1"})
    _write(skills_dir / "alpha", {"SKILL.md": "v1", "references/a.md": "旧参考"})
    _write(skills_dir / "local-only", {"SKILL.md": "自建"})
    args = ["--skills-dir", str(skills_dir), "--example-dir", str(example_dir)]

    assert _run(module, monkeypatch, ["--apply", *args]) == 0
    # 分叉项被覆盖为预置副本，旧副本整体备份进 .preset-backups/ 容器
    assert (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8") == "v2"
    (backup,) = (skills_dir / ".preset-backups").glob("alpha.preset-backup-*")
    assert (backup / "SKILL.md").read_text(encoding="utf-8") == "v1"
    assert (backup / "references/a.md").read_text(encoding="utf-8") == "旧参考"
    # 缺失项直接安装；本地自建不动
    assert (skills_dir / "beta/SKILL.md").read_text(encoding="utf-8") == "v1"
    assert (skills_dir / "local-only/SKILL.md").read_text(encoding="utf-8") == "自建"
    # 幂等：同步后 check 归零；备份容器不进“本地非预置”播报
    assert _run(module, monkeypatch, ["--check", *args]) == 0
    output = capsys.readouterr().out
    local_only_lines = [line for line in output.splitlines() if line.startswith("另有")]
    assert local_only_lines
    for line in local_only_lines:
        assert "preset-backup" not in line
        assert "local-only" in line


def test_backup_container_is_invisible_to_runtime_scan(tmp_path, monkeypatch, caplog):
    """--apply 留下的备份容器不得被 scan_skills 当 Skill 处理（否则目录名
    与 frontmatter name 不符，每轮扫描一条 WARNING）。"""
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(
        example_dir / "alpha",
        {"SKILL.md": "---\nname: alpha\ndescription: 预置 v2。\n---\n"},
    )
    _write(
        skills_dir / "alpha",
        {"SKILL.md": "---\nname: alpha\ndescription: 预置 v1。\n---\n"},
    )
    assert _run(
        module,
        monkeypatch,
        ["--apply", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    ) == 0
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.skills.catalog"):
        loaded = scan_skills(skills_dir)
    assert [skill.name for skill in loaded] == ["alpha"]
    assert not caplog.records


def test_apply_rename_failure_preserves_original(tmp_path, monkeypatch, capsys):
    """备份改名自身失败（如 Windows 文件占用）：部署者原副本必须原样保留，
    且不得发生任何清理动作（回滚分支只允许在改名成功后介入）。"""
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "alpha", {"SKILL.md": "v2"})
    _write(skills_dir / "alpha", {"SKILL.md": "v1 定制"})

    def _failing_rename(self, target):
        raise OSError("simulated lock")

    monkeypatch.setattr(Path, "rename", _failing_rename)
    code = _run(
        module,
        monkeypatch,
        ["--apply", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    )
    assert code == 2
    assert (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8") == "v1 定制"
    container = skills_dir / ".preset-backups"
    assert not container.exists() or list(container.iterdir()) == []
    assert "alpha" in capsys.readouterr().err


def test_apply_partial_copy_cleaned_up(tmp_path, monkeypatch, capsys):
    """missing 分支拷贝中途失败：本次新建的半成品目标必须清掉，不留残缺
    Skill 目录污染运行时扫描面。"""
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "beta", {"SKILL.md": "v1", "references/a.md": "x"})

    def _partial_copytree(src, dst):
        dst.mkdir()
        (dst / "SKILL.md").write_text("v1", encoding="utf-8")
        raise OSError("simulated disk full")

    monkeypatch.setattr(module.shutil, "copytree", _partial_copytree)
    code = _run(
        module,
        monkeypatch,
        ["--apply", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    )
    assert code == 2
    assert not (skills_dir / "beta").exists()
    assert "beta" in capsys.readouterr().err


def test_apply_skips_conflict_and_reports(tmp_path, monkeypatch, capsys):
    module = _load_script()
    skills_dir, example_dir = _pair(tmp_path)
    _write(example_dir / "alpha", {"SKILL.md": "v1"})
    (skills_dir / "alpha").write_text("同名文件，不是目录", encoding="utf-8")
    code = _run(
        module,
        monkeypatch,
        ["--apply", "--skills-dir", str(skills_dir), "--example-dir", str(example_dir)],
    )
    assert code == 2
    assert "conflict" in capsys.readouterr().out
    assert (skills_dir / "alpha").is_file()  # 冲突项不被触碰


def test_missing_example_dir_exits_two(tmp_path, monkeypatch, capsys):
    module = _load_script()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    code = _run(
        module,
        monkeypatch,
        ["--check", "--skills-dir", str(skills_dir), "--example-dir", str(tmp_path / "none")],
    )
    assert code == 2
    assert "预置目录不存在" in capsys.readouterr().err
