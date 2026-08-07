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
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit


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
class MCPInlineImageCandidate:
    """Unvalidated MCP image data, retained only for the delivery boundary."""

    content_index: int
    data: str = field(repr=False)
    mime_type: str


@dataclass(slots=True)
class MCPDeferredContentCandidate:
    """Safe metadata for non-image content that is not delivered yet."""

    kind: Literal["resource", "audio", "link"]
    content_index: int
    mime_type: str = ""
    scheme: str = ""
    has_text: bool = False
    has_blob: bool = False


@dataclass(slots=True)
class MCPResultDiagnostic:
    code: Literal[
        "invalid-response",
        "invalid-content-item",
        "invalid-image",
        "unknown-content-type",
    ]
    content_index: int | None = None
    declared_type: str = ""


@dataclass(slots=True)
class MCPToolCallResult:
    """Type-safe MCP tool result, with display formatting kept at this boundary."""

    text: list[str] = field(default_factory=list)
    structured_content: Any | None = None
    images: list[MCPInlineImageCandidate] = field(default_factory=list)
    deferred: list[MCPDeferredContentCandidate] = field(default_factory=list)
    diagnostics: list[MCPResultDiagnostic] = field(default_factory=list)
    is_error: bool = False

    @property
    def content(self) -> str:
        """Render safe text and bounded notices without serializing raw content items."""
        parts = list(self.text)
        if not parts and self.structured_content is not None:
            parts.append(json.dumps(self.structured_content, ensure_ascii=False))

        if self.images:
            parts.append(f"MCP 工具返回了 {len(self.images)} 个尚未交付的图片项。")

        for kind in ("resource", "audio", "link"):
            count = sum(1 for item in self.deferred if item.kind == kind)
            if count:
                parts.append(f"MCP 工具省略了尚未支持的内容：{count} 个 {kind} 项。")

        if self.diagnostics:
            parts.append(f"MCP 工具省略了 {len(self.diagnostics)} 个格式错误或未知的内容项。")

        return "\n".join(part for part in parts if part).strip() or "MCP 工具未返回可显示内容。"


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


def _safe_metadata(value: Any, *, limit: int = 64) -> str:
    """Keep only bounded label-like metadata out of untrusted MCP values."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._/+:-]+", "_", value.strip())
    return cleaned[:limit]


def _uri_scheme(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        scheme = urlsplit(value).scheme
    except ValueError:
        return ""
    return _safe_metadata(scheme, limit=24)


def _mime_type_from(item: dict[str, Any]) -> str:
    return _safe_metadata(item.get("mimeType", item.get("mime_type", "")))


def _format_tool_result(payload: dict[str, Any]) -> MCPToolCallResult:
    result = MCPToolCallResult(
        structured_content=payload.get("structuredContent"),
        is_error=bool(payload.get("isError", False)),
    )
    raw_content = payload.get("content", [])
    if raw_content is None:
        raw_content = []
    if not isinstance(raw_content, list):
        result.diagnostics.append(MCPResultDiagnostic(code="invalid-response"))
        return result

    for index, item in enumerate(raw_content):
        if not isinstance(item, dict):
            result.diagnostics.append(
                MCPResultDiagnostic(code="invalid-content-item", content_index=index)
            )
            continue

        declared_type = item.get("type")
        if not isinstance(declared_type, str):
            result.diagnostics.append(
                MCPResultDiagnostic(code="invalid-content-item", content_index=index)
            )
            continue

        if declared_type == "text":
            text = item.get("text")
            if isinstance(text, str):
                normalized = text.strip()
                if normalized:
                    result.text.append(normalized)
            else:
                result.diagnostics.append(
                    MCPResultDiagnostic(code="invalid-content-item", content_index=index)
                )
            continue

        if declared_type == "image":
            data = item.get("data")
            mime_type = _mime_type_from(item)
            if isinstance(data, str) and data and mime_type:
                result.images.append(
                    MCPInlineImageCandidate(
                        content_index=index,
                        data=data,
                        mime_type=mime_type,
                    )
                )
            else:
                result.diagnostics.append(
                    MCPResultDiagnostic(code="invalid-image", content_index=index)
                )
            continue

        if declared_type == "resource":
            resource = item.get("resource")
            if not isinstance(resource, dict):
                result.diagnostics.append(
                    MCPResultDiagnostic(code="invalid-content-item", content_index=index)
                )
                continue
            result.deferred.append(
                MCPDeferredContentCandidate(
                    kind="resource",
                    content_index=index,
                    mime_type=_mime_type_from(resource),
                    scheme=_uri_scheme(resource.get("uri")),
                    has_text=isinstance(resource.get("text"), str),
                    has_blob=isinstance(resource.get("blob"), str),
                )
            )
            continue

        if declared_type == "audio":
            result.deferred.append(
                MCPDeferredContentCandidate(
                    kind="audio", content_index=index, mime_type=_mime_type_from(item)
                )
            )
            continue

        if declared_type in {"resource_link", "link", "url"}:
            result.deferred.append(
                MCPDeferredContentCandidate(
                    kind="link",
                    content_index=index,
                    mime_type=_mime_type_from(item),
                    scheme=_uri_scheme(item.get("uri", item.get("url"))),
                )
            )
            continue

        result.diagnostics.append(
            MCPResultDiagnostic(
                code="unknown-content-type",
                content_index=index,
                declared_type=_safe_metadata(declared_type),
            )
        )

    return result
