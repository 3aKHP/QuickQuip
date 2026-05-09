from __future__ import annotations

import json

from fastapi import APIRouter

from quickquip.common.paths import CONFIG_LLM_TOML, MCP_STATUS_JSON_PATH
from quickquip.llm.config import load_llm_config

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
            server_tools[sid].append({
                "name": b["tool_name"],
                "description": b["description"],
            })

        servers = []
        for s in data["statuses"]:
            servers.append({
                "id": s["id"],
                "transport": s.get("transport", ""),
                "enabled": s.get("enabled", False),
                "connected": s.get("connected", False),
                "tool_count": s.get("tool_count", 0),
                "error": s.get("error"),
                "detail": s.get("detail", ""),
                "tools": server_tools.get(s["id"], []),
                "runtime_available": True,
            })
        return {"servers": servers}

    # 2) Runtime MCP manager (same process, e.g. local dev)
    try:
        from quickquip.llm.service import llm_service

        statuses = llm_service.mcp_manager.get_statuses()
        bindings = llm_service.mcp_manager.bindings
    except Exception:
        statuses = []
        bindings = {}

    if statuses:
        server_tools: dict[str, list[dict]] = {}
        for binding in bindings.values():
            if binding.server_id not in server_tools:
                server_tools[binding.server_id] = []
            server_tools[binding.server_id].append({
                "name": binding.tool_name,
                "description": binding.description,
            })

        servers = []
        for status in statuses:
            servers.append({
                "id": status.id,
                "transport": status.transport,
                "enabled": status.enabled,
                "connected": status.connected,
                "tool_count": status.tool_count,
                "error": status.error,
                "detail": status.detail,
                "tools": server_tools.get(status.id, []),
                "runtime_available": True,
            })
        return {"servers": servers}

    # 3) Config-only: no runtime data available at all
    config = load_llm_config(CONFIG_LLM_TOML)
    if config.load_error or not config.mcp.servers:
        return {"servers": []}

    servers = []
    for s in config.mcp.servers:
        servers.append({
            "id": s.id,
            "transport": s.transport,
            "enabled": s.enabled,
            "connected": False,
            "tool_count": 0,
            "error": None,
            "detail": "runtime 未连接（等待 bot 进程写入状态文件）",
            "tools": [],
            "runtime_available": False,
        })
    return {"servers": servers}
