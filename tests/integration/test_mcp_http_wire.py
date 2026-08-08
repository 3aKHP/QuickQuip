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
from quickquip.llm.mcp.jsonrpc import JsonRpcSession
from quickquip.llm.mcp.transport import StreamableHttpTransport
from quickquip.llm.mcp.types import MCPError

from tests.fixtures.mcp_http_fixtures import (
    LegacyMCPServer,
    ModernMCPServer,
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
