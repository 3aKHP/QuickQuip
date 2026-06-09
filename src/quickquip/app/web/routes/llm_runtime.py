from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from quickquip.app.web.action_queue import action_queue
from quickquip.app.web.audit import audit_logger

router = APIRouter()

_SCOPE_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")
_WEB_ADMIN_HEALTH_SCOPE = "__web_admin__"


class ScopeBody(BaseModel):
    scope_key: str


class DeleteMessageBody(BaseModel):
    scope_key: str
    message_id: str


class HealthBody(BaseModel):
    verbose: bool = False
    scope_key: str = _WEB_ADMIN_HEALTH_SCOPE


def _validate_scope_key(scope_key: str) -> str:
    key = scope_key.strip()
    if not _SCOPE_KEY_RE.match(key):
        raise HTTPException(status_code=422, detail="scope_key must be 5-12 digits or 'private:USER_ID'")
    return key


def _validate_health_scope_key(scope_key: str) -> str:
    key = scope_key.strip()
    if not key or key == _WEB_ADMIN_HEALTH_SCOPE:
        return _WEB_ADMIN_HEALTH_SCOPE
    return _validate_scope_key(key)


@router.post("/llm-runtime/health")
def queue_health_check(body: HealthBody, request: Request):
    scope_key = _validate_health_scope_key(body.scope_key)
    action = action_queue.enqueue("health_check", {"verbose": body.verbose, "scope_key": scope_key})
    audit_logger.log(
        request,
        action="queue",
        target_type="llm_runtime",
        target_id="health",
        summary_after={"action_id": action["id"], "verbose": body.verbose, "scope_key": scope_key},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/reload")
def reload_runtime(request: Request):
    action = action_queue.enqueue("llm_reload")
    audit_logger.log(request, action="queue", target_type="llm_runtime", target_id="config", summary_after={"action_id": action["id"]})
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/mcp/reload")
def reload_mcp(request: Request):
    action = action_queue.enqueue("mcp_reload")
    audit_logger.log(request, action="queue", target_type="llm_runtime", target_id="mcp", summary_after={"action_id": action["id"]})
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/personas/reload")
def reload_personas(request: Request):
    action = action_queue.enqueue("personas_reload")
    audit_logger.log(
        request,
        action="queue",
        target_type="llm_runtime",
        target_id="personas",
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/rules/reload")
def reload_rules(request: Request):
    action = action_queue.enqueue("rules_reload")
    audit_logger.log(
        request,
        action="queue",
        target_type="llm_runtime",
        target_id="chat_rules",
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/context/clear")
def clear_context(body: ScopeBody, request: Request):
    scope_key = _validate_scope_key(body.scope_key)
    action = action_queue.enqueue("clear_context", {"scope_key": scope_key})
    audit_logger.log(
        request,
        action="queue",
        target_type="llm_context",
        target_id=scope_key,
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.post("/llm-runtime/context/delete-message")
def delete_message(body: DeleteMessageBody, request: Request):
    scope_key = _validate_scope_key(body.scope_key)
    message_id = body.message_id.strip()
    if not message_id:
        raise HTTPException(status_code=422, detail="message_id is required")
    action = action_queue.enqueue(
        "delete_context_message",
        {"scope_key": scope_key, "message_id": message_id},
    )
    audit_logger.log(
        request,
        action="queue",
        target_type="llm_context_message",
        target_id=f"{scope_key}:{message_id}",
        summary_after={"action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action}


@router.get("/llm-runtime/actions")
def list_actions(limit: int = 20):
    return {"actions": action_queue.list_recent(limit)}
