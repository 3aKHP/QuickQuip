"""Wave 2: MCP dual-era config validation, types, sanitization, alias conflicts.

Covers:
- MCPServerConfig negotiation field parsing + validation rules
- MCPServerStatus new dual-era fields (backward compat with positional args)
- MCPConnectionInfo dataclass
- Failure kind constants
- _sanitize_url / _sanitize_error_message (secret hygiene)
- _detect_alias_conflicts (fail-closed collision detection)
"""
from __future__ import annotations

from quickquip.llm.config import _read_mcp_servers
from quickquip.llm.mcp.types import (
    MCP_FAILURE_KINDS,
    MCP_FAILURE_TIMEOUT,
    MCPConnectionInfo,
    MCPError,
    MCPServerStatus,
    MCPToolBinding,
    _detect_alias_conflicts,
    _sanitize_error_message,
    _sanitize_url,
)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_missing_negotiation_defaults_to_legacy():
    """Servers without negotiation are strictly legacy (backward compatible)."""
    servers = _read_mcp_servers([{"id": "s1", "transport": "stdio", "command": "echo"}])
    assert len(servers) == 1
    assert servers[0].negotiation == "legacy"
    assert servers[0].supported_protocol_versions == []


def test_legacy_mode_accepted_for_any_transport():
    """Legacy negotiation works with stdio, docker, http, and sse."""
    for transport in ("stdio", "docker", "http", "sse"):
        servers = _read_mcp_servers([{"id": "s1", "transport": transport, "command": "echo"}])
        assert len(servers) == 1
        assert servers[0].negotiation == "legacy"


def test_auto_mode_requires_http_transport():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "stdio", "command": "echo",
         "negotiation": "auto", "supported_protocol_versions": ["2026-07-28"]},
    ])
    assert servers == []


def test_modern_mode_requires_http_transport():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "sse", "url": "http://example.test",
         "negotiation": "modern", "supported_protocol_versions": ["2026-07-28"]},
    ])
    assert servers == []


def test_auto_mode_parses_supported_versions():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "http", "url": "http://example.test/mcp",
         "negotiation": "auto", "supported_protocol_versions": ["2026-07-28", "2026-03-01"]},
    ])
    assert len(servers) == 1
    assert servers[0].negotiation == "auto"
    assert servers[0].supported_protocol_versions == ["2026-07-28", "2026-03-01"]


def test_modern_mode_requires_non_empty_version_list():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "http", "url": "http://example.test/mcp",
         "negotiation": "modern"},
    ])
    assert servers == []


def test_auto_mode_requires_non_empty_version_list():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "http", "url": "http://example.test/mcp",
         "negotiation": "auto"},
    ])
    assert servers == []


def test_unknown_negotiation_mode_skipped():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "http", "url": "http://example.test",
         "negotiation": "future"},
    ])
    assert servers == []


def test_duplicate_server_id_skipped():
    servers = _read_mcp_servers([
        {"id": "dup", "transport": "stdio", "command": "echo"},
        {"id": "dup", "transport": "stdio", "command": "cat"},
    ])
    assert len(servers) == 1
    assert servers[0].command == "echo"


def test_valid_modern_http_server_parsed():
    servers = _read_mcp_servers([
        {"id": "prts", "transport": "http", "url": "http://example.test/mcp",
         "negotiation": "modern", "supported_protocol_versions": ["2026-07-28"]},
    ])
    assert len(servers) == 1
    s = servers[0]
    assert s.negotiation == "modern"
    assert s.supported_protocol_versions == ["2026-07-28"]
    assert s.transport == "http"


def test_whitespace_versions_stripped():
    servers = _read_mcp_servers([
        {"id": "s1", "transport": "http", "url": "http://example.test",
         "negotiation": "modern", "supported_protocol_versions": ["  2026-07-28  ", ""]},
    ])
    assert len(servers) == 1
    assert servers[0].supported_protocol_versions == ["2026-07-28"]


# ---------------------------------------------------------------------------
# MCPServerStatus backward compatibility
# ---------------------------------------------------------------------------

def test_server_status_positional_args_unchanged():
    """Existing positional construction still works (no new required fields)."""
    status = MCPServerStatus("s1", "http", True)
    assert status.id == "s1"
    assert status.transport == "http"
    assert status.enabled is True
    assert status.connected is False
    assert status.tool_count == 0
    assert status.error is None
    assert status.detail == ""
    # New fields have defaults
    assert status.negotiation == "legacy"
    assert status.era == "unknown"
    assert status.failure_kind == ""
    assert status.negotiated_protocol_version == ""


def test_server_status_dual_era_fields_settable():
    status = MCPServerStatus(
        id="s1", transport="http", enabled=True, connected=True,
        negotiation="modern", era="modern",
        failure_kind=MCP_FAILURE_TIMEOUT,
        negotiated_protocol_version="2026-07-28",
    )
    assert status.negotiation == "modern"
    assert status.era == "modern"
    assert status.failure_kind == "timeout"
    assert status.negotiated_protocol_version == "2026-07-28"


# ---------------------------------------------------------------------------
# MCPConnectionInfo
# ---------------------------------------------------------------------------

def test_connection_info_defaults():
    info = MCPConnectionInfo(
        server_id="s1", negotiation="auto", era="unknown",
        configured_protocol_version="2026-07-28",
    )
    assert info.negotiated_protocol_version == ""
    assert info.session_id is None
    assert info.capabilities == {}
    assert info.server_info is None
    assert info.generation == 0


def test_connection_info_modern_has_no_session():
    info = MCPConnectionInfo(
        server_id="s1", negotiation="modern", era="modern",
        configured_protocol_version="2026-07-28",
        negotiated_protocol_version="2026-07-28",
    )
    assert info.session_id is None


# ---------------------------------------------------------------------------
# Failure kind constants
# ---------------------------------------------------------------------------

def test_failure_kinds_are_distinct_strings():
    assert len(MCP_FAILURE_KINDS) == 8
    assert all(isinstance(k, str) for k in MCP_FAILURE_KINDS)


def test_failure_kinds_cover_expected_categories():
    expected = {"config", "probe", "legacy-handshake", "modern-negotiation",
                "auth", "timeout", "routing", "transport"}
    assert MCP_FAILURE_KINDS == expected


# ---------------------------------------------------------------------------
# URL sanitization
# ---------------------------------------------------------------------------

def test_sanitize_url_strips_query_string():
    url = "https://example.test/mcp?token=secret123&key=abc"
    assert _sanitize_url(url) == "https://example.test/mcp"


def test_sanitize_url_strips_fragment():
    url = "https://example.test/mcp#section"
    assert _sanitize_url(url) == "https://example.test/mcp"


def test_sanitize_url_preserves_path():
    url = "https://example.test/api/v1/mcp"
    assert _sanitize_url(url) == "https://example.test/api/v1/mcp"


def test_sanitize_url_preserves_port():
    url = "https://example.test:8443/mcp?token=x"
    assert _sanitize_url(url) == "https://example.test:8443/mcp"


def test_sanitize_url_empty():
    assert _sanitize_url("") == ""


def test_sanitize_url_non_absolute_returned_as_is():
    """Non-URL strings (commands, paths) pass through unchanged."""
    assert _sanitize_url("/usr/bin/python") == "/usr/bin/python"
    assert _sanitize_url("docker run -i image") == "docker run -i image"


# ---------------------------------------------------------------------------
# Error message sanitization
# ---------------------------------------------------------------------------

def test_sanitize_error_message_removes_urls():
    exc = MCPError("连接 https://example.test/mcp?token=SECRET 失败")
    result = _sanitize_error_message(exc)
    assert "SECRET" not in result
    assert "[url]" in result


def test_sanitize_error_message_truncates():
    exc = MCPError("x" * 500)
    assert len(_sanitize_error_message(exc)) == 200


def test_sanitize_error_message_preserves_safe_text():
    exc = MCPError("MCP server s1 调用 initialize 超时")
    assert _sanitize_error_message(exc) == "MCP server s1 调用 initialize 超时"


# ---------------------------------------------------------------------------
# Alias conflict detection
# ---------------------------------------------------------------------------

def test_detect_alias_conflicts_no_duplicates():
    bindings = [
        MCPToolBinding(alias="mcp_a_tool1", server_id="a", tool_name="tool1", description="", input_schema={}),
        MCPToolBinding(alias="mcp_b_tool2", server_id="b", tool_name="tool2", description="", input_schema={}),
    ]
    assert _detect_alias_conflicts(bindings) == set()


def test_detect_alias_conflicts_finds_exact_duplicates():
    bindings = [
        MCPToolBinding(alias="mcp_a_tool1", server_id="a", tool_name="tool1", description="", input_schema={}),
        MCPToolBinding(alias="mcp_a_tool1", server_id="b", tool_name="tool1", description="", input_schema={}),
    ]
    assert _detect_alias_conflicts(bindings) == {"mcp_a_tool1"}


def test_detect_alias_conflicts_finds_sanitization_collisions():
    """_sanitize_tool_name normalizes 'foo.bar' and 'foo_bar' to the same alias."""
    from quickquip.llm.mcp.types import _build_tool_alias

    alias1 = _build_tool_alias("srv", "foo.bar")
    alias2 = _build_tool_alias("srv", "foo_bar")
    # The sanitizer replaces '.' with '_', producing identical aliases
    assert alias1 == alias2

    bindings = [
        MCPToolBinding(alias=alias1, server_id="srv", tool_name="foo.bar", description="", input_schema={}),
        MCPToolBinding(alias=alias2, server_id="srv", tool_name="foo_bar", description="", input_schema={}),
    ]
    conflicts = _detect_alias_conflicts(bindings)
    assert alias1 in conflicts


def test_detect_alias_conflicts_empty():
    assert _detect_alias_conflicts([]) == set()
