"""In-process MCP HTTP server fixtures for wire-level testing.

Two ASGI-callable servers:

- :class:`LegacyMCPServer` — legacy (initialize/session) MCP Streamable HTTP.
  Records every received request for assertion and supports JSON / inline-SSE /
  204 responses, session-id creation, and ``-32601`` for unknown methods.

- :class:`ModernMCPServer` — modern (2026-07-28 ``server/discover``) MCP.
  Records requests, validates ``_meta`` / routing headers, and supports
  request-scoped SSE streaming.

These are intentionally minimal for Wave 0; later waves extend them with
stale-session 404, version mismatch, auth failures, ``input_required``
downgrade, and other edge cases.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal


# ---------------------------------------------------------------------------
# ASGI helpers
# ---------------------------------------------------------------------------

async def _read_body(receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            more = message.get("more_body", False)
        elif message["type"] == "http.disconnect":
            break
    return body


def _header_dict(scope: dict[str, Any]) -> dict[str, str]:
    return {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", [])
    }


async def _send_json(
    send,
    *,
    status: int,
    body_dict: dict[str, Any],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(body_dict).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_sse(
    send,
    *,
    envelope: dict[str, Any],
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = f"data: {json.dumps(envelope)}\n\n".encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"text/event-stream"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _send_no_content(send) -> None:
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _send_error(
    send,
    *,
    status: int,
    message: str = "",
) -> None:
    body = message.encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"text/plain"),
        (b"content-length", str(len(body)).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Legacy MCP server
# ---------------------------------------------------------------------------

_DEFAULT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Echo back the input text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "ping",
        "description": "Return pong.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class LegacyMCPServer:
    """Minimal legacy MCP Streamable HTTP server (ASGI callable).

    Tracks received requests in ``self.requests`` for assertion.  Creates a
    ``mcp-session-id`` on ``initialize`` and expects it on subsequent requests.
    Supports JSON and inline-SSE response modes via ``response_mode``.
    """

    def __init__(
        self,
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "legacy-sess-1",
        response_mode: Literal["json", "sse"] = "json",
    ) -> None:
        self._tools = tools if tools is not None else list(_DEFAULT_TOOLS)
        self._session_id = session_id
        self._response_mode = response_mode
        self.requests: list[dict[str, Any]] = []
        self.session_ids_received: list[str] = []

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        body = await _read_body(receive)
        headers = _header_dict(scope)
        payload: dict[str, Any] = json.loads(body) if body else {}
        method = payload.get("method", "")
        request_id = payload.get("id")
        params = payload.get("params", {})

        self.requests.append({"method": method, "params": params, "headers": headers})
        self.session_ids_received.append(headers.get("mcp-session-id", ""))

        session_header: list[tuple[bytes, bytes]] = [
            (b"mcp-session-id", self._session_id.encode())
        ]

        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legacy-test-server", "version": "1.0.0"},
            }
            envelope = {"jsonrpc": "2.0", "id": request_id, "result": result}
            if self._response_mode == "sse":
                await _send_sse(send, envelope=envelope, extra_headers=session_header)
            else:
                await _send_json(send, status=200, body_dict=envelope, extra_headers=session_header)
            return

        if method == "notifications/initialized":
            await _send_no_content(send)
            return

        if method == "tools/list":
            cursor = params.get("cursor")
            if cursor:
                # Second page or beyond — return remaining tools, no nextCursor.
                tools_page = [t for t in self._tools if t["name"] > cursor]
            elif len(self._tools) > 1:
                # First page — return first tool with a nextCursor.
                tools_page = [self._tools[0]]
            else:
                tools_page = list(self._tools)
            result: dict[str, Any] = {"tools": tools_page}
            if tools_page and len(self._tools) > 1 and not cursor:
                result["nextCursor"] = tools_page[-1]["name"]
            envelope = {"jsonrpc": "2.0", "id": request_id, "result": result}
            if self._response_mode == "sse":
                await _send_sse(send, envelope=envelope, extra_headers=session_header)
            else:
                await _send_json(send, status=200, body_dict=envelope, extra_headers=session_header)
            return

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            if tool_name == "echo":
                text = arguments.get("text", "")
                content = [{"type": "text", "text": f"echo: {text}"}]
            elif tool_name == "ping":
                content = [{"type": "text", "text": "pong"}]
            else:
                content = [{"type": "text", "text": f"unknown tool: {tool_name}"}]
            envelope = {"jsonrpc": "2.0", "id": request_id, "result": {"content": content}}
            if self._response_mode == "sse":
                await _send_sse(send, envelope=envelope, extra_headers=session_header)
            else:
                await _send_json(send, status=200, body_dict=envelope, extra_headers=session_header)
            return

        # Unknown method (e.g. server/discover) → JSON-RPC -32601
        envelope = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
        await _send_json(send, status=200, body_dict=envelope)


# ---------------------------------------------------------------------------
# Modern MCP server
# ---------------------------------------------------------------------------

class StaleSessionLegacyServer:
    """Legacy server with controllable session invalidation.

    Issues a fresh ``mcp-session-id`` on each ``initialize``.  When
    ``invalidate_session()`` is called, all non-initialize requests with
    the previous session-id receive HTTP 404, simulating server-side
    session expiry.  This lets tests verify stale-session reconnect
    (read-only retry) and no-replay (tools/call) behavior.
    """

    def __init__(self) -> None:
        self._init_count = 0
        self._invalidated = False
        self.requests: list[dict[str, Any]] = []

    def invalidate_session(self) -> None:
        self._invalidated = True

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        body = await _read_body(receive)
        headers = _header_dict(scope)
        payload: dict[str, Any] = json.loads(body) if body else {}
        method = payload.get("method", "")
        request_id = payload.get("id")
        session_id = headers.get("mcp-session-id", "")

        self.requests.append({"method": method, "session_id": session_id})

        if method == "initialize":
            self._init_count += 1
            self._invalidated = False
            new_session = f"stale-sess-{self._init_count}"
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stale-test", "version": "1.0"},
                },
            }, extra_headers=[(b"mcp-session-id", new_session.encode())])
            return

        if method == "notifications/initialized":
            await _send_no_content(send)
            return

        if self._invalidated and session_id:
            await _send_error(send, status=404, message="Session expired")
            return

        if method == "tools/list":
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id,
                "result": {"tools": _DEFAULT_TOOLS},
            }, extra_headers=[(b"mcp-session-id", session_id.encode())])
            return

        if method == "tools/call":
            arguments = payload.get("params", {}).get("arguments", {})
            text = arguments.get("text", "")
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": f"echo: {text}"}]},
            }, extra_headers=[(b"mcp-session-id", session_id.encode())])
            return


class ModernMCPServer:
    """Minimal modern MCP (2026-07-28) server (ASGI callable).

    Responds to ``server/discover``, ``tools/list``, and ``tools/call``.
    Validates that requests carry ``_meta`` with protocol version and that
    routing headers (``MCP-Protocol-Version``, ``Mcp-Method``) are present.
    No session management — each request is self-contained.
    """

    PROTOCOL_VERSION = "2026-07-28"

    def __init__(
        self,
        *,
        tools: list[dict[str, Any]] | None = None,
        protocol_versions: list[str] | None = None,
    ) -> None:
        self._tools = tools if tools is not None else list(_DEFAULT_TOOLS)
        self._protocol_versions = protocol_versions or [self.PROTOCOL_VERSION]
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        body = await _read_body(receive)
        headers = _header_dict(scope)
        payload: dict[str, Any] = json.loads(body) if body else {}
        method = payload.get("method", "")
        request_id = payload.get("id")
        params = payload.get("params", {})
        meta = payload.get("_meta", {})

        self.requests.append({
            "method": method,
            "params": params,
            "_meta": meta,
            "headers": headers,
        })

        # Validate modern routing headers on all requests
        proto_header = headers.get("mcp-protocol-version", "")
        method_header = headers.get("mcp-method", "")
        if not proto_header or not method_header:
            await _send_json(send, status=400, body_dict={
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32600, "message": "Missing routing headers"},
            })
            return

        if method == "server/discover":
            result = {
                "capabilities": {"tools": {}},
                "protocolVersions": self._protocol_versions,
                "serverInfo": {"name": "modern-test-server", "version": "2.0.0"},
            }
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id, "result": result,
            }, extra_headers=[(b"mcp-protocol-version", self.PROTOCOL_VERSION.encode())])
            return

        if method == "tools/list":
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id,
                "result": {"tools": self._tools},
            }, extra_headers=[(b"mcp-protocol-version", self.PROTOCOL_VERSION.encode())])
            return

        if method == "tools/call":
            arguments = params.get("arguments", {})
            text = arguments.get("text", "")
            await _send_json(send, status=200, body_dict={
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": f"echo: {text}"}]},
            }, extra_headers=[(b"mcp-protocol-version", self.PROTOCOL_VERSION.encode())])
            return

        await _send_json(send, status=200, body_dict={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }, extra_headers=[(b"mcp-protocol-version", self.PROTOCOL_VERSION.encode())])


class StreamingModernMCPServer:
    """Modern MCP server that streams SSE events with configurable delays.

    Used by the Wave 0 spike to prove request-scoped streaming cancellation
    and timeout behavior.  Sends the first SSE event immediately, then waits
    ``delay_seconds`` before sending the second event.
    """

    PROTOCOL_VERSION = "2026-07-28"

    def __init__(self, *, delay_seconds: float = 30.0) -> None:
        self._delay = delay_seconds
        self.first_event_sent = asyncio.Event()
        self.second_event_attempted = False

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        body = await _read_body(receive)
        payload: dict[str, Any] = json.loads(body) if body else {}
        request_id = payload.get("id")

        headers = [
            (b"content-type", b"text/event-stream"),
            (b"mcp-protocol-version", self.PROTOCOL_VERSION.encode()),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})

        first = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"step": 1}})
        await send({
            "type": "http.response.body",
            "body": f"data: {first}\n\n".encode(),
            "more_body": True,
        })
        self.first_event_sent.set()

        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            raise

        self.second_event_attempted = True
        second = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"step": 2}})
        await send({
            "type": "http.response.body",
            "body": f"data: {second}\n\n".encode(),
        })
