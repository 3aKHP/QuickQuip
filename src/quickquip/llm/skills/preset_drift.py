"""预置 Skill 漂移检测：skills/ 与 skills.example/ 同名目录的字节级比对。

预置 Skill 经部署者手动复制到达 ``skills/``，版本升级后本地副本不会自动
更新（self-docs 的「与部署版本对齐」承诺会在旧副本上静默失效）。本模块
提供只读检测基元：目录内容指纹 + 同名分叉比对。分叉信息只进日志与
``/skill list``，不进 catalog 块与任何模型可见内容，不占 catalog 预算。

本模块刻意保持 stdlib 自包含（不 import 包内任何模块）：主机侧同步脚本
``scripts/sync_preset_skills.py`` 按文件路径直接装载本模块，与运行时共用
同一份实现，在无项目 venv 的部署驱动机上也能运行。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

# 单文件哈希读盘上限：与 catalog.py 的每轮扫描读盘防护同量级。超限文件
# 以标记入行（指纹依旧确定，分叉依旧可检），不做全量读盘——误放进目录的
# 大文件不能让每轮检测同步读盘数百 MB。
_MAX_HASHABLE_FILE_BYTES = 256 * 1024
# 单次指纹遍历的条目上限（与 catalog 资源条数上限同源），超出以标记收尾。
_MAX_FINGERPRINT_ENTRIES = 200


@dataclass(frozen=True, slots=True)
class PresetDrift:
    """一个已安装 Skill 与同版本预置副本的字节级分叉。"""

    name: str
    installed_sha256: str
    preset_sha256: str


def skill_dir_fingerprint(root_dir: Path) -> str:
    """skill 目录的全量内容指纹：所有常规文件的「相对路径 + SHA-256」聚合。

    纯字节比对，不解析、不校验：部署者改动目录内任何文件都改变指纹。
    符号链接与非常规项以标记入行（与同路径常规文件必然不同指纹）；读失败
    与超限文件同样以标记入行，不做全量读盘。空目录不参与指纹（copy 同步
    会按预置侧重建目录结构）。遍历顺序由 os.walk 的排序约束保证确定。
    """
    lines: list[str] = []
    truncated = False
    for directory, dirnames, filenames in os.walk(root_dir, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            if len(lines) >= _MAX_FINGERPRINT_ENTRIES:
                truncated = True
                break
            absolute = Path(directory) / filename
            relative = absolute.relative_to(root_dir).as_posix()
            if absolute.is_symlink():
                lines.append(f"{relative}\0symlink")
                continue
            if not absolute.is_file():
                lines.append(f"{relative}\0not-a-file")
                continue
            try:
                size = absolute.stat().st_size
            except OSError:
                lines.append(f"{relative}\0stat-error")
                continue
            if size > _MAX_HASHABLE_FILE_BYTES:
                lines.append(f"{relative}\0oversized:{size}")
                continue
            try:
                digest = hashlib.sha256(absolute.read_bytes()).hexdigest()
            except OSError:
                lines.append(f"{relative}\0read-error")
                continue
            lines.append(f"{relative}\0{digest}")
        if truncated:
            break
    if truncated:
        lines.append("\0truncated")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def detect_preset_drift(catalog_dir: Path, preset_dir: Path) -> list[PresetDrift]:
    """比对两侧同名 Skill 的目录指纹，返回分叉名单（按 name 字典序）。

    preset_dir 缺失或不可读时 fail-open 返回空（pip 安装形态无此目录）；
    仅存在于单侧的 Skill 不参与——预置件未安装不是运行时要报告的漂移，
    由同步脚本的三态报告覆盖。
    """
    if not preset_dir.is_dir():
        return []
    try:
        preset_names = sorted(
            child.name
            for child in preset_dir.iterdir()
            if not child.is_symlink() and child.is_dir()
        )
    except OSError:
        return []
    drift: list[PresetDrift] = []
    for name in preset_names:
        installed = catalog_dir / name
        if installed.is_symlink() or not installed.is_dir():
            continue
        installed_sha256 = skill_dir_fingerprint(installed)
        preset_sha256 = skill_dir_fingerprint(preset_dir / name)
        if installed_sha256 != preset_sha256:
            drift.append(
                PresetDrift(
                    name=name,
                    installed_sha256=installed_sha256,
                    preset_sha256=preset_sha256,
                )
            )
    return drift
