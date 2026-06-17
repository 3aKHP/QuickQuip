"""Unit tests for JsonRpcSession — request lifecycle and pending cleanup.

Covers the three exit paths of ``request()`` that determine whether the
pending-future entry leaks:
- normal response (already popped by _handle_message)
- timeout (TimeoutError → MCPError)
- cancellation during wait_for (CancelledError — previously leaked)

Also covers _reader_loop using _fail_pending as a single cleanup point
(previously called twice: once in except, once in finally).
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from quickquip.llm.mcp.jsonrpc import JsonRpcSession
from quickquip.llm.mcp.transport import Transport
from quickquip.llm.mcp.types import MCPError


class _FakeTransport(Transport):
    """Minimal Transport for testing: send() is an AsyncMock, receive() blocks on inbox.

    Inherits from Transport so it stays in sync with the abstract interface
    as it evolves, rather than relying on duck typing.
    """

    def __init__(self):
        super().__init__()
        self._send_mock = AsyncMock()

    async def send(self, payload: dict[str, Any]) -> None:
        await self._send_mock(payload)

    async def start(self) -> None:
        pass

    async def receive(self):
        while True:
            message = await self._inbox.get()
            if message is None:
                return
            yield message

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._inbox.put_nowait(None)

    def push_response(self, request_id: int, result: dict[str, Any]) -> None:
        """Simulate the server sending a JSON-RPC response into the inbox."""
        self._inbox.put_nowait({"jsonrpc": "2.0", "id": request_id, "result": result})


@pytest.fixture
def session():
    transport = _FakeTransport()
    sess = JsonRpcSession(transport, server_id="test-server", timeout_seconds=1.0)
    return sess, transport


@pytest.mark.asyncio
async def test_request_normal_response_pops_pending(session):
    sess, transport = session
    await sess.start()

    # Pre-feed a response for request_id=1 (the first request)
    transport.push_response(1, {"ok": True})

    result = await sess.request("tools/list", {})
    assert result == {"ok": True}
    # Pending must be empty after a successful round-trip
    assert 1 not in sess._pending

    await sess.aclose()


@pytest.mark.asyncio
async def test_request_timeout_raises_mcp_error_and_pops_pending(session):
    sess, _ = session
    await sess.start()

    short_timeout_sess = JsonRpcSession(_FakeTransport(), server_id="test", timeout_seconds=0.05)
    await short_timeout_sess.start()

    with pytest.raises(MCPError, match="超时"):
        await short_timeout_sess.request("tools/list", {})

    # The timed-out request_id must not linger in _pending
    assert len(short_timeout_sess._pending) == 0
    await short_timeout_sess.aclose()
    await sess.aclose()


@pytest.mark.asyncio
async def test_request_cancelled_pops_pending(session):
    """Backlog #8: cancellation must not leak the future in _pending."""
    sess, _ = session
    await sess.start()

    # Start a request that will hang (no response pushed), then cancel it
    task = asyncio.create_task(sess.request("tools/list", {}))
    await asyncio.sleep(0.01)  # let the task reach wait_for

    request_id = 1
    assert request_id in sess._pending  # future is registered

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Key assertion: the cancelled request's future must have been cleaned up
    assert request_id not in sess._pending, "cancelled request leaked future in _pending"

    await sess.aclose()


@pytest.mark.asyncio
async def test_reader_loop_fail_pending_cleans_up(session):
    """_reader_loop's finally block fails all pending futures on disconnect.
    Verifies the outcome (futures are failed with MCPError), not the internal
    call count of _fail_pending.
    """
    sess, transport = session
    await sess.start()

    # Register a pending future manually, then close the transport's receive()
    # stream to trigger _reader_loop exit → finally → _fail_pending.
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    sess._pending[99] = future

    # Trigger reader loop exit by closing the session
    await sess.aclose()

    # The future must have been failed with MCPError (not still pending)
    assert future.done()
    with pytest.raises(MCPError):
        future.result()
