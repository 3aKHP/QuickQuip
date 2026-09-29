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

核心逻辑在包内 quickquip.llm.skills.preset_sync（stdlib 自包含，供
Web Admin 后端复用），本脚本只承载 CLI 呈现，按文件路径装载该实现。

用法：
    python scripts/sync_preset_skills.py            # 只报告
    python scripts/sync_preset_skills.py --check    # 只报告（部署脚本用）
    python scripts/sync_preset_skills.py --apply    # 执行同步（留备份）
"""
from __future__ import annotations

import argparse
import functools
import importlib.util

# 本脚本不直接调用 shutil：保留该属性作为测试 patch 点（patch 全局 shutil
# 模块对象的 copytree/rmtree 即对 preset_sync 生效）。
import shutil  # noqa: F401
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 默认目录与 quickquip.common.paths 的 SKILLS_DIR / SKILLS_EXAMPLE_DIR 一致。
# 本工具刻意不 import 包（避免连带 yaml/dotenv 等第三方依赖，保证无项目
# venv 的部署驱动机可跑），路径规则在此保留一份带注释的副本。
SKILLS_DIR = PROJECT_ROOT / "skills"
SKILLS_EXAMPLE_DIR = PROJECT_ROOT / "skills.example"

_PACKAGE_DIR = PROJECT_ROOT / "src" / "quickquip" / "llm" / "skills"


def _register_parent_stubs() -> None:
    """为路径装载的模块预注册合成父包，使包内 import 形式可解析。

    只登记 sys.modules 中缺失的层级（同进程已 import 真实包时不得覆盖）；
    stub 是仅携带 ``__path__``（指向真实目录）的空 ModuleType，不执行任何
    包初始化，因此不会连带装入第三方依赖。
    """
    chain = (
        ("quickquip", PROJECT_ROOT / "src" / "quickquip"),
        ("quickquip.llm", PROJECT_ROOT / "src" / "quickquip" / "llm"),
        ("quickquip.llm.skills", _PACKAGE_DIR),
    )
    for name, path in chain:
        if name in sys.modules:
            continue
        stub = ModuleType(name)
        stub.__path__ = [str(path)]
        sys.modules[name] = stub


def _load_packaged_module(module_name: str, filename: str):
    """按文件路径装载包内 stdlib 自包含模块（与包内真身同一源文件）。

    本脚本是主机侧运维工具，要求在只有系统 Python、没有项目 venv 的部署
    驱动机上也能跑：走包 import 会连带装入 yaml/dotenv 等第三方依赖，故
    直接装载刻意保持 stdlib 自包含的源文件。同进程已存在同名模块时直接
    复用（如 pytest 内真实包已 import），避免同一源文件的两个类对象并存。
    """
    _register_parent_stubs()
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    module_path = _PACKAGE_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法装载 {module_path}")
    module = importlib.util.module_from_spec(spec)
    # exec_module 期间 dataclass 处理会按 __module__ 回查 sys.modules，
    # 不预先注册会让 @dataclass 装饰器拿不到模块命名空间。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@functools.cache
def _preset_sync():
    """依次装载 preset_drift 与 preset_sync（后者 import 前者；延迟到首次使用）。"""
    _load_packaged_module("quickquip.llm.skills.preset_drift", "preset_drift.py")
    return _load_packaged_module("quickquip.llm.skills.preset_sync", "preset_sync.py")


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

    sync = _preset_sync()
    state_labels = {
        sync.SyncState.CURRENT: "已安装，与预置副本一致",
        sync.SyncState.DIVERGED: "已安装，与预置副本不同",
        sync.SyncState.MISSING: "未安装",
        sync.SyncState.CONFLICT: "存在同名非目录项，需人工处理",
    }

    rows = sync.classify_presets(skills_dir, example_dir)
    counts = {state: sum(1 for row in rows if row.state is state) for state in sync.SyncState}
    print(f"预置 Skill 状态（{skills_dir} ↔ {example_dir}）：")
    for row in rows:
        print(f"  {row.state.value:<9} {row.name}（{state_labels[row.state]}）")

    local_only = sync.local_only_names(skills_dir, {row.name for row in rows})
    if local_only:
        print(f"另有 {len(local_only)} 个本地 Skill 非预置，不处理：{'、'.join(local_only)}")

    pending = counts[sync.SyncState.MISSING] + counts[sync.SyncState.DIVERGED]
    if counts[sync.SyncState.CONFLICT]:
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
    outcomes, failures = sync.apply_presets(rows, skills_dir, example_dir)
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
        f"{counts[sync.SyncState.CURRENT]} 项原本一致。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
