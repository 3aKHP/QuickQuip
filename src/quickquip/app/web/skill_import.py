"""Skill 安装摄取管线：zip/文件夹清单归一、摄取护栏、候选发现与安装落盘。

承载 ``routes/skills.py`` 安装端点（``/skills/import/*``）的核心摄取逻辑，
路由层保持薄；stash 存取在 ``skill_import_stash``，GitHub URL 解析与下载在
``skill_import_github``。安装准入与运行时扫描共用 ``parse_skill_bytes``
（W2）；confirm 以 frontmatter ``name`` 建目标目录原子安装，第三方原目录名
不参与校验。

护栏：条目数 ≤500、解压总量 ≤32MiB、单文件 ≤1MiB；每条目相对路径过
``assert_safe_relative_path``；zip 拒符号链接（external_attr 高位 unix
mode）与绝对路径条目。GitHub 带 subpath 时子树过滤提前到本模块 ingest
阶段，树外条目不触发上述上限（monorepo 挑单个 Skill 不受整仓规模影响）。
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from quickquip.app.web import skill_import_stash
from quickquip.llm.skills import preset_sync
from quickquip.llm.skills.catalog import SKILL_FILE_NAME, assert_safe_relative_path
from quickquip.llm.skills.parser import SkillDiagnostic, parse_skill_bytes

logger = logging.getLogger(__name__)

# 摄取护栏：条目数、解压总量与单文件上限（超限一律 422）。
MAX_IMPORT_ENTRIES = 500
MAX_IMPORT_TOTAL_BYTES = 32 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 1024 * 1024

# 安装暂存目录：catalog 根下的 ``.install-*``（mkdtemp 生成，rename 后消失；
# 崩溃残留按 mtime 判陈旧后在下次安装前惰性清理）。路由列表按此前缀排除。
INSTALL_STAGING_PREFIX = ".install-"
_STALE_STAGING_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class IngestEntry:
    """归一化后的一个载荷文件（归档内相对 POSIX 路径 + 字节内容）。"""

    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    """一个候选 Skill 的验收报告；解析失败时 name/description 为 None。"""

    root: str
    ok: bool
    name: str | None
    description: str | None
    has_scripts: bool
    script_files: list[str]
    file_count: int
    total_bytes: int
    diagnostics: list[SkillDiagnostic]
    conflict: bool


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


class IngestLimitError(HTTPException):
    """摄取条目数/总量上限触发的 422。

    单独成类是为了让 GitHub inspect 路由识别「仓库整体超限」这一形态：
    URL 不带 subpath 时在 detail 上追加「用 /tree/<ref>/<subdir> 定位单个
    子目录」的引导文案；其余 422（坏 zip、危险条目等）不追加。
    """


def _safe_entry_path(path: str, *, what: str) -> None:
    try:
        assert_safe_relative_path(path)
    except ValueError:
        raise _unprocessable(f"{what} path is not a safe relative path: {path}") from None


def _check_file_size(path: str, size: int, *, what: str) -> None:
    if size > MAX_IMPORT_FILE_BYTES:
        raise _unprocessable(
            f"{what} entry exceeds the {MAX_IMPORT_FILE_BYTES}-byte per-file limit: {path}"
        )


# ── 摄取：zip / 文件夹清单归一 ────────────────────────────────────


def decode_zip_b64(archive_b64: str) -> bytes:
    """base64 → zip 字节；非法 base64 → 422。大小上限由路由层判定。"""
    try:
        return base64.b64decode(archive_b64, validate=True)
    except (binascii.Error, ValueError):
        raise _unprocessable("archive_b64 is not valid base64") from None


def ingest_zip_bytes(data: bytes, *, scope: str = "") -> list[IngestEntry]:
    """zip 字节载荷归一化为条目列表，逐项过护栏。

    ``scope`` 非空时（GitHub ``/tree/<ref>/<subpath>`` 导入）只保留顶层目录
    下 subpath 子树内的条目：树外条目直接丢弃，不做校验、不计入条目数与
    总量上限。保留的条目维持归档内相对路径（候选根与 confirm 语义不变）。
    """
    scope_parts = scope.split("/") if scope else []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _unprocessable("payload is not a valid zip archive") from None
    entries: list[IngestEntry] = []
    total_bytes = 0
    kept = 0
    with archive:
        for info in archive.infolist():
            name = info.filename
            if scope_parts:
                # 顶层目录名（<repo>-<ref>）不参与匹配，按段比对子树归属。
                parts = name.rstrip("/").split("/")
                if parts[1 : 1 + len(scope_parts)] != scope_parts:
                    continue
            kept += 1
            if kept > MAX_IMPORT_ENTRIES:
                raise IngestLimitError(
                    status_code=422,
                    detail=f"archive has more than {MAX_IMPORT_ENTRIES} entries",
                )
            # unix mode 存在 external_attr 高 16 位；符号链接条目一律拒绝。
            if stat.S_ISLNK(info.external_attr >> 16):
                raise _unprocessable(f"archive entry is a symbolic link: {name}")
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                raise _unprocessable(f"archive entry uses an absolute path: {name}")
            if info.is_dir():
                stripped = name.rstrip("/")
                if stripped:
                    _safe_entry_path(stripped, what="archive entry")
                continue
            _safe_entry_path(name, what="archive entry")
            _check_file_size(name, info.file_size, what="archive")
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, RuntimeError) as exc:
                # CRC 校验失败或加密条目：统一按无法解出的载荷拒绝。
                raise _unprocessable(f"archive entry cannot be extracted: {name}") from exc
            _check_file_size(name, len(content), what="archive")
            total_bytes += len(content)
            if total_bytes > MAX_IMPORT_TOTAL_BYTES:
                raise IngestLimitError(
                    status_code=422,
                    detail=f"archive expands beyond the {MAX_IMPORT_TOTAL_BYTES}-byte total limit",
                )
            entries.append(IngestEntry(path=name, data=content))
    return entries


def ingest_folder(files: dict[str, str]) -> list[IngestEntry]:
    """``webkitdirectory`` 清单（relpath → base64）归一化为条目列表。"""
    if len(files) > MAX_IMPORT_ENTRIES:
        raise _unprocessable(f"folder manifest has more than {MAX_IMPORT_ENTRIES} files")
    entries: list[IngestEntry] = []
    total_bytes = 0
    for relpath, encoded in files.items():
        _safe_entry_path(relpath, what="folder entry")
        # 解码前先做字符长度粗检，避免超大 base64 字符串先吃掉内存。
        if len(encoded) > MAX_IMPORT_FILE_BYTES * 2:
            _check_file_size(relpath, MAX_IMPORT_FILE_BYTES + 1, what="folder")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise _unprocessable(f"folder entry is not valid base64: {relpath}") from None
        _check_file_size(relpath, len(data), what="folder")
        total_bytes += len(data)
        if total_bytes > MAX_IMPORT_TOTAL_BYTES:
            raise _unprocessable(
                f"folder manifest expands beyond the {MAX_IMPORT_TOTAL_BYTES}-byte total limit"
            )
        entries.append(IngestEntry(path=relpath, data=data))
    return entries


# ── 候选发现 ─────────────────────────────────────────────────────


def discover_candidates(entries: list[IngestEntry], catalog_dir: Path) -> list[ImportCandidate]:
    """所有以 SKILL.md 结尾的条目，其所在目录即候选根（``""`` = 载荷根）。

    每候选跑 ``parse_skill_bytes``（不传 expected_name：第三方原目录名
    不参与校验，安装时以 frontmatter name 建目录）产出验收报告；
    ``conflict`` 表示生效目录已存在同名 skill。
    """
    roots = sorted({
        entry.path[: -len(SKILL_FILE_NAME)].rstrip("/")
        for entry in entries
        if entry.path == SKILL_FILE_NAME or entry.path.endswith(f"/{SKILL_FILE_NAME}")
    })
    candidates: list[ImportCandidate] = []
    for root in roots:
        prefix = f"{root}/" if root else ""
        members = [entry for entry in entries if entry.path.startswith(prefix)]
        script_files = sorted(
            entry.path[len(prefix):]
            for entry in members
            if entry.path[len(prefix):].split("/")[0] == "scripts"
        )
        skill_entry = next(
            (entry for entry in members if entry.path == f"{prefix}{SKILL_FILE_NAME}"),
            None,
        )
        assert skill_entry is not None  # root 由 SKILL.md 条目派生，必然存在
        ok = False
        name: str | None = None
        description: str | None = None
        parsed = parse_skill_bytes(skill_entry.data)
        if parsed.ok and parsed.metadata is not None:
            ok = True
            name = parsed.metadata.name
            description = parsed.metadata.description
        conflict = False
        if name:
            conflict = os.path.lexists(catalog_dir / name)
        candidates.append(
            ImportCandidate(
                root=root,
                ok=ok,
                name=name,
                description=description,
                has_scripts=bool(script_files),
                script_files=script_files,
                file_count=len(members),
                total_bytes=sum(len(entry.data) for entry in members),
                diagnostics=list(parsed.diagnostics),
                conflict=conflict,
            )
        )
    return candidates


# ── confirm：从 stash 原子安装 ─────────────────────────────────────


def cleanup_stale_staging(catalog_dir: Path, *, now: float | None = None) -> None:
    """清掉 catalog 根下残留的安装暂存目录（中断遗物；按 mtime 判陈旧，
    避免误删并发安装正在使用的暂存目录）。"""
    try:
        children = list(catalog_dir.iterdir())
    except OSError:
        return
    cutoff = (now if now is not None else time.time()) - _STALE_STAGING_SECONDS
    for child in children:
        if not child.name.startswith(INSTALL_STAGING_PREFIX) or not child.is_dir():
            continue
        try:
            stale = child.stat().st_mtime < cutoff
        except OSError:
            continue
        if stale:
            shutil.rmtree(child, ignore_errors=True)


def install_from_stash(
    base: Path,
    token: str,
    root: str,
    catalog_dir: Path,
    *,
    overwrite: bool = False,
) -> tuple[str, Path | None]:
    """以候选根 frontmatter ``name`` 建目标目录安装，返回 ``(name, backup)``。

    同名已存在且未 overwrite → 409；overwrite 先把旧目录整体改名到
    ``unique_backup_path``。安装走临时目录 + rename 原子落盘：暂存目录
    先于 backup 改名创建，任何失败统一回滚（清暂存 + 备份回迁）。成功后
    删除 stash；409 时保留 stash 供 overwrite 重试。
    """
    stored = skill_import_stash.load_stash_entries(base, token)
    entries = [IngestEntry(path=path, data=data) for path, data in stored]
    if root:
        try:
            assert_safe_relative_path(root)
        except ValueError:
            raise _unprocessable(f"invalid candidate root: {root}") from None
    prefix = f"{root}/" if root else ""
    skill_entry = next(
        (entry for entry in entries if entry.path == f"{prefix}{SKILL_FILE_NAME}"),
        None,
    )
    if skill_entry is None:
        raise _unprocessable("no SKILL.md found under the selected root")
    parsed = parse_skill_bytes(skill_entry.data)
    if not parsed.ok or parsed.metadata is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "candidate SKILL.md is invalid",
                "diagnostics": [
                    {"kind": diagnostic.kind, "message": diagnostic.message}
                    for diagnostic in parsed.diagnostics
                ],
            },
        )
    name = parsed.metadata.name
    members = [entry for entry in entries if entry.path.startswith(prefix)]

    catalog_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_staging(catalog_dir)
    target = catalog_dir / name
    staging = Path(tempfile.mkdtemp(prefix=INSTALL_STAGING_PREFIX, dir=catalog_dir))
    backup: Path | None = None
    try:
        if os.path.lexists(target):
            if not overwrite:
                raise HTTPException(status_code=409, detail=f"skill '{name}' already exists")
            backup = preset_sync.unique_backup_path(catalog_dir, name)
            backup.parent.mkdir(parents=True, exist_ok=True)
            target.rename(backup)
        for entry in members:
            relative = entry.path[len(prefix):]
            assert_safe_relative_path(relative)
            destination = staging.joinpath(*relative.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(entry.data)
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and not os.path.lexists(target):
            try:
                backup.rename(target)
            except OSError:
                logger.error("skill install rollback failed, old copy kept at %s", backup)
        raise
    skill_import_stash.drop_stash(base, token)
    return name, backup
