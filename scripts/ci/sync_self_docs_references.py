"""Synchronize skills.example/self-docs references from the public docs allowlist.

Usage:
    python scripts/ci/sync_self_docs_references.py          # write mode
    python scripts/ci/sync_self_docs_references.py --check  # read-only drift check

Sources are limited to a closed allowlist: README.md / CHANGELOG.md /
ROADMAP.md / CONTRIBUTING.md / SECURITY.md at the repo root plus every
docs/**/*.md page (docs/assets/ excluded). Each page flattens to a
deterministic one-level resource name under references/ (root files get a
"root-" prefix, docs pages join path segments with "-"); name collisions are
fatal. Generated files carry a "<!-- Generated from <source>; do not edit -->"
marker, and a keyword-enhanced index.md (per-page title + backtick-quoted
command/config tokens) is produced as the grep-miss fallback.

Fail-closed source checks reject symlinks, non-regular files, NUL bytes,
invalid UTF-8, oversize resources, unsafe names, and any content embedding the
local checkout path. SKILL.md routing-table references are validated against
the generated set in both modes. Write mode replaces references/ atomically
via staging + rename; check mode compares byte-for-byte and exits non-zero on
any drift.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_RESOURCES = 200
MAX_RESOURCE_BYTES = 256 * 1024
MAX_KEYWORDS_PER_RESOURCE = 10

ROOT_SOURCE_FILES = ("README.md", "CHANGELOG.md", "ROADMAP.md", "CONTRIBUTING.md", "SECURITY.md")
DOCS_DIR_NAME = "docs"
DOCS_EXCLUDED_ROOTS = ("docs/assets",)

SKILL_DIR = Path("skills.example") / "self-docs"
REFERENCES_DIR_NAME = "references"

_TITLE_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_BACKTICK_PATTERN = re.compile(r"`([^`\n]{2,48})`")
_ROUTING_REFERENCE_PATTERN = re.compile(r"references/[A-Za-z0-9._-]+")

INDEX_MARKER = (
    "<!-- Generated index; do not edit. "
    "Run: python scripts/ci/sync_self_docs_references.py -->"
)


class SyncError(Exception):
    """Fail-closed 源检查或生成流程中的硬错误。"""


@dataclass(frozen=True, slots=True)
class SourceEntry:
    public_path: str
    absolute_path: Path
    resource_name: str


def generated_marker(public_path: str) -> str:
    return f"<!-- Generated from {public_path}; do not edit -->"


def resource_name_for(public_path: str) -> str:
    normalized = public_path.replace("\\", "/").lower()
    if "/" not in normalized:
        return f"root-{normalized}"
    return normalized.replace("/", "-")


def _walk_markdown_files(directory: Path, root: Path) -> list[Path]:
    found: list[Path] = []
    for child in sorted(directory.iterdir(), key=lambda path: path.name):
        relative = child.relative_to(root).as_posix()
        if child.is_symlink():
            raise SyncError(f"公开源中的符号链接被拒绝：{relative}")
        if child.is_dir():
            if relative in DOCS_EXCLUDED_ROOTS:
                continue
            found.extend(_walk_markdown_files(child, root))
        elif child.is_file():
            if child.name.lower().endswith(".md"):
                found.append(child)
        else:
            raise SyncError(f"公开源中的非常规文件被拒绝：{relative}")
    return found


def collect_source_entries(root: Path) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    seen: set[str] = set()

    def add(public_path: str, absolute: Path) -> None:
        name = resource_name_for(public_path)
        if name in seen:
            raise SyncError(f'资源名冲突："{name}" 来自 "{public_path}"')
        seen.add(name)
        entries.append(SourceEntry(public_path, absolute, name))

    for filename in ROOT_SOURCE_FILES:
        candidate = root / filename
        try:
            info = candidate.lstat()
        except OSError:
            continue
        if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise SyncError(f"公开源根文件必须是常规文件：{filename}")
        add(filename, candidate)

    docs_root = root / DOCS_DIR_NAME
    if docs_root.is_symlink():
        raise SyncError(f"公开源目录不得为符号链接：{DOCS_DIR_NAME}")
    if docs_root.is_dir():
        for absolute in _walk_markdown_files(docs_root, root):
            add(absolute.relative_to(root).as_posix(), absolute)

    entries.sort(key=lambda entry: entry.resource_name)
    return entries


def read_source_text(entry: SourceEntry) -> str:
    try:
        raw = entry.absolute_path.read_bytes()
    except OSError as exc:
        raise SyncError(f"源文件读取失败：{entry.public_path}（{exc.strerror or exc}）") from exc
    if b"\0" in raw:
        raise SyncError(f"源文件含 NUL 字节：{entry.public_path}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SyncError(f"源文件不是合法 UTF-8：{entry.public_path}") from exc
    if "�" in text:
        raise SyncError(f"源文件含 U+FFFD 替换字符：{entry.public_path}")
    return text


def extract_title(text: str, fallback: str) -> str:
    match = _TITLE_PATTERN.search(text)
    return match.group(1).strip() if match else fallback


def extract_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for match in _BACKTICK_PATTERN.finditer(text):
        token = match.group(1).strip()
        if not token or token in seen or not any(char.isalnum() for char in token):
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= MAX_KEYWORDS_PER_RESOURCE:
            break
    return keywords


def _categorize(public_path: str) -> str:
    if "/" not in public_path:
        return "root"
    if public_path == "docs/index.md":
        return "index"
    if public_path.startswith("docs/user/"):
        return "user"
    if public_path.startswith("docs/admin/"):
        return "admin"
    if public_path.startswith("docs/dev/"):
        return "dev"
    return "other"


_SECTION_ORDER = ("root", "index", "user", "admin", "dev", "other")
_SECTION_TITLES = {
    "root": "Root 文档",
    "index": "文档导航",
    "user": "用户文档（群友）",
    "admin": "管理文档（部署与运维）",
    "dev": "开发文档",
    "other": "其他",
}


def generate_index(entries: list[SourceEntry], source_texts: dict[str, str]) -> str:
    lines = [
        INDEX_MARKER,
        "",
        "# QuickQuip 文档索引",
        "",
        "与部署版本对齐的公开文档快照，是 self-docs Skill 的路由总表与检索兜底索引。",
        "",
        "## 路由指引",
        "",
        "- 群友命令、玩法、梗触发 → 用户文档（`docs-user-*`）。",
        "- 部署、配置、运维、报错排查 → 管理文档（`docs-admin-*`）。",
        "- 架构、模块契约、开发约定 → 开发文档（`docs-dev-*`）。",
        "- 项目概览与安装 → `root-readme.md`；版本行为变更 → `root-changelog.md`；"
        "计划功能 → `root-roadmap.md`。",
        "- 每条列出该页标题与关键词；`search_skill_resources` 未命中时按关键词挑页，"
        "用 `read_skill_resource` 阅读。",
        "- 文档未覆盖的问题如实说明缺失，不要凭训练记忆编造。",
        "",
    ]
    groups: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        groups.setdefault(_categorize(entry.public_path), []).append(entry)
    for section in _SECTION_ORDER:
        group = groups.get(section)
        if not group:
            continue
        lines.append(f"## {_SECTION_TITLES[section]}")
        lines.append("")
        for entry in group:
            text = source_texts[entry.resource_name]
            title = extract_title(text, entry.resource_name.removesuffix(".md"))
            line = f"- `{entry.public_path}` → `references/{entry.resource_name}` — {title}"
            keywords = extract_keywords(text)
            if keywords:
                line += " ｜ 关键词：" + "、".join(keywords)
            lines.append(line)
        lines.append("")
    return "\n".join(lines) + "\n"


def read_skill_markdown(root: Path) -> str:
    path = root / SKILL_DIR / "SKILL.md"
    try:
        info = path.lstat()
    except OSError:
        raise SyncError(f"{SKILL_DIR.as_posix()}/SKILL.md 不存在；路由表校验需要它。") from None
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SyncError("self-docs 的 SKILL.md 必须是常规文件。")
    raw = path.read_bytes()
    if b"\0" in raw:
        raise SyncError("self-docs 的 SKILL.md 含 NUL 字节。")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SyncError("self-docs 的 SKILL.md 不是合法 UTF-8。") from None


def validate_contents(
    contents: dict[str, str], root: Path, skill_markdown: str
) -> list[str]:
    errors: list[str] = []
    if len(contents) > MAX_RESOURCES:
        errors.append(f"资源数 {len(contents)} 超过上限 {MAX_RESOURCES}。")
    for name in sorted(contents):
        content = contents[name]
        size = len(content.encode("utf-8"))
        if size > MAX_RESOURCE_BYTES:
            errors.append(f'资源 "{name}" 为 {size} 字节，超过 {MAX_RESOURCE_BYTES} 字节上限。')
        if "\0" in content:
            errors.append(f'资源 "{name}" 含 NUL 字节。')
        if ".." in name or "/" in name or "\\" in name:
            errors.append(f'资源名 "{name}" 不是安全的一层文件名。')
    checkout_path = str(root)
    for name in sorted(contents):
        if checkout_path in contents[name]:
            errors.append(f'资源 "{name}" 含本地 checkout 路径。')
    referenced = sorted(set(_ROUTING_REFERENCE_PATTERN.findall(skill_markdown)))
    for token in referenced:
        target = token.removeprefix("references/")
        if target not in contents:
            errors.append(f'SKILL.md 引用的 "{token}" 不在生成的资源集中。')
    return errors


def run_check(references_dir: Path, contents: dict[str, str]) -> int:
    drift: list[str] = []
    invalid: set[str] = set()
    if references_dir.is_dir():
        for child in sorted(references_dir.iterdir(), key=lambda path: path.name):
            if child.is_symlink() or not child.is_file():
                drift.append(f"invalid: references/{child.name}（非常规文件）")
                invalid.add(child.name)
            elif child.name not in contents:
                drift.append(f"extra: references/{child.name}")
    for name in sorted(contents):
        if name in invalid:
            continue
        path = references_dir / name
        if not path.is_file():
            drift.append(f"missing: references/{name}")
            continue
        if path.read_bytes() != contents[name].encode("utf-8"):
            drift.append(f"changed: references/{name}")
    if drift:
        print("self-docs references 与公开文档源不同步：", file=sys.stderr)
        for item in drift:
            print(f"  {item}", file=sys.stderr)
        print("运行：python scripts/ci/sync_self_docs_references.py", file=sys.stderr)
        return 1
    print(f"OK: {len(contents)} references are in sync.")
    return 0


def run_write(root: Path, contents: dict[str, str]) -> int:
    skill_root = root / SKILL_DIR
    references_dir = skill_root / REFERENCES_DIR_NAME
    staging_dir = skill_root / f".references-staging-{os.getpid()}"
    old_dir = skill_root / f".references-old-{os.getpid()}"
    # 历史中断可能留下任意 pid 的暂存/旧目录：write 前一律清扫（含本次）。
    for pattern in (".references-staging-*", ".references-old-*"):
        for leftover in skill_root.glob(pattern):
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover, ignore_errors=True)
    try:
        staging_dir.mkdir(parents=True)
        for name in sorted(contents):
            (staging_dir / name).write_bytes(contents[name].encode("utf-8"))
        had_old = references_dir.exists() or references_dir.is_symlink()
        if had_old:
            os.rename(references_dir, old_dir)
        try:
            os.rename(staging_dir, references_dir)
        except OSError:
            if had_old:
                os.rename(old_dir, references_dir)
            raise
        shutil.rmtree(old_dir, ignore_errors=True)
        print(f"Synced {len(contents)} references to {SKILL_DIR.as_posix()}/references/.")
        return 0
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(old_dir, ignore_errors=True)


def build_contents(root: Path) -> dict[str, str]:
    entries = collect_source_entries(root)
    source_texts: dict[str, str] = {}
    contents: dict[str, str] = {}
    for entry in entries:
        text = read_source_text(entry)
        source_texts[entry.resource_name] = text
        contents[entry.resource_name] = f"{generated_marker(entry.public_path)}\n\n{text}"
    contents["index.md"] = generate_index(entries, source_texts)
    return contents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验漂移不写入；漂移或校验失败时退出码非零。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="仓库根目录（默认取脚本所在仓库）。",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        contents = build_contents(root)
        skill_markdown = read_skill_markdown(root)
        errors = validate_contents(contents, root, skill_markdown)
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    references_dir = root / SKILL_DIR / REFERENCES_DIR_NAME
    if args.check:
        return run_check(references_dir, contents)
    try:
        return run_write(root, contents)
    except OSError as exc:
        print(f"ERROR: 写入 references 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
