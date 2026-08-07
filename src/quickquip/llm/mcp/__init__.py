"""MCP (Model Context Protocol) client package.

Split from the former monolithic ``mcp.py`` into:
- :mod:`.types` — dataclasses, exception, alias/filter/schema helpers
- :mod:`.transport` — Transport ABC + Stdio/StreamableHttp/Sse + SSE parsing
- :mod:`.jsonrpc` — JsonRpcSession (JSON-RPC 2.0 over any Transport)
- :mod:`.client` — MCPClient + MCPClientManager + _build_transport

This ``__init__`` re-exports the public surface so that
``from quickquip.llm.mcp import X`` continues to work unchanged.
"""
from __future__ import annotations

from quickquip.llm.mcp.types import (
    MCPError,
    MCPDeferredContentCandidate,
    MCPInlineImageCandidate,
    MCPResultDiagnostic,
    MCPToolBinding,
    MCPServerStatus,
    MCPToolCallResult,
    deliver_mcp_tool_result,
)
from quickquip.llm.mcp.transport import (
    SseTransport,
    StdioTransport,
    StreamableHttpTransport,
    Transport,
)
from quickquip.llm.mcp.jsonrpc import JsonRpcSession
from quickquip.llm.mcp.client import MCPClient, MCPClientManager

__all__ = [
    "MCPClient",
    "MCPClientManager",
    "MCPError",
    "MCPInlineImageCandidate",
    "MCPDeferredContentCandidate",
    "MCPResultDiagnostic",
    "MCPToolBinding",
    "MCPServerStatus",
    "MCPToolCallResult",
    "deliver_mcp_tool_result",
    "Transport",
    "StdioTransport",
    "StreamableHttpTransport",
    "SseTransport",
    "JsonRpcSession",
]
