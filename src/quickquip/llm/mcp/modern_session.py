"""Modern MCP (2026-07-28) HTTP session.

Request-scoped HTTP transport for modern MCP.  Each request is a
self-contained POST carrying ``_meta`` and routing headers.  No
session-id, no reader loop, no shared inbox — the protocol is stateless
per-request.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from quickquip.llm.config import MCPServerConfig
from quickquip.llm.mcp.transport import _require_httpx
from quickquip.llm.mcp.types import (
    MCPLegacyFallbackSignal,
    MCPError,
    MCP_FAILURE_AUTH,
    MCP_FAILURE_MODERN_NEGOTIATION,
    MCP_FAILURE_TIMEOUT,
    MCP_FAILURE_TRANSPORT,
    _sanitize_error_message,
)
from quickquip.llm.mcp.codec import (
    build_modern_body,
    build_routing_headers,
    detect_input_required,
    is_recognized_modern_error_body,
    parse_response_envelope,
    parse_sse_response,
)

logger = logging.getLogger(__name__)

_ACCEPT = "application/json, text/event-stream"
_LEGACY_FALLBACK_STATUSES = frozenset({400, 404, 405})


class ModernHttpSession:
    """Modern MCP HTTP session: per-request POST with _meta and routing headers."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._client: Any = None  # httpx.AsyncClient
        self._next_id = 1
        self.protocol_version = ""

    async def start(self) -> None:
        httpx = _require_httpx()
        if not self.config.url:
            raise MCPError(f"MCP server {self.config.id} 缺少 url")
        self._client = httpx.AsyncClient(
            headers=self.config.headers,
            timeout=self.config.timeout_seconds,
        )

    async def discover(
        self,
        *,
        protocol_version: str,
        supported_versions: list[str],
    ) -> dict[str, Any]:
        """Send ``server/discover`` probe.

        Returns the DiscoverResult dict on success.
        Raises MCPLegacyFallbackSignal if the server appears legacy.
        Raises MCPError on hard failures (auth, 5xx, timeout, version mismatch).
        """
        request_id = self._next_id
        self._next_id += 1

        body = build_modern_body("server/discover", {}, request_id, protocol_version)
        headers = build_routing_headers("server/discover", {}, protocol_version)
        response = await self._post(body, headers)

        if response.status_code == 200:
            try:
                result = self._parse_response(response)
            except MCPError as exc:
                # A legacy server may return HTTP 200 with a JSON-RPC error
                # (e.g. -32601 for unknown method "server/discover").
                if not is_recognized_modern_error_body(response.content):
                    raise MCPLegacyFallbackSignal(
                        f"MCP server {self.config.id} 探测判定为 legacy"
                        f"（discover 返回 JSON-RPC error）"
                    )
                raise MCPError(
                    f"MCP server {self.config.id} modern 协商失败：{exc}",
                    failure_kind=MCP_FAILURE_MODERN_NEGOTIATION,
                ) from exc
            server_versions = result.get("protocolVersions", [])
            if isinstance(server_versions, list) and server_versions:
                intersection = [v for v in supported_versions if v in server_versions]
                if not intersection:
                    raise MCPError(
                        f"MCP server {self.config.id} modern 版本无交集"
                        f"（client={supported_versions}, server={server_versions}）",
                        failure_kind=MCP_FAILURE_MODERN_NEGOTIATION,
                    )
                self.protocol_version = intersection[0]
            else:
                self.protocol_version = protocol_version
            return result

        self._raise_for_probe_error(response)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a modern request and return the result dict."""
        if not self.protocol_version:
            raise MCPError(f"MCP server {self.config.id} modern session 未完成 discover")

        request_id = self._next_id
        self._next_id += 1

        pv = self.protocol_version
        body = build_modern_body(method, params, request_id, pv)
        headers = build_routing_headers(method, params, pv)
        response = await self._post(body, headers)

        if response.status_code >= 400:
            self._raise_for_request_error(response, method)

        result = self._parse_response(response)
        if detect_input_required(result):
            raise MCPError(
                f"MCP server {self.config.id} {method} 返回 input_required（MRTR 暂不支持）",
                failure_kind=MCP_FAILURE_MODERN_NEGOTIATION,
            )
        return result

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post(self, body: dict[str, Any], routing_headers: dict[str, str]) -> Any:
        """Send a POST and return the httpx Response."""
        httpx = _require_httpx()
        if self._client is None:
            raise MCPError(f"MCP server {self.config.id} modern session 尚未启动")
        merged: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": _ACCEPT,
            **routing_headers,
        }
        try:
            return await self._client.post(
                self.config.url,
                content=json.dumps(body, ensure_ascii=False).encode(),
                headers=merged,
            )
        except httpx.TimeoutException as exc:
            raise MCPError(
                f"MCP server {self.config.id} modern 请求超时",
                failure_kind=MCP_FAILURE_TIMEOUT,
            ) from exc
        except httpx.RequestError as exc:
            raise MCPError(
                f"MCP server {self.config.id} modern 请求失败：{_sanitize_error_message(exc)}",
                failure_kind=MCP_FAILURE_TRANSPORT,
            ) from exc

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Parse JSON or SSE response body into a result dict."""
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return parse_sse_response(response.text)
        try:
            data = response.json()
        except ValueError as exc:
            raise MCPError(
                f"MCP server {self.config.id} modern 返回了非 JSON 响应",
                failure_kind=MCP_FAILURE_TRANSPORT,
            ) from exc
        if not isinstance(data, dict):
            raise MCPError(
                f"MCP server {self.config.id} modern 响应不是对象",
                failure_kind=MCP_FAILURE_TRANSPORT,
            )
        return parse_response_envelope(data)

    def _raise_for_probe_error(self, response: Any) -> None:
        """Classify a failed server/discover probe response."""
        status = response.status_code
        if status in _LEGACY_FALLBACK_STATUSES:
            if is_recognized_modern_error_body(response.content):
                raise MCPError(
                    f"MCP server {self.config.id} modern 协商失败：HTTP {status}",
                    failure_kind=MCP_FAILURE_MODERN_NEGOTIATION,
                    http_status=status,
                )
            raise MCPLegacyFallbackSignal(
                f"MCP server {self.config.id} 探测判定为 legacy（HTTP {status}）"
            )
        raise self._classify_http_error(status)

    def _raise_for_request_error(self, response: Any, method: str) -> None:
        """Classify a failed modern request response."""
        status = response.status_code
        # Try to parse JSON-RPC error from body for better diagnostics
        try:
            data = response.json()
            if isinstance(data, dict) and "error" in data:
                error = data["error"]
                msg = error.get("message", "未知错误") if isinstance(error, dict) else str(error)
                raise MCPError(
                    f"MCP server {self.config.id} {method} 失败：{msg}",
                    http_status=status,
                )
        except (ValueError, TypeError):
            pass
        raise self._classify_http_error(status)

    @staticmethod
    def _classify_http_error(status: int) -> MCPError:
        kind = MCP_FAILURE_AUTH if status in (401, 403) else MCP_FAILURE_TRANSPORT
        return MCPError(f"HTTP {status}", failure_kind=kind, http_status=status)
