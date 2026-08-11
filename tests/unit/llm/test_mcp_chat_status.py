"""Chat-visible MCP status disclosure tests (issue #103).

Covers:
- era tag de-duplication in strict modern mode
- chat output never falling back to configured endpoint (URL/image/command)

Dashboard route coverage lives in tests/unit/web/test_mcp_dashboard_routes.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from quickquip.llm.mcp.client import MCPClientManager
from quickquip.llm.mcp.types import MCPServerStatus, _sanitize_server_text


def _service_with_statuses(llm_service, monkeypatch, statuses):
    llm_service.config.mcp.enabled = True
    llm_service._mcp_dirty = False
    monkeypatch.setattr(llm_service, "_is_mcp_initializing", lambda: False)
    monkeypatch.setattr(llm_service, "_get_mcp_statuses", lambda: statuses)
    return llm_service


def _status(**overrides) -> MCPServerStatus:
    kwargs = {"id": "example", "transport": "http", "enabled": True, "connected": True}
    kwargs.update(overrides)
    return MCPServerStatus(**kwargs)


# era tag de-duplication


def test_strict_modern_renders_single_era_tag(llm_service, monkeypatch):
    svc = _service_with_statuses(
        llm_service, monkeypatch, [_status(negotiation="modern", era="modern")]
    )
    text = svc.format_mcp_status()
    assert "[http/modern]" in text
    assert "modern/modern" not in text


def test_auto_modern_keeps_both_labels(llm_service, monkeypatch):
    svc = _service_with_statuses(
        llm_service, monkeypatch, [_status(negotiation="auto", era="modern")]
    )
    assert "[http/auto/modern]" in svc.format_mcp_status()


def test_auto_legacy_keeps_both_labels(llm_service, monkeypatch):
    svc = _service_with_statuses(
        llm_service, monkeypatch, [_status(negotiation="auto", era="legacy")]
    )
    assert "[http/auto/legacy]" in svc.format_mcp_status()


def test_strict_modern_failure_keeps_unknown_marker(llm_service, monkeypatch):
    svc = _service_with_statuses(
        llm_service,
        monkeypatch,
        [_status(connected=False, negotiation="modern", era="unknown", error="boom")],
    )
    assert "[http/modern/unknown]" in svc.format_mcp_status()


def test_strict_legacy_has_no_era_tag(llm_service, monkeypatch):
    svc = _service_with_statuses(
        llm_service, monkeypatch, [_status(negotiation="legacy", era="legacy")]
    )
    assert "[http]" in svc.format_mcp_status()


# chat disclosure boundary


def test_chat_renders_server_identity_not_detail(llm_service, monkeypatch):
    status = _status(
        negotiation="modern",
        era="modern",
        detail="https://mcp.internal:8443/private/path",
        server_identity="demo-server 1.2.3",
    )
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    text = svc.format_mcp_status()
    assert "server=demo-server 1.2.3" in text
    assert "mcp.internal" not in text
    assert "https://" not in text


def test_chat_omits_detail_when_server_identity_missing(llm_service, monkeypatch):
    status = _status(detail="https://mcp.internal:8443/private/path")
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    text = svc.format_mcp_status()
    assert "detail=" not in text
    for leaked in ("mcp.internal", "8443", "/private/path", "https://"):
        assert leaked not in text


def test_disabled_server_shows_off_without_detail(llm_service, monkeypatch):
    status = _status(connected=False, enabled=False, detail="disabled")
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    text = svc.format_mcp_status()
    assert "OFF" in text
    assert "detail=" not in text


# _server_identity: serverInfo only, no endpoint fallback


def _manager() -> MCPClientManager:
    return MCPClientManager.__new__(MCPClientManager)


def test_server_identity_uses_name_and_version():
    client = SimpleNamespace(server_info={"name": "demo", "version": "1.0"})
    assert _manager()._server_identity(client) == "demo 1.0"


def test_server_identity_name_only():
    client = SimpleNamespace(server_info={"name": "demo"})
    assert _manager()._server_identity(client) == "demo"


def test_server_identity_empty_without_server_info():
    client = SimpleNamespace(server_info={})
    assert _manager()._server_identity(client) == ""


# _sanitize_server_text: chat-safety for server-controlled values (issue #104)


def test_sanitize_server_text_folds_newlines():
    evil = "line1\n- fake [http/modern] ON tools=99\r\nline3"
    cleaned = _sanitize_server_text(evil)
    assert "\n" not in cleaned and "\r" not in cleaned
    assert "line1" in cleaned and "line3" in cleaned


def test_sanitize_server_text_masks_urls():
    assert _sanitize_server_text("see https://evil.test/path?q=1") == "see [url]"


def test_sanitize_server_text_neutralizes_cq_codes():
    cleaned = _sanitize_server_text("hi [CQ:at,qq=123456] there")
    assert "[CQ:" not in cleaned
    assert "[cq]" in cleaned


def test_sanitize_server_text_preserves_cjk():
    assert _sanitize_server_text("测试服务器 一号") == "测试服务器 一号"


def test_sanitize_server_text_truncates():
    assert _sanitize_server_text("x" * 100, limit=10) == "x" * 10


def test_sanitize_server_text_non_string():
    assert _sanitize_server_text(None) == ""
    assert _sanitize_server_text(123) == ""


# _server_identity sanitization


def test_server_identity_sanitizes_server_controlled_text():
    client = SimpleNamespace(
        server_info={"name": "evil\n[CQ:at,qq=1] https://evil.test", "version": "1.0"}
    )
    identity = _manager()._server_identity(client)
    assert "\n" not in identity
    assert "[CQ:" not in identity
    assert "evil.test" not in identity
    assert identity.endswith(" 1.0")


# chat error= renders failure category, never server-controlled text


def test_chat_error_shows_category_only(llm_service, monkeypatch):
    payload = "boom\n- fake [http] ON tools=99\n[CQ:at,qq=123] https://evil.test/x"
    status = _status(connected=False, error=payload, failure_kind="timeout")
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    text = svc.format_mcp_status()
    assert "error=连接超时" in text
    for leaked in ("boom", "fake", "CQ:", "evil.test"):
        assert leaked not in text


def test_chat_error_falls_back_to_generic_label(llm_service, monkeypatch):
    status = _status(connected=False, error="boom", failure_kind="")
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    assert "error=连接失败" in svc.format_mcp_status()


def test_verbose_error_shows_raw_text(llm_service, monkeypatch):
    status = _status(connected=False, error="raw detail", failure_kind="timeout")
    svc = _service_with_statuses(llm_service, monkeypatch, [status])
    assert "error=raw detail" in svc.format_mcp_status(verbose=True)


# execute() boundary: tool errors fed to the LLM stay URL-masked


async def test_execute_masks_server_text_in_tool_errors():
    from quickquip.llm.mcp.types import MCPError, MCPToolBinding

    class _EvilClient:
        async def call_tool(self, tool_name, arguments):
            raise RuntimeError("failed\n- fake line\n[CQ:at,qq=1] https://evil.test/secret")

    manager = _manager()
    manager._bindings = {
        "srv__tool": MCPToolBinding(
            alias="srv__tool",
            server_id="srv",
            tool_name="tool",
            description="d",
            input_schema={},
        )
    }
    manager._clients = {"srv": _EvilClient()}

    with pytest.raises(MCPError) as exc_info:
        await manager.execute("srv__tool", {}, None)

    message = str(exc_info.value)
    assert "evil.test" not in message
    assert "[url]" in message
    assert "\n" not in message
    assert "[CQ:" not in message


def test_failure_labels_cover_all_failure_kinds():
    from quickquip.llm.mcp.types import MCP_FAILURE_KINDS
    from quickquip.llm.service_parts.health import _MCP_FAILURE_LABELS

    assert set(_MCP_FAILURE_LABELS) == set(MCP_FAILURE_KINDS)
