"""Skill 管理路由：目录 CRUD、预置同步与两阶段安装管线（``/ops/api/skills``）。

生效目录经 ``_effective_catalog_dir()`` 现读 ``config/llm.toml`` 的
``[skills].catalog_dir``（缺失/异常回退默认 ``SKILLS_DIR``），配合运行时
每轮现扫实现天然热部署（W5/W6）。文本资源写入走 FileLock + tmp/replace
原子落盘；锁文件统一在 catalog 根（skill 内容树外，避免被资源扫描编入
清单、被 preset_drift 计入指纹）；全部写操作记审计。固定路径
（``/skills/presets``、``/skills/import/*``）先于 ``/skills/{name}`` 声明，
避免被参数路径吞掉。
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import stat
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from filelock import FileLock
from pydantic import BaseModel, Field, field_validator

from quickquip.app.web import skill_import, skill_import_github, skill_import_stash
from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import CONFIG_LLM_TOML, DATA_DIR, SKILLS_EXAMPLE_DIR
from quickquip.llm.skills import preset_sync
from quickquip.llm.skills.catalog import (
    SKILL_FILE_NAME,
    assert_safe_relative_path,
    load_skill_with_diagnostics,
    read_configured_catalog_dir,
    resolve_catalog_dir,
    resolve_file_in,
)
from quickquip.llm.skills.parser import (
    MAX_SKILL_FILE_BYTES,
    SKILL_NAME_PATTERN,
    parse_skill_markdown,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# 模块级常量作测试 patch 点（personas 先例）；生效目录随请求现算，
# patch ``_effective_catalog_dir`` 即可整体重定向。
_EXAMPLE_DIR = SKILLS_EXAMPLE_DIR
_STASH_DIR = DATA_DIR / "tmp" / "skill-import"
_LLM_CONFIG_PATH = CONFIG_LLM_TOML

# zip 安装包以 base64 字符串承载：pydantic 按字符数卡上限，换算为恰好放行
# 16MiB 解码字节的 b64 长度；解码后的字节数在路由里再显式校验一次。
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_B64_CHARS = math.ceil(_MAX_ARCHIVE_BYTES / 3) * 4
# folder manifest 单值（base64 字符）上限：解码后 ≤1MiB 的粗检口径。
_MAX_FILE_B64_CHARS = 2 * 1024 * 1024


class SkillCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    content: str = Field(max_length=MAX_SKILL_FILE_BYTES)


class SkillFileWriteBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=MAX_SKILL_FILE_BYTES)


class PresetApplyBody(BaseModel):
    names: list[str] | None = None


class ImportInspectBody(BaseModel):
    kind: str = Field(min_length=1, max_length=16)
    archive_b64: str | None = Field(default=None, max_length=_MAX_ARCHIVE_B64_CHARS)
    files: dict[str, str] | None = None

    @field_validator("files")
    @classmethod
    def _files_within_limits(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        # folder manifest 在请求模型层先挡一轮（条数/单值/总长），
        # skill_import.ingest_folder 的逐项检查保留作纵深防御。
        if value is None:
            return value
        if len(value) > skill_import.MAX_IMPORT_ENTRIES:
            raise ValueError(
                f"folder manifest has more than {skill_import.MAX_IMPORT_ENTRIES} files"
            )
        total = 0
        for relpath, encoded in value.items():
            if len(encoded) > _MAX_FILE_B64_CHARS:
                raise ValueError(f"folder entry is too large: {relpath}")
            total += len(encoded)
            if total > _MAX_ARCHIVE_B64_CHARS:
                raise ValueError("folder manifest exceeds the total size limit")
        return value


class GithubInspectBody(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class ImportConfirmBody(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    root: str = ""
    overwrite: bool = False


def _effective_catalog_dir() -> Path:
    """``[skills].catalog_dir`` 的生效目录：tomllib 直读，缺失/异常回退默认。"""
    return resolve_catalog_dir(read_configured_catalog_dir(_LLM_CONFIG_PATH))


def _validate_name(name: str) -> None:
    if not SKILL_NAME_PATTERN.fullmatch(name):
        raise HTTPException(
            status_code=422,
            detail="skill name must match ^[a-z0-9][a-z0-9-]*$",
        )


def _require_skill_dir(name: str) -> Path:
    _validate_name(name)
    skill_dir = _effective_catalog_dir() / name
    if skill_dir.is_symlink() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="skill not found")
    return skill_dir


def _skill_lock(catalog_dir: Path, name: str) -> FileLock:
    """每 skill 一把锁，锁文件放 catalog 根（内容树外）。

    锁文件若落在 skill 目录内会被资源扫描编入清单、被 preset_drift 计入
    指纹（在线编辑过的预置 skill 会永久 diverged）。管理面低并发，粒度够。
    """
    return FileLock(str(catalog_dir / f"{name}.lock"))


def _diagnostics_payload(diagnostics) -> list[dict]:
    return [{"kind": item.kind, "message": item.message} for item in diagnostics]


def _preset_states(catalog_dir: Path) -> dict[str, preset_sync.SyncState]:
    return {
        row.name: row.state
        for row in preset_sync.classify_presets(catalog_dir, _EXAMPLE_DIR)
    }


def _resolve_for_write(skill_dir: Path, relative_path: str) -> Path:
    """写侧路径加固第一步：相对形状校验并拼接落点（包含性校验分离）。"""
    try:
        assert_safe_relative_path(relative_path)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="path is not a safe skill-relative path",
        ) from None
    return skill_dir.joinpath(*relative_path.split("/"))


def _require_contained(skill_dir: Path, path: Path) -> None:
    """``path``（须已存在）的 realpath 必须位于 skill 根内。"""
    real_root = skill_dir.resolve()
    try:
        real = path.resolve(strict=True)
    except OSError:
        raise HTTPException(
            status_code=422,
            detail="path is not contained in the skill directory",
        ) from None
    if real != real_root and real_root not in real.parents:
        raise HTTPException(
            status_code=422,
            detail="path is not contained in the skill directory",
        )


def _check_contained(skill_dir: Path, target: Path) -> None:
    """写盘前复检：target 的父目录（此时已存在）必须真实位于 skill 根内。"""
    _require_contained(skill_dir, target.parent)


def _check_ancestor_contained(skill_dir: Path, target: Path) -> None:
    """mkdir 之前的包含性校验：最深的已存在祖先不得随符号链接逃逸出根。"""
    ancestor = target.parent
    while not os.path.lexists(ancestor):
        ancestor = ancestor.parent
    _require_contained(skill_dir, ancestor)


# ── 固定路径：预置同步与安装管线必须先于 /skills/{name} 声明 ──────────


@router.get("/skills")
def list_skills():
    catalog_dir = _effective_catalog_dir()
    states = _preset_states(catalog_dir)
    items = []
    if catalog_dir.is_dir():
        for child in sorted(catalog_dir.iterdir()):
            if child.is_symlink() or not child.is_dir():
                continue
            # 备份容器与安装暂存目录不是 skill。
            if child.name == preset_sync.BACKUP_CONTAINER_NAME:
                continue
            if child.name.startswith(skill_import.INSTALL_STAGING_PREFIX):
                continue
            loaded, load_diagnostics = load_skill_with_diagnostics(child)
            resource_count, has_scripts, total_bytes = _dir_stats(child)
            state = states.get(child.name)
            items.append({
                "name": child.name,
                "ok": loaded is not None,
                "description": loaded.metadata.description if loaded else "",
                "diagnostics": _diagnostics_payload(load_diagnostics),
                "resource_count": resource_count,
                "has_scripts": has_scripts,
                "total_bytes": total_bytes,
                "mtime": int(child.stat().st_mtime),
                "preset_state": (
                    state.value
                    if state in (preset_sync.SyncState.CURRENT, preset_sync.SyncState.DIVERGED)
                    else None
                ),
            })
    return {"skills": items}


def _dir_stats(skill_dir: Path) -> tuple[int, bool, int]:
    """（资源条数, 是否含 scripts/, 总字节）；SKILL.md 计入总字节不计入条数。"""
    resource_count = 0
    has_scripts = False
    total_bytes = 0
    for directory, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            relative = absolute.relative_to(skill_dir).as_posix()
            if absolute.is_symlink() or not absolute.is_file():
                continue
            try:
                total_bytes += absolute.stat().st_size
            except OSError:
                continue
            if relative == SKILL_FILE_NAME:
                continue
            resource_count += 1
            if relative.split("/")[0] == "scripts":
                has_scripts = True
    return resource_count, has_scripts, total_bytes


@router.post("/skills", status_code=201)
def create_skill(body: SkillCreateBody, request: Request):
    _validate_name(body.name)
    parsed = parse_skill_markdown(body.content, expected_name=body.name)
    if not parsed.ok or parsed.metadata is None:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "invalid SKILL.md content",
                "diagnostics": _diagnostics_payload(parsed.diagnostics),
            },
        )
    catalog_dir = _effective_catalog_dir()
    target = catalog_dir / body.name
    if os.path.lexists(target):
        raise HTTPException(status_code=409, detail="skill already exists")
    # 锁文件在 catalog 根，取锁前必须保证 catalog 目录存在。
    catalog_dir.mkdir(parents=True, exist_ok=True)
    skill_file = target / SKILL_FILE_NAME
    tmp = skill_file.with_name(skill_file.name + ".tmp")
    with _skill_lock(catalog_dir, body.name):
        try:
            target.mkdir()
        except FileExistsError:
            raise HTTPException(status_code=409, detail="skill already exists") from None
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(skill_file)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    logger.warning(
        "skill created via web admin: %s (%d bytes)", body.name, len(body.content)
    )
    audit_logger.log(request, action="create", target_type="skill", target_id=body.name)
    return {"name": body.name}


@router.get("/skills/presets")
def list_presets():
    catalog_dir = _effective_catalog_dir()
    rows = preset_sync.classify_presets(catalog_dir, _EXAMPLE_DIR)
    presets = [
        {
            "name": row.name,
            "state": row.state.value,
            "label": preset_sync.STATE_LABELS[row.state],
        }
        for row in rows
    ]
    local_only = preset_sync.local_only_names(catalog_dir, {row.name for row in rows})
    return {"presets": presets, "local_only": local_only}


@router.post("/skills/presets/apply")
def apply_presets_route(body: PresetApplyBody, request: Request):
    catalog_dir = _effective_catalog_dir()
    rows = preset_sync.classify_presets(catalog_dir, _EXAMPLE_DIR)
    # 空（缺省或空列表）= 全部 missing+diverged，与脚本 --apply 语义一致。
    names = set(body.names) if body.names else None
    outcomes, failures = preset_sync.apply_presets(rows, catalog_dir, _EXAMPLE_DIR, names)
    logger.warning(
        "skill presets synced via web admin: %d applied, %d failed",
        len(outcomes),
        len(failures),
    )
    audit_logger.log(
        request,
        action="sync",
        target_type="skill",
        target_id=",".join(outcome.name for outcome in outcomes) or "none",
    )
    return {
        "outcomes": [
            {
                "name": outcome.name,
                "backup": str(outcome.backup) if outcome.backup is not None else None,
            }
            for outcome in outcomes
        ],
        "failures": failures,
    }


def _inspect_and_stash(
    entries: list[skill_import.IngestEntry],
    *,
    kind: str,
    source_url: str = "",
    empty_detail: str | None = None,
) -> dict:
    """候选发现 + stash 落盘的共用收尾；``empty_detail`` 非空时零候选即 422。"""
    candidates = skill_import.discover_candidates(entries, _effective_catalog_dir())
    if not candidates and empty_detail is not None:
        raise HTTPException(status_code=422, detail=empty_detail)
    token = skill_import_stash.stash_payload(
        _STASH_DIR, entries, kind=kind, source_url=source_url
    )
    return {
        "token": token,
        "candidates": [asdict(candidate) for candidate in candidates],
    }


@router.post("/skills/import/inspect")
def inspect_import(body: ImportInspectBody):
    if body.kind == "zip":
        if body.archive_b64 is None:
            raise HTTPException(status_code=422, detail="archive_b64 is required for kind=zip")
        archive_bytes = skill_import.decode_zip_b64(body.archive_b64)
        if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=422, detail="archive exceeds the 16MiB limit")
        entries = skill_import.ingest_zip_bytes(archive_bytes)
    elif body.kind == "folder":
        if body.files is None:
            raise HTTPException(status_code=422, detail="files is required for kind=folder")
        entries = skill_import.ingest_folder(body.files)
    else:
        raise HTTPException(status_code=422, detail="kind must be 'zip' or 'folder'")
    return _inspect_and_stash(entries, kind=body.kind)


@router.post("/skills/import/github/inspect")
def inspect_github_import(body: GithubInspectBody):
    target = skill_import_github.parse_github_url(body.url)
    archive = skill_import_github.download_github_zip(target)
    try:
        # subpath 过滤提前到 ingest 阶段：树外条目不触发条目数/总量护栏，
        # monorepo 里挑单个 Skill 不受整仓规模影响。
        entries = skill_import.ingest_zip_bytes(archive, scope=target.subpath)
    except skill_import.IngestLimitError as exc:
        if not target.subpath:
            exc.detail = (
                f"{exc.detail}; if the repository contains multiple skills, "
                "use a /tree/<ref>/<subdirectory> URL to point at a single skill directory"
            )
        raise
    empty_detail = (
        f"no SKILL.md found under the subdirectory '{target.subpath}'"
        if target.subpath
        else "no SKILL.md found in the repository archive"
    )
    result = _inspect_and_stash(
        entries, kind="github", source_url=body.url, empty_detail=empty_detail
    )
    if target.subpath:
        narrowed = [
            candidate
            for candidate in result["candidates"]
            if candidate["root"] == target.subpath
            or candidate["root"].endswith(f"/{target.subpath}")
        ]
        if narrowed:
            result["candidates"] = narrowed
    return result


@router.post("/skills/import/confirm")
def confirm_import(body: ImportConfirmBody, request: Request):
    name, backup = skill_import.install_from_stash(
        _STASH_DIR,
        body.token,
        body.root,
        _effective_catalog_dir(),
        overwrite=body.overwrite,
    )
    logger.warning(
        "skill installed via web admin: %s (root=%s, backup=%s)", name, body.root, backup
    )
    audit_logger.log(request, action="install", target_type="skill", target_id=name)
    return {"name": name, "backup": str(backup) if backup is not None else None}


# ── 参数路径：单 skill 详情与资源编辑 ────────────────────────────────


@router.get("/skills/{name}")
def get_skill(name: str):
    skill_dir = _require_skill_dir(name)
    loaded, load_diagnostics = load_skill_with_diagnostics(skill_dir)
    if loaded is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "skill is not loadable",
                "diagnostics": _diagnostics_payload(load_diagnostics),
            },
        )
    resources = []
    for resource in loaded.resources:
        item = {
            "path": resource.path,
            "kind": resource.kind,
            "size_bytes": resource.size_bytes,
        }
        if resource.sha256:
            item["sha256"] = resource.sha256
        resources.append(item)
    return {
        "name": loaded.name,
        "metadata": asdict(loaded.metadata),
        "body": loaded.body,
        "resources": resources,
        "diagnostics": _diagnostics_payload(loaded.diagnostics),
    }


@router.delete("/skills/{name}")
def delete_skill(name: str, request: Request):
    skill_dir = _require_skill_dir(name)
    catalog_dir = skill_dir.parent
    with _skill_lock(catalog_dir, name):
        shutil.rmtree(skill_dir)
    # filelock 不自动清理锁文件：删除后 best-effort 清掉孤儿 <name>.lock。
    try:
        (catalog_dir / f"{name}.lock").unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("skill lock file cleanup failed for %s: %s", name, exc)
    logger.warning("skill deleted via web admin: %s", name)
    audit_logger.log(request, action="delete", target_type="skill", target_id=name)
    return {"ok": True}


@router.get("/skills/{name}/file")
def read_skill_file(name: str, path: str):
    skill_dir = _require_skill_dir(name)
    # 坏 skill 的文件同样需要可读可修，故只要求目录存在；加固走
    # resolve_file_in（lstat + realpath 双重校验）。
    try:
        assert_safe_relative_path(path)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="path is not a safe skill-relative path"
        ) from None
    try:
        target = resolve_file_in(skill_dir, path)
    except ValueError:
        raise HTTPException(status_code=404, detail="file not found") from None
    try:
        size = target.stat().st_size
    except OSError:
        raise HTTPException(status_code=404, detail="file not found") from None
    if size > MAX_SKILL_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds the 256KiB limit")
    try:
        content = target.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="file is not valid UTF-8") from None
    if content.startswith("\ufeff"):
        content = content[1:]
    return {"path": path, "content": content, "size_bytes": size}


@router.put("/skills/{name}/file")
def write_skill_file(name: str, body: SkillFileWriteBody, request: Request):
    skill_dir = _require_skill_dir(name)
    target = _resolve_for_write(skill_dir, body.path)
    raw = body.content.encode("utf-8")
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise HTTPException(status_code=422, detail="content exceeds the 256KiB limit")
    if body.path == SKILL_FILE_NAME:
        parsed = parse_skill_markdown(body.content, expected_name=name)
        if not parsed.ok or parsed.metadata is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "invalid SKILL.md content",
                    "diagnostics": _diagnostics_payload(parsed.diagnostics),
                },
            )
    is_create = not os.path.lexists(target)
    # 包含性校验先于 mkdir：最深的已存在祖先不得随符号链接逃逸出根。
    _check_ancestor_contained(skill_dir, target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(
            status_code=409,
            detail="target path conflicts with an existing non-directory entry",
        ) from None
    # mkdir 后、写盘前复检落点父目录（防范符号链接竞态交换）。
    _check_contained(skill_dir, target)
    tmp = target.with_name(target.name + ".tmp")
    with _skill_lock(skill_dir.parent, name):
        try:
            tmp.write_text(body.content, encoding="utf-8")
            tmp.replace(target)
        except (FileExistsError, NotADirectoryError):
            tmp.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail="target path conflicts with an existing non-directory entry",
            ) from None
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    action = "create" if is_create else "update"
    logger.warning(
        "skill file %s via web admin: %s:%s (%d bytes)",
        "created" if is_create else "updated",
        name,
        body.path,
        len(raw),
    )
    audit_logger.log(
        request,
        action=action,
        target_type="skill",
        target_id=f"{name}:{body.path}",
    )
    return {"ok": True}


@router.delete("/skills/{name}/file")
def delete_skill_file(name: str, path: str, request: Request):
    skill_dir = _require_skill_dir(name)
    if path == SKILL_FILE_NAME:
        raise HTTPException(status_code=409, detail="SKILL.md cannot be deleted")
    target = _resolve_for_write(skill_dir, path)
    try:
        info = target.lstat()
    except OSError:
        raise HTTPException(status_code=404, detail="file not found") from None
    if target.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise HTTPException(status_code=404, detail="file not found")
    _check_contained(skill_dir, target)
    with _skill_lock(skill_dir.parent, name):
        target.unlink()
    logger.warning("skill file deleted via web admin: %s:%s", name, path)
    audit_logger.log(
        request,
        action="delete",
        target_type="skill",
        target_id=f"{name}:{path}",
    )
    return {"ok": True}
