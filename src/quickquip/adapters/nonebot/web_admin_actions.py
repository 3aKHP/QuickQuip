from __future__ import annotations

import re
from typing import Any

from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    get_llm_service,
    reload_chat_rules_pipeline,
)
from quickquip.app.web.action_queue import WebAdminAction, action_queue
from quickquip.chat.awakening import reload_config as reload_awakening_config
from quickquip.chat.daily_briefing import normalize_period

_SCOPE_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")
_WEB_ADMIN_HEALTH_SCOPE = "__web_admin__"


def _chat_type(scope_key: str) -> str:
    return "private" if scope_key.startswith("private:") else "group"


def _chat_id(scope_key: str) -> str:
    if scope_key == _WEB_ADMIN_HEALTH_SCOPE:
        return scope_key
    return scope_key.removeprefix("private:")


def _validate_scope(scope_key: Any) -> str:
    key = str(scope_key or "").strip()
    if not _SCOPE_KEY_RE.match(key):
        raise ValueError("scope_key must be 5-12 digits or 'private:USER_ID'")
    return key


def _normalize_health_scope(scope_key: Any) -> str:
    key = str(scope_key or "").strip()
    if not key or key == _WEB_ADMIN_HEALTH_SCOPE:
        return _WEB_ADMIN_HEALTH_SCOPE
    return _validate_scope(key)


def _get_bot():
    import nonebot

    return nonebot.get_bot()


async def _execute_runtime_action(action: WebAdminAction) -> dict[str, Any]:
    _ensure_llm_bindings()
    svc = get_llm_service()

    if action.action_type == "llm_reload":
        config = await svc.reload_runtime(background=True)
        return {"ok": not bool(config.load_error), "load_error": config.load_error}

    if action.action_type == "mcp_reload":
        await svc.reload_mcp(background=False)
        return {"ok": True, "status": svc.format_mcp_status(verbose=True)}

    if action.action_type == "personas_reload":
        count, error = svc.reload_personas()
        return {"ok": error is None, "count": count, "error": error}

    if action.action_type == "rules_reload":
        summary = reload_chat_rules_pipeline()
        return {"ok": True, "summary": summary}

    if action.action_type == "awakening_reload":
        reload_awakening_config()
        # 同一 job ID 重注册，使新的 boredom_scan_interval 无需重启立即生效
        from quickquip.adapters.nonebot.awakening_plugin import register_boredom_scan_job

        scan_interval = register_boredom_scan_job()
        summary = reload_chat_rules_pipeline()
        return {"ok": True, "summary": summary, "boredom_scan_interval": scan_interval}

    if action.action_type == "health_check":
        scope_key = _normalize_health_scope(action.payload.get("scope_key"))
        verbose = bool(action.payload.get("verbose", False))
        text = await svc.format_health(_chat_id(scope_key), chat_type=_chat_type(scope_key), verbose=verbose)
        return {"ok": True, "text": text}

    if action.action_type == "clear_context":
        scope_key = _validate_scope(action.payload.get("scope_key"))
        deleted = svc.clear_context(_chat_id(scope_key), chat_type=_chat_type(scope_key))
        return {"deleted": deleted}

    if action.action_type == "delete_context_message":
        scope_key = _validate_scope(action.payload.get("scope_key"))
        message_id = str(action.payload.get("message_id") or "").strip()
        if not message_id:
            raise ValueError("message_id is required")
        deleted = svc.delete_message_from_context(scope_key, message_id)
        return {"deleted": deleted}

    raise ValueError(f"unknown runtime action: {action.action_type}")


async def _execute_summary_now(action: WebAdminAction) -> dict[str, Any]:
    group_id = str(action.payload.get("group_id") or "").strip()
    if not group_id.isdigit():
        raise ValueError("group_id is required")
    from quickquip.adapters.nonebot.daily_summary_plugin import send_daily_summary_now

    return await send_daily_summary_now(group_id, _get_bot())


async def _execute_briefing_now(action: WebAdminAction) -> dict[str, Any]:
    group_id = str(action.payload.get("group_id") or "").strip()
    if not group_id.isdigit():
        raise ValueError("group_id is required")
    period_raw = str(action.payload.get("period") or "").strip()
    period = normalize_period(period_raw) if period_raw else None
    from quickquip.adapters.nonebot.daily_briefing_plugin import send_daily_briefing_now

    return await send_daily_briefing_now(group_id, period, _get_bot())


async def _execute_period_report_now(action: WebAdminAction) -> dict[str, Any]:
    group_id = str(action.payload.get("group_id") or "").strip()
    if not group_id.isdigit():
        raise ValueError("group_id is required")
    period_type = str(action.payload.get("period_type") or "").strip()
    if period_type not in {"weekly", "monthly"}:
        raise ValueError("period_type must be weekly or monthly")
    from quickquip.adapters.nonebot.daily_summary_plugin import send_period_report_now

    return await send_period_report_now(group_id, period_type, _get_bot())


async def execute_web_admin_action(action: WebAdminAction) -> dict[str, Any]:
    if action.action_type == "summary_now":
        return await _execute_summary_now(action)
    if action.action_type == "briefing_now":
        return await _execute_briefing_now(action)
    if action.action_type == "period_report_now":
        return await _execute_period_report_now(action)
    return await _execute_runtime_action(action)


async def process_web_admin_actions(limit: int = 5) -> None:
    for action in action_queue.claim(limit):
        try:
            result = await execute_web_admin_action(action)
        except Exception as exc:
            action_queue.fail(action.id, str(exc))
        else:
            action_queue.complete(action.id, result)
