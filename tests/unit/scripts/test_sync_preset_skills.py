"""预置 Skill 同步脚本的三态报告、备份覆盖与退出码。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
    # 分叉项被覆盖为预置副本，旧副本整体备份
    assert (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8") == "v2"
    (backup,) = skills_dir.glob("alpha.preset-backup-*")
    assert (backup / "SKILL.md").read_text(encoding="utf-8") == "v1"
    assert (backup / "references/a.md").read_text(encoding="utf-8") == "旧参考"
    # 缺失项直接安装；本地自建不动
    assert (skills_dir / "beta/SKILL.md").read_text(encoding="utf-8") == "v1"
    assert (skills_dir / "local-only/SKILL.md").read_text(encoding="utf-8") == "自建"
    # 幂等：同步后 check 归零；备份目录不进“本地非预置”播报
    assert _run(module, monkeypatch, ["--check", *args]) == 0
    output = capsys.readouterr().out
    local_only_lines = [line for line in output.splitlines() if line.startswith("另有")]
    assert local_only_lines and all("preset-backup" not in line for line in local_only_lines)


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
