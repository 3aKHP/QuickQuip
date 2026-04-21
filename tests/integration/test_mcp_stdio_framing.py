"""MCP stdio transport must support two framings:
- line-based JSON (bare JSON + newline)
- Content-Length headers (LSP-style)
"""
from __future__ import annotations

import json

from plugins.llm_config import MCPServerConfig
from quickquip.llm.mcp import StdioTransport

from tests.fixtures.mcp_io import DummyAsyncReader, DummyAsyncWriter, DummyProcess


async def test_send_emits_line_without_content_length_header():
    transport = StdioTransport(MCPServerConfig(id="stdio-test"))
    writer = DummyAsyncWriter()
    transport.process = DummyProcess(
        stdin=writer,
        stdout=DummyAsyncReader(),
        stderr=DummyAsyncReader(),
    )

    await transport.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    sent = writer.buffer.decode("utf-8")
    assert "Content-Length" not in sent
    assert sent.endswith("\n")
    assert json.loads(sent.strip())["method"] == "initialize"


async def test_read_line_framed_message():
    transport = StdioTransport(MCPServerConfig(id="stdio-test"))
    line_message = b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
    transport.process = DummyProcess(
        stdin=DummyAsyncWriter(),
        stdout=DummyAsyncReader(line_message),
        stderr=DummyAsyncReader(),
    )
    msg = await transport._read_message()
    assert msg == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


async def test_read_content_length_framed_message():
    transport = StdioTransport(MCPServerConfig(id="stdio-test"))
    payload = b'{"jsonrpc":"2.0","id":2,"result":{"ok":true}}'
    header_message = (
        f"Content-Length: {len(payload)}\r\nX-Test: 1\r\n\r\n".encode("ascii") + payload
    )
    transport.process = DummyProcess(
        stdin=DummyAsyncWriter(),
        stdout=DummyAsyncReader(header_message),
        stderr=DummyAsyncReader(),
    )
    msg = await transport._read_message()
    assert msg == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
