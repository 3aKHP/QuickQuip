# -*- coding: utf-8 -*-
"""预置 Skill 同步工具：检视并对齐 skills/ 与 skills.example/。

预置 Skill 经手动复制到达 skills/，版本升级后本地副本不会自动更新。本工具
对每个预置 Skill 报告三态：

    current   已安装且与当前版本预置副本逐字节一致
    diverged  已安装但与预置副本不同（升级后的陈旧副本或本地定制）
    missing   未安装

默认（或 --check）只报告不写入，有 missing/diverged 时退出码 1；
--apply 执行同步：missing 直接安装，diverged 先把本地副本整体改名为
<name>.preset-backup-<时间戳> 再安装预置副本（本地定制不丢，确认后自行
清理备份）。bot 每轮请求现扫 skills/，同步当轮生效，无需重启。

用法：
    python scripts/sync_preset_skills.py            # 只报告
    python scripts/sync_preset_skills.py --check    # 只报告（部署脚本用）
    python scripts/sync_preset_skills.py --apply    # 执行同步（留备份）
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_preset_drift_module():
    """按文件路径装载运行时同一份 preset_drift 实现。

    本脚本是主机侧运维工具，要求在只有系统 Python、没有项目 venv 的部署
    驱动机上也能跑：走包 import 会连带装入 yaml/dotenv 等第三方依赖，故
    直接装载这个刻意保持 stdlib 自包含的模块（指纹实现仍然只有一份）。
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


_preset_drift = _load_preset_drift_module()

_STATE_LABELS = {
    "current": "已安装，与预置副本一致",
    "diverged": "已安装，与预置副本不同",
    "missing": "未安装",
    "conflict": "存在同名非目录项，需人工处理",
}


def _preset_names(example_dir: Path) -> list[str]:
    return sorted(
        child.name
        for child in example_dir.iterdir()
        if not child.is_symlink() and child.is_dir()
    )


def _classify(skills_dir: Path, example_dir: Path) -> list[tuple[str, str]]:
    drift_names = {
        item.name for item in _preset_drift.detect_preset_drift(skills_dir, example_dir)
    }
    rows = []
    for name in _preset_names(example_dir):
        installed = skills_dir / name
        if installed.is_symlink() or (installed.exists() and not installed.is_dir()):
            state = "conflict"
        elif not installed.is_dir():
            state = "missing"
        elif name in drift_names:
            state = "diverged"
        else:
            state = "current"
        rows.append((name, state))
    return rows


def _unique_backup_path(skills_dir: Path, name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = skills_dir / f"{name}.preset-backup-{stamp}"
    suffix = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = skills_dir / f"{name}.preset-backup-{stamp}-{suffix}"
        suffix += 1
    return candidate


def _apply(rows: list[tuple[str, str]], skills_dir: Path, example_dir: Path) -> list[str]:
    """执行同步，返回失败描述列表（空 = 全部成功）。"""
    failures: list[str] = []
    for name, state in rows:
        if state in ("current", "conflict"):
            continue
        source = example_dir / name
        target = skills_dir / name
        backup: Path | None = None
        try:
            if state == "diverged":
                backup = _unique_backup_path(skills_dir, name)
                target.rename(backup)
            shutil.copytree(source, target)
        except OSError as exc:
            # 覆盖更新中途失败：清掉半成品并回滚本地原副本。
            if backup is not None:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup.exists() and not target.exists():
                    backup.rename(target)
            failures.append(f"{name}：{exc.strerror or exc}")
            continue
        if backup is not None:
            print(f"  {name}: 已备份到 {backup} 并安装预置副本")
        else:
            print(f"  {name}: 已安装预置副本")
    return failures


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
    parser.add_argument(
        "--skills-dir", type=Path, default=PROJECT_ROOT / "skills", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--example-dir",
        type=Path,
        default=PROJECT_ROOT / "skills.example",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    skills_dir: Path = args.skills_dir
    example_dir: Path = args.example_dir
    if not example_dir.is_dir():
        print(f"预置目录不存在：{example_dir}（pip 安装形态无此目录，无需同步）", file=sys.stderr)
        return 2

    rows = _classify(skills_dir, example_dir)
    counts = {state: sum(1 for _, s in rows if s == state) for state in _STATE_LABELS}
    print(f"预置 Skill 状态（{skills_dir} ↔ {example_dir}）：")
    for name, state in rows:
        print(f"  {state:<9} {name}（{_STATE_LABELS[state]}）")

    installed_names = {name for name, _ in rows}
    local_only = (
        sorted(
            child.name
            for child in skills_dir.iterdir()
            if not child.is_symlink()
            and child.is_dir()
            and child.name not in installed_names
            and ".preset-backup-" not in child.name  # 本工具留下的备份不播报
        )
        if skills_dir.is_dir()
        else []
    )
    if local_only:
        print(f"另有 {len(local_only)} 个本地 Skill 非预置，不处理：{'、'.join(local_only)}")

    pending = counts["missing"] + counts["diverged"]
    if counts["conflict"]:
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
    failures = _apply(rows, skills_dir, example_dir)
    if failures:
        print(f"同步失败 {len(failures)} 项：", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 2
    print(f"同步完成：{pending} 项已对齐预置副本，{counts['current']} 项原本一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
