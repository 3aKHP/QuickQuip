from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import tempfile
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]
    _HTTPX_AVAILABLE = False

from quickquip.llm.config import MCPConfig, MCPServerConfig
from quickquip.llm.tools import ToolExecutionContext


logger = logging.getLogger(__name__)


@contextmanager
def _temp_env_file(env: dict[str, str]):
    """Write env vars to a 600-permission temp file, yield its path, delete on exit.
    Yields None if env is empty (no file created).
    """
    if not env:
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="mcp-env-", suffix=".env")
    try:
        with os.fdopen(fd, "w") as f:
            for key, value in env.items():
                f.write(f"{key}={value}\n")
        os.chmod(path, 0o600)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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


# --------------------------------------------------------------------------- #
# Transport layer                                                             #
# --------------------------------------------------------------------------- #


class Transport(ABC):
    """Abstract bidirectional JSON-RPC message pipe.

    Subclasses push incoming envelopes to `self._inbox`. Pushing `None` signals
    end-of-stream (connection closed). The session layer iterates via
    `receive()` and stays agnostic to how bytes move on the wire.
    """

    def __init__(self) -> None:
        self._inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._closed = False

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def send(self, payload: dict[str, Any]) -> None: ...

    @abstractmethod
    async def aclose(self) -> None: ...

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            message = await self._inbox.get()
            if message is None:
                return
            yield message

    def _push(self, message: dict[str, Any]) -> None:
        self._inbox.put_nowait(message)

    def _close_inbox(self) -> None:
        if not self._closed:
            self._closed = True
            self._inbox.put_nowait(None)


class StdioTransport(Transport):
    """stdio / `docker run -i` transport.

    Spawns a subprocess, exchanges newline- or LSP-framed JSON-RPC over
    stdin/stdout, and mirrors stderr into the logger.
    """

    def __init__(self, config: MCPServerConfig):
        super().__init__()
        self.config = config
        self.process: Process | None = None
        self._stdout_buffer = bytearray()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    def _build_command(self) -> tuple[list[str], dict[str, str], str | None, dict[str, str]]:
        """Return (command, process_env, cwd, docker_env).

        docker_env is non-empty only for docker transport — these vars are
        passed via --env-file to keep secrets out of ps output.
        """
        if self.config.transport == "stdio":
            if not self.config.command:
                raise MCPError(f"MCP server {self.config.id} 缺少 command")
            command = [self.config.command, *self.config.args]
            env = {**os.environ, **self.config.env}
            return command, env, self.config.cwd, {}

        if self.config.transport == "docker":
            if not self.config.image:
                raise MCPError(f"MCP server {self.config.id} 缺少 image")

            command = [self.config.docker_command, "run", "-i", "--rm", "--pull", self.config.pull_policy]
            if self.config.network:
                command.extend(["--network", self.config.network])
            if self.config.container_workdir:
                command.extend(["-w", self.config.container_workdir])
            for mount in self.config.mounts:
                command.extend(["-v", mount])
            # env vars are injected via --env-file in start() to avoid leaking
            # secrets into process arguments (visible in ps/proc/cmdline)
            command.extend(self.config.docker_args)
            command.append(self.config.image)
            command.extend(self.config.args)
            env = dict(os.environ)
            return command, env, self.config.cwd, dict(self.config.env)

        raise MCPError(f"MCP server {self.config.id} 使用了未知 stdio transport：{self.config.transport}")

    async def start(self) -> None:
        command, env, cwd, docker_env = self._build_command()
        self._stdout_buffer.clear()
        logger.info("Starting MCP server %s with transport=%s", self.config.id, self.config.transport)
        with _temp_env_file(docker_env) as env_file:
            if env_file is not None:
                image_idx = command.index(self.config.image)
                command = command[:image_idx] + ["--env-file", env_file] + command[image_idx:]
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        # temp file is deleted here; the child process already captured its env
        self._reader_task = asyncio.create_task(self._reader_loop(), name=f"mcp-reader-{self.config.id}")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name=f"mcp-stderr-{self.config.id}")

    async def send(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPError(f"MCP server {self.config.id} 尚未启动")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.process.stdin.write(body + b"\n")
        await self.process.stdin.drain()

    async def _reader_loop(self) -> None:
        try:
            while True:
                message = await self._read_message()
                if message is None:
                    break
                self._push(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP reader for %s stopped: %s", self.config.id, exc)
        finally:
            self._close_inbox()

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

    async def aclose(self) -> None:
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._close_inbox()

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


class StreamableHttpTransport(Transport):
    """MCP Streamable HTTP: single POST endpoint; responses are JSON or inline SSE."""

    def __init__(self, config: MCPServerConfig):
        super().__init__()
        self.config = config
        self._client: "httpx.AsyncClient | None" = None
        self._session_id: str | None = None

    async def start(self) -> None:
        if not _HTTPX_AVAILABLE:
            raise MCPError("HTTP MCP transport 需要 httpx，请执行 pip install httpx")
        if not self.config.url:
            raise MCPError(f"MCP server {self.config.id} 缺少 url")
        self._client = httpx.AsyncClient(
            headers=self.config.headers,
            timeout=self.config.timeout_seconds,
        )

    async def send(self, payload: dict[str, Any]) -> None:
        if self._client is None:
            raise MCPError(f"MCP server {self.config.id} 尚未启动")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        try:
            response = await self._client.post(
                self.config.url,
                content=json.dumps(payload, ensure_ascii=False).encode(),
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MCPError(f"MCP server {self.config.id} HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise MCPError(f"MCP server {self.config.id} 请求失败：{exc}") from exc

        returned_session = response.headers.get("mcp-session-id")
        if returned_session:
            self._session_id = returned_session

        is_notification = "id" not in payload
        if is_notification or response.status_code == 204 or not response.content:
            return

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for envelope in _parse_sse_block(response.text):
                self._push(envelope)
        else:
            try:
                envelope = response.json()
            except ValueError as exc:
                raise MCPError(f"MCP server {self.config.id} 返回了非 JSON 响应") from exc
            if isinstance(envelope, dict):
                self._push(envelope)

    async def aclose(self) -> None:
        self._close_inbox()
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class SseTransport(Transport):
    """Classic MCP HTTP+SSE: GET `url` opens the inbound SSE stream; the server
    emits an `endpoint` event whose data is the POST URL used for outbound
    requests. Response envelopes arrive as `message` events on the SSE stream.
    """

    def __init__(self, config: MCPServerConfig):
        super().__init__()
        self.config = config
        self._client: "httpx.AsyncClient | None" = None
        self._sse_task: asyncio.Task[None] | None = None
        self._post_url: str | None = None
        self._endpoint_ready = asyncio.Event()
        self._endpoint_error: Exception | None = None

    async def start(self) -> None:
        if not _HTTPX_AVAILABLE:
            raise MCPError("SSE MCP transport 需要 httpx，请执行 pip install httpx")
        if not self.config.url:
            raise MCPError(f"MCP server {self.config.id} 缺少 url")

        self._client = httpx.AsyncClient(
            headers=self.config.headers,
            timeout=httpx.Timeout(self.config.timeout_seconds, read=None),
        )
        self._sse_task = asyncio.create_task(self._sse_loop(), name=f"mcp-sse-{self.config.id}")

        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), timeout=self.config.timeout_seconds)
        except asyncio.TimeoutError as exc:
            await self._cancel_sse_task()
            raise MCPError(f"MCP server {self.config.id} 等待 endpoint 事件超时") from exc

        if self._endpoint_error is not None:
            await self._cancel_sse_task()
            raise MCPError(f"MCP server {self.config.id} SSE 连接失败：{self._endpoint_error}") from self._endpoint_error

    async def send(self, payload: dict[str, Any]) -> None:
        if self._client is None or self._post_url is None:
            raise MCPError(f"MCP server {self.config.id} 尚未启动")

        headers = {"Content-Type": "application/json"}
        try:
            response = await self._client.post(
                self._post_url,
                content=json.dumps(payload, ensure_ascii=False).encode(),
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MCPError(f"MCP server {self.config.id} HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise MCPError(f"MCP server {self.config.id} 请求失败：{exc}") from exc
        # Classic SSE transport: POST typically returns 202 Accepted with no body;
        # the JSON-RPC response arrives on the SSE stream. Nothing to push here.

    async def _sse_loop(self) -> None:
        assert self._client is not None
        headers = {"Accept": "text/event-stream"}
        try:
            async with self._client.stream("GET", self.config.url, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    self._endpoint_error = exc
                    self._endpoint_ready.set()
                    return

                async for event_name, data in _iter_sse_events(response.aiter_lines()):
                    if event_name == "endpoint":
                        self._set_endpoint(data)
                    elif event_name in ("message", ""):
                        # "" = data-only events (event field absent defaults to "message")
                        self._dispatch_message(data)
                    # ignore other events (ping, keepalive, ...)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP SSE stream for %s stopped: %s", self.config.id, exc)
            if not self._endpoint_ready.is_set():
                self._endpoint_error = exc
                self._endpoint_ready.set()
        finally:
            self._close_inbox()

    def _set_endpoint(self, data: str) -> None:
        endpoint = data.strip()
        if not endpoint:
            return
        # Spec allows relative paths; resolve against the SSE URL.
        if endpoint.startswith(("http://", "https://")):
            self._post_url = endpoint
        else:
            from urllib.parse import urljoin
            self._post_url = urljoin(self.config.url, endpoint)
        self._endpoint_ready.set()

    def _dispatch_message(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("MCP SSE [%s] 丢弃无法解析的 data 行", self.config.id)
            return
        if isinstance(envelope, dict):
            self._push(envelope)

    async def _cancel_sse_task(self) -> None:
        if self._sse_task is not None:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass
            self._sse_task = None

    async def aclose(self) -> None:
        await self._cancel_sse_task()
        self._close_inbox()
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_sse_block(body: str) -> list[dict[str, Any]]:
    """Parse a single SSE response body (as delivered inline via POST) and
    return every JSON-decodable `data:` payload."""
    envelopes: list[dict[str, Any]] = []
    for raw_event in body.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[len("data:"):].lstrip()
            for line in raw_event.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        try:
            envelope = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(envelope, dict):
            envelopes.append(envelope)
    return envelopes


async def _iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """Parse a server-sent events stream into (event_name, data) tuples."""
    event_name = ""
    data_lines: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue  # comment / keepalive
        if ":" in line:
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
        else:
            field, value = line, ""
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)


# --------------------------------------------------------------------------- #
# Protocol layer (JSON-RPC 2.0 session)                                       #
# --------------------------------------------------------------------------- #


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
            self._pending.pop(request_id, None)
            raise MCPError(f"MCP server {self._server_id} 调用 {method} 超时") from exc

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
            self._fail_pending(f"MCP server {self._server_id} 连接中断：{exc}")
        finally:
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


# --------------------------------------------------------------------------- #
# Client (thin business layer) + manager                                      #
# --------------------------------------------------------------------------- #


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

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._transport = _build_transport(config)
        self._session = JsonRpcSession(
            self._transport,
            server_id=config.id,
            timeout_seconds=config.timeout_seconds,
        )
        self.server_info: dict[str, Any] = {}

    async def start(self) -> None:
        await self._session.start()
        await self._initialize()

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
        await self._session.notify("notifications/initialized", {})

    async def list_tools(self) -> list[dict[str, Any]]:
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
        result = await self._session.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        if not isinstance(result, dict):
            raise MCPError(f"MCP 工具 {tool_name} 返回了不可识别的响应")
        return _format_tool_result(result)

    async def aclose(self) -> None:
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

    async def _connect_with_retry(
        self,
        server: MCPServerConfig,
        *,
        attempts: int = 3,
        backoff_seconds: float = 2.0,
    ) -> tuple[MCPClient, list[dict[str, Any]]]:
        """Start MCPClient + list tools, retrying on transient startup failures.

        Covers the common compose cold-boot race where sidecar MCP servers
        take a few seconds longer than bot init to become ready.
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
                if attempt < attempts:
                    logger.info(
                        "MCP server %s attempt %d/%d failed (%s); retrying in %.1fs",
                        server.id, attempt, attempts, exc, backoff_seconds,
                    )
                    await asyncio.sleep(backoff_seconds)
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
            except Exception as exc:
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

    def _describe_server(self, server: MCPServerConfig, client: MCPClient) -> str:
        server_name = str(client.server_info.get("name", "")).strip()
        server_version = str(client.server_info.get("version", "")).strip()
        if server_name and server_version:
            return f"{server_name} {server_version}"
        if server_name:
            return server_name
        if server.transport in ("http", "sse"):
            return server.url
        if server.transport == "docker":
            return server.image
        return server.command
