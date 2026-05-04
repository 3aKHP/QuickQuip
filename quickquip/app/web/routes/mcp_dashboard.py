from __future__ import annotations

from fastapi import APIRouter

from quickquip.llm.config import load_llm_config

router = APIRouter()


@router.get("/mcp-dashboard")
def get_mcp_dashboard():
    # Try the runtime MCP manager first
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

    # Fallback: read server list from config when runtime is unavailable.
    # Set runtime_available=False so the frontend can show a neutral
    # "status unknown" indicator instead of the alarming "connection failed".
    config = load_llm_config("config/llm.toml")
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
            "detail": "runtime 未连接（web-admin 进程未同步 MCP）",
            "tools": [],
            "runtime_available": False,
        })
    return {"servers": servers}
