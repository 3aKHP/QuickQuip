"""Skill 目录扫描、路径加固与 catalog 预算裁剪。

每轮构建系统提示时现扫目录（目录小，成本可忽略；天然支持热部署，
无 reload 钩子）。单个坏 skill fail-closed 跳过并告警，不拖垮有效邻居。

路径加固与文件解析的边界：``assert_safe_relative_path`` 拒绝绝对路径、
``..``、反斜杠、空段与 NUL；``resolve_skill_file`` 在加固之上做 lstat +
realpath 双重校验，证明目标是 skill 根内的常规文件、未随符号链接逃逸。
read/search/run 三个工具共用同一套加固。

预算：catalog 渲染字节 ≤ min(上下文窗口 2%, catalog_max_bytes)。超限先按
蓝本统一截短 description（160 → 80 字符），仍超限按 name 字典序保前弃后
（与渲染序一致，确定性可测），淘汰事件记告警日志。永不淘汰到空：单个
最短形态仍超限时保留该条目，激活依旧可行。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from quickquip.common.paths import SKILLS_DIR
from quickquip.llm.skills.parser import (
    MAX_SKILL_FILE_BYTES,
    SkillDiagnostic,
    SkillMetadata,
    parse_skill_markdown,
)

logger = logging.getLogger(__name__)

SKILL_FILE_NAME = "SKILL.md"

# 单个 skill 编入清单的附属资源条数上限（超出停止遍历并记诊断）。
MAX_RESOURCES_PER_SKILL = 200

# scripts/ 下单个脚本文件的字节上限（超出不编入清单、不可执行，记诊断）。
# 扫描期对每个脚本做 SHA-256 全量读盘，没有该上限时误放进目录的大文件
# 会让每轮 LLM 请求的目录扫描同步读盘数百 MB（Deep-CR L2-3）。
MAX_SCRIPT_FILE_BYTES = 256 * 1024

_FALLBACK_BUDGET_BYTES = 8 * 1024
_SHORTENED_DESCRIPTION_CHARS = 160
_MIN_DESCRIPTION_CHARS = 80
# 每 token 字节近似（与蓝本一致：上下文窗口 2% 的 token 数 ×2 得字节预算）。
_BYTES_PER_TOKEN = 2

_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class SkillResource:
    """skill 根内一个常规文件的清单条目（skill 相对 POSIX 路径）。"""

    path: str
    kind: str  # reference | asset | script | other
    size_bytes: int
    # 仅 scripts/ 下文件计算：run_skill_script 执行前复验用。
    sha256: str = ""


@dataclass(slots=True)
class LoadedSkill:
    """一个通过校验的 skill 根。``root_dir`` 是宿主机内部状态，
    不得出现在 catalog 条目、诊断或任何模型可见内容里。"""

    name: str
    root_dir: Path
    metadata: SkillMetadata
    body: str
    body_sha256: str
    resources: list[SkillResource] = field(default_factory=list)
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    """路由视图条目：只有 name + description，永不含路径。"""

    name: str
    description: str


@dataclass(slots=True)
class SkillCatalog:
    """预算裁剪后的有效 catalog。

    ``entries``/``hash``/``omitted`` 是可上模型面的路由视图；``by_name``
    是工具执行器解析正文/资源的宿主机侧映射（内部状态，只含保留下来的
    条目，被淘汰的 skill 不可激活）。
    """

    entries: list[SkillCatalogEntry]
    hash: str
    omitted: list[str] = field(default_factory=list)
    by_name: dict[str, LoadedSkill] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [entry.name for entry in self.entries]


def resolve_catalog_dir(configured: str = "") -> Path:
    """``[skills] catalog_dir`` 的生效目录：空 = 默认 ``SKILLS_DIR``；
    相对路径按项目根解析。"""
    text = configured.strip()
    if not text:
        return SKILLS_DIR
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = SKILLS_DIR.parent / path
    return path


def derive_catalog_budget_bytes(
    context_window_tokens: int | None, catalog_max_bytes: int
) -> int:
    """预算 = min(上下文窗口 2%, catalog_max_bytes)；窗口未知时用 catalog_max_bytes。"""
    fallback = catalog_max_bytes if catalog_max_bytes > 0 else _FALLBACK_BUDGET_BYTES
    if not context_window_tokens or context_window_tokens <= 0:
        return fallback
    window_budget = max(1, int(context_window_tokens * 0.02)) * _BYTES_PER_TOKEN
    return min(window_budget, fallback)


# ── 路径加固 ─────────────────────────────────────────────────────


def assert_safe_relative_path(skill_relative_path: str) -> None:
    """校验 skill 相对路径字符串；任何不安全形状抛 ValueError。

    反斜杠一律拒绝：它在 Windows 是路径分隔符、在 POSIX 是合法文件名字符，
    接受它会引入平台相关的归一化歧义。
    """
    if not skill_relative_path or "\0" in skill_relative_path:
        raise ValueError("Skill 路径不能为空。")
    if "\\" in skill_relative_path:
        raise ValueError(f"Skill 路径必须使用正斜杠：{skill_relative_path}")
    if skill_relative_path.startswith("/") or re.match(r"^[A-Za-z]:/", skill_relative_path):
        raise ValueError(f"Skill 路径必须是相对路径：{skill_relative_path}")
    parts = skill_relative_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"不安全的 Skill 路径：{skill_relative_path}")


def classify_resource(skill_relative_path: str) -> str:
    """按约定顶层目录归类资源。"""
    top = skill_relative_path.split("/")[0]
    if top == "references":
        return "reference"
    if top == "assets":
        return "asset"
    if top == "scripts":
        return "script"
    return "other"


def utf8_safe_boundary(raw: bytes, max_bytes: int) -> int:
    """≤ max_bytes 且不劈开 UTF-8 序列的最大前缀长度。"""
    boundary = min(max_bytes, len(raw))
    # 0b10xxxxxx 是 UTF-8 后续字节；回退到序列起点。boundary == len(raw)
    # 时整段取全，天然安全，无需也不能检查 raw[boundary]。
    while 0 < boundary < len(raw) and (raw[boundary] & 0b1100_0000) == 0b1000_0000:
        boundary -= 1
    return boundary


def resolve_skill_file(skill: LoadedSkill, relative_path: str) -> Path:
    """把 skill 相对路径解析为 skill 根内的常规文件。

    ``assert_safe_relative_path`` 拒绝穿越与绝对形态；lstat + realpath
    双重校验证明目标是常规文件且未随符号链接交换逃逸出根。失败抛
    ValueError（消息不含宿主机绝对路径）。
    """
    assert_safe_relative_path(relative_path)
    absolute = skill.root_dir.joinpath(*relative_path.split("/"))
    try:
        info = absolute.lstat()
    except OSError:
        raise ValueError(f'Skill 资源 "{relative_path}" 不存在。') from None
    if absolute.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Skill 资源 "{relative_path}" 不是 skill 根内的常规文件。')
    try:
        real_file = absolute.resolve(strict=True)
        real_root = skill.root_dir.resolve(strict=True)
    except OSError:
        raise ValueError(f'Skill 资源 "{relative_path}" 无法校验真实路径。') from None
    if real_file != real_root and real_root not in real_file.parents:
        raise ValueError(f'Skill 资源 "{relative_path}" 逃逸出 skill 根，已拒绝。')
    return absolute


# ── 目录扫描 ─────────────────────────────────────────────────────


def scan_skills(catalog_dir: Path) -> list[LoadedSkill]:
    """扫描 catalog 目录，返回全部通过校验的 skill（按 name 字典序）。

    目录不存在视为未部署，返回空列表且不打日志（默认零扰动）；单个
    坏 skill 跳过一次 WARNING。
    """
    if not catalog_dir.is_dir():
        return []
    skills: list[LoadedSkill] = []
    try:
        children = sorted(catalog_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        # 扫描瞬间目录被移走/权限收紧：按未部署同语义处理，不向上抛。
        logger.warning("skill catalog 目录读取失败（%s），按空目录处理", exc)
        return []
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        skill = _load_skill(child)
        if skill is None:
            continue
        skills.append(skill)
    skills.sort(key=lambda skill: skill.name)
    return skills


def _load_skill(root_dir: Path) -> LoadedSkill | None:
    name = root_dir.name
    skill_path = root_dir / SKILL_FILE_NAME
    try:
        info = skill_path.lstat()
    except OSError:
        return None
    if skill_path.is_symlink() or not stat.S_ISREG(info.st_mode):
        _warn_skip(name, "not-a-regular-file", "SKILL.md 不是常规文件。")
        return None
    if info.st_size > MAX_SKILL_FILE_BYTES:
        _warn_skip(name, "oversized-skill", f"SKILL.md 超过 {MAX_SKILL_FILE_BYTES} 字节上限。")
        return None
    try:
        raw = skill_path.read_bytes()
        # 读后 lstat 复检：读出与首检之间被换成符号链接/非常规文件时拒绝。
        rechecked = skill_path.lstat()
        if skill_path.is_symlink() or not stat.S_ISREG(rechecked.st_mode):
            _warn_skip(name, "not-a-regular-file", "SKILL.md 读取期间被替换为非常规文件。")
            return None
    except OSError as exc:
        _warn_skip(name, "read-error", f"SKILL.md 读取失败：{exc.strerror or exc}")
        return None
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM):]
    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _warn_skip(name, "invalid-utf8", "SKILL.md 不是有效 UTF-8。")
        return None

    parsed = parse_skill_markdown(content, expected_name=name)
    if not parsed.ok or parsed.metadata is None:
        first = (
            parsed.diagnostics[0]
            if parsed.diagnostics
            else SkillDiagnostic("invalid", "未知校验失败")
        )
        _warn_skip(name, first.kind, first.message)
        return None

    resources, resource_diagnostics = _walk_skill_files(root_dir)
    for diagnostic in resource_diagnostics:
        logger.warning("skill %s 资源清单诊断 [%s] %s", name, diagnostic.kind, diagnostic.message)
    return LoadedSkill(
        name=name,
        root_dir=root_dir,
        metadata=parsed.metadata,
        body=parsed.body,
        body_sha256=parsed.body_sha256,
        resources=resources,
        diagnostics=[*parsed.diagnostics, *resource_diagnostics],
    )


def _walk_skill_files(root_dir: Path) -> tuple[list[SkillResource], list[SkillDiagnostic]]:
    """遍历 skill 根内的常规文件（SKILL.md 除外），拒符号链接/非常规项/
    不安全相对路径，条数上限 MAX_RESOURCES_PER_SKILL。"""
    resources: list[SkillResource] = []
    diagnostics: list[SkillDiagnostic] = []
    for directory, dirnames, filenames in os.walk(root_dir, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            relative = absolute.relative_to(root_dir).as_posix()
            if relative == SKILL_FILE_NAME:
                continue
            if absolute.is_symlink():
                diagnostics.append(
                    SkillDiagnostic("resource-symlink", f"不支持符号链接：{relative}。")
                )
                continue
            if not absolute.is_file():
                diagnostics.append(
                    SkillDiagnostic("resource-path-unsafe", f"不支持的文件系统项：{relative}。")
                )
                continue
            try:
                assert_safe_relative_path(relative)
            except ValueError:
                diagnostics.append(
                    SkillDiagnostic(
                        "resource-path-unsafe", f"{relative} 不是受支持的 skill 相对路径。"
                    )
                )
                continue
            if len(resources) >= MAX_RESOURCES_PER_SKILL:
                diagnostics.append(
                    SkillDiagnostic(
                        "resource-count-oversize",
                        f"资源条数超过 {MAX_RESOURCES_PER_SKILL} 上限，其余条目不编入清单。",
                    )
                )
                break
            kind = classify_resource(relative)
            try:
                size_bytes = absolute.stat().st_size
            except OSError as exc:
                # walk 列名与 stat 之间文件被移走：记诊断跳过，不中断整轮扫描。
                diagnostics.append(
                    SkillDiagnostic("read-error", f"{relative}：{exc.strerror or exc}")
                )
                continue
            sha256 = ""
            if kind == "script":
                if size_bytes > MAX_SCRIPT_FILE_BYTES:
                    # 哈希路径无读取上限（Deep-CR L2-3）：先按 stat 拒绝
                    # 超限脚本，避免每轮扫描对误放大文件做全量读盘。
                    diagnostics.append(
                        SkillDiagnostic(
                            "script-oversize",
                            f"{relative}：脚本超过 {MAX_SCRIPT_FILE_BYTES} 字节上限，"
                            "不编入清单。",
                        )
                    )
                    continue
                try:
                    sha256 = hashlib.sha256(absolute.read_bytes()).hexdigest()
                except OSError as exc:
                    diagnostics.append(
                        SkillDiagnostic("read-error", f"{relative}：{exc.strerror or exc}")
                    )
                    continue
            resources.append(
                SkillResource(
                    path=relative,
                    kind=kind,
                    size_bytes=size_bytes,
                    sha256=sha256,
                )
            )
    return resources, diagnostics


def _warn_skip(name: str, kind: str, message: str) -> None:
    logger.warning("跳过无效 skill %s [%s] %s", name, kind, message)


# ── 预算裁剪 ─────────────────────────────────────────────────────


def build_catalog(
    skills: list[LoadedSkill], *, budget_bytes: int
) -> SkillCatalog:
    """从扫描产物构建有效 catalog：渲染序 = name 字典序；先截短再淘汰。"""
    budget = max(1, budget_bytes)
    candidates = [
        _CatalogCandidate(skill=skill, description=skill.metadata.description)
        for skill in sorted(skills, key=lambda skill: skill.name)
    ]

    kept = _apply_budget(candidates, budget)
    kept_names = {candidate.skill.name for candidate in kept}
    omitted = [
        candidate.skill.name
        for candidate in candidates
        if candidate.skill.name not in kept_names
    ]
    if omitted:
        logger.warning(
            "skill catalog 超过 %d 字节预算，按字典序保前弃后淘汰：%s",
            budget,
            ", ".join(omitted),
        )
    return SkillCatalog(
        entries=[
            SkillCatalogEntry(name=candidate.skill.name, description=candidate.description)
            for candidate in kept
        ],
        hash=_compute_catalog_hash([candidate.skill for candidate in kept]),
        omitted=omitted,
        by_name={candidate.skill.name: candidate.skill for candidate in kept},
    )


@dataclass(slots=True)
class _CatalogCandidate:
    """预算裁剪的工作副本：description 是可变路由数据；skill 本体不动，
    ``by_name`` 始终指向扫描时的原始 ``LoadedSkill``。"""

    skill: LoadedSkill
    description: str


def _apply_budget(candidates: list[_CatalogCandidate], budget: int) -> list[_CatalogCandidate]:
    if _catalog_bytes(candidates) <= budget:
        return list(candidates)

    shortened = _shorten_all(candidates, _SHORTENED_DESCRIPTION_CHARS)
    if _catalog_bytes(shortened) <= budget:
        return shortened

    minimal = _shorten_all(candidates, _MIN_DESCRIPTION_CHARS)
    if _catalog_bytes(minimal) <= budget:
        return minimal

    # 淘汰序 = 字典序保前弃后（与渲染序一致）；永不淘汰到空。
    kept = list(minimal)
    for candidate in reversed(minimal):
        if _catalog_bytes(kept) <= budget or len(kept) == 1:
            break
        kept.remove(candidate)
    return kept


def _shorten_all(candidates: list[_CatalogCandidate], max_chars: int) -> list[_CatalogCandidate]:
    return [
        _CatalogCandidate(
            skill=candidate.skill,
            description=_truncate_chars(candidate.description, max_chars),
        )
        for candidate in candidates
    ]


def _truncate_chars(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max(1, max_chars - 1)]}…"


def _catalog_bytes(candidates: list[_CatalogCandidate]) -> int:
    return sum(
        len(f"{candidate.skill.name}\n{candidate.description}\n".encode("utf-8"))
        for candidate in candidates
    )


def _compute_catalog_hash(skills: list[LoadedSkill]) -> str:
    """有效 catalog 的身份指纹：按 name 排序的 ``name\\0body_sha256`` 行。

    description 截短（可变路由数据）不改变 hash；增删 skill 或正文内容
    版本变化会改变它。
    """
    payload = "\n".join(
        f"{skill.name}\0{skill.body_sha256}"
        for skill in sorted(skills, key=lambda skill: skill.name)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
