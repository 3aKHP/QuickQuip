from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass(slots=True)
class VocabEntry:
    name: str
    aliases: list[str]
    note: str = ""


@dataclass(slots=True)
class VocabMatch:
    name: str
    alias: str
    note: str = ""


@dataclass(slots=True)
class VocabIndex:
    entries: list[VocabEntry] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "VocabIndex":
        vocab_path = Path(path)
        if not vocab_path.exists():
            return cls()

        section = ""
        entries: list[VocabEntry] = []
        glossary: dict[str, str] = {}

        for raw_line in vocab_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue

            if not raw_line.startswith(" "):
                if ":" in raw_line:
                    section = raw_line.split(":", 1)[0].strip()
                continue

            if section in {"核心成员", "次核心成员", "次核心成员追加"}:
                match = re.match(r"^\s{2,}([^:]+):\s*\[(.*?)\]\s*(?:#\s*(.*))?$", raw_line)
                if not match:
                    continue
                name = match.group(1).strip()
                aliases_raw = match.group(2).strip()
                note = (match.group(3) or "").strip()
                aliases = [alias.strip() for alias in aliases_raw.split(",") if alias.strip()]
                entries.append(VocabEntry(name=name, aliases=aliases, note=note))
                continue

            if section == "部分黑话解析":
                match = re.match(r"^\s{2,}([^：:]+)[：:]\s*(.+)$", raw_line)
                if not match:
                    continue
                glossary[match.group(1).strip()] = match.group(2).strip()

        return cls(entries=entries, glossary=glossary)

    def find_matches(self, text: str, limit: int = 4) -> list[VocabMatch]:
        normalized = text.strip()
        if not normalized:
            return []

        matches: list[VocabMatch] = []
        seen_names: set[str] = set()

        literals: list[tuple[str, VocabEntry]] = []
        for entry in self.entries:
            for alias in [entry.name, *entry.aliases]:
                alias = alias.strip()
                if not alias or "*" in alias:
                    continue
                literals.append((alias, entry))

        literals.sort(key=lambda item: len(item[0]), reverse=True)
        for alias, entry in literals:
            if alias not in normalized:
                continue
            if entry.name in seen_names:
                continue
            matches.append(VocabMatch(name=entry.name, alias=alias, note=entry.note))
            seen_names.add(entry.name)
            if len(matches) >= limit:
                break

        return matches

    def merge(self, other: "VocabIndex") -> "VocabIndex":
        """Return a new VocabIndex with *other* overriding/adding to *self*."""
        merged_entries: dict[str, VocabEntry] = {e.name: e for e in self.entries}
        for entry in other.entries:
            merged_entries[entry.name] = entry
        merged_glossary = {**self.glossary, **other.glossary}
        return VocabIndex(entries=list(merged_entries.values()), glossary=merged_glossary)

    def find_glossary(self, text: str, limit: int = 3) -> list[tuple[str, str]]:
        normalized = text.strip()
        if not normalized:
            return []

        matches: list[tuple[str, str]] = []
        for term, meaning in sorted(self.glossary.items(), key=lambda item: len(item[0]), reverse=True):
            if term not in normalized:
                continue
            matches.append((term, meaning))
            if len(matches) >= limit:
                break
        return matches
