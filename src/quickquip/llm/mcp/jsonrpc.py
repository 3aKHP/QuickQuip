"""JSON-RPC 2.0 session layer for MCP.

``JsonRpcSession`` drives any ``Transport``: owns request-id generation,
pending-future bookkeeping, background message dispatch, and timeout
enforcement. Fully transport-agnostic.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from quickquip.llm.mcp.transport import Transport
from quickquip.llm.mcp.types import MCPError

logger = logging.getLogger(__name__)


class JsonRpcSession:
    """JSON-RPC 2.0 session driving any `Transport`.

    Owns request-id generation, pending-future bookkeeping, background message
    dispatch, and timeout enforcement. Fully transport-agnostic.
    """

    def __init__(self, transport: Transport, *, server_id: str, timeout_seconds: float):
        self._transport = transport
        self._server_id = server_id
        self._timeout = timeout_seconds
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._transport.start()
        self._reader_task = asyncio.create_task(self._reader_loop(), name=f"mcp-session-{self._server_id}")

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future

        try:
            await self._transport.send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        except Exception:
            self._pending.pop(request_id, None)
            raise

        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            raise MCPError(f"MCP server {self._server_id} 调用 {method} 超时") from exc
        finally:
            # Ensure the pending entry is removed on every exit path:
            # normal return (already popped by _handle_message), timeout,
            # or cancellation (which previously leaked the future).
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._transport.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _reader_loop(self) -> None:
        try:
            async for message in self._transport.receive():
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP session %s reader stopped: %s", self._server_id, exc)
        finally:
            # Single cleanup point: fail all pending futures on any exit.
            # (Previously _fail_pending was also called in the except block,
            # double-failing futures with an overwritten message.)
            self._fail_pending(f"MCP server {self._server_id} 已断开")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            try:
                request_id = int(message["id"])
            except (TypeError, ValueError):
                return
            future = self._pending.pop(request_id, None)
            if future is None or future.done():
                return
            if "error" in message:
                error = message.get("error", {})
                detail = error.get("message", "未知错误") if isinstance(error, dict) else str(error)
                future.set_exception(MCPError(str(detail)))
                return
            result = message.get("result", {})
            future.set_result(result if isinstance(result, dict) else {})
            return

        if "id" in message and "method" in message:
            await self._transport.send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
            return

        if message.get("method") == "notifications/tools/list_changed":
            logger.info("MCP server %s reported tools/list change", self._server_id)

    def _fail_pending(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError(message))
        self._pending.clear()

    async def aclose(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        await self._transport.aclose()
        self._fail_pending(f"MCP server {self._server_id} 已关闭")
