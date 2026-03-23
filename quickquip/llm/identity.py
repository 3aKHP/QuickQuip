from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import ast


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


def _finalize_entry(section: str, payload: dict[str, object]) -> IdentityEntry | None:
    canonical_name = _parse_scalar(str(payload.get("canonical_name", ""))).strip()
    if not canonical_name:
        return None

    if section == "special_accounts":
        qq_ids = [_parse_scalar(str(payload.get("qq_id", ""))).strip()]
    else:
        qq_ids = _parse_list_value(payload.get("qq_ids"))

    qq_ids = [qq_id for qq_id in qq_ids if qq_id]
    aliases = _parse_list_value(payload.get("aliases"))
    note = _parse_scalar(str(payload.get("note", ""))).strip()
    if not qq_ids:
        return None

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
            return cls()

        section = ""
        current: dict[str, object] | None = None
        current_list_key: str | None = None
        entries: list[IdentityEntry] = []

        for raw_line in identity_path.read_text(encoding="utf-8").splitlines():
            cleaned = _strip_inline_comment(raw_line)
            if not cleaned.strip():
                continue

            indent = len(cleaned) - len(cleaned.lstrip(" "))
            stripped = cleaned.strip()

            if indent == 0 and stripped.endswith(":"):
                if current is not None and section in {"people", "special_accounts"}:
                    entry = _finalize_entry(section, current)
                    if entry is not None:
                        entries.append(entry)
                section = stripped[:-1].strip()
                current = None
                current_list_key = None
                continue

            if section not in {"people", "special_accounts"}:
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

        if current is not None and section in {"people", "special_accounts"}:
            entry = _finalize_entry(section, current)
            if entry is not None:
                entries.append(entry)

        index = cls(entries=entries)
        index._build_indexes()
        return index

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

    def render_mention(self, user_id: int | str) -> str:
        match = self.resolve_user(user_id)
        if match.is_registered and match.canonical_name:
            return f"@{match.canonical_name}"
        return f"@QQ{match.user_id}"

    def search(self, query: str, limit: int = 5) -> list[IdentityEntry]:
        normalized = query.strip()
        if not normalized:
            return []

        results: list[IdentityEntry] = []
        seen_names: set[str] = set()

        direct = self.by_qq.get(normalized)
        if direct is not None:
            return [direct]

        for alias, entry in sorted(self.by_alias.items(), key=lambda item: len(item[0]), reverse=True):
            if alias not in normalized:
                continue
            if entry.canonical_name in seen_names:
                continue
            results.append(entry)
            seen_names.add(entry.canonical_name)
            if len(results) >= limit:
                return results

        for entry in self.entries:
            if entry.canonical_name in seen_names:
                continue
            haystacks = [entry.canonical_name, *entry.aliases, entry.note, *entry.qq_ids]
            if any(normalized in str(item) for item in haystacks if str(item).strip()):
                results.append(entry)
                seen_names.add(entry.canonical_name)
                if len(results) >= limit:
                    break

        return results
