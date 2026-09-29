"""预置同步逻辑（preset_sync.py）：四态分类、选名过滤、备份与失败回滚。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from quickquip.llm.skills import preset_sync
from quickquip.llm.skills.preset_sync import (
    BACKUP_CONTAINER_NAME,
    BACKUP_NAME_INFIX,
    STATE_LABELS,
    PresetSkillRow,
    SyncOutcome,
    SyncState,
    apply_presets,
    classify_presets,
    local_only_names,
    unique_backup_path,
)

from tests.unit.llm.skills.conftest import write_skill


# ── classify_presets ─────────────────────────────────────────────


def test_classify_four_states(preset_pair, tmp_path):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "一致。")
    write_skill(skills_dir, "alpha", "一致。")
    write_skill(example_dir, "beta", "预置 v2。")
    write_skill(skills_dir, "beta", "预置 v1。")
    write_skill(example_dir, "gamma", "未安装。")
    write_skill(example_dir, "delta", "冲突。")
    (skills_dir / "delta").write_text("同名文件，不是目录", encoding="utf-8")
    write_skill(example_dir, "epsilon", "符号链接冲突。")
    elsewhere = write_skill(tmp_path / "elsewhere", "epsilon", "别处。")
    (skills_dir / "epsilon").symlink_to(elsewhere, target_is_directory=True)

    rows = classify_presets(skills_dir, example_dir)

    assert rows == [
        PresetSkillRow("alpha", SyncState.CURRENT),
        PresetSkillRow("beta", SyncState.DIVERGED),
        PresetSkillRow("delta", SyncState.CONFLICT),
        PresetSkillRow("epsilon", SyncState.CONFLICT),
        PresetSkillRow("gamma", SyncState.MISSING),
    ]


def test_classify_missing_example_dir_returns_empty(preset_pair):
    skills_dir, _ = preset_pair
    write_skill(skills_dir, "alpha", "本地副本。")
    assert classify_presets(skills_dir, skills_dir.parent / "no-such-dir") == []


# ── local_only_names ─────────────────────────────────────────────


def test_local_only_names_filters_preset_backup_and_non_dirs(preset_pair, tmp_path):
    skills_dir, _ = preset_pair
    write_skill(skills_dir, "my-own", "自建。")
    write_skill(skills_dir, "alpha", "预置。")
    (skills_dir / BACKUP_CONTAINER_NAME).mkdir()
    (skills_dir / "stray.txt").write_text("普通文件", encoding="utf-8")
    elsewhere = write_skill(tmp_path / "elsewhere", "linked", "别处。")
    (skills_dir / "linked").symlink_to(elsewhere, target_is_directory=True)

    assert local_only_names(skills_dir, {"alpha"}) == ["my-own"]


def test_local_only_names_missing_dir_returns_empty(tmp_path):
    assert local_only_names(tmp_path / "no-such-dir", {"alpha"}) == []


# ── unique_backup_path ───────────────────────────────────────────


def test_unique_backup_path_appends_suffix_on_collision(preset_pair, tmp_path, monkeypatch):
    skills_dir, _ = preset_pair

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 29, 12, 0, 0)

    monkeypatch.setattr(preset_sync, "datetime", _FixedDatetime)

    first = unique_backup_path(skills_dir, "alpha")
    assert first.parent == skills_dir / BACKUP_CONTAINER_NAME
    assert first.name == f"alpha{BACKUP_NAME_INFIX}20260929-120000"

    first.mkdir(parents=True)
    second = unique_backup_path(skills_dir, "alpha")
    assert second.name == f"alpha{BACKUP_NAME_INFIX}20260929-120000-2"

    # 失效符号链接（exists() 为 False）同样视作占用，不得覆盖
    second.symlink_to(tmp_path / "no-such-target")
    third = unique_backup_path(skills_dir, "alpha")
    assert third.name == f"alpha{BACKUP_NAME_INFIX}20260929-120000-3"


# ── apply_presets ────────────────────────────────────────────────


def test_apply_installs_missing_and_backs_up_diverged(preset_pair):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "预置 v2。", files={"references/a.md": "新参考"})
    write_skill(example_dir, "beta", "未安装。")
    write_skill(skills_dir, "alpha", "预置 v1。", files={"references/a.md": "旧参考"})
    write_skill(skills_dir, "local-only", "自建。")

    rows = classify_presets(skills_dir, example_dir)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir)

    assert failures == []
    (backup,) = (skills_dir / BACKUP_CONTAINER_NAME).glob(f"alpha{BACKUP_NAME_INFIX}*")
    assert outcomes == [SyncOutcome("alpha", backup), SyncOutcome("beta", None)]
    # 分叉项被覆盖为预置副本，旧副本整体保留在备份路径
    assert "预置 v2。" in (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8")
    assert "预置 v1。" in (backup / "SKILL.md").read_text(encoding="utf-8")
    assert (backup / "references/a.md").read_text(encoding="utf-8") == "旧参考"
    # 缺失项直接安装；本地自建不动
    assert "未安装。" in (skills_dir / "beta/SKILL.md").read_text(encoding="utf-8")
    assert "自建。" in (skills_dir / "local-only/SKILL.md").read_text(encoding="utf-8")
    # 幂等：同步后重新分类全部一致
    assert {row.state for row in classify_presets(skills_dir, example_dir)} == {
        SyncState.CURRENT
    }


def test_apply_names_filter_selects_subset(preset_pair):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "预置 v2。")
    write_skill(example_dir, "beta", "未安装。")
    write_skill(example_dir, "gamma", "未安装。")
    write_skill(skills_dir, "alpha", "预置 v1。")

    rows = classify_presets(skills_dir, example_dir)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir, names={"alpha", "gamma"})

    assert failures == []
    assert [outcome.name for outcome in outcomes] == ["alpha", "gamma"]
    assert not (skills_dir / "beta").exists()
    assert (skills_dir / "gamma/SKILL.md").is_file()


def test_apply_names_filter_ignores_non_pending_and_unknown(preset_pair):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "一致。")
    write_skill(skills_dir, "alpha", "一致。")
    write_skill(example_dir, "beta", "未安装。")

    rows = classify_presets(skills_dir, example_dir)
    outcomes, failures = apply_presets(
        rows, skills_dir, example_dir, names={"alpha", "unknown"}
    )

    assert outcomes == []
    assert failures == []
    assert not (skills_dir / "beta").exists()


def test_apply_skips_current_and_conflict(preset_pair):
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "一致。")
    write_skill(skills_dir, "alpha", "一致。")
    write_skill(example_dir, "delta", "冲突。")
    (skills_dir / "delta").write_text("同名文件，不是目录", encoding="utf-8")

    rows = classify_presets(skills_dir, example_dir)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir)

    assert outcomes == []
    assert failures == []
    assert (skills_dir / "delta").is_file()


def test_apply_diverged_copy_failure_rolls_back(preset_pair, monkeypatch):
    """diverged 分支拷贝中途失败：清掉半成品并把部署者原副本回滚复位。"""
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "预置 v2。", files={"references/a.md": "新参考"})
    write_skill(skills_dir, "alpha", "预置 v1。", files={"references/a.md": "旧参考"})
    rows = classify_presets(skills_dir, example_dir)

    def _partial_copytree(src, dst):
        dst.mkdir()
        (dst / "SKILL.md").write_text("半成品", encoding="utf-8")
        raise OSError("simulated disk full")

    monkeypatch.setattr(shutil, "copytree", _partial_copytree)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir)

    assert outcomes == []
    assert len(failures) == 1
    assert "alpha" in failures[0]
    assert "预置 v1。" in (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8")
    assert (skills_dir / "alpha/references/a.md").read_text(encoding="utf-8") == "旧参考"
    # 回滚把备份改名回原位，容器内不留残留
    container = skills_dir / BACKUP_CONTAINER_NAME
    assert not container.exists() or list(container.iterdir()) == []


def test_apply_missing_copy_failure_cleans_partial(preset_pair, monkeypatch):
    """missing 分支拷贝中途失败：本次新建的半成品目标必须清掉。"""
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "beta", "未安装。", files={"references/a.md": "x"})
    rows = classify_presets(skills_dir, example_dir)

    def _partial_copytree(src, dst):
        dst.mkdir()
        (dst / "SKILL.md").write_text("半成品", encoding="utf-8")
        raise OSError("simulated disk full")

    monkeypatch.setattr(shutil, "copytree", _partial_copytree)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir)

    assert outcomes == []
    assert len(failures) == 1
    assert "beta" in failures[0]
    assert not (skills_dir / "beta").exists()


def test_apply_backup_rename_failure_preserves_original(preset_pair, monkeypatch):
    """备份改名自身失败（如 Windows 文件占用）：部署者原副本必须原样保留，
    且不得发生任何清理动作（回滚分支只允许在改名成功后介入）。"""
    skills_dir, example_dir = preset_pair
    write_skill(example_dir, "alpha", "预置 v2。")
    write_skill(skills_dir, "alpha", "预置 v1 定制。")
    rows = classify_presets(skills_dir, example_dir)

    def _failing_rename(self, target):
        raise OSError("simulated lock")

    monkeypatch.setattr(Path, "rename", _failing_rename)
    outcomes, failures = apply_presets(rows, skills_dir, example_dir)

    assert outcomes == []
    assert len(failures) == 1
    assert "alpha" in failures[0]
    assert "预置 v1 定制。" in (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8")
    container = skills_dir / BACKUP_CONTAINER_NAME
    assert not container.exists() or list(container.iterdir()) == []


def test_state_labels_cover_all_states_uniquely():
    """四态 label 与 SyncState 一一对应、互异且非空（单一 owner 防漂移）。"""
    assert set(STATE_LABELS) == set(SyncState)
    labels = list(STATE_LABELS.values())
    assert all(labels)
    assert len(set(labels)) == len(labels)
