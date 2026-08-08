"""MCP transport layer: subprocess (stdio/docker), Streamable HTTP, and SSE.

Provides the abstract ``Transport`` base plus three concrete transports.
Each transport is a bidirectional JSON-RPC message pipe that pushes
incoming envelopes into an ``asyncio.Queue`` inbox.

httpx is imported lazily via :func:`_require_httpx` at ``start()`` time
(not module import time) so that environments with deferred package
installation (e.g. Windows embedded Python) can make httpx available
between module import and first use.
"""
from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from contextlib import contextmanager
import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

try:
    import httpx
except ModuleNotFoundError:
    httpx = None  # type: ignore[assignment]

from quickquip.llm.config import MCPServerConfig
from quickquip.llm.mcp.types import (
    MCPError,
    MCPStaleSessionError,
    MCP_FAILURE_AUTH,
    MCP_FAILURE_TIMEOUT,
    MCP_FAILURE_TRANSPORT,
    _sanitize_error_message,
)

logger = logging.getLogger(__name__)


def _require_httpx():
    """Import httpx at call time (``start()``), not module import time.

    Environments with deferred package installation (e.g. Windows embedded
    Python) may make httpx available between module import and first use.
    Once imported, the module-level ``httpx`` is set for subsequent calls.
    """
    global httpx
    if httpx is None:
        try:
            import httpx as _httpx
        except ModuleNotFoundError:
            raise MCPError(
                "HTTP/SSE MCP transport 需要 httpx，请执行 pip install httpx"
            ) from None
        httpx = _httpx
    return httpx


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
        _require_httpx()
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
            status = exc.response.status_code
            if status == 404 and self._session_id:
                self._session_id = None
                raise MCPStaleSessionError(
                    f"MCP server {self.config.id} session expired"
                ) from exc
            raise MCPError(
                f"MCP server {self.config.id} HTTP {status}",
                failure_kind=MCP_FAILURE_AUTH if status in (401, 403) else MCP_FAILURE_TRANSPORT,
                http_status=status,
            ) from exc
        except httpx.RequestError as exc:
            kind = MCP_FAILURE_TIMEOUT if isinstance(exc, httpx.TimeoutException) else MCP_FAILURE_TRANSPORT
            raise MCPError(
                f"MCP server {self.config.id} 请求失败：{_sanitize_error_message(exc)}",
                failure_kind=kind,
            ) from exc

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
        _require_httpx()
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
            status = exc.response.status_code
            raise MCPError(
                f"MCP server {self.config.id} HTTP {status}",
                failure_kind=MCP_FAILURE_AUTH if status in (401, 403) else MCP_FAILURE_TRANSPORT,
                http_status=status,
            ) from exc
        except httpx.RequestError as exc:
            kind = MCP_FAILURE_TIMEOUT if isinstance(exc, httpx.TimeoutException) else MCP_FAILURE_TRANSPORT
            raise MCPError(
                f"MCP server {self.config.id} 请求失败：{_sanitize_error_message(exc)}",
                failure_kind=kind,
            ) from exc
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
