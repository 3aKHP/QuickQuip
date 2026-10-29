"""预置 Skill 同步：``skills/`` 对齐 ``skills.example/`` 的分类、备份与应用。

预置 Skill 经手动复制到达 ``skills/``，版本升级后本地副本不会自动更新。
本模块对每个预置 Skill 给出四态分类（current/diverged/missing/conflict），
并提供对齐应用基元：missing 直接安装；diverged 先把本地副本整体移入备份
容器再安装预置副本，拷贝中途失败时按分支回滚或清理半成品。本地定制不丢，
确认后由部署者自行清理备份。

本模块刻意保持 stdlib 自包含（仅依赖同包 ``preset_drift``）：主机侧同步
脚本 ``scripts/maintenance/sync_preset_skills.py`` 按文件路径装载本模块，与 Web Admin
后端的包内 import 共用同一份实现，在无项目 venv 的部署驱动机上也能运行。
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from quickquip.llm.skills.preset_drift import detect_preset_drift, preset_skill_names

# 备份容器目录：<skills>/.preset-backups/<name>.preset-backup-<时间戳>。
# 容器自身无 SKILL.md，scan_skills 静默跳过（不进 catalog、不产生跳过
# 告警）；容器名也不满足 Skill 目录名 ^[a-z0-9][a-z0-9-]*$。
BACKUP_CONTAINER_NAME = ".preset-backups"
BACKUP_NAME_INFIX = ".preset-backup-"
SYNC_STAGING_PREFIX = ".preset-sync-"


class SyncState(StrEnum):
    CURRENT = "current"
    DIVERGED = "diverged"
    MISSING = "missing"
    CONFLICT = "conflict"


# 四态的中文呈现文案（单一 owner）：主机侧同步脚本与 Web Admin 预置同步
# 面板共用，避免两份副本漂移。
STATE_LABELS: dict[SyncState, str] = {
    SyncState.CURRENT: "已安装，与预置副本一致",
    SyncState.DIVERGED: "已安装，与预置副本不同",
    SyncState.MISSING: "未安装",
    SyncState.CONFLICT: "存在同名非目录项，需人工处理",
}


@dataclass(frozen=True, slots=True)
class PresetSkillRow:
    """一个预置 Skill 的对齐状态。"""

    name: str
    state: SyncState


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """一个同步成功项的结果；``backup`` 是 diverged 覆盖更新的备份路径。"""

    name: str
    backup: Path | None


def classify_presets(skills_dir: Path, example_dir: Path) -> list[PresetSkillRow]:
    """对每个预置 Skill 给出对齐状态（按 name 字典序）。

    分叉判定复用 preset_drift 的字节级指纹比对；符号链接与同名的非目录项
    归为 CONFLICT——同步不触碰形态异常的本地项，留待人工处理。
    """
    drift_names = {item.name for item in detect_preset_drift(skills_dir, example_dir)}
    rows = []
    for name in preset_skill_names(example_dir):
        installed = skills_dir / name
        if installed.is_symlink() or (installed.exists() and not installed.is_dir()):
            state = SyncState.CONFLICT
        elif not installed.is_dir():
            state = SyncState.MISSING
        elif name in drift_names:
            state = SyncState.DIVERGED
        else:
            state = SyncState.CURRENT
        rows.append(PresetSkillRow(name=name, state=state))
    return rows


def local_only_names(skills_dir: Path, preset_names: set[str]) -> list[str]:
    """``skills/`` 下非预置、非备份容器的本地 Skill 名（播报与展示用）。"""
    if not skills_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_dir.iterdir()
        if not child.is_symlink()
        and child.is_dir()
        and child.name not in preset_names
        and child.name != BACKUP_CONTAINER_NAME
        and not child.name.startswith(SYNC_STAGING_PREFIX)
    )


def unique_backup_path(skills_dir: Path, name: str) -> Path:
    """备份目标路径：容器内 ``<name>.preset-backup-<时间戳>``，撞名追加序号。

    存在性判定同时覆盖符号链接（``exists()`` 对失效符号链接返回 False），
    保证任何形式的同名残留都不会被覆盖。
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    container = skills_dir / BACKUP_CONTAINER_NAME
    candidate = container / f"{name}{BACKUP_NAME_INFIX}{stamp}"
    suffix = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = container / f"{name}{BACKUP_NAME_INFIX}{stamp}-{suffix}"
        suffix += 1
    return candidate


def apply_presets(
    rows: list[PresetSkillRow],
    skills_dir: Path,
    example_dir: Path,
    names: set[str] | None = None,
    *,
    lock_factory: Callable[[str], AbstractContextManager] | None = None,
) -> tuple[list[SyncOutcome], list[str]]:
    """执行同步，返回（成功项, 失败描述列表）。

    ``names`` 是选名过滤（Web Admin 按需勾选同步）：``None`` 处理全部
    待处理项；给定集合时只处理集合内且状态为 missing/diverged 的行。
    current/conflict 行在任何情况下都不触碰。
    """
    outcomes: list[SyncOutcome] = []
    failures: list[str] = []
    for row in rows:
        if row.state in (SyncState.CURRENT, SyncState.CONFLICT):
            continue
        if names is not None and row.name not in names:
            continue
        try:
            with lock_factory(row.name) if lock_factory else nullcontext():
                outcome = _apply_preset(row, skills_dir, example_dir)
        except OSError as exc:
            failures.append(f"{row.name}：{exc.strerror or exc}")
            continue
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes, failures


def _apply_preset(
    row: PresetSkillRow, skills_dir: Path, example_dir: Path
) -> SyncOutcome | None:
    """持锁后复查状态，暂存完整副本再激活，仅清理本操作的暂存树。"""
    current = next(
        (item for item in classify_presets(skills_dir, example_dir) if item.name == row.name),
        None,
    )
    if current is not None and current.state is SyncState.CURRENT:
        return None
    if current is None or current.state is not row.state:
        raise OSError("状态已变化，请刷新后重试")
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=SYNC_STAGING_PREFIX, dir=skills_dir))
    staging = staging_root / row.name
    target = skills_dir / row.name
    backup: Path | None = None
    try:
        shutil.copytree(example_dir / row.name, staging)
        if row.state is SyncState.DIVERGED:
            backup = unique_backup_path(skills_dir, row.name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.rename(backup)
        # 对 missing 的竞争目标不做清理；rename 失败时保留另一写入者的目录。
        staging.rename(target)
    except OSError:
        if backup is not None and not target.exists() and not target.is_symlink():
            try:
                backup.rename(target)
            except OSError as exc:
                raise OSError(f"回滚失败，原副本保留在 {backup}（{exc}）") from exc
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return SyncOutcome(name=row.name, backup=backup)
