"""Process-local identity snapshots, independent of the model runtime."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from quickquip.common.identity import IdentityIndex
from quickquip.common.paths import LLM_IDENTITIES_YAML_PATH, STATS_JSON_PATH

logger = logging.getLogger(__name__)


@dataclass
class IdentitySnapshot:
    index: IdentityIndex = field(default_factory=IdentityIndex)
    names: dict[str, str] = field(default_factory=dict)

    def name(self, qq, snapshot="") -> str:
        qq = str(qq or "")
        registered = self.index.resolve_user(qq).canonical_name
        for value in (registered, self.names.get(qq), snapshot):
            name = str(value or "").strip()
            if name and name != "未知" and name != qq and name != f"QQ{qq}":
                return name
        return f"QQ{qq}"

    def candidates(self, query: str) -> set[str]:
        query = query.strip().removeprefix("@")
        if query.startswith("QQ") and query[2:].isascii() and query[2:].isdigit():
            query = query[2:]
        if query.isascii() and query.isdigit():
            return {query}
        result = set()
        for entry in self.index.entries:
            if query in [entry.canonical_name, *entry.aliases, *entry.qq_ids]:
                result.update(q for q in entry.qq_ids if self.index.by_qq.get(q) is entry)
        result.update(q for q, name in self.names.items() if name == query)
        return result


    def ambiguous(self, candidates: set[str]) -> bool:
        """Distinct entries are distinct people; one entry may own multiple QQs."""
        people = set()
        for qq in candidates:
            entry = self.index.by_qq.get(qq)
            people.add(("entry", id(entry)) if entry is not None else ("qq", qq))
        return len(people) > 1


class IdentityRepository:
    def __init__(self, path=LLM_IDENTITIES_YAML_PATH, stats_path=STATS_JSON_PATH):
        self.path, self.stats_path = Path(path), Path(stats_path)
        self._files = OrderedDict()
        self._merged = OrderedDict()
        self._base_override: IdentityIndex | None = None
        self._lock = threading.RLock()
        self.names_provider = None

    def set_base_index(self, index: IdentityIndex):
        """Compatibility replacement, owned by the repository until explicit reload."""
        with self._lock:
            self._base_override = index
            self._merged.clear()

    def invalidate(self):
        with self._lock:
            self._base_override = None
            self._merged.clear()
            for key, (_, stamp, value) in list(self._files.items()):
                self._files[key] = (float("-inf"), object(), value)

    def _read(self, path, loader, empty):
        now = time.monotonic()
        last, stamp, value = self._files.get(path, (float("-inf"), None, empty))
        if now - last < 5:
            return value
        try:
            new_stamp = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
            if new_stamp != stamp:
                value = loader(path) if new_stamp else empty
                stamp = new_stamp
        except Exception:
            logger.exception("身份快照加载失败，保留上次有效数据：%s", path)
        self._files[path] = (now, stamp, value)
        self._files.move_to_end(path)
        if len(self._files) > 1024:
            self._files.popitem(last=False)
        return value

    def snapshot(self, scope) -> IdentitySnapshot:
        scope = str(scope)
        with self._lock:
            index = self._base_override if self._base_override is not None else self._read(self.path, _load_index, IdentityIndex())
            if scope.isascii() and scope.isdigit():
                group = self._read(self.path.parent / scope / "identities.yaml", _load_index, IdentityIndex())
                cached = self._merged.get(scope)
                if cached is None or cached[0] is not index or cached[1] is not group:
                    cached = (index, group, index.merge(group))
                    self._merged[scope] = cached
                self._merged.move_to_end(scope)
                if len(self._merged) > 512:
                    self._merged.popitem(last=False)
                index = cached[2]
            stats = self._read(self.stats_path, _load_stats, {})
            names = dict(stats.get(scope, {}).get("user_names", {}))
            if self.names_provider and not scope.startswith("private:"):
                names.update(self.names_provider(scope) or {})
            return IdentitySnapshot(index, names)


def _is_placeholder_entry(entry: dict) -> bool:
    """模板占位条目：标准名与 QQ 号均未填写，按不存在处理。"""
    if str(entry.get("canonical_name") or "").strip():
        return False
    ids = entry.get("qq_ids")
    if isinstance(ids, str):
        ids = [ids]
    if any(str(q).strip() for q in (ids or [])):
        return False
    return not str(entry.get("qq_id") or "").strip()


def _declares_substantive_entries(data) -> bool:
    for section in ("people", "special_accounts"):
        for entry in (data or {}).get(section, []) or []:
            if not _is_placeholder_entry(entry):
                return True
    return False


def _load_index(path):
    # Validate the document before the compatibility parser; incomplete writes must not replace a valid index.
    import yaml
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is not None and not isinstance(data, dict):
        raise ValueError("identity document must be a mapping")
    for section in ("people", "special_accounts"):
        entries = (data or {}).get(section, []) or []
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError("identity entries must be mappings in a list")
    index = IdentityIndex.from_text(raw, path)
    if _declares_substantive_entries(data) and not index.entries:
        raise ValueError("identity document contains no valid entries")
    return index


def _load_stats(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("stats must be a mapping")
    for group in data.values():
        if not isinstance(group, dict) or not isinstance(group.get("user_names", {}), dict):
            raise ValueError("group stats must contain a user_names mapping")
        if any(not isinstance(name, str) for name in group.get("user_names", {}).values()):
            raise ValueError("member names must be strings")
    return data


identities = IdentityRepository()
