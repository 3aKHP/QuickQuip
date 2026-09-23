"""MCP 客户端与进程内 HTTP 服务的协议集成。

覆盖 legacy 初始化/会话复用、现代协商与路由、工具请求（含分页聚合）、
失效会话恢复及有副作用的调用禁止自动重放。
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from quickquip.llm.config import MCPServerConfig
from quickquip.llm.mcp.client import MCPClient
from quickquip.llm.mcp.jsonrpc import JsonRpcSession
from quickquip.llm.mcp.modern_session import ModernHttpSession
from quickquip.llm.mcp.transport import StreamableHttpTransport
from quickquip.llm.mcp.types import MCPError, MCPStaleSessionError

from tests.fixtures.mcp_http_fixtures import (
    LegacyMCPServer,
    ModernMCPServer,
    StaleSessionLegacyServer,
)


# ---------------------------------------------------------------------------
# Test helper: ASGI-backed StreamableHttpTransport
# ---------------------------------------------------------------------------

class _AsgiHttpTransport(StreamableHttpTransport):
    """StreamableHttpTransport backed by an in-process ASGI app.

    Overrides ``start()`` to wire ``httpx.ASGITransport`` instead of the
    network transport, enabling real HTTP wire tests without a TCP server.
    """

    def __init__(self, config: MCPServerConfig, *, app: Any) -> None:
        super().__init__(config)
        self._test_app = app

    async def start(self) -> None:
        if not self.config.url:
            raise MCPError(f"MCP server {self.config.id} 缺少 url")
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._test_app),
            base_url="http://testserver",
            headers=self.config.headers,
            timeout=self.config.timeout_seconds,
        )


def _http_config(**overrides) -> MCPServerConfig:
    defaults: dict[str, Any] = dict(
        id="wire-test",
        transport="http",
        url="http://testserver/mcp",
        timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


# ---------------------------------------------------------------------------
# Legacy wire characterization
# ---------------------------------------------------------------------------

async def test_legacy_initialize_sends_correct_request_and_stores_session():
    """initialize carries protocolVersion + clientInfo; session-id is stored."""
    server = LegacyMCPServer(session_id="test-session-abc")
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        result = await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        # notifications/initialized follows initialize (mirrors MCPClient._initialize)
        await session.notify("notifications/initialized", {})

        # Server responded with serverInfo
        assert result["serverInfo"]["name"] == "legacy-test-server"

        # The first request was initialize with correct params
        init_req = server.requests[0]
        assert init_req["method"] == "initialize"
        assert init_req["params"]["protocolVersion"] == "2025-03-26"
        assert init_req["params"]["clientInfo"]["name"] == "QuickQuip"

        # Second request was notifications/initialized (notification, no id)
        assert server.requests[1]["method"] == "notifications/initialized"

        # initialize request did NOT carry a session-id
        assert server.session_ids_received[0] == ""
    finally:
        await session.aclose()


async def test_legacy_session_id_is_reused_on_subsequent_requests():
    """After initialize, subsequent requests carry the returned mcp-session-id."""
    server = LegacyMCPServer(session_id="reuse-sess-99")
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        await session.notify("notifications/initialized", {})
        # Session-id should now be stored on the transport
        assert transport._session_id == "reuse-sess-99"

        await session.request("tools/list", {})
        # The tools/list request carried the session-id header
        assert server.session_ids_received[2] == "reuse-sess-99"
    finally:
        await session.aclose()


async def test_legacy_list_tools_paginates_until_exhausted():
    """MCPClient.list_tools follows nextCursor until the catalog is exhausted."""
    tools_catalog = [
        {"name": "echo", "description": "Echo back the input text.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "ping", "description": "Return pong.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "quack", "description": "Return quack.",
         "inputSchema": {"type": "object", "properties": {}}},
    ]
    server = LegacyMCPServer(tools=tools_catalog)
    config = _http_config()
    client = _asgi_client(config, server)
    await client._session.start()
    try:
        await client._initialize()

        tools = await client.list_tools()

        # All three tools collected across both pages, order preserved
        assert [t["name"] for t in tools] == ["echo", "ping", "quack"]
        # Wire saw exactly two tools/list: seed request, then cursor follow-up
        list_requests = [r for r in server.requests if r["method"] == "tools/list"]
        assert len(list_requests) == 2
        assert "cursor" not in list_requests[0]["params"]
        assert list_requests[1]["params"]["cursor"] == "echo"
    finally:
        await client.aclose()


async def test_legacy_tools_call_returns_text_content():
    """tools/call returns result with text content items."""
    server = LegacyMCPServer()
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        result = await session.request(
            "tools/call",
            {"name": "echo", "arguments": {"text": "hello world"}},
        )
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "echo: hello world"
    finally:
        await session.aclose()


async def test_legacy_sse_response_mode():
    """Inline SSE responses are parsed identically to JSON responses."""
    server = LegacyMCPServer(response_mode="sse")
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        result = await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        # SSE response still delivers the same result as JSON
        assert result["serverInfo"]["name"] == "legacy-test-server"
        assert result["protocolVersion"] == "2025-03-26"
    finally:
        await session.aclose()


async def test_legacy_notification_returns_no_response_body():
    """notifications/initialized gets a 204 / empty body, not a JSON-RPC envelope."""
    server = LegacyMCPServer()
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        # notify() should complete without raising (no response expected)
        await session.notify("notifications/initialized", {})

        # The notification was recorded
        notif_reqs = [r for r in server.requests if r["method"] == "notifications/initialized"]
        assert len(notif_reqs) == 1
    finally:
        await session.aclose()


async def test_legacy_unknown_method_returns_32601():
    """Legacy server returns -32601 for server/discover (proves legacy era)."""
    server = LegacyMCPServer()
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        with pytest.raises(MCPError):
            await session.request("server/discover", {})
    finally:
        await session.aclose()


async def test_legacy_requests_carry_no_modern_headers():
    """Legacy requests must NOT contain modern routing headers or _meta."""
    server = LegacyMCPServer()
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        init_headers = server.requests[0]["headers"]
        assert "mcp-protocol-version" not in init_headers
        assert "mcp-method" not in init_headers
        assert "mcp-name" not in init_headers
    finally:
        await session.aclose()


# ---------------------------------------------------------------------------
# Modern streaming spike
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Wave 3: stale-session handling
# ---------------------------------------------------------------------------

def _asgi_client(config: MCPServerConfig, server: Any) -> MCPClient:
    """Build an MCPClient with an ASGI-backed transport for in-process testing."""
    client = MCPClient(config)
    transport = _AsgiHttpTransport(config, app=server)
    client._transport = transport
    client._session = JsonRpcSession(
        transport, server_id=config.id, timeout_seconds=config.timeout_seconds
    )
    return client


async def test_stale_session_list_tools_reconnects():
    """Read-only tools/list triggers bounded reconnect on stale session 404."""
    server = StaleSessionLegacyServer()
    config = _http_config()
    client = _asgi_client(config, server)
    await client._session.start()

    # Initialize establishes session stale-sess-1
    await client._initialize()
    assert client._transport._session_id == "stale-sess-1"

    # Invalidate: subsequent requests with stale-sess-1 get 404
    server.invalidate_session()

    try:
        # list_tools should detect stale session, reconnect, and retry
        tools = await client.list_tools()
        assert len(tools) == 2  # default tools: echo, ping

        # After reconnect, session should be stale-sess-2
        assert client._transport._session_id == "stale-sess-2"
        assert client._connection_info.generation == 1
    finally:
        await client.aclose()


async def test_stale_session_call_tool_does_not_replay():
    """tools/call on stale session raises without replaying."""
    server = StaleSessionLegacyServer()
    config = _http_config()
    client = _asgi_client(config, server)
    await client._session.start()

    await client._initialize()
    # list_tools succeeds (session still valid)
    tools = await client.list_tools()
    assert len(tools) == 2

    # Invalidate session
    server.invalidate_session()

    try:
        # tools/call should fail WITHOUT replaying
        with pytest.raises(MCPError, match="未自动重放"):
            await client.call_tool("echo", {"text": "should-not-replay"})

        # Verify the server only saw ONE tools/call attempt (no replay)
        call_requests = [r for r in server.requests if r["method"] == "tools/call"]
        assert len(call_requests) == 1
    finally:
        await client.aclose()


async def test_transport_404_without_session_is_not_stale():
    """404 without a session-id is a plain HTTP error, not stale session."""

    async def always_404(scope, receive, send):
        if scope["type"] != "http":
            return
        await send(
            {"type": "http.response.start", "status": 404, "headers": [(b"content-length", b"0")]}
        )
        await send({"type": "http.response.body", "body": b""})

    config = _http_config()
    transport = _AsgiHttpTransport(config, app=always_404)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        # Direct request without prior initialize (no session-id)
        with pytest.raises(MCPError) as exc_info:
            await session.request("tools/list", {})
        # Should NOT be a stale-session error
        assert not isinstance(exc_info.value, MCPStaleSessionError)
    finally:
        await session.aclose()


# ---------------------------------------------------------------------------
# Wave 4: modern session and auto negotiation
# ---------------------------------------------------------------------------

def _patch_modern_asgi(monkeypatch, app: Any) -> None:
    """Patch ModernHttpSession.start to use ASGI transport for in-process testing."""
    async def _asgi_start(self: ModernHttpSession) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=self.config.headers,
            timeout=self.config.timeout_seconds,
        )
    monkeypatch.setattr(ModernHttpSession, "start", _asgi_start)


def _modern_config(**overrides: Any) -> MCPServerConfig:
    defaults: dict[str, Any] = dict(
        id="modern-test",
        transport="http",
        url="http://testserver/mcp",
        timeout_seconds=5.0,
        negotiation="modern",
        supported_protocol_versions=["2026-07-28"],
    )
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


async def test_modern_mode_discover_and_list(monkeypatch):
    """Modern negotiation: discover → list_tools through modern session."""
    app = ModernMCPServer()
    _patch_modern_asgi(monkeypatch, app)
    config = _modern_config()
    client = MCPClient(config)
    try:
        await client.start()
        assert client._is_modern
        assert client._connection_info.era == "modern"
        assert client.server_info == {"name": "modern-test-server", "version": "2.0.0"}
        assert client._connection_info.server_info == client.server_info
        assert client._connection_info.negotiated_protocol_version == "2026-07-28"

        tools = await client.list_tools()
        assert len(tools) == 2  # default tools: echo, ping
    finally:
        await client.aclose()


async def test_modern_mode_tools_call(monkeypatch):
    """Modern tools/call returns result through modern session."""
    app = ModernMCPServer()
    _patch_modern_asgi(monkeypatch, app)
    config = _modern_config()
    client = MCPClient(config)
    try:
        await client.start()
        result = await client.call_tool("echo", {"text": "modern hello"})
        assert result.text == ["echo: modern hello"]
    finally:
        await client.aclose()


async def test_modern_mode_accepts_pre_final_discovery_fields(monkeypatch):
    """Early 2026-07-28 servers remain usable through the draft fallback."""
    app = ModernMCPServer(draft_discovery=True)
    _patch_modern_asgi(monkeypatch, app)
    client = MCPClient(_modern_config())
    try:
        await client.start()
        assert client.server_info == {"name": "modern-test-server", "version": "2.0.0"}
        assert client.negotiated_protocol_version == "2026-07-28"
    finally:
        await client.aclose()


async def test_modern_request_carries_meta_and_headers(monkeypatch):
    """Modern requests include _meta, MCP-Protocol-Version, Mcp-Method, Mcp-Name."""
    app = ModernMCPServer()
    _patch_modern_asgi(monkeypatch, app)
    config = _modern_config()
    client = MCPClient(config)
    try:
        await client.start()
        await client.call_tool("echo", {"text": "check headers"})

        # Find the tools/call request
        call_req = next(r for r in app.requests if r["method"] == "tools/call")
        # _meta is inside params (per MCP 2026-07-28 spec)
        meta = call_req["params"]["_meta"]
        assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
        assert meta["io.modelcontextprotocol/clientInfo"]["name"] == "QuickQuip"
        # Routing headers
        headers = call_req["headers"]
        assert headers["mcp-protocol-version"] == "2026-07-28"
        assert headers["mcp-method"] == "tools/call"
        assert headers["mcp-name"] == "echo"
    finally:
        await client.aclose()


async def test_auto_falls_back_to_legacy(monkeypatch):
    """Auto negotiation falls back when probe detects legacy server."""
    app = LegacyMCPServer()  # returns -32601 for server/discover
    _patch_modern_asgi(monkeypatch, app)

    # Also patch legacy transport to use ASGI
    config = _modern_config(negotiation="auto")
    transport = _AsgiHttpTransport(config, app=app)

    client = MCPClient(config)
    client._transport = transport
    client._session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    try:
        await client.start()
        # Should have fallen back to legacy
        assert not client._is_modern
        assert client._connection_info.era == "legacy"

        tools = await client.list_tools()
        assert len(tools) == 2
    finally:
        await client.aclose()


async def test_auto_stays_modern(monkeypatch):
    """Auto negotiation stays modern when probe succeeds."""
    app = ModernMCPServer()
    _patch_modern_asgi(monkeypatch, app)
    config = _modern_config(negotiation="auto")
    client = MCPClient(config)
    try:
        await client.start()
        assert client._is_modern
        assert client._connection_info.era == "modern"
    finally:
        await client.aclose()


async def test_modern_version_mismatch_fails(monkeypatch):
    """Modern negotiation fails when no version intersection."""
    app = ModernMCPServer(protocol_versions=["2099-01-01"])
    _patch_modern_asgi(monkeypatch, app)
    config = _modern_config(supported_protocol_versions=["2026-07-28"])
    client = MCPClient(config)
    try:
        with pytest.raises(MCPError, match="无交集"):
            await client.start()
    finally:
        await client.aclose()
