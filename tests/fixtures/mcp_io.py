"""Async I/O dummies for MCP stdio transport tests.

Supports both line-based framing (bare JSON + newline) and Content-Length
framing (LSP-style headers + body).
"""
from __future__ import annotations

import asyncio


class DummyAsyncWriter:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None


class DummyAsyncReader:
    def __init__(self, *chunks: bytes) -> None:
        self.buffer = bytearray()
        for chunk in chunks:
            self.buffer.extend(chunk)

    async def readline(self) -> bytes:
        if not self.buffer:
            return b""
        try:
            newline_index = self.buffer.index(b"\n") + 1
        except ValueError:
            newline_index = len(self.buffer)
        data = bytes(self.buffer[:newline_index])
        del self.buffer[:newline_index]
        return data

    async def readexactly(self, count: int) -> bytes:
        if len(self.buffer) < count:
            partial = bytes(self.buffer)
            self.buffer.clear()
            raise asyncio.IncompleteReadError(partial=partial, expected=count)
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    async def read(self, count: int = -1) -> bytes:
        if count < 0 or count >= len(self.buffer):
            data = bytes(self.buffer)
            self.buffer.clear()
            return data
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data


class DummyProcess:
    def __init__(self, *, stdin=None, stdout=None, stderr=None) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0
