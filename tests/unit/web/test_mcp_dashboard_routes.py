from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import mcp_dashboard  # noqa: E402


def test_dashboard_status_file_branch_exposes_era_fields(tmp_path, monkeypatch):
    status_file = tmp_path / "mcp_status.json"
    status_file.write_text(
        json.dumps(
            {
                "statuses": [
                    {
                        "id": "example",
                        "transport": "http",
                        "enabled": True,
                        "connected": True,
                        "tool_count": 2,
                        "error": None,
                        "detail": "https://mcp.internal:8443/private/path",
                        "server_identity": "demo-server 1.2.3",
                        "negotiation": "modern",
                        "era": "modern",
                        "failure_kind": "",
                        "negotiated_protocol_version": "2025-06-18",
                    }
                ],
                "bindings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_dashboard, "_STATUS_PATH", status_file)

    server = mcp_dashboard.get_mcp_dashboard()["servers"][0]

    assert server["server_identity"] == "demo-server 1.2.3"
    assert server["negotiation"] == "modern"
    assert server["era"] == "modern"
    assert server["era_tag"] == "/modern"
    assert server["negotiated_protocol_version"] == "2025-06-18"
    assert server["failure_kind"] == ""


def test_dashboard_status_file_branch_mixed_era_tag(tmp_path, monkeypatch):
    status_file = tmp_path / "mcp_status.json"
    status_file.write_text(
        json.dumps(
            {
                "statuses": [
                    {
                        "id": "auto-server",
                        "transport": "http",
                        "enabled": True,
                        "connected": True,
                        "tool_count": 1,
                        "negotiation": "auto",
                        "era": "legacy",
                    }
                ],
                "bindings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_dashboard, "_STATUS_PATH", status_file)

    server = mcp_dashboard.get_mcp_dashboard()["servers"][0]
    assert server["era_tag"] == "/auto/legacy"


def test_dashboard_status_file_branch_defaults_missing_era_fields(tmp_path, monkeypatch):
    """Status files written by older bot versions lack the new fields."""
    status_file = tmp_path / "mcp_status.json"
    status_file.write_text(
        json.dumps(
            {
                "statuses": [
                    {
                        "id": "example",
                        "transport": "http",
                        "enabled": True,
                        "connected": True,
                        "tool_count": 0,
                        "error": None,
                        "detail": "",
                    }
                ],
                "bindings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_dashboard, "_STATUS_PATH", status_file)

    server = mcp_dashboard.get_mcp_dashboard()["servers"][0]

    assert server["server_identity"] == ""
    assert server["negotiation"] == "legacy"
    assert server["era"] == "unknown"
    assert server["era_tag"] == ""  # legacy/unknown 不显示多余标签
    assert server["negotiated_protocol_version"] == ""


def test_dashboard_runtime_branch_exposes_era_tag(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from quickquip.llm.mcp.types import MCPServerStatus

    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(mcp_dashboard, "_STATUS_PATH", tmp_path / "missing.json")

    status = MCPServerStatus(
        id="runtime-server",
        transport="http",
        enabled=True,
        connected=True,
        tool_count=3,
        negotiation="modern",
        era="modern",
    )

    manager = SimpleNamespace(
        get_statuses=lambda: [status],
        bindings={},
    )
    monkeypatch.setattr(message_pipeline, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(message_pipeline, "get_llm_service", lambda: SimpleNamespace(mcp_manager=manager))

    server = mcp_dashboard.get_mcp_dashboard()["servers"][0]

    assert server["id"] == "runtime-server"
    assert server["runtime_available"] is True
    assert server["era_tag"] == "/modern"


def test_dashboard_config_only_branch_era_tag_empty(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import quickquip.app.message_pipeline as message_pipeline

    monkeypatch.setattr(mcp_dashboard, "_STATUS_PATH", tmp_path / "missing.json")
    # 运行时分支直接失败，落到 config-only 分支
    monkeypatch.setattr(
        message_pipeline,
        "_ensure_llm_bindings",
        lambda: (_ for _ in ()).throw(RuntimeError("no runtime")),
    )

    server_entry = SimpleNamespace(id="cfg-server", transport="stdio", enabled=True)

    def _fake_load(_path):
        return SimpleNamespace(load_error=None, mcp=SimpleNamespace(servers=[server_entry]))

    monkeypatch.setattr(mcp_dashboard, "load_llm_config", _fake_load)

    server = mcp_dashboard.get_mcp_dashboard()["servers"][0]

    assert server["id"] == "cfg-server"
    assert server["runtime_available"] is False
    assert server["era_tag"] == ""
