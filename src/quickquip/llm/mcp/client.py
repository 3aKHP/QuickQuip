"""MCP client and multi-server manager.

``MCPClient`` is a thin protocol surface (initialize / tools/list / tools/call)
over a single ``JsonRpcSession``. ``MCPClientManager`` owns the collection of
clients, builds tool bindings, writes the shared status file for web-admin,
and dispatches tool execution by alias.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from quickquip.llm.config import MCPConfig, MCPServerConfig
from quickquip.llm.tools import LLMToolOutput, ToolExecutionContext
from quickquip.llm.mcp.jsonrpc import JsonRpcSession
from quickquip.llm.mcp.modern_session import ModernHttpSession
from quickquip.llm.mcp.transport import (
    SseTransport,
    StdioTransport,
    StreamableHttpTransport,
    Transport,
)
from quickquip.llm.mcp.types import (
    MCPError,
    MCPLegacyFallbackSignal,
    MCPStaleSessionError,
    MCPToolBinding,
    MCPServerStatus,
    MCPToolCallResult,
    MCPConnectionInfo,
    MCP_FAILURE_AUTH,
    MCP_FAILURE_CONFIG,
    _build_tool_alias,
    _sanitize_error_message,
    _sanitize_url,
    deliver_mcp_tool_result,
    _format_tool_result,
    _normalize_tool_filter,
    _schema_from_tool,
    _tool_filter_matches,
)

logger = logging.getLogger(__name__)


def _build_transport(config: MCPServerConfig) -> Transport:
    transport = config.transport
    if transport in ("stdio", "docker"):
        return StdioTransport(config)
    if transport == "http":
        return StreamableHttpTransport(config)
    if transport == "sse":
        return SseTransport(config)
    raise MCPError(f"MCP server {config.id} 使用了未知 transport：{transport}")


class MCPClient:
    """MCP protocol surface (initialize / tools). Transport-agnostic."""

    _MAX_STALE_RECONNECTS = 2

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._transport = _build_transport(config)
        self._session = JsonRpcSession(
            self._transport,
            server_id=config.id,
            timeout_seconds=config.timeout_seconds,
        )
        self._modern_session: ModernHttpSession | None = None
        self.server_info: dict[str, Any] = {}
        self._connection_info = MCPConnectionInfo(
            server_id=config.id,
            negotiation=config.negotiation,
            era="unknown",
            configured_protocol_version=config.protocol_version,
        )

    @property
    def _is_modern(self) -> bool:
        return self._modern_session is not None

    def _pick_modern_version(self) -> str:
        versions = self.config.supported_protocol_versions
        return versions[0] if versions else "2026-07-28"

    async def start(self) -> None:
        negotiation = self.config.negotiation
        if negotiation == "legacy":
            await self._session.start()
            await self._initialize()
            self._connection_info.era = "legacy"
        elif negotiation == "modern":
            await self._start_modern()
        elif negotiation == "auto":
            await self._start_auto()
        else:
            raise MCPError(
                f"MCP server {self.config.id} 未知 negotiation 模式：{negotiation!r}",
                failure_kind=MCP_FAILURE_CONFIG,
            )

    async def _start_modern(self) -> None:
        self._modern_session = ModernHttpSession(self.config)
        await self._modern_session.start()
        result = await self._modern_session.discover(
            protocol_version=self._pick_modern_version(),
            supported_versions=self.config.supported_protocol_versions,
        )
        self._on_modern_connected(result)

    async def _start_auto(self) -> None:
        """Auto negotiation: probe modern, fall back to legacy on legacy signal."""
        modern = ModernHttpSession(self.config)
        await modern.start()
        try:
            result = await modern.discover(
                protocol_version=self._pick_modern_version(),
                supported_versions=self.config.supported_protocol_versions,
            )
        except MCPLegacyFallbackSignal:
            await modern.aclose()
        else:
            self._modern_session = modern
            self._on_modern_connected(result)
            return
        # Legacy fallback
        await self._session.start()
        await self._initialize()
        self._connection_info.era = "legacy"

    def _on_modern_connected(self, discover_result: dict[str, Any]) -> None:
        self._connection_info.era = "modern"
        self.server_info = discover_result.get("serverInfo", {}) if isinstance(discover_result, dict) else {}
        self._connection_info.server_info = self.server_info or None
        caps = discover_result.get("capabilities", {})
        if isinstance(caps, dict):
            self._connection_info.capabilities = caps
        assert self._modern_session is not None
        self._connection_info.negotiated_protocol_version = self._modern_session.protocol_version

    async def _initialize(self) -> None:
        result = await self._session.request(
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "QuickQuip", "version": "1.0"},
            },
        )
        self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        if isinstance(result, dict):
            self._connection_info.capabilities = result.get("capabilities", {})
            self._connection_info.server_info = self.server_info or None
            negotiated = str(result.get("protocolVersion", "")).strip()
            if negotiated:
                self._connection_info.negotiated_protocol_version = negotiated
        self._connection_info.session_id = getattr(self._transport, "_session_id", None)
        await self._session.notify("notifications/initialized", {})

    async def _reconnect(self) -> None:
        """Re-establish a stale legacy connection: re-initialize for a new session."""
        self._connection_info.generation += 1
        await self._initialize()

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._is_modern:
            return await self._list_tools_modern()
        for attempt in range(self._MAX_STALE_RECONNECTS + 1):
            try:
                return await self._list_tools_once()
            except MCPStaleSessionError:
                if attempt >= self._MAX_STALE_RECONNECTS:
                    raise
                logger.info("MCP server %s session expired, reconnecting", self.config.id)
                await self._reconnect()
        # unreachable, but satisfies type checker
        return []

    async def _list_tools_modern(self) -> list[dict[str, Any]]:
        assert self._modern_session is not None
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = await self._modern_session.request("tools/list", params)
            current_tools = result.get("tools", []) if isinstance(result, dict) else []
            tools.extend(item for item in current_tools if isinstance(item, dict))
            cursor = str(result.get("nextCursor", "")).strip() if isinstance(result, dict) else ""
            if not cursor:
                break
        return tools

    async def _list_tools_once(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = await self._session.request("tools/list", params)
            current_tools = result.get("tools", []) if isinstance(result, dict) else []
            tools.extend(item for item in current_tools if isinstance(item, dict))
            cursor = str(result.get("nextCursor", "")).strip() if isinstance(result, dict) else ""
            if not cursor:
                break
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        if self._is_modern:
            return await self._call_tool_modern(tool_name, arguments)
        try:
            result = await self._session.request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )
        except MCPStaleSessionError:
            # Do NOT replay tools/call to avoid duplicate side effects.
            raise MCPError(
                f"MCP server {self.config.id} tools/call 中途 session 过期，未自动重放"
            )
        if not isinstance(result, dict):
            raise MCPError(f"MCP 工具 {tool_name} 返回了不可识别的响应")
        return _format_tool_result(result)

    async def _call_tool_modern(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        assert self._modern_session is not None
        result = await self._modern_session.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        if not isinstance(result, dict):
            raise MCPError(f"MCP 工具 {tool_name} 返回了不可识别的响应")
        return _format_tool_result(result)

    async def aclose(self) -> None:
        if self._modern_session is not None:
            await self._modern_session.aclose()
            self._modern_session = None
        await self._session.aclose()


class MCPClientManager:
    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._bindings: dict[str, MCPToolBinding] = {}
        self._statuses: dict[str, MCPServerStatus] = {}

    @property
    def bindings(self) -> dict[str, MCPToolBinding]:
        return dict(self._bindings)

    def get_statuses(self) -> list[MCPServerStatus]:
        return [self._statuses[key] for key in sorted(self._statuses)]

    async def _pull_image(self, server: MCPServerConfig) -> None:
        logger.info("Pulling Docker image for MCP server %s: %s", server.id, server.image)
        proc = await asyncio.create_subprocess_exec(
            server.docker_command, "pull", server.image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            output = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
            raise MCPError(f"docker pull {server.image} 失败（exit {proc.returncode}）：{output}")
        logger.info("Pulled image %s for MCP server %s", server.image, server.id)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Classify whether a startup failure is worth retrying.

        Auth (401/403), config errors, and 4xx client errors are not retryable.
        Timeout, transport, and 5xx are retryable (compose cold-boot race, etc.).
        """
        if isinstance(exc, MCPError):
            if exc.failure_kind == MCP_FAILURE_AUTH:
                return False
            if exc.failure_kind == MCP_FAILURE_CONFIG:
                return False
            if exc.http_status and 400 <= exc.http_status < 500:
                return False
        return True

    async def _connect_with_retry(
        self,
        server: MCPServerConfig,
        *,
        attempts: int = 3,
        backoff_seconds: float = 2.0,
    ) -> tuple[MCPClient, list[dict[str, Any]]]:
        """Start MCPClient + list tools, retrying on transient startup failures.

        Covers the common compose cold-boot race where sidecar MCP servers
        take a few seconds longer than bot init to become ready.  Auth,
        config, and 4xx errors are not retried.
        """
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            client = MCPClient(server)
            try:
                await client.start()
                tools = await client.list_tools()
                return client, tools
            except Exception as exc:
                last_exc = exc
                await client.aclose()
                if attempt < attempts and self._is_retryable(exc):
                    logger.info(
                        "MCP server %s attempt %d/%d failed (%s); retrying in %.1fs",
                        server.id, attempt, attempts, exc, backoff_seconds,
                    )
                    await asyncio.sleep(backoff_seconds)
                else:
                    break
        assert last_exc is not None
        raise last_exc

    async def sync(self, config: MCPConfig, *, force_pull: bool = False) -> list[MCPToolBinding]:
        await self.aclose()
        self._statuses = {}
        self._bindings = {}

        if not config.enabled:
            return []

        bindings: list[MCPToolBinding] = []
        for server in config.servers:
            if not server.enabled:
                self._statuses[server.id] = MCPServerStatus(
                    id=server.id,
                    transport=server.transport,
                    enabled=False,
                    detail="disabled",
                )
                continue

            status = MCPServerStatus(
                id=server.id,
                transport=server.transport,
                enabled=True,
                negotiation=server.negotiation,
            )
            client: MCPClient | None = None
            try:
                if force_pull and server.transport == "docker":
                    await self._pull_image(server)
                client, tools = await self._connect_with_retry(server)
                server_bindings = self._build_bindings(server, tools)
                bindings.extend(server_bindings)
                self._clients[server.id] = client
                status.connected = True
                status.tool_count = len(server_bindings)
                status.detail = self._describe_server(server, client)
                status.era = client._connection_info.era
                status.negotiated_protocol_version = client._connection_info.negotiated_protocol_version
            except Exception as exc:
                status.error = _sanitize_error_message(exc)
                if isinstance(exc, MCPError):
                    status.failure_kind = exc.failure_kind
                logger.warning("Failed to initialize MCP server %s: %s", server.id, exc)
            self._statuses[server.id] = status

        self._bindings = {binding.alias: binding for binding in bindings}
        self._write_status_file()
        return bindings

    def _write_status_file(self) -> None:
        """Write current MCP status to a JSON file shared with web-admin."""
        try:
            from quickquip.common.paths import MCP_STATUS_JSON_PATH

            path = MCP_STATUS_JSON_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            statuses = []
            for s in self.get_statuses():
                statuses.append({
                    "id": s.id,
                    "transport": s.transport,
                    "enabled": s.enabled,
                    "connected": s.connected,
                    "tool_count": s.tool_count,
                    "error": s.error,
                    "detail": s.detail,
                    "negotiation": s.negotiation,
                    "era": s.era,
                    "failure_kind": s.failure_kind,
                    "negotiated_protocol_version": s.negotiated_protocol_version,
                })
            bindings_list = []
            for alias, b in self._bindings.items():
                bindings_list.append({
                    "alias": alias,
                    "server_id": b.server_id,
                    "tool_name": b.tool_name,
                    "description": b.description,
                })
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"statuses": statuses, "bindings": bindings_list},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception:
            logger.warning("Failed to write MCP status file", exc_info=True)

    async def execute(
        self,
        alias: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> LLMToolOutput:
        _ = context
        binding = self._bindings.get(alias)
        if binding is None:
            raise MCPError(f"未知 MCP 工具：{alias}")
        client = self._clients.get(binding.server_id)
        if client is None:
            raise MCPError(f"MCP server 未连接：{binding.server_id}")

        result = await client.call_tool(binding.tool_name, arguments)
        return deliver_mcp_tool_result(
            result,
            server_id=binding.server_id,
            tool_name=binding.tool_name,
        )

    async def aclose(self) -> None:
        clients = list(self._clients.values())
        self._clients = {}
        self._bindings = {}
        for client in clients:
            await client.aclose()

    def _build_bindings(
        self,
        server: MCPServerConfig,
        tools: list[dict[str, Any]],
    ) -> list[MCPToolBinding]:
        include = _normalize_tool_filter(server.include_tools or server.allowed_tools)
        exclude = _normalize_tool_filter(server.exclude_tools)
        bindings: list[MCPToolBinding] = []
        for raw_tool in tools:
            tool_name = str(raw_tool.get("name", "")).strip()
            if not tool_name:
                continue
            alias = _build_tool_alias(server.id, tool_name, prefix=server.tool_prefix)
            if include and not _tool_filter_matches(include, tool_name=tool_name, alias=alias):
                continue
            if exclude and _tool_filter_matches(exclude, tool_name=tool_name, alias=alias):
                continue
            bindings.append(
                MCPToolBinding(
                    alias=alias,
                    server_id=server.id,
                    tool_name=tool_name,
                    description=str(raw_tool.get("description", "")).strip()
                    or f"MCP tool {tool_name} from {server.id}",
                    input_schema=_schema_from_tool(raw_tool),
                )
            )
        return bindings

    def _describe_server(self, server: MCPServerConfig, client: MCPClient) -> str:
        server_name = str(client.server_info.get("name", "")).strip()
        server_version = str(client.server_info.get("version", "")).strip()
        if server_name and server_version:
            return f"{server_name} {server_version}"
        if server_name:
            return server_name
        if server.transport in ("http", "sse"):
            return _sanitize_url(server.url)
        if server.transport == "docker":
            return server.image
        return server.command
