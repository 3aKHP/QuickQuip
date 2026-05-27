from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    daily_briefing_enabled_groups,
    daily_enabled_groups,
    get_llm_service,
    reload_chat_rules_pipeline,
    rule_switch,
)
from quickquip.app.web.action_queue import WebAdminAction, action_queue
from quickquip.chat.daily_briefing import normalize_period

_SCOPE_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")


def _chat_type(scope_key: str) -> str:
    return "private" if scope_key.startswith("private:") else "group"


def _chat_id(scope_key: str) -> str:
    return scope_key.removeprefix("private:")


def _validate_scope(scope_key: Any) -> str:
    key = str(scope_key or "").strip()
    if not _SCOPE_KEY_RE.match(key):
        raise ValueError("scope_key must be 5-12 digits or 'private:USER_ID'")
    return key


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
        return {"ok": True, "status": svc.format_mcp_status()}

    if action.action_type == "personas_reload":
        count, error = svc.reload_personas()
        return {"ok": error is None, "count": count, "error": error}

    if action.action_type == "rules_reload":
        summary = reload_chat_rules_pipeline()
        return {"ok": True, "summary": summary}

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
    if not daily_enabled_groups.contains(group_id):
        raise RuntimeError("daily summary is not enabled for this group")

    from quickquip.adapters.nonebot.daily_summary_plugin import (
        _LOCAL_TZ,
        _mark_triggered,
        _on_cooldown,
        _run_generation,
        _send_long_message,
    )

    if _on_cooldown(group_id):
        raise RuntimeError("summary generation is on cooldown")

    bot = _get_bot()
    _mark_triggered(group_id)

    now = datetime.now(tz=_LOCAL_TZ)
    yesterday = now.date() - timedelta(days=1)
    start_dt = now.replace(
        year=yesterday.year,
        month=yesterday.month,
        day=yesterday.day,
        hour=6,
        minute=0,
        second=0,
        microsecond=0,
    )
    date_label = (
        start_dt.strftime("%Y年%m月%d日 06:00")
        + " 至 "
        + now.strftime("%m月%d日 %H:%M")
    )
    result = await _run_generation(
        group_id,
        start_dt.timestamp(),
        now.timestamp(),
        date_label,
    )
    if result is None:
        raise RuntimeError("summary generation skipped or failed")

    content, model_used = result
    await _send_long_message(bot, int(group_id), content)
    return {"model_used": model_used, "char_count": len(content)}


async def _execute_briefing_now(action: WebAdminAction) -> dict[str, Any]:
    group_id = str(action.payload.get("group_id") or "").strip()
    if not group_id.isdigit():
        raise ValueError("group_id is required")
    if not daily_briefing_enabled_groups.contains(group_id) or not rule_switch.is_enabled(group_id, "daily_briefing"):
        raise RuntimeError("daily briefing is not enabled for this group")

    from quickquip.adapters.nonebot.daily_briefing_plugin import (
        _LOCAL_TZ,
        _default_period_for_now,
        _mark_triggered,
        _on_cooldown,
        _render_briefing,
    )

    if _on_cooldown(group_id):
        raise RuntimeError("briefing generation is on cooldown")

    period_raw = str(action.payload.get("period") or "").strip()
    period = normalize_period(period_raw) if period_raw else None
    if period is None:
        period = _default_period_for_now(datetime.now(tz=_LOCAL_TZ))

    bot = _get_bot()
    _mark_triggered(group_id)
    content, model_used = await _render_briefing(group_id, period)
    await bot.send_group_msg(group_id=int(group_id), message=content)
    return {"period": period, "model_used": model_used, "char_count": len(content)}


async def execute_web_admin_action(action: WebAdminAction) -> dict[str, Any]:
    if action.action_type == "summary_now":
        return await _execute_summary_now(action)
    if action.action_type == "briefing_now":
        return await _execute_briefing_now(action)
    return await _execute_runtime_action(action)


async def process_web_admin_actions(limit: int = 5) -> None:
    for action in action_queue.claim(limit):
        try:
            result = await execute_web_admin_action(action)
        except Exception as exc:
            action_queue.fail(action.id, str(exc))
        else:
            action_queue.complete(action.id, result)
