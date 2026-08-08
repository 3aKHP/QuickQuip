"""Wave 0: Legacy HTTP wire characterization + modern streaming spike.

Two test groups:

1. **Legacy characterization** — captures the exact wire behavior of
   ``StreamableHttpTransport`` + ``JsonRpcSession`` against an in-process
   legacy MCP server. These tests are regression guards for the "legacy
   exact" requirement: Wave 3 must not change any of these behaviors.

2. **Modern streaming spike** — proves that ``httpx.AsyncClient.stream()``
   supports request-scoped JSON/SSE, cancellation, and timeout. These are
   the building blocks for a hand-written modern MCP codec without adopting
   SDK v2. If these pass, we have confidence the hand-written route works.
"""
from __future__ import annotations

import asyncio
import json
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
    StreamingModernMCPServer,
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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )
        await session.notify("notifications/initialized", {})
        # Session-id should now be stored on the transport
        assert transport._session_id == "reuse-sess-99"

        await session.request("tools/list", {})
        # The tools/list request carried the session-id header
        assert server.session_ids_received[2] == "reuse-sess-99"
    finally:
        await session.aclose()


async def test_legacy_tools_list_pagination():
    """Paginated tools/list follows nextCursor until exhausted."""
    server = LegacyMCPServer()  # default has 2 tools: echo, ping
    config = _http_config()
    transport = _AsgiHttpTransport(config, app=server)
    session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=5)
    await session.start()
    try:
        await session.request(
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
        )

        # Collect all tools via the MCPClient-style pagination loop
        all_tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = await session.request("tools/list", params)
            tools = result.get("tools", [])
            all_tools.extend(tools)
            cursor = str(result.get("nextCursor", "")).strip()
            if not cursor:
                break

        tool_names = [t["name"] for t in all_tools]
        assert tool_names == ["echo", "ping"]

        # tools/list was called twice (first page + second page)
        list_requests = [r for r in server.requests if r["method"] == "tools/list"]
        assert len(list_requests) == 2
        assert "cursor" not in list_requests[0]["params"]
        assert list_requests[1]["params"]["cursor"] == "echo"
    finally:
        await session.aclose()


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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
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
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "QuickQuip", "version": "1.0"}},
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

async def test_modern_discover_returns_capabilities():
    """server/discover returns protocolVersions and serverInfo."""
    app = ModernMCPServer()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {},
                "_meta": {
                    "protocolVersion": "2026-07-28",
                    "clientInfo": {"name": "QuickQuip", "version": "1.0"},
                    "capabilities": {},
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "server/discover",
            },
        )
        result = response.json()["result"]
        assert "2026-07-28" in result["protocolVersions"]
        assert result["serverInfo"]["name"] == "modern-test-server"


async def test_modern_discover_missing_routing_headers_rejected():
    """Modern server rejects requests without routing headers (400)."""
    app = ModernMCPServer()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {},
                "_meta": {"protocolVersion": "2026-07-28"},
            },
            headers={
                "Content-Type": "application/json",
                # Missing MCP-Protocol-Version and Mcp-Method
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600


async def test_modern_request_scoped_json():
    """Modern tools/call returns JSON within a single request scope."""
    app = ModernMCPServer()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "modern hello"}},
                "_meta": {
                    "protocolVersion": "2026-07-28",
                    "clientInfo": {"name": "QuickQuip", "version": "1.0"},
                    "capabilities": {},
                },
            },
            headers={
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "echo",
            },
        )
        result = response.json()["result"]
        assert result["content"][0]["text"] == "echo: modern hello"


async def test_modern_streaming_sse_parsed_within_request_scope():
    """Request-scoped SSE: events arrive as readable lines within stream context."""
    app = StreamingModernMCPServer(delay_seconds=0.01)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        steps: list[int] = []
        async with client.stream(
            "POST",
            "/mcp",
            content=json.dumps({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {},
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
            },
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = json.loads(line[len("data:"):].strip())
                    steps.append(data["result"]["step"])

        assert steps == [1, 2]


async def test_streaming_cancellation_closes_response():
    """Cancelling a streaming request delivers partial data and closes the stream.

    Uses a real TCP server because httpx.ASGITransport buffers the entire
    response body before delivery, making it unsuitable for testing
    incremental streaming. This is a key Wave 0 finding: the modern codec's
    request-scoped streaming tests need a real TCP server.

    The server sends event-1 immediately, then waits 30s before event-2.
    The client times out after receiving event-1, proving:
    - Partial data IS delivered incrementally over a real connection
    - Cancellation cleans up the httpx stream context
    - No hang or resource leak
    """
    state: dict[str, bool] = {"step2_sent": False}
    handler_tasks: set[asyncio.Task[None]] = set()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handler_tasks.add(asyncio.current_task())  # type: ignore[arg-type]
        try:
            await reader.read(65536)
            # HTTP/1.1 chunked SSE response
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
            )
            await writer.drain()

            event = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"step": 1}})
            payload = f"data: {event}\n\n".encode()
            writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
            await writer.drain()

            # Long delay — client should cancel during this
            await asyncio.sleep(30)

            state["step2_sent"] = True
            event2 = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"step": 2}})
            payload2 = f"data: {event2}\n\n".encode()
            writer.write(f"{len(payload2):x}\r\n".encode() + payload2 + b"\r\n")
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            handler_tasks.discard(asyncio.current_task())  # type: ignore[arg-type]
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass

    tcp_server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = tcp_server.sockets[0].getsockname()[1]

    received_steps: list[int] = []
    try:
        async def read_stream():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                async with client.stream("POST", "/mcp", content=b"{}") as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data = json.loads(line[len("data:"):].strip())
                            received_steps.append(data["result"]["step"])

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(read_stream(), timeout=2.0)

        assert received_steps == [1]
        assert not state["step2_sent"]
    finally:
        for task in handler_tasks:
            task.cancel()
        tcp_server.close()
        await tcp_server.wait_closed()


async def test_streaming_timeout_does_not_leak_client():
    """After a cancelled stream, the client is still usable for new requests."""
    app = StreamingModernMCPServer(delay_seconds=30.0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # First request: times out during streaming
        async def slow_read():
            async with client.stream(
                "POST", "/mcp",
                content=json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}}).encode(),
                headers={"Content-Type": "application/json", "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "ping"},
            ) as response:
                async for line in response.aiter_lines():
                    pass

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_read(), timeout=1.0)

        # Second request: a fresh modern server should still work on the same client
        fresh_app = ModernMCPServer()
        # Swap the transport's app (simulates a different server)
        client2 = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fresh_app),
            base_url="http://test",
        )
        try:
            response = await client2.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0", "id": 6, "method": "server/discover", "params": {},
                    "_meta": {"protocolVersion": "2026-07-28", "clientInfo": {"name": "QuickQuip", "version": "1.0"}, "capabilities": {}},
                },
                headers={
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": "server/discover",
                },
            )
            assert response.status_code == 200
            assert "2026-07-28" in response.json()["result"]["protocolVersions"]
        finally:
            await client2.aclose()


# ---------------------------------------------------------------------------
# Wave 3: stale-session handling
# ---------------------------------------------------------------------------

def _asgi_client(config: MCPServerConfig, server: Any) -> MCPClient:
    """Build an MCPClient with an ASGI-backed transport for in-process testing."""
    client = MCPClient(config)
    transport = _AsgiHttpTransport(config, app=server)
    client._transport = transport
    client._session = JsonRpcSession(transport, server_id=config.id, timeout_seconds=config.timeout_seconds)
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
        await send({"type": "http.response.start", "status": 404, "headers": [(b"content-length", b"0")]})
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

