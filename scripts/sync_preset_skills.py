# -*- coding: utf-8 -*-
"""预置 Skill 同步工具：检视并对齐 skills/ 与 skills.example/。

预置 Skill 经手动复制到达 skills/，版本升级后本地副本不会自动更新。本工具
对每个预置 Skill 报告三态：

    current   已安装且与当前版本预置副本逐字节一致
    diverged  已安装但与预置副本不同（升级后的陈旧副本或本地定制）
    missing   未安装

默认（或 --check）只报告不写入，有 missing/diverged 时退出码 1；
--apply 执行同步：missing 直接安装，diverged 先把本地副本整体移入
skills/.preset-backups/<name>.preset-backup-<时间戳> 再安装预置副本（备份
容器自身无 SKILL.md，运行时扫描不感知；本地定制不丢，确认后自行清理）。
bot 每轮请求现扫 skills/，同步当轮生效，无需重启。

用法：
    python scripts/sync_preset_skills.py            # 只报告
    python scripts/sync_preset_skills.py --check    # 只报告（部署脚本用）
    python scripts/sync_preset_skills.py --apply    # 执行同步（留备份）
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 默认目录与 quickquip.common.paths 的 SKILLS_DIR / SKILLS_EXAMPLE_DIR 一致。
# 本工具刻意不 import 包（避免连带 yaml/dotenv 等第三方依赖，保证无项目
# venv 的部署驱动机可跑），路径规则在此保留一份带注释的副本。
SKILLS_DIR = PROJECT_ROOT / "skills"
SKILLS_EXAMPLE_DIR = PROJECT_ROOT / "skills.example"

# 备份容器目录：<skills>/.preset-backups/<name>.preset-backup-<时间戳>。
# 容器自身无 SKILL.md，scan_skills 静默跳过（不进 catalog、不产生跳过
# 告警）；容器名也不满足 Skill 目录名 ^[a-z0-9][a-z0-9-]*$。
BACKUP_CONTAINER_NAME = ".preset-backups"
BACKUP_NAME_INFIX = ".preset-backup-"


@functools.cache
def _preset_drift():
    """按文件路径装载运行时同一份 preset_drift 实现（延迟到首次使用）。

    本脚本是主机侧运维工具，要求在只有系统 Python、没有项目 venv 的部署
    驱动机上也能跑：走包 import 会连带装入 yaml/dotenv 等第三方依赖，故
    直接装载这个刻意保持 stdlib 自包含的模块（合成名
    ``quickquip_preset_drift``，与包内真身是同一源文件的两个模块对象；
    指纹实现仍然只有一份）。
    """
    module_path = PROJECT_ROOT / "src" / "quickquip" / "llm" / "skills" / "preset_drift.py"
    spec = importlib.util.spec_from_file_location("quickquip_preset_drift", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法装载 {module_path}")
    module = importlib.util.module_from_spec(spec)
    # exec_module 期间 dataclass 处理会按 __module__ 回查 sys.modules，
    # 不预先注册会让 @dataclass 装饰器拿不到模块命名空间。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SyncState(StrEnum):
    CURRENT = "current"
    DIVERGED = "diverged"
    MISSING = "missing"
    CONFLICT = "conflict"


_STATE_LABELS: dict[SyncState, str] = {
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


def _classify(skills_dir: Path, example_dir: Path) -> list[PresetSkillRow]:
    drift_names = {
        item.name for item in _preset_drift().detect_preset_drift(skills_dir, example_dir)
    }
    rows = []
    for name in _preset_drift().preset_skill_names(example_dir):
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


def _local_only_names(skills_dir: Path, preset_names: set[str]) -> list[str]:
    """skills/ 下非预置、非本工具备份容器的本地 Skill 名（播报用）。"""
    if not skills_dir.is_dir():
        return []
    return sorted(
        child.name
        for child in skills_dir.iterdir()
        if not child.is_symlink()
        and child.is_dir()
        and child.name not in preset_names
        and child.name != BACKUP_CONTAINER_NAME
    )


def _unique_backup_path(skills_dir: Path, name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    container = skills_dir / BACKUP_CONTAINER_NAME
    candidate = container / f"{name}{BACKUP_NAME_INFIX}{stamp}"
    suffix = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = container / f"{name}{BACKUP_NAME_INFIX}{stamp}-{suffix}"
        suffix += 1
    return candidate


def _apply(
    rows: list[PresetSkillRow], skills_dir: Path, example_dir: Path
) -> tuple[list[SyncOutcome], list[str]]:
    """执行同步，返回（成功项, 失败描述列表）。"""
    outcomes: list[SyncOutcome] = []
    failures: list[str] = []
    for row in rows:
        if row.state in (SyncState.CURRENT, SyncState.CONFLICT):
            continue
        source = example_dir / row.name
        target = skills_dir / row.name
        backup: Path | None = None
        renamed = False
        try:
            if row.state is SyncState.DIVERGED:
                backup = _unique_backup_path(skills_dir, row.name)
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
                renamed = True
            shutil.copytree(source, target)
        except OSError as exc:
            if renamed:
                # 备份改名成功、拷贝中途失败：清掉半成品并回滚本地原副本；
                # 回滚自身也可能失败，原副本至少保留在备份路径。
                assert backup is not None  # renamed=True 只在 backup 赋值之后成立
                try:
                    if target.exists():
                        shutil.rmtree(target)
                    backup.rename(target)
                except OSError as rollback_exc:
                    failures.append(
                        f"{row.name}：回滚失败，原副本保留在 {backup}（{rollback_exc}）"
                    )
            elif row.state is SyncState.MISSING and target.exists():
                # missing 分支拷贝中途失败：目标是本次新建的半成品，直接清理；
                # diverged 分支改名失败时 target 是部署者原副本，绝不触碰。
                shutil.rmtree(target, ignore_errors=True)
            failures.append(f"{row.name}：{exc.strerror or exc}")
            continue
        outcomes.append(SyncOutcome(name=row.name, backup=backup))
    return outcomes, failures


def main() -> int:
    # Windows 控制台默认代码页（如 cp1252）无法编码中文输出：统一重配为
    # UTF-8 并以替换符兜底。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只报告，不写入（默认）")
    mode.add_argument(
        "--apply", action="store_true", help="执行同步：安装缺失项、覆盖更新分叉项（留备份）"
    )
    parser.add_argument("--skills-dir", type=Path, default=SKILLS_DIR, help=argparse.SUPPRESS)
    parser.add_argument(
        "--example-dir", type=Path, default=SKILLS_EXAMPLE_DIR, help=argparse.SUPPRESS
    )
    args = parser.parse_args()

    skills_dir: Path = args.skills_dir
    example_dir: Path = args.example_dir
    if not example_dir.is_dir():
        print(f"预置目录不存在：{example_dir}（pip 安装形态无此目录，无需同步）", file=sys.stderr)
        return 2

    rows = _classify(skills_dir, example_dir)
    counts = {state: sum(1 for row in rows if row.state is state) for state in SyncState}
    print(f"预置 Skill 状态（{skills_dir} ↔ {example_dir}）：")
    for row in rows:
        print(f"  {row.state.value:<9} {row.name}（{_STATE_LABELS[row.state]}）")

    local_only = _local_only_names(skills_dir, {row.name for row in rows})
    if local_only:
        print(f"另有 {len(local_only)} 个本地 Skill 非预置，不处理：{'、'.join(local_only)}")

    pending = counts[SyncState.MISSING] + counts[SyncState.DIVERGED]
    if counts[SyncState.CONFLICT]:
        print("存在同名冲突项，请先人工处理后再同步。", file=sys.stderr)
        return 2
    if not args.apply:
        if pending:
            print(
                "提示：可运行 python scripts/sync_preset_skills.py --apply "
                "安装缺失项、更新分叉项（原副本自动备份）；暂不更新不影响使用。"
            )
            return 1
        print("全部一致，无需同步。")
        return 0

    if not pending:
        print("全部一致，无需同步。")
        return 0
    outcomes, failures = _apply(rows, skills_dir, example_dir)
    for outcome in outcomes:
        if outcome.backup is not None:
            print(f"  {outcome.name}: 已备份到 {outcome.backup} 并安装预置副本")
        else:
            print(f"  {outcome.name}: 已安装预置副本")
    if failures:
        print(f"同步失败 {len(failures)} 项：", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 2
    print(
        f"同步完成：{pending} 项已对齐预置副本，"
        f"{counts[SyncState.CURRENT]} 项原本一致。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
