from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import ast

logger = logging.getLogger(__name__)

IDENTITY_SECTIONS = ("people", "special_accounts")


@dataclass(slots=True)
class IdentityEntry:
    canonical_name: str
    qq_ids: list[str]
    aliases: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class IdentityMatch:
    user_id: str
    sender_name: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    note: str = ""
    is_registered: bool = False


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return line[:index].rstrip()
    return line.rstrip()


def _parse_scalar(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if normalized[0] in {"'", '"'} and normalized[-1] == normalized[0]:
        try:
            return str(ast.literal_eval(normalized))
        except (SyntaxError, ValueError):
            return normalized[1:-1]
    return normalized


def _parse_list_value(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []

    normalized = str(value).strip()
    if not normalized:
        return []
    if normalized.startswith("[") and normalized.endswith("]"):
        try:
            parsed = ast.literal_eval(normalized)
        except (SyntaxError, ValueError):
            parsed = [item.strip() for item in normalized[1:-1].split(",")]
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [_parse_scalar(normalized)]


def _entry_text(value: object) -> str:
    """条目字段值的文本形态；空值（None 或解析器的空列表占位）按未填写处理。"""
    if value is None or value == []:
        return ""
    return str(value)


def declared_entry_fields(section: str, payload: dict[str, object]) -> tuple[str, list[str]]:
    """提取条目声明的标准名与 QQ 号（规范化、去空值），供条目解析与占位判定共用。"""
    canonical_name = _parse_scalar(_entry_text(payload.get("canonical_name"))).strip()
    if section == "special_accounts":
        qq_ids = [_parse_scalar(_entry_text(payload.get("qq_id"))).strip()]
    else:
        qq_ids = _parse_list_value(payload.get("qq_ids"))
    return canonical_name, [qq_id for qq_id in qq_ids if qq_id]


def _finalize_entry(section: str, payload: dict[str, object]) -> IdentityEntry | None:
    canonical_name, qq_ids = declared_entry_fields(section, payload)
    if not canonical_name or not qq_ids:
        return None

    aliases = _parse_list_value(payload.get("aliases"))
    note = _parse_scalar(_entry_text(payload.get("note"))).strip()
    return IdentityEntry(
        canonical_name=canonical_name,
        qq_ids=qq_ids,
        aliases=aliases,
        note=note,
    )


@dataclass(slots=True)
class IdentityIndex:
    entries: list[IdentityEntry] = field(default_factory=list)
    by_qq: dict[str, IdentityEntry] = field(default_factory=dict)
    by_alias: dict[str, IdentityEntry] = field(default_factory=dict)
    by_name: dict[str, IdentityEntry] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "IdentityIndex":
        identity_path = Path(path)
        if not identity_path.exists():
            logger.info("身份资料文件不存在，按空身份索引处理：%s", identity_path)
            return cls()

        try:
            raw_text = identity_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("无法读取身份资料文件 %s：%s", identity_path, exc)
            return cls()

        return cls.from_text(raw_text, identity_path)

    @classmethod
    def from_text(cls, raw_text: str, identity_path: str | Path = "<text>") -> "IdentityIndex":
        section = ""
        current: dict[str, object] | None = None
        current_list_key: str | None = None
        entries: list[IdentityEntry] = []

        for raw_line in raw_text.splitlines():
            cleaned = _strip_inline_comment(raw_line)
            if not cleaned.strip():
                continue

            indent = len(cleaned) - len(cleaned.lstrip(" "))
            stripped = cleaned.strip()

            if indent == 0 and stripped.endswith(":"):
                if current is not None and section in IDENTITY_SECTIONS:
                    entry = _finalize_entry(section, current)
                    if entry is not None:
                        entries.append(entry)
                section = stripped[:-1].strip()
                current = None
                current_list_key = None
                continue

            if section not in IDENTITY_SECTIONS:
                continue

            if indent == 2 and stripped.startswith("- "):
                if current is not None:
                    entry = _finalize_entry(section, current)
                    if entry is not None:
                        entries.append(entry)
                current = {}
                current_list_key = None
                stripped = stripped[2:].strip()
                if stripped and ":" in stripped:
                    key, raw_value = stripped.split(":", 1)
                    key = key.strip()
                    raw_value = raw_value.strip()
                    if raw_value:
                        current[key] = raw_value
                    else:
                        current[key] = []
                        current_list_key = key
                continue

            if current is None:
                continue

            if indent == 4 and ":" in stripped:
                key, raw_value = stripped.split(":", 1)
                key = key.strip()
                raw_value = raw_value.strip()
                if raw_value:
                    current[key] = raw_value
                    current_list_key = None
                else:
                    current[key] = []
                    current_list_key = key
                continue

            if indent >= 6 and stripped.startswith("- ") and current_list_key:
                current.setdefault(current_list_key, [])
                current[current_list_key].append(_parse_scalar(stripped[2:].strip()))

        if current is not None and section in IDENTITY_SECTIONS:
            entry = _finalize_entry(section, current)
            if entry is not None:
                entries.append(entry)

        if not entries:
            logger.warning(
                "身份资料文件 %s 存在但无有效条目（空白模板或字段缺失），按空身份索引处理",
                identity_path,
            )
        else:
            logger.info("身份资料文件 %s 已加载 %d 条身份", identity_path, len(entries))

        index = cls(entries=entries)
        index._build_indexes()
        return index

    def merge(self, other: "IdentityIndex") -> "IdentityIndex":
        """Return a new IdentityIndex with *other* overriding/adding to *self*."""
        overridden = set(other.by_qq)
        entries = []
        for entry in self.entries:
            remaining = [q for q in entry.qq_ids if q not in overridden]
            if remaining:
                entries.append(
                    IdentityEntry(
                        entry.canonical_name, remaining, list(entry.aliases), entry.note
                    )
                )
        result = IdentityIndex(entries=[*entries, *other.entries])
        result._build_indexes()
        return result

    def _build_indexes(self) -> None:
        self.by_qq.clear()
        self.by_alias.clear()
        self.by_name.clear()

        for entry in self.entries:
            if entry.canonical_name not in self.by_name:
                self.by_name[entry.canonical_name] = entry

            for qq_id in entry.qq_ids:
                if qq_id and qq_id not in self.by_qq:
                    self.by_qq[qq_id] = entry

            for alias in [entry.canonical_name, *entry.aliases]:
                alias = alias.strip()
                if alias and alias not in self.by_alias:
                    self.by_alias[alias] = entry

    def resolve_user(self, user_id: int | str, sender_name: str = "") -> IdentityMatch:
        user_key = str(user_id).strip()
        entry = self.by_qq.get(user_key)
        if entry is None:
            return IdentityMatch(
                user_id=user_key,
                sender_name=sender_name.strip(),
                canonical_name="",
            )

        return IdentityMatch(
            user_id=user_key,
            sender_name=sender_name.strip(),
            canonical_name=entry.canonical_name,
            aliases=list(entry.aliases),
            note=entry.note,
            is_registered=True,
        )

    def render_mention(self, user_id: int | str, fallback_name: str = "") -> str:
        """渲染 @ 提及文本：登记成员用标准身份，未登记用 ``fallback_name``
        （通常为群名片），两者皆无时退回 ``@QQ 号`` 数字形态。"""
        match = self.resolve_user(user_id)
        if match.is_registered and match.canonical_name:
            return f"@{match.canonical_name}"
        normalized = fallback_name.strip()
        if normalized:
            return f"@{normalized}"
        return f"@QQ{match.user_id}"

    def search(self, query: str, limit: int = 5) -> list[IdentityEntry]:
        normalized = query.strip()
        if not normalized:
            return []

        direct = self.by_qq.get(normalized)
        if direct is not None:
            return [direct]
        return [entry for entry in self.entries if normalized in entry.note or any(
            normalized in value or value in normalized
            for value in [entry.canonical_name, *entry.aliases, *entry.qq_ids]
            if value
        )][:limit]
