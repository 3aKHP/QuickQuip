"""Skill 安装摄取管线：zip/文件夹清单归一、护栏、候选发现、stash 与 GitHub 下载。

承载 ``routes/skills.py`` 安装端点（``/skills/import/*``）的全部摄取逻辑，
路由层保持薄。两阶段交互：inspect 归一化载荷、跑护栏与候选验收报告后把
载荷落 stash（TTL 30 分钟，每次 inspect 惰性清理）；confirm 从 stash 取回，
以 frontmatter ``name`` 建目标目录原子安装（W2：第三方原目录名不参与校验）。

护栏与运行时扫描共用 ``parse_skill_markdown`` 作安装准入；路径一律过
``assert_safe_relative_path``；zip 拒符号链接（external_attr 高位 unix
mode）与绝对路径条目。GitHub 只放行 github.com/codeload.github.com，
经 codeload 下载 zip（``HEAD`` 免 API 查默认分支），流式硬上限 32MiB。
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from quickquip.llm.skills import preset_sync
from quickquip.llm.skills.catalog import SKILL_FILE_NAME, assert_safe_relative_path
from quickquip.llm.skills.parser import parse_skill_markdown

logger = logging.getLogger(__name__)

# 摄取护栏：条目数、解压总量与单文件上限（超限一律 422）。
MAX_IMPORT_ENTRIES = 500
MAX_IMPORT_TOTAL_BYTES = 32 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 1024 * 1024

STASH_TTL_SECONDS = 30 * 60

_GITHUB_TIMEOUT_SECONDS = 20.0
_GITHUB_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class IngestEntry:
    """归一化后的一个载荷文件（skill 相对 POSIX 路径 + 字节内容）。"""

    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class GithubTarget:
    """GitHub 导入目标；``ref`` 为空表示默认分支（下载时用 HEAD）。"""

    owner: str
    repo: str
    ref: str = ""
    subpath: str = ""


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


# ── 摄取：zip / 文件夹清单归一 ────────────────────────────────────


def ingest_zip(archive_b64: str) -> list[IngestEntry]:
    """base64 zip 载荷归一化为条目列表，逐项过护栏。"""
    try:
        data = base64.b64decode(archive_b64, validate=True)
    except (binascii.Error, ValueError):
        raise _unprocessable("archive_b64 is not valid base64") from None
    return ingest_zip_bytes(data)


def ingest_zip_bytes(data: bytes, *, scope: str = "") -> list[IngestEntry]:
    """zip 字节载荷归一化为条目列表，逐项过护栏。

    ``scope`` 非空时（GitHub ``/tree/<ref>/<subpath>`` 导入）只保留顶层目录
    下 subpath 子树内的条目：树外条目直接丢弃，不做校验、不计入条目数与
    总量上限——monorepo 里挑单个 Skill 时，整仓规模不应触发摄取护栏。
    保留的条目维持归档内相对路径（候选根与 confirm 语义不变）。
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
            if info.file_size > MAX_IMPORT_FILE_BYTES:
                raise _unprocessable(
                    f"archive entry exceeds the {MAX_IMPORT_FILE_BYTES}-byte per-file limit: {name}"
                )
            try:
                content = archive.read(info)
            except (zipfile.BadZipFile, RuntimeError) as exc:
                # CRC 校验失败或加密条目：统一按无法解出的载荷拒绝。
                raise _unprocessable(f"archive entry cannot be extracted: {name}") from exc
            if len(content) > MAX_IMPORT_FILE_BYTES:
                raise _unprocessable(
                    f"archive entry exceeds the {MAX_IMPORT_FILE_BYTES}-byte per-file limit: {name}"
                )
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
            raise _unprocessable(
                f"folder entry exceeds the {MAX_IMPORT_FILE_BYTES}-byte per-file limit: {relpath}"
            )
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise _unprocessable(f"folder entry is not valid base64: {relpath}") from None
        if len(data) > MAX_IMPORT_FILE_BYTES:
            raise _unprocessable(
                f"folder entry exceeds the {MAX_IMPORT_FILE_BYTES}-byte per-file limit: {relpath}"
            )
        total_bytes += len(data)
        if total_bytes > MAX_IMPORT_TOTAL_BYTES:
            raise _unprocessable(
                f"folder manifest expands beyond the {MAX_IMPORT_TOTAL_BYTES}-byte total limit"
            )
        entries.append(IngestEntry(path=relpath, data=data))
    return entries


# ── 候选发现 ─────────────────────────────────────────────────────


def discover_candidates(entries: list[IngestEntry], catalog_dir: Path) -> list[dict]:
    """所有以 SKILL.md 结尾的条目，其所在目录即候选根（``""`` = 载荷根）。

    每候选跑 ``parse_skill_markdown``（不传 expected_name：第三方原目录名
    不参与校验，安装时以 frontmatter name 建目录）产出验收报告；
    ``conflict`` 表示生效目录已存在同名 skill。
    """
    roots = sorted({
        entry.path[: -len(SKILL_FILE_NAME)].rstrip("/")
        for entry in entries
        if entry.path == SKILL_FILE_NAME or entry.path.endswith(f"/{SKILL_FILE_NAME}")
    })
    candidates: list[dict] = []
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
        diagnostics: list[dict] = []
        try:
            raw = skill_entry.data
            if raw.startswith(_UTF8_BOM):
                raw = raw[len(_UTF8_BOM):]
            content = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            diagnostics.append({"kind": "invalid-utf8", "message": "SKILL.md is not valid UTF-8"})
        else:
            parsed = parse_skill_markdown(content)
            diagnostics.extend(
                {"kind": diagnostic.kind, "message": diagnostic.message}
                for diagnostic in parsed.diagnostics
            )
            if parsed.ok and parsed.metadata is not None:
                ok = True
                name = parsed.metadata.name
                description = parsed.metadata.description
        conflict = False
        if name:
            target = catalog_dir / name
            conflict = os.path.lexists(target)
        candidates.append({
            "root": root,
            "ok": ok,
            "name": name,
            "description": description,
            "has_scripts": bool(script_files),
            "script_files": script_files,
            "file_count": len(members),
            "total_bytes": sum(len(entry.data) for entry in members),
            "diagnostics": diagnostics,
            "conflict": conflict,
        })
    return candidates


# ── stash：inspect 落盘、confirm 取回 ──────────────────────────────


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


def stash_payload(base: Path, entries: list[IngestEntry], meta: dict) -> str:
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
    meta_path = stash_dir / "meta.json"
    meta_path.write_text(
        json.dumps({**meta, "created_at": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    return token


def load_stash_entries(base: Path, token: str) -> list[IngestEntry]:
    """取回 stash 载荷；token 形态非法、不存在或过期一律 404。"""
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=404, detail="import session not found or expired")
    stash_dir = base / token
    if not stash_dir.is_dir():
        raise HTTPException(status_code=404, detail="import session not found or expired")
    if time.time() - _stash_created(stash_dir) > STASH_TTL_SECONDS:
        shutil.rmtree(stash_dir, ignore_errors=True)
        raise HTTPException(status_code=404, detail="import session expired")
    tree = stash_dir / "tree"
    entries: list[IngestEntry] = []
    for directory, dirnames, filenames in os.walk(tree):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            entries.append(
                IngestEntry(
                    path=absolute.relative_to(tree).as_posix(),
                    data=absolute.read_bytes(),
                )
            )
    return entries


def drop_stash(base: Path, token: str) -> None:
    if _TOKEN_RE.fullmatch(token):
        shutil.rmtree(base / token, ignore_errors=True)


# ── confirm：从 stash 原子安装 ─────────────────────────────────────


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
    ``unique_backup_path``。安装走临时目录 + rename 原子落盘，失败时
    清理半成品并回滚旧副本。成功后删除 stash。
    """
    entries = load_stash_entries(base, token)
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
    try:
        raw = skill_entry.data
        if raw.startswith(_UTF8_BOM):
            raw = raw[len(_UTF8_BOM):]
        content = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise _unprocessable("SKILL.md under the selected root is not valid UTF-8") from None
    parsed = parse_skill_markdown(content)
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
    target = catalog_dir / name
    backup: Path | None = None
    if os.path.lexists(target):
        if not overwrite:
            raise HTTPException(status_code=409, detail=f"skill '{name}' already exists")
        backup = preset_sync.unique_backup_path(catalog_dir, name)
        backup.parent.mkdir(parents=True, exist_ok=True)
        target.rename(backup)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=catalog_dir))
    try:
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
    drop_stash(base, token)
    return name, backup


# ── GitHub 导入 ───────────────────────────────────────────────────


def parse_github_url(url: str) -> GithubTarget:
    """解析 ``https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]]``。

    各段必须匹配 ``^[A-Za-z0-9_.-]+$``；``/blob/`` 形态拒绝并引导改用
    仓库或目录链接。非 github.com 域名一律 422。
    """
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.hostname not in _GITHUB_HOSTS:
        raise _unprocessable(
            "only https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]] URLs are supported"
        )
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        raise _unprocessable("github URL must include owner and repository")
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    ref = ""
    subpath = ""
    rest = segments[2:]
    if rest:
        marker = rest[0]
        if marker == "blob":
            raise _unprocessable(
                "blob URLs point to a single file; use the repository or tree URL instead"
            )
        if marker != "tree" or len(rest) < 2:
            raise _unprocessable(
                "unsupported github URL; use https://github.com/<owner>/<repo>[/tree/<ref>[/<subpath>]]"
            )
        ref = rest[1]
        subpath = "/".join(rest[2:])
    check_segments = [owner, repo]
    if rest:
        check_segments.extend(rest[1:])
    for segment in check_segments:
        if not _GITHUB_SEGMENT_RE.fullmatch(segment):
            raise _unprocessable(f"github URL contains an invalid segment: {segment}")
    return GithubTarget(owner=owner, repo=repo, ref=ref, subpath=subpath)


def download_github_zip(target: GithubTarget) -> bytes:
    """经 codeload.github.com 下载仓库 zip（流式硬上限 32MiB，超时 20s）。

    只放行构造出的 codeload URL（段已校验、不跟随重定向，宿主机不会被
    诱导访问其他域名）。失败文案区分网络不可达/仓库不存在/超限。
    """
    ref = target.ref or "HEAD"
    url = f"https://codeload.github.com/{target.owner}/{target.repo}/zip/{ref}"
    try:
        with httpx.Client(timeout=_GITHUB_TIMEOUT_SECONDS, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    raise HTTPException(
                        status_code=502,
                        detail="unexpected redirect from github; refusing to follow",
                    )
                if response.status_code == 404:
                    raise HTTPException(
                        status_code=502,
                        detail="repository or ref not found on github.com "
                        "(private repositories are not supported)",
                    )
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"github download failed with status {response.status_code}",
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_IMPORT_TOTAL_BYTES:
                        raise _unprocessable(
                            f"repository archive exceeds the "
                            f"{MAX_IMPORT_TOTAL_BYTES}-byte download limit"
                        )
                    chunks.append(chunk)
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=502,
            detail="timed out reaching github.com; check outbound network "
            "connectivity from the deployment host",
        ) from None
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="cannot reach github.com; check outbound network "
            "connectivity from the deployment host",
        ) from None
    return b"".join(chunks)
