from __future__ import annotations

import json

from fastapi import APIRouter

from quickquip.common.paths import MCP_STATUS_JSON_PATH
from quickquip.llm.config_document import compile_document
from quickquip.llm.config_service import get_config_service
from quickquip.llm.mcp.types import format_mcp_era_tag

router = APIRouter()

_STATUS_PATH = MCP_STATUS_JSON_PATH


def _read_status_file() -> dict | None:
    try:
        return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@router.get("/mcp-dashboard")
def get_mcp_dashboard():
    # 1) Shared status file (written by bot process after each MCP sync)
    data = _read_status_file()
    if data and data.get("statuses"):
        server_tools: dict[str, list[dict]] = {}
        for b in data.get("bindings", []):
            sid = b["server_id"]
            if sid not in server_tools:
                server_tools[sid] = []
            server_tools[sid].append(
                {
                    "name": b["tool_name"],
                    "description": b["description"],
                }
            )

        servers = []
        for s in data["statuses"]:
            negotiation = s.get("negotiation", "legacy")
            era = s.get("era", "unknown")
            servers.append(
                {
                    "id": s["id"],
                    "transport": s.get("transport", ""),
                    "enabled": s.get("enabled", False),
                    "connected": s.get("connected", False),
                    "tool_count": s.get("tool_count", 0),
                    "error": s.get("error"),
                    "detail": s.get("detail", ""),
                    "server_identity": s.get("server_identity", ""),
                    "negotiation": negotiation,
                    "era": era,
                    "era_tag": format_mcp_era_tag(negotiation, era),
                    "failure_kind": s.get("failure_kind", ""),
                    "negotiated_protocol_version": s.get("negotiated_protocol_version", ""),
                    "tools": server_tools.get(s["id"], []),
                    "runtime_available": True,
                }
            )
        return {"servers": servers}

    # Published configuration describes expected servers; bot status is the runtime authority.
    published = get_config_service().read("published")
    config = compile_document(published["document"], revision=published["revision"])
    if config.load_error or not config.mcp.servers:
        return {"servers": []}

    servers = []
    for s in config.mcp.servers:
        negotiation = getattr(s, "negotiation", "legacy")
        servers.append(
            {
                "id": s.id,
                "transport": s.transport,
                "enabled": s.enabled,
                "connected": False,
                "tool_count": 0,
                "error": None,
                "detail": "runtime 未连接（等待 bot 进程写入状态文件）",
                "negotiation": negotiation,
                "era": "unknown",
                "era_tag": "",
                "failure_kind": "",
                "negotiated_protocol_version": "",
                "tools": [],
                "runtime_available": False,
            }
        )
    return {"servers": servers}
