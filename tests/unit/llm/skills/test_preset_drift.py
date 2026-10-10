"""预置漂移检测（preset_drift.py）：目录指纹与同名分叉比对。"""
from __future__ import annotations

import os

from quickquip.llm.skills import detect_preset_drift, preset_skill_names, skill_dir_fingerprint
from quickquip.llm.skills.catalog import MAX_RESOURCES_PER_SKILL, MAX_SCRIPT_FILE_BYTES
from quickquip.llm.skills.preset_drift import (
    _MAX_FINGERPRINT_ENTRIES,
    _MAX_HASHABLE_FILE_BYTES,
)

from tests.unit.llm.skills.conftest import write_skill


# ── skill_dir_fingerprint ────────────────────────────────────────


def test_fingerprint_deterministic_and_content_sensitive(tmp_path):
    root = write_skill(tmp_path, "demo", "演示。", files={"references/a.md": "参考"})
    first = skill_dir_fingerprint(root)
    assert first == skill_dir_fingerprint(root)
    (root / "references" / "a.md").write_text("改动", encoding="utf-8")
    assert skill_dir_fingerprint(root) != first


def test_fingerprint_sensitive_to_add_remove_and_rename(tmp_path):
    root = write_skill(tmp_path, "demo", "演示。", files={"references/a.md": "参考"})
    base = skill_dir_fingerprint(root)
    (root / "references" / "b.md").write_text("新增", encoding="utf-8")
    assert skill_dir_fingerprint(root) != base
    (root / "references" / "b.md").rename(root / "references" / "c.md")
    assert skill_dir_fingerprint(root) != base
    (root / "references" / "c.md").unlink()
    assert skill_dir_fingerprint(root) == base


def test_fingerprint_symlink_differs_from_regular_file(tmp_path):
    root = write_skill(tmp_path, "demo", "演示。")
    target = tmp_path / "outside.txt"
    target.write_text("内容", encoding="utf-8")
    plain = skill_dir_fingerprint(root)
    (root / "references").mkdir()
    (root / "references" / "leak.md").symlink_to(target)
    linked = skill_dir_fingerprint(root)
    assert linked != plain
    # 符号链接替换成同内容常规文件：指纹仍不同（形态本身参与指纹）
    (root / "references" / "leak.md").unlink()
    (root / "references" / "leak.md").write_text("内容", encoding="utf-8")
    assert skill_dir_fingerprint(root) != linked


def test_fingerprint_marks_symlinked_directories(tmp_path):
    """符号链接目录必须参与指纹：followlinks=False 下它不递归也不进
    filenames，不以标记入行就漏检「子目录被换成符号链接」的改动。"""
    root = write_skill(tmp_path, "demo", "演示。")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.md").write_text("x", encoding="utf-8")
    plain = skill_dir_fingerprint(root)
    (root / "references").symlink_to(elsewhere, target_is_directory=True)
    linked = skill_dir_fingerprint(root)
    assert linked != plain
    # 符号链接目录替换为真实目录（同内容文件）：指纹仍不同
    (root / "references").unlink()
    (root / "references").mkdir()
    (root / "references" / "x.md").write_text("x", encoding="utf-8")
    assert skill_dir_fingerprint(root) != linked


def test_fingerprint_oversized_file_uses_marker_without_full_read(tmp_path):
    root = write_skill(tmp_path, "demo", "演示。")
    big = root / "references"
    big.mkdir()
    (big / "big.bin").write_bytes(os.urandom(_MAX_HASHABLE_FILE_BYTES + 1))
    marked = skill_dir_fingerprint(root)
    # 超限文件内容变化（同尺寸）不改变标记形态，指纹稳定且不读盘
    (big / "big.bin").write_bytes(os.urandom(_MAX_HASHABLE_FILE_BYTES + 1))
    assert skill_dir_fingerprint(root) == marked
    # 回到可哈希尺寸后内容重新参与指纹
    (big / "big.bin").write_bytes(b"small")
    assert skill_dir_fingerprint(root) != marked


def test_limits_align_with_catalog_scan_guards():
    """stdlib 自包含约束下的并行常量：与 catalog 扫描防护同源对齐。"""
    assert _MAX_HASHABLE_FILE_BYTES == MAX_SCRIPT_FILE_BYTES
    assert _MAX_FINGERPRINT_ENTRIES == MAX_RESOURCES_PER_SKILL


# ── preset_skill_names / detect_preset_drift ─────────────────────


def test_preset_skill_names_fail_open_and_filter(preset_pair, tmp_path):
    skills_dir, example_dir = preset_pair
    assert preset_skill_names(tmp_path / "no-such-dir") == []
    write_skill(example_dir, "beta", "预置。")
    write_skill(example_dir, "alpha", "预置。")
    elsewhere = write_skill(tmp_path / "elsewhere", "gamma", "别处。")
    (example_dir / "gamma").symlink_to(elsewhere, target_is_directory=True)
    assert preset_skill_names(example_dir) == ["alpha", "beta"]


def test_detect_diverged_only_when_bytes_differ(preset_pair):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "self-docs", "预置。", files={"references/a.md": "v2"})
    write_skill(skills_dir, "self-docs", "预置。", files={"references/a.md": "v1"})
    (drift,) = detect_preset_drift(skills_dir, example_dir)
    assert drift.name == "self-docs"
    assert drift.installed_sha256 != drift.preset_sha256
    # 对齐后分叉消失
    write_skill(skills_dir, "self-docs", "预置。", files={"references/a.md": "v2"})
    assert detect_preset_drift(skills_dir, example_dir) == []


def test_detect_ignores_single_side_entries(preset_pair):
    skills_dir, example_dir = preset_pair
    # 预置有而本地未安装（missing）：运行时检测不报告，归同步脚本三态
    write_skill(example_dir, "self-docs", "预置。")
    # 本地自建（非预置）：不报告
    write_skill(skills_dir, "my-custom", "自建。")
    assert detect_preset_drift(skills_dir, example_dir) == []


def test_detect_fail_open_when_example_dir_missing(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    write_skill(skills_dir, "self-docs", "本地副本。")
    assert detect_preset_drift(skills_dir, tmp_path / "no-such-dir") == []


def test_detect_skips_symlinked_installed_dir(preset_pair, tmp_path):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "self-docs", "预置。")
    elsewhere = write_skill(tmp_path / "elsewhere", "self-docs", "别处。")
    (skills_dir / "self-docs").symlink_to(elsewhere, target_is_directory=True)
    assert detect_preset_drift(skills_dir, example_dir) == []


def test_detect_multiple_diverged_sorted_by_name(preset_pair):
    skills_dir, example_dir = preset_pair
    for name in ("beta", "alpha"):
        write_skill(example_dir, name, "预置 v2。")
        write_skill(skills_dir, name, "预置 v1。")
    write_skill(example_dir, "gamma", "一致。")
    write_skill(skills_dir, "gamma", "一致。")
    assert [item.name for item in detect_preset_drift(skills_dir, example_dir)] == [
        "alpha",
        "beta",
    ]
