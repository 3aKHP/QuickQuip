"""Dynamic tool discovery state for the tool-call loop.

Owns the mutable `loaded_names` set and the two meta-tool handlers
(`tool_search` / `tool_list`) that grow it. The loop only asks
`is_loaded` / `loaded_specs` and forwards the model's meta-tool calls;
the loaded set has this single owner.
"""

from __future__ import annotations

import json


class ToolDiscovery:
    """Per-run tool discovery/loading state."""

    def __init__(
        self,
        *,
        enabled: bool,
        tool_registry,
        tool_search_name: str,
        tool_list_name: str,
        enabled_tool_names: list[str] | None,
        initial_tool_names: list[str] | None,
        search_limit: int,
        max_loaded_tools: int,
        request_tools,
    ):
        self.enabled = enabled
        self._tool_registry = tool_registry
        self._tool_search_name = tool_search_name
        self._tool_list_name = tool_list_name
        self._enabled_names = [name for name in enabled_tool_names or [] if name.strip()]
        loaded_names = [name for name in initial_tool_names or [] if name.strip()]
        if not loaded_names:
            loaded_names = [spec.name for spec in request_tools]
        self._loaded_names = loaded_names
        self._max_loaded_tools = max(1, min(max_loaded_tools, 64))
        self._search_limit = max(1, min(search_limit, 20))

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded_names

    def loaded_specs(self, fallback_tools):
        if not self.enabled:
            return fallback_tools
        return self._tool_registry.get_specs(self._loaded_names)

    def _append_loaded_tool(self, name: str) -> bool:
        if name in self._loaded_names:
            return False
        if self._enabled_names and name not in self._enabled_names:
            return False
        if len(self._loaded_names) >= self._max_loaded_tools:
            return False
        self._loaded_names.append(name)
        return True

    def load_from_search_call(self, call) -> list[str]:
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError:
            return []
        query = str(arguments.get("query", "")).strip()
        category = str(arguments.get("category", "")).strip()
        try:
            limit = int(arguments.get("limit", self._search_limit) or self._search_limit)
        except (TypeError, ValueError):
            limit = self._search_limit
        matches = self._tool_registry.search_manifest(
            query,
            enabled_names=self._enabled_names or None,
            exclude_names=[self._tool_search_name],
            category=category,
            limit=max(1, min(limit, self._search_limit)),
        )
        loaded: list[str] = []
        for entry in matches:
            if self._append_loaded_tool(entry.name):
                loaded.append(entry.name)
        return loaded

    def load_from_list_call(self, call) -> list[str]:
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError:
            return []
        mode = str(arguments.get("mode", "")).strip().lower()
        if mode != "load":
            return []
        raw_names = arguments.get("names", [])
        if not isinstance(raw_names, list):
            return []
        loaded: list[str] = []
        for raw_name in raw_names[:self._search_limit]:
            name = str(raw_name).strip()
            if not name or name == self._tool_list_name or name == self._tool_search_name:
                continue
            if not self._tool_registry.has_tool(name):
                continue
            if self._append_loaded_tool(name):
                loaded.append(name)
        return loaded
