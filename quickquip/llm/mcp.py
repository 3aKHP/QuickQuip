from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from typing import Any

from quickquip.llm.config import MCPConfig, MCPServerConfig
from quickquip.llm.tools import ToolExecutionContext


logger = logging.getLogger(__name__)
_DOCKER_SOCKET_MOUNT = "/var/run/docker.sock:/var/run/docker.sock"


class MCPError(RuntimeError):
    pass


@dataclass(slots=True)
class MCPToolBinding:
    alias: str
    server_id: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class MCPServerStatus:
    id: str
    transport: str
    enabled: bool
    connected: bool = False
    tool_count: int = 0
    error: str | None = None
    detail: str = ""


@dataclass(slots=True)
class MCPToolCallResult:
    content: str
    is_error: bool = False


def _sanitize_tool_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    normalized = normalized.strip("_")
    return normalized or "tool"


def _build_tool_alias(server_id: str, tool_name: str, prefix: str | None = None) -> str:
    base_prefix = _sanitize_tool_name(prefix or server_id)
    base_tool = _sanitize_tool_name(tool_name)
    alias = f"mcp_{base_prefix}_{base_tool}"
    if len(alias) <= 64:
        return alias

    digest = hashlib.sha1(f"{server_id}:{tool_name}".encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    head = alias[: 64 - len(suffix)]
    return f"{head}{suffix}"


def _schema_from_tool(raw_tool: dict[str, Any]) -> dict[str, Any]:
    for key in ("inputSchema", "input_schema"):
        schema = raw_tool.get(key)
        if isinstance(schema, dict):
            return schema
    return {"type": "object", "properties": {}}


def _text_from_content_block(item: dict[str, Any]) -> str:
    if item.get("type") == "text":
        return str(item.get("text", "")).strip()
    return ""


def _format_tool_result(payload: dict[str, Any]) -> MCPToolCallResult:
    parts: list[str] = []
    for item in payload.get("content", []) or []:
        if not isinstance(item, dict):
            continue
        text = _text_from_content_block(item)
        if text:
            parts.append(text)

    if not parts and payload.get("structuredContent") is not None:
        parts.append(json.dumps(payload["structuredContent"], ensure_ascii=False))

    if not parts and payload.get("content"):
        parts.append(json.dumps(payload["content"], ensure_ascii=False))

    content = "\n".join(part for part in parts if part).strip()
    return MCPToolCallResult(
        content=content or "MCP 工具未返回可显示内容。",
        is_error=bool(payload.get("isError", False)),
    )


class StdioMCPClient:
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Process | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_request_id = 1
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stdout_buffer = bytearray()
        self.server_info: dict[str, Any] = {}

    def _build_command(self) -> tuple[list[str], dict[str, str], str | None]:
        if self.config.transport == "stdio":
            if not self.config.command:
                raise MCPError(f"MCP server {self.config.id} 缺少 command")
            command = [self.config.command, *self.config.args]
            env = {**os.environ, **self.config.env}
            cwd = self.config.cwd
            return command, env, cwd

        if self.config.transport == "docker":
            if not self.config.image:
                raise MCPError(f"MCP server {self.config.id} 缺少 image")

            command = [self.config.docker_command, "run", "-i", "--rm"]
            if self.config.network:
                command.extend(["--network", self.config.network])
            if self.config.container_workdir:
                command.extend(["-w", self.config.container_workdir])
            for mount in self.config.mounts:
                command.extend(["-v", mount])
            if self.config.mount_docker_socket:
                command.extend(["-v", _DOCKER_SOCKET_MOUNT])
            for key, value in self.config.env.items():
                command.extend(["-e", f"{key}={value}"])
            command.extend(self.config.docker_args)
            command.append(self.config.image)
            command.extend(self.config.args)
            env = dict(os.environ)
            return command, env, self.config.cwd

        raise MCPError(f"MCP server {self.config.id} 使用了未知 transport：{self.config.transport}")

    async def start(self) -> None:
        command, env, cwd = self._build_command()
        self._stdout_buffer.clear()
        logger.info("Starting MCP server %s with transport=%s", self.config.id, self.config.transport)
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._reader_loop(), name=f"mcp-reader-{self.config.id}")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name=f"mcp-stderr-{self.config.id}")
        await self._initialize()

    async def _initialize(self) -> None:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "QuickQuip",
                    "version": "1.0",
                },
            },
        )
        self.server_info = result.get("serverInfo", {}) if isinstance(result, dict) else {}
        await self.notify("notifications/initialized", {})

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = await self.request("tools/list", params)
            current_tools = result.get("tools", []) if isinstance(result, dict) else []
            tools.extend(item for item in current_tools if isinstance(item, dict))
            cursor = str(result.get("nextCursor", "")).strip() if isinstance(result, dict) else ""
            if not cursor:
                break

        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolCallResult:
        result = await self.request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if not isinstance(result, dict):
            raise MCPError(f"MCP 工具 {tool_name} 返回了不可识别的响应")
        return _format_tool_result(result)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None:
            raise MCPError(f"MCP server {self.config.id} 尚未启动")

        request_id = self._next_request_id
        self._next_request_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )

        try:
            return await asyncio.wait_for(future, timeout=self.config.timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MCPError(f"MCP server {self.config.id} 调用 {method} 超时") from exc

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def _send_message(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPError(f"MCP server {self.config.id} 尚未启动")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.process.stdin.write(body + b"\n")
        await self.process.stdin.drain()

    async def _reader_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                message = await self._read_message()
                if message is None:
                    break
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP reader for %s stopped: %s", self.config.id, exc)
            self._fail_pending(f"MCP server {self.config.id} 连接中断：{exc}")
        finally:
            self._fail_pending(f"MCP server {self.config.id} 已断开")

    async def _read_message(self) -> dict[str, Any] | None:
        while True:
            line = await self._read_line()
            if not line:
                return None
            if not line.strip():
                continue
            if self._is_content_length_header(line):
                return await self._read_header_message(line)
            return self._decode_message(line)

    def _is_content_length_header(self, line: bytes) -> bool:
        return line.decode("ascii", errors="replace").lower().startswith("content-length:")

    async def _read_header_message(self, first_header_line: bytes) -> dict[str, Any]:
        content_length = self._parse_content_length(first_header_line)
        while True:
            line = await self._read_line()
            if not line:
                raise MCPError("MCP 消息头被提前截断")
            if line in {b"\r\n", b"\n"}:
                break
            if self._is_content_length_header(line):
                content_length = self._parse_content_length(line)

        body = await self._read_exactly(content_length)
        return self._decode_message(body)

    def _parse_content_length(self, line: bytes) -> int:
        header = line.decode("ascii", errors="replace").strip()
        try:
            content_length = int(header.split(":", 1)[1].strip())
        except (IndexError, ValueError) as exc:
            raise MCPError("读取到无效的 Content-Length") from exc
        if content_length <= 0:
            raise MCPError("读取到无效的 Content-Length")
        return content_length

    def _decode_message(self, body: bytes) -> dict[str, Any]:
        payload = json.loads(body.decode("utf-8").strip())
        if not isinstance(payload, dict):
            raise MCPError("MCP 响应不是对象")
        return payload

    async def _read_line(self) -> bytes:
        assert self.process is not None and self.process.stdout is not None
        while True:
            newline_index = self._stdout_buffer.find(b"\n")
            if newline_index >= 0:
                end = newline_index + 1
                data = bytes(self._stdout_buffer[:end])
                del self._stdout_buffer[:end]
                return data

            chunk = await self.process.stdout.read(4096)
            if not chunk:
                if not self._stdout_buffer:
                    return b""
                data = bytes(self._stdout_buffer)
                self._stdout_buffer.clear()
                return data
            self._stdout_buffer.extend(chunk)

    async def _read_exactly(self, count: int) -> bytes:
        assert self.process is not None and self.process.stdout is not None
        while len(self._stdout_buffer) < count:
            chunk = await self.process.stdout.read(count - len(self._stdout_buffer))
            if not chunk:
                partial = bytes(self._stdout_buffer)
                self._stdout_buffer.clear()
                raise asyncio.IncompleteReadError(partial=partial, expected=count)
            self._stdout_buffer.extend(chunk)

        data = bytes(self._stdout_buffer[:count])
        del self._stdout_buffer[:count]
        return data

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            request_id = int(message["id"])
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
            await self._send_message(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "Method not found",
                    },
                }
            )
            return

        if message.get("method") == "notifications/tools/list_changed":
            logger.info("MCP server %s reported tools/list change", self.config.id)

    async def _stderr_loop(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.info("MCP stderr [%s] %s", self.config.id, text)
        except asyncio.CancelledError:
            raise

    def _fail_pending(self, message: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPError(message))
        self._pending.clear()

    async def aclose(self) -> None:
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if self.process is None:
            self._stdout_buffer.clear()
            return

        if self.process.stdin is not None:
            self.process.stdin.close()

        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

        self.process = None
        self._stdout_buffer.clear()


class MCPClientManager:
    def __init__(self):
        self._clients: dict[str, StdioMCPClient] = {}
        self._bindings: dict[str, MCPToolBinding] = {}
        self._statuses: dict[str, MCPServerStatus] = {}

    @property
    def bindings(self) -> dict[str, MCPToolBinding]:
        return dict(self._bindings)

    def get_statuses(self) -> list[MCPServerStatus]:
        return [self._statuses[key] for key in sorted(self._statuses)]

    async def sync(self, config: MCPConfig) -> list[MCPToolBinding]:
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
            )
            client: StdioMCPClient | None = None
            try:
                client = StdioMCPClient(server)
                await client.start()
                tools = await client.list_tools()
                server_bindings = self._build_bindings(server, tools)
                bindings.extend(server_bindings)
                self._clients[server.id] = client
                status.connected = True
                status.tool_count = len(server_bindings)
                status.detail = self._describe_server(server, client)
            except Exception as exc:
                if client is not None:
                    await client.aclose()
                status.error = str(exc)
                logger.warning("Failed to initialize MCP server %s: %s", server.id, exc)
            self._statuses[server.id] = status

        self._bindings = {binding.alias: binding for binding in bindings}
        return bindings

    async def execute(
        self,
        alias: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> str:
        _ = context
        binding = self._bindings.get(alias)
        if binding is None:
            raise MCPError(f"未知 MCP 工具：{alias}")
        client = self._clients.get(binding.server_id)
        if client is None:
            raise MCPError(f"MCP server 未连接：{binding.server_id}")

        result = await client.call_tool(binding.tool_name, arguments)
        if result.is_error:
            raise MCPError(result.content)
        return result.content

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
        allowed = {item.strip() for item in server.allowed_tools if item.strip()}
        bindings: list[MCPToolBinding] = []
        for raw_tool in tools:
            tool_name = str(raw_tool.get("name", "")).strip()
            if not tool_name:
                continue
            if allowed and tool_name not in allowed:
                continue

            alias = _build_tool_alias(server.id, tool_name, prefix=server.tool_prefix)
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

    def _describe_server(self, server: MCPServerConfig, client: StdioMCPClient) -> str:
        server_name = str(client.server_info.get("name", "")).strip()
        server_version = str(client.server_info.get("version", "")).strip()
        if server_name and server_version:
            return f"{server_name} {server_version}"
        if server_name:
            return server_name
        if server.transport == "docker":
            return server.image
        return server.command
