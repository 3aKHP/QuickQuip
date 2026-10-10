"""Skill 导入 stash：inspect 载荷落盘、TTL 惰性清理、confirm 取回与删除。

两阶段安装的中间态载体：inspect 把归一化后的载荷落到
``<stash_dir>/<token>/tree/`` 并写 ``meta.json``（kind/source_url/
created_at）；confirm 凭 token 取回，成功后删除。token 目录 TTL 30 分钟，
每次 stash 写入时惰性清理过期项（无后台线程）。本模块刻意不认识
``skill_import.IngestEntry``（避免环形依赖），条目按 ``path``/``data``
属性协议读写。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Iterable, Protocol

from fastapi import HTTPException

from quickquip.llm.skills.catalog import assert_safe_relative_path

STASH_TTL_SECONDS = 30 * 60

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class StashEntryLike(Protocol):
    """stash 读写条目的最小结构（``skill_import.IngestEntry`` 天然满足）。"""

    path: str
    data: bytes


def _stash_created(stash_dir: Path) -> float:
    meta_path = stash_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        created = meta.get("created_at")
        if isinstance(created, (int, float)):
            return float(created)
    except (OSError, ValueError):
        pass
    try:
        return stash_dir.stat().st_mtime
    except OSError:
        return 0.0


def cleanup_stash(base: Path, *, now: float | None = None) -> None:
    """惰性清理过期 stash（TTL 30 分钟）；目录缺失/单删失败均不向上抛。"""
    if not base.is_dir():
        return
    cutoff = (now if now is not None else time.time()) - STASH_TTL_SECONDS
    try:
        children = list(base.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir() or not _TOKEN_RE.fullmatch(child.name):
            continue
        if _stash_created(child) < cutoff:
            shutil.rmtree(child, ignore_errors=True)


def stash_payload(
    base: Path,
    entries: Iterable[StashEntryLike],
    *,
    kind: str,
    source_url: str = "",
) -> str:
    """把原始载荷落 ``<base>/<token>/tree/`` 并写 meta.json，返回 token。"""
    cleanup_stash(base)
    token = secrets.token_urlsafe(16)
    stash_dir = base / token
    tree = stash_dir / "tree"
    tree.mkdir(parents=True)
    for entry in entries:
        # 摄取侧已逐项校验；落盘前复检防回归。
        assert_safe_relative_path(entry.path)
        target = tree.joinpath(*entry.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.data)
    meta = {"kind": kind, "source_url": source_url, "created_at": time.time()}
    (stash_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return token


def load_stash_entries(base: Path, token: str) -> list[tuple[str, bytes]]:
    """取回 stash 载荷（``(相对路径, 字节)`` 列表）；token 形态非法、
    不存在或过期一律 404。"""
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=404, detail="import session not found or expired")
    stash_dir = base / token
    if not stash_dir.is_dir():
        raise HTTPException(status_code=404, detail="import session not found or expired")
    if time.time() - _stash_created(stash_dir) > STASH_TTL_SECONDS:
        shutil.rmtree(stash_dir, ignore_errors=True)
        raise HTTPException(status_code=404, detail="import session expired")
    tree = stash_dir / "tree"
    entries: list[tuple[str, bytes]] = []
    for directory, dirnames, filenames in os.walk(tree):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            entries.append((absolute.relative_to(tree).as_posix(), absolute.read_bytes()))
    return entries


def drop_stash(base: Path, token: str) -> None:
    if _TOKEN_RE.fullmatch(token):
        shutil.rmtree(base / token, ignore_errors=True)
