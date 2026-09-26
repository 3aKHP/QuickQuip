"""SKILL.md frontmatter 解析与校验（纯函数，不触碰文件系统）。

解析 Agent Skills 开放标准的可移植核心：YAML frontmatter + Markdown 正文，
必填 ``name`` / ``description``，可选 ``license`` / ``compatibility`` /
字符串到字符串的 ``metadata``。frontmatter 用 PyYAML ``safe_load`` 解析，
不手写 YAML 子集。任何读不明白的形态都判定为无效 skill，由扫描方
fail-closed 跳过并告警。

限额：单文件 ≤ 256KiB，description ≤ 1024 字符，name 必须匹配
``SKILL_NAME_PATTERN`` 且等于所在目录名。诊断信息不得携带宿主机绝对路径。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import yaml

MAX_SKILL_FILE_BYTES = 256 * 1024
MAX_DESCRIPTION_CHARS = 1024
MAX_NAME_LENGTH = 64
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_FRONTMATTER_FENCE = re.compile(r"^---\s*$")
_KNOWN_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}


@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    """稳定的诊断标识 + 人类可读细节（不得包含宿主机绝对路径）。"""

    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """SKILL.md frontmatter 中运行时认可的子集。

    未识别字段只在 ``unknown_fields`` 留名，不产生任何运行时行为。
    """

    name: str
    description: str
    license: str = ""
    compatibility: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    unknown_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class ParseSkillResult:
    ok: bool
    metadata: SkillMetadata | None = None
    body: str = ""
    body_sha256: str = ""
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)


def _fail(diagnostics: list[SkillDiagnostic]) -> ParseSkillResult:
    return ParseSkillResult(ok=False, diagnostics=diagnostics)


def parse_skill_markdown(content: str, expected_name: str = "") -> ParseSkillResult:
    """解析并校验 SKILL.md 文本。

    ``expected_name`` 为所在目录名；name 与目录名不一致是硬校验失败
    （标准要求两者一致）。
    """
    diagnostics: list[SkillDiagnostic] = []

    if len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
        return _fail([
            SkillDiagnostic(
                "oversized-skill",
                f"SKILL.md 超过 {MAX_SKILL_FILE_BYTES} 字节上限。",
            )
        ])

    lines = content.split("\n")
    if not lines or not _FRONTMATTER_FENCE.match(lines[0].rstrip("\r")):
        return _fail([
            SkillDiagnostic("missing-frontmatter", "SKILL.md 必须以 --- frontmatter 围栏开头。")
        ])
    close_index = -1
    for index in range(1, len(lines)):
        if _FRONTMATTER_FENCE.match(lines[index].rstrip("\r")):
            close_index = index
            break
    if close_index == -1:
        return _fail([
            SkillDiagnostic("missing-closing-fence", "SKILL.md frontmatter 缺少收尾的 --- 围栏。")
        ])

    frontmatter_text = "\n".join(lines[1:close_index])
    body = "\n".join(lines[close_index + 1:])
    try:
        raw_fields = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return _fail([SkillDiagnostic("parse-error", f"frontmatter YAML 解析失败：{exc}")])
    if raw_fields is None:
        raw_fields = {}
    if not isinstance(raw_fields, dict):
        return _fail([
            SkillDiagnostic("parse-error", "frontmatter 必须是键值映射。")
        ])

    unknown_keys = sorted(str(key) for key in raw_fields if key not in _KNOWN_FRONTMATTER_KEYS)
    for key in unknown_keys:
        diagnostics.append(
            SkillDiagnostic("unsupported-field", f'未识别的 frontmatter 字段 "{key}" 已忽略。')
        )
    if "allowed-tools" in raw_fields:
        diagnostics.append(
            SkillDiagnostic(
                "allowed-tools-ignored",
                "allowed-tools 仅为兼容性解析，运行时忽略；工具面由部署配置决定。",
            )
        )

    name = raw_fields.get("name")
    if not isinstance(name, str) or not name.strip():
        return _fail([
            *diagnostics,
            SkillDiagnostic("name-missing", "frontmatter 缺少非空字符串 name。"),
        ])
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH or not SKILL_NAME_PATTERN.fullmatch(name):
        return _fail([
            *diagnostics,
            SkillDiagnostic(
                "name-invalid",
                f'Skill name "{name}" 必须是 1-{MAX_NAME_LENGTH} 字符、'
                "小写字母/数字/连字符且以字母或数字开头。",
            ),
        ])
    if expected_name and name != expected_name:
        return _fail([
            *diagnostics,
            SkillDiagnostic(
                "name-directory-mismatch",
                f'Skill name "{name}" 与目录名 "{expected_name}" 不一致。',
            ),
        ])

    description = raw_fields.get("description")
    if not isinstance(description, str) or not description.strip():
        return _fail([
            *diagnostics,
            SkillDiagnostic("description-missing", "frontmatter 缺少非空字符串 description。"),
        ])
    if len(description) > MAX_DESCRIPTION_CHARS:
        return _fail([
            *diagnostics,
            SkillDiagnostic(
                "description-oversized",
                f"description 为 {len(description)} 字符，超过 {MAX_DESCRIPTION_CHARS} 字符上限。",
            ),
        ])

    metadata_map = _read_metadata_map(raw_fields.get("metadata"))
    if isinstance(metadata_map, SkillDiagnostic):
        return _fail([*diagnostics, metadata_map])

    license_value = raw_fields.get("license")
    compatibility_value = raw_fields.get("compatibility")
    metadata = SkillMetadata(
        name=name,
        description=description,
        license=license_value.strip() if isinstance(license_value, str) else "",
        compatibility=compatibility_value.strip() if isinstance(compatibility_value, str) else "",
        metadata=metadata_map,
        unknown_fields=tuple(unknown_keys),
    )
    return ParseSkillResult(
        ok=True,
        metadata=metadata,
        body=body,
        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        diagnostics=diagnostics,
    )


def _read_metadata_map(raw: object) -> dict[str, str] | SkillDiagnostic:
    """``metadata`` 仅接受字符串到标量的映射；标量值统一转为字符串。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return SkillDiagnostic("parse-error", "frontmatter metadata 必须是键值映射。")
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, (dict, list)):
            return SkillDiagnostic(
                "parse-error", f"frontmatter metadata.{key} 只接受标量值。"
            )
        result[str(key)] = value if isinstance(value, str) else str(value)
    return result
