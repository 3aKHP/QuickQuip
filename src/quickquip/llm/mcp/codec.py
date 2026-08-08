"""Modern MCP (2026-07-28) request/response codec.

Pure functions for building modern JSON-RPC requests with ``_meta``,
routing headers (``MCP-Protocol-Version``, ``Mcp-Method``, ``Mcp-Name``),
modern error classification, and response parsing.  No networking or
asyncio — safe to import from anywhere.
"""
from __future__ import annotations

import json
from typing import Any

from quickquip.llm.mcp.types import MCPError

_CLIENT_INFO: dict[str, str] = {"name": "QuickQuip", "version": "1.0"}

_META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
_META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
_META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

# Methods that require Mcp-Name header (from params.name or params.uri)
_METHODS_WITH_NAME_HEADER = frozenset({"tools/call", "resources/read", "prompts/get"})

# Recognized modern JSON-RPC error codes that prove a server is modern
# (used by auto-negotiation to distinguish modern errors from legacy signals).
_RECOGNIZED_MODERN_ERROR_CODES = frozenset({-32022, -32020})


def is_recognized_modern_error_body(body: bytes | str) -> bool:
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


def build_meta(protocol_version: str) -> dict[str, Any]:
    """Build the ``_meta`` dict carried inside ``params``."""
    return {
        _META_PROTOCOL_VERSION: protocol_version,
        _META_CLIENT_INFO: dict(_CLIENT_INFO),
        _META_CLIENT_CAPABILITIES: {},
    }


def build_modern_body(
    method: str,
    params: dict[str, Any],
    request_id: int,
    protocol_version: str,
) -> dict[str, Any]:
    """Build a modern JSON-RPC request body with ``_meta`` injected into params."""
    merged_params: dict[str, Any] = dict(params)
    merged_params["_meta"] = build_meta(protocol_version)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": merged_params,
    }


def build_routing_headers(
    method: str,
    params: dict[str, Any],
    protocol_version: str,
) -> dict[str, str]:
    """Build modern routing headers.

    ``MCP-Protocol-Version`` and ``Mcp-Method`` are always required.
    ``Mcp-Name`` is required for tools/call, resources/read, prompts/get
    (sourced from ``params.name`` or ``params.uri``).
    """
    headers: dict[str, str] = {
        "MCP-Protocol-Version": protocol_version,
        "Mcp-Method": method,
    }
    if method in _METHODS_WITH_NAME_HEADER:
        name = params.get("name") or params.get("uri") or ""
        if isinstance(name, str) and name:
            headers["Mcp-Name"] = name
    return headers


def detect_input_required(result: dict[str, Any]) -> bool:
    """Check whether a modern result is an InputRequiredResult (MRTR).

    QuickQuip does not implement MRTR in the first dual-era release.
    Detected results are surfaced as unsupported.
    """
    return bool(result.get("inputRequests"))


def parse_response_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``result`` dict from a JSON-RPC response envelope.

    Raises MCPError if the envelope contains an ``error``.
    """
    if "error" in data:
        error = data.get("error", {})
        detail = error.get("message", "未知错误") if isinstance(error, dict) else str(error)
        raise MCPError(str(detail))
    result = data.get("result", {})
    return result if isinstance(result, dict) else {}


def parse_sse_response(text: str) -> dict[str, Any]:
    """Parse an SSE response body and return the final JSON-RPC result.

    Reuses ``_parse_sse_block`` from transport to avoid duplicating the
    SSE body parser.  Returns the last envelope containing ``result`` or
    ``error``; earlier notifications are skipped.
    """
    from quickquip.llm.mcp.transport import _parse_sse_block

    envelopes = _parse_sse_block(text)
    for env in reversed(envelopes):
        if "result" in env or "error" in env:
            return parse_response_envelope(env)
    raise MCPError("SSE 流中未找到 JSON-RPC 响应")
