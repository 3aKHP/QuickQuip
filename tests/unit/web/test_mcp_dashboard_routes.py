from __future__ import annotations

import json

from quickquip.app.web.routes import mcp_dashboard


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
    assert server["negotiated_protocol_version"] == "2025-06-18"
    assert server["failure_kind"] == ""


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
    assert server["negotiated_protocol_version"] == ""
