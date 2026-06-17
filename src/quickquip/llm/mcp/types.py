"""MCP data types, exceptions, and tool-manipulation helpers.

Holds the dataclasses (``MCPToolBinding``, ``MCPServerStatus``,
``MCPToolCallResult``), the ``MCPError`` exception, and the pure functions
for alias generation, tool filtering, schema extraction, and result
formatting. No transport, networking, or asyncio code lives here — this
module is safe to import from anywhere without pulling in subprocess or
httpx machinery.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


class MCPError(RuntimeError):
    pass


@dataclass(slots=True)
class MCPToolBinding:
    alias: str
    server_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class MCPServerStatus:
    id: str
    transport: str
    enabled: bool
    connected: bool = False
    tool_count: int = 0
    error: str | None = None
    detail: str = ""


@dataclass(slots=True)
class MCPToolCallResult:
    content: str
    is_error: bool = False


def _sanitize_tool_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    normalized = normalized.strip("_")
    return normalized or "tool"


def _build_tool_alias(server_id: str, tool_name: str, prefix: str | None = None) -> str:
    base_prefix = _sanitize_tool_name(prefix or server_id)
    base_tool = _sanitize_tool_name(tool_name)
    alias = f"mcp_{base_prefix}_{base_tool}"
    if len(alias) <= 64:
        return alias

    digest = hashlib.sha1(f"{server_id}:{tool_name}".encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    head = alias[: 64 - len(suffix)]
    return f"{head}{suffix}"


def _normalize_tool_filter(items: list[str]) -> set[str]:
    return {item.strip() for item in items if item.strip()}


def _tool_filter_matches(filters: set[str], *, tool_name: str, alias: str) -> bool:
    return tool_name in filters or alias in filters


def _schema_from_tool(raw_tool: dict[str, Any]) -> dict[str, Any]:
    for key in ("inputSchema", "input_schema"):
        schema = raw_tool.get(key)
        if isinstance(schema, dict):
            return schema
    return {"type": "object", "properties": {}}


def _text_from_content_block(item: dict[str, Any]) -> str:
    if item.get("type") == "text":
        return str(item.get("text", "")).strip()
    return ""


def _format_tool_result(payload: dict[str, Any]) -> MCPToolCallResult:
    parts: list[str] = []
    for item in payload.get("content", []) or []:
        if not isinstance(item, dict):
            continue
        text = _text_from_content_block(item)
        if text:
            parts.append(text)

    if not parts and payload.get("structuredContent") is not None:
        parts.append(json.dumps(payload["structuredContent"], ensure_ascii=False))

    if not parts and payload.get("content"):
        parts.append(json.dumps(payload["content"], ensure_ascii=False))

    content = "\n".join(part for part in parts if part).strip()
    return MCPToolCallResult(
        content=content or "MCP 工具未返回可显示内容。",
        is_error=bool(payload.get("isError", False)),
    )
