from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from plugins.llm_tools import LLMToolCall, LLMToolResult, LLMToolSpec, ToolExecutionContext


class ToolValidationError(ValueError):
    pass


ToolHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[str] | str]


@dataclass(slots=True)
class RegisteredTool:
    spec: LLMToolSpec
    handler: ToolHandler


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

    def register(self, spec: LLMToolSpec, handler: ToolHandler) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_specs(self, enabled_names: list[str] | None = None) -> list[LLMToolSpec]:
        if enabled_names is None:
            return [item.spec for item in self._tools.values()]
        enabled_set = {name.strip() for name in enabled_names if name.strip()}
        return [item.spec for item in self._tools.values() if item.spec.name in enabled_set]

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
