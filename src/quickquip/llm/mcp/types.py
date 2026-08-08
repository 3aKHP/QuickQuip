"""MCP data types, exceptions, and tool-manipulation helpers.

Holds the dataclasses (``MCPToolBinding``, ``MCPServerStatus``,
``MCPToolCallResult``), the ``MCPError`` exception, and the pure functions
for alias generation, tool filtering, schema extraction, and result
formatting. No transport, networking, or asyncio code lives here — this
module is safe to import from anywhere without pulling in subprocess or
httpx machinery.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import warnings
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Literal
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

from quickquip.llm.tools import LLMInlineImage, LLMToolOutput


class MCPError(RuntimeError):
    def __init__(self, *args: Any, failure_kind: str = "", http_status: int = 0) -> None:
        super().__init__(*args)
        self.failure_kind = failure_kind
        self.http_status = http_status


class MCPStaleSessionError(MCPError):
    """Raised when a request carrying mcp-session-id receives HTTP 404.

    Indicates the server has discarded the session and a new legacy
    initialize is required.  Read-only requests may trigger a bounded
    reconnect; tools/call must NOT be replayed.
    """
    pass


class MCPLegacyFallbackSignal(MCPError):
    """Internal signal: auto probe detected a legacy server.

    Not a real failure — the caller (MCPClient._start_auto) should close
    the modern probe and fall back to legacy initialize.
    """
    pass


# Recognized modern JSON-RPC error codes that prove a server is modern
# (used by auto-negotiation to distinguish modern errors from legacy signals).
_RECOGNIZED_MODERN_ERROR_CODES = frozenset({-32022, -32020})


def _is_recognized_modern_error_body(body: bytes | str) -> bool:
    """Check whether an HTTP error body contains a recognized modern JSON-RPC error.

    Modern servers use 400 for UnsupportedProtocolVersionError (-32022) and
    HeaderMismatch (-32020).  If the body contains one of these, the server
    speaks modern MCP.  Otherwise (empty, HTML, or non-modern JSON-RPC), the
    caller should treat it as a legacy fallback signal.
    """
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return False
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    error = data.get("error")
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    return isinstance(code, (int, float)) and int(code) in _RECOGNIZED_MODERN_ERROR_CODES


# ---------------------------------------------------------------------------
# Failure classification (Wave 2)
# ---------------------------------------------------------------------------

MCP_FAILURE_CONFIG = "config"
MCP_FAILURE_PROBE = "probe"
MCP_FAILURE_LEGACY_HANDSHAKE = "legacy-handshake"
MCP_FAILURE_MODERN_NEGOTIATION = "modern-negotiation"
MCP_FAILURE_AUTH = "auth"
MCP_FAILURE_TIMEOUT = "timeout"
MCP_FAILURE_ROUTING = "routing"
MCP_FAILURE_TRANSPORT = "transport"

MCP_FAILURE_KINDS = frozenset({
    MCP_FAILURE_CONFIG,
    MCP_FAILURE_PROBE,
    MCP_FAILURE_LEGACY_HANDSHAKE,
    MCP_FAILURE_MODERN_NEGOTIATION,
    MCP_FAILURE_AUTH,
    MCP_FAILURE_TIMEOUT,
    MCP_FAILURE_ROUTING,
    MCP_FAILURE_TRANSPORT,
})


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
    negotiation: str = "legacy"
    era: str = "unknown"
    failure_kind: str = ""
    negotiated_protocol_version: str = ""


@dataclass(slots=True)
class MCPConnectionInfo:
    """Per-server connection state for dual-era MCP.

    ``configured_protocol_version`` is the legacy pin (from config) or the
    modern offer list joined as a string; ``negotiated_protocol_version``
    is the version actually agreed upon (empty until negotiation completes).

    ``generation`` increments on each reconnect so stale pending futures
    can be discarded.
    """

    server_id: str
    negotiation: str  # legacy | auto | modern
    era: str  # legacy | modern | unknown
    configured_protocol_version: str
    negotiated_protocol_version: str = ""
    session_id: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    server_info: dict[str, Any] | None = None
    generation: int = 0


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
        return self.format_content(undelivered_images=len(self.images))

    def format_content(
        self,
        *,
        undelivered_images: int = 0,
        omitted_images: int = 0,
        budget_omitted_images: int = 0,
    ) -> str:
        """Render safe text and bounded notices without raw MCP payloads."""
        parts = list(self.text)
        if not parts and self.structured_content is not None:
            parts.append(json.dumps(self.structured_content, ensure_ascii=False))

        if undelivered_images:
            parts.append(f"MCP 工具返回了 {undelivered_images} 个尚未交付的图片项。")
        if omitted_images:
            parts.append(f"MCP 工具省略了 {omitted_images} 个无效或超出限制的图片项。")
        if budget_omitted_images:
            parts.append(f"MCP 工具省略了 {budget_omitted_images} 个超出当前请求图片预算的图片项。")

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


def _detect_alias_conflicts(bindings: list[MCPToolBinding]) -> set[str]:
    """Return aliases that appear more than once across all bindings.

    Collisions can arise from ``_sanitize_tool_name`` normalization
    (e.g. ``a-b`` and ``a_b`` produce the same alias) or from identical
    tool names across different servers.  Callers should treat conflicting
    aliases as fail-closed: do not register any binding whose alias is in
    the returned set.
    """
    counts: dict[str, int] = {}
    for binding in bindings:
        counts[binding.alias] = counts.get(binding.alias, 0) + 1
    return {alias for alias, count in counts.items() if count > 1}


_MAX_SAFE_ERROR_LENGTH = 200
_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


def _sanitize_url(url: str) -> str:
    """Strip query string and fragment from a URL to prevent credential leakage.

    Tokens passed as URL query parameters (e.g. ``?key=...``) must never
    appear in status JSON, dashboards, or logs.  Non-absolute URLs (paths,
    commands) are returned unchanged.
    """
    if not isinstance(url, str) or not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme or not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _sanitize_error_message(exc: BaseException, *, limit: int = _MAX_SAFE_ERROR_LENGTH) -> str:
    """Remove URLs from exception messages for safe status/logging use.

    httpx ``RequestError`` string representations include the full request
    URL, which may carry credentials in the query string.
    """
    msg = str(exc)
    msg = _URL_PATTERN.sub("[url]", msg)
    return msg[:limit]


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


_SUPPORTED_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
})
_IMAGE_FORMAT_MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024


def _decode_image_candidate(candidate: MCPInlineImageCandidate) -> bytes | None:
    """Strictly decode and inspect one candidate without exposing its data."""
    encoded = candidate.data
    if not encoded or len(encoded) % 4:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", encoded):
        return None
    padding = len(encoded) - len(encoded.rstrip("="))
    if padding > 2 or (padding and "=" in encoded[:-padding]):
        return None
    estimated_size = (len(encoded) // 4) * 3 - padding
    if estimated_size > _MAX_INLINE_IMAGE_BYTES:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(decoded) > _MAX_INLINE_IMAGE_BYTES:
        return None
    if base64.b64encode(decoded).decode("ascii") != encoded:
        return None
    return decoded


def _validated_image(candidate: MCPInlineImageCandidate) -> bytes | None:
    declared_mime = candidate.mime_type.lower()
    if declared_mime not in _SUPPORTED_IMAGE_MIME_TYPES:
        return None
    decoded = _decode_image_candidate(candidate)
    if decoded is None:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(decoded)) as image:
                detected_mime = _IMAGE_FORMAT_MIME_TYPES.get(image.format or "")
                image.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        UnidentifiedImageError,
    ):
        return None
    if detected_mime != declared_mime:
        return None
    return decoded


def deliver_mcp_tool_result(
    result: MCPToolCallResult,
    *,
    server_id: str,
    tool_name: str,
) -> LLMToolOutput:
    """Validate MCP image candidates and prepare a bounded rich tool result."""
    if result.is_error:
        return LLMToolOutput(
            content=result.format_content(undelivered_images=len(result.images)),
            is_error=True,
        )

    images: list[LLMInlineImage] = []
    omitted_images = 0
    for candidate in result.images:
        if len(images) >= 5:
            omitted_images += 1
            continue
        decoded = _validated_image(candidate)
        if decoded is None:
            omitted_images += 1
            continue
        images.append(
            LLMInlineImage(
                data=decoded,
                media_type=candidate.mime_type.lower(),
                source_label=f"MCP/{_safe_metadata(server_id)}/{_safe_metadata(tool_name)} image {len(images) + 1}",
            )
        )
    return LLMToolOutput(
        content=result.format_content(omitted_images=omitted_images),
        images=images,
    )
