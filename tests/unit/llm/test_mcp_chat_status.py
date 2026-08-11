"""Chat-visible MCP status disclosure tests (issue #103).

Covers:
- era tag de-duplication in strict modern mode
- chat output never falling back to configured endpoint (URL/image/command)

Dashboard route coverage lives in tests/unit/web/test_mcp_dashboard_routes.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from quickquip.llm.mcp.client import MCPClientManager
from quickquip.llm.mcp.types import MCPServerStatus


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
