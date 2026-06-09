from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from quickquip.llm.tools import (
    LLMToolCall,
    LLMToolResult,
    LLMToolSpec,
    ToolExecutionContext,
    ToolManifestEntry,
)


class ToolValidationError(ValueError):
    pass


ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[str] | str]


@dataclass(slots=True)
class RegisteredTool:
    spec: LLMToolSpec
    handler: ToolHandler
    source: str = "builtin"
    category: str = ""
    keywords: list[str] | None = None
    always_loaded: bool = False


def _collect_schema_argument_names(schema: dict[str, Any]) -> list[str]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    return [str(name) for name in properties if str(name).strip()]


def _normalize_search_terms(text: str) -> list[str]:
    normalized = text.lower().replace("_", " ").replace("-", " ")
    terms = [part for part in normalized.split() if part]
    stripped = text.strip().lower()
    if stripped and stripped not in terms:
        terms.append(stripped)
    return terms


def _score_manifest_entry(entry: ToolManifestEntry, query: str, category: str = "") -> int:
    query_terms = _normalize_search_terms(query)
    if not query_terms:
        return 0

    category_filter = category.strip().lower()
    if category_filter:
        category_text = entry.category.lower()
        source_text = entry.source.lower()
        if category_filter not in category_text and category_filter not in source_text:
            return 0

    name_text = entry.name.lower().replace("_", " ")
    description_text = entry.description.lower()
    category_text = entry.category.lower()
    source_text = entry.source.lower()
    argument_text = " ".join(entry.argument_names).lower().replace("_", " ")
    keyword_text = " ".join(entry.keywords).lower().replace("_", " ")
    searchable_text = " ".join(
        [name_text, description_text, category_text, source_text, argument_text, keyword_text]
    )

    score = 0
    for term in query_terms:
        if term == entry.name.lower() or term == name_text:
            score += 120
        elif term in name_text:
            score += 80
        if term in keyword_text:
            score += 50
        if term in description_text:
            score += 35
        if term in argument_text:
            score += 25
        if term in category_text or term in source_text:
            score += 20
        if term in searchable_text:
            score += 5
    return score


def _is_type_match(expected_type: str, value: Any) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def validate_tool_arguments(schema: dict[str, Any], payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ToolValidationError("工具参数必须是对象")

    if schema.get("type") not in {None, "object"}:
        raise ToolValidationError("当前只支持 object 类型工具参数 schema")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict):
        properties = {}
    if not isinstance(required, list):
        required = []

    for key in required:
        if key not in payload:
            raise ToolValidationError(f"缺少必填字段：{key}")

    validated: dict[str, Any] = {}
    for key, value in payload.items():
        property_schema = properties.get(key, {})
        if not isinstance(property_schema, dict):
            property_schema = {}

        expected_type = property_schema.get("type")
        if isinstance(expected_type, str) and not _is_type_match(expected_type, value):
            raise ToolValidationError(f"字段 {key} 类型不匹配，应为 {expected_type}")

        enum_values = property_schema.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
            raise ToolValidationError(f"字段 {key} 不在允许范围内：{enum_values}")

        validated[key] = value

    return validated


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        spec: LLMToolSpec,
        handler: ToolHandler,
        *,
        source: str = "builtin",
        category: str = "",
        keywords: list[str] | None = None,
        always_loaded: bool = False,
    ) -> None:
        self._tools[spec.name] = RegisteredTool(
            spec=spec,
            handler=handler,
            source=source,
            category=category,
            keywords=list(keywords or []),
            always_loaded=always_loaded,
        )

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_specs(self, enabled_names: list[str] | None = None) -> list[LLMToolSpec]:
        if enabled_names is None:
            return [item.spec for item in self._tools.values()]
        enabled_set = {name.strip() for name in enabled_names if name.strip()}
        return [item.spec for item in self._tools.values() if item.spec.name in enabled_set]

    def get_specs(self, names: list[str]) -> list[LLMToolSpec]:
        specs: list[LLMToolSpec] = []
        seen: set[str] = set()
        for name in names:
            normalized = name.strip()
            if not normalized or normalized in seen:
                continue
            registered = self._tools.get(normalized)
            if registered is None:
                continue
            specs.append(registered.spec)
            seen.add(normalized)
        return specs

    def list_manifest(self, enabled_names: list[str] | None = None) -> list[ToolManifestEntry]:
        if enabled_names is None:
            tools = list(self._tools.values())
        else:
            enabled_set = {name.strip() for name in enabled_names if name.strip()}
            tools = [item for item in self._tools.values() if item.spec.name in enabled_set]
        return [
            ToolManifestEntry(
                name=item.spec.name,
                description=item.spec.description,
                source=item.source,
                category=item.category,
                keywords=list(item.keywords or []),
                argument_names=_collect_schema_argument_names(item.spec.input_schema),
                always_loaded=item.always_loaded,
            )
            for item in tools
        ]

    def list_groups(self, enabled_names: list[str] | None = None) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for entry in self.list_manifest(enabled_names):
            group_name = entry.category or entry.source or "builtin"
            group = groups.setdefault(
                group_name,
                {
                    "name": group_name,
                    "source": entry.source,
                    "tool_count": 0,
                    "sample_tools": [],
                },
            )
            group["tool_count"] += 1
            if len(group["sample_tools"]) < 5:
                group["sample_tools"].append(entry.name)
        return sorted(groups.values(), key=lambda item: str(item["name"]))

    def list_manifest_page(
        self,
        *,
        enabled_names: list[str] | None = None,
        group: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ToolManifestEntry], int]:
        group_filter = group.strip().lower()
        entries = self.list_manifest(enabled_names)
        if group_filter:
            entries = [
                item for item in entries
                if group_filter in (item.category or "").lower()
                or group_filter in item.source.lower()
            ]
        entries.sort(key=lambda item: item.name)
        total = len(entries)
        safe_limit = max(1, min(limit, 50))
        safe_page = max(1, page)
        start = (safe_page - 1) * safe_limit
        return entries[start:start + safe_limit], total

    def search_manifest(
        self,
        query: str,
        *,
        enabled_names: list[str] | None = None,
        exclude_names: list[str] | None = None,
        category: str = "",
        limit: int = 5,
    ) -> list[ToolManifestEntry]:
        excluded = {name.strip() for name in exclude_names or [] if name.strip()}
        scored: list[tuple[int, ToolManifestEntry]] = []
        for entry in self.list_manifest(enabled_names):
            if entry.name in excluded:
                continue
            score = _score_manifest_entry(entry, query, category)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [entry for _, entry in scored[: max(1, min(limit, 20))]]

    async def execute(self, call: LLMToolCall, context: ToolExecutionContext) -> LLMToolResult:
        registered = self._tools.get(call.name)
        if registered is None:
            return LLMToolResult(
                call_id=call.id,
                name=call.name,
                content=f"未知工具：{call.name}",
                is_error=True,
            )

        try:
            raw_args = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return LLMToolResult(
                call_id=call.id,
                name=call.name,
                content=f"工具参数 JSON 解析失败：{exc}",
                is_error=True,
            )

        try:
            arguments = validate_tool_arguments(registered.spec.input_schema, raw_args)
        except ToolValidationError as exc:
            return LLMToolResult(
                call_id=call.id,
                name=call.name,
                content=f"工具参数校验失败：{exc}",
                is_error=True,
            )

        try:
            result = registered.handler(arguments, context)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            return LLMToolResult(
                call_id=call.id,
                name=call.name,
                content=f"工具执行失败：{exc}",
                is_error=True,
            )

        return LLMToolResult(
            call_id=call.id,
            name=call.name,
            content=str(result).strip(),
            is_error=False,
        )
