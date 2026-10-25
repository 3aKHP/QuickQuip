import logging
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import LLM_DB_PATH
from quickquip.llm.config import REASONING_EFFORT_CHOICES
from quickquip.llm.config_document import compile_document
from quickquip.llm.config_service import get_config_service
from quickquip.app.web.routes.llm_configuration import ConfigurationRoute
from quickquip.llm.store import LLMStore

router = APIRouter(route_class=ConfigurationRoute)
logger = logging.getLogger(__name__)

_DB = LLM_DB_PATH

# group_settings is keyed by LLMService.build_chat_scope_key output, which is
# the raw numeric group_id for groups and "private:USER_ID" for private chats.
# Both forms must be accepted; everything else is rejected to stop path-ish
# inputs from reaching SQL.
_SCOPE_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")


def _validate_group_id(group_id: str) -> None:
    if not _SCOPE_KEY_RE.match(group_id):
        raise HTTPException(
            status_code=422, detail="scope key must be 5-12 digits or 'private:USER_ID'"
        )


def _store():
    return get_config_service().scope_settings


class GroupSettingsBody(BaseModel):
    # Each field is optional. Pydantic model_dump(exclude_unset=True) is used
    # to distinguish "client omitted" from "client sent null". Sending null
    # clears the override; omitting leaves the field untouched.
    enabled: bool | None = None
    memory_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    agent_delivery_intermediate_enabled: bool | None = None
    agent_delivery_final_enabled: bool | None = None
    provider_id: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    persona_id: str | None = Field(default=None, max_length=64)
    trigger_prefix: str | None = Field(default=None, max_length=32)
    allow_prefix: bool | None = None
    allow_at: bool | None = None
    history_limit: int | None = Field(default=None, ge=0, le=200)
    # 思考档位覆盖（六档词表单源 REASONING_EFFORT_CHOICES；null = 跟随 provider 配置档）
    reasoning_effort: str | None = None

    @field_validator("reasoning_effort")
    @classmethod
    def _check_reasoning_effort(cls, value: str | None) -> str | None:
        if value is not None and value not in REASONING_EFFORT_CHOICES:
            raise ValueError(f"reasoning_effort 须为 {'/'.join(REASONING_EFFORT_CHOICES)} 之一")
        return value


@router.get("/group-settings/options")
def get_options():
    try:
        published = get_config_service().read("published")
        cfg = compile_document(published["document"], revision=published["revision"])
    except Exception as e:
        logger.warning("failed to load published LLM configuration: %s", type(e).__name__)
        return {"providers": [], "personas": [], "defaults": {}, "load_error": str(e)}

    providers = [
        {
            "id": p.id,
            "default_model": p.default_model,
            "models": list(p.models),
            "reasoning_effort": p.reasoning_effort,
        }
        for p in cfg.providers.values()
    ]
    personas = [
        {
            "id": p.id,
            "display_name": p.display_name,
            "scope": list(p.scope),
        }
        for p in cfg.personas.values()
    ]
    defaults = {
        "enabled": cfg.runtime.enabled,
        "memory_enabled": cfg.runtime.memory_enabled,
        "auto_memory_enabled": cfg.runtime.auto_memory_enabled,
        "agent_delivery_intermediate_enabled": cfg.runtime.agent_delivery_intermediate_enabled,
        "agent_delivery_final_enabled": cfg.runtime.agent_delivery_final_enabled,
        "provider_id": cfg.runtime.default_provider,
        "persona_id": cfg.runtime.default_persona,
        "trigger_prefix": cfg.triggers.default_prefix,
        "allow_prefix": cfg.triggers.allow_prefix,
        "allow_at": cfg.triggers.allow_at,
        "history_limit": cfg.runtime.history_limit,
    }
    return {
        "providers": providers,
        "personas": personas,
        "defaults": defaults,
        "load_error": cfg.load_error,
    }


def _format_group_entry(group_id: str, row) -> dict:
    """Format a single group entry, with DB row data merged in if available."""
    entry = {
        "group_id": group_id,
        "type": "private" if group_id.startswith("private:") else "group",
        "enabled": None,
        "memory_enabled": None,
        "auto_memory_enabled": None,
        "agent_delivery_intermediate_enabled": None,
        "agent_delivery_final_enabled": None,
        "provider_id": None,
        "model": None,
        "persona_id": None,
        "trigger_prefix": None,
        "allow_prefix": None,
        "allow_at": None,
        "history_limit": None,
        "reasoning_effort": None,
        "updated_at": None,
    }
    if row is not None:
        entry.update(
            {
                "enabled": None if row["enabled"] is None else bool(row["enabled"]),
                "memory_enabled": (
                    None if row["memory_enabled"] is None else bool(row["memory_enabled"])
                ),
                "auto_memory_enabled": (
                    None if row["auto_memory_enabled"] is None else bool(row["auto_memory_enabled"])
                ),
                "agent_delivery_intermediate_enabled": (
                    None
                    if row["agent_delivery_intermediate_enabled"] is None
                    else bool(row["agent_delivery_intermediate_enabled"])
                ),
                "agent_delivery_final_enabled": (
                    None
                    if row["agent_delivery_final_enabled"] is None
                    else bool(row["agent_delivery_final_enabled"])
                ),
                "provider_id": row["provider_id"],
                "model": row["model"],
                "persona_id": row["persona_id"],
                "trigger_prefix": row["trigger_prefix"],
                "allow_prefix": None if row["allow_prefix"] is None else bool(row["allow_prefix"]),
                "allow_at": None if row["allow_at"] is None else bool(row["allow_at"]),
                "history_limit": row["history_limit"],
                "reasoning_effort": row["reasoning_effort"],
                "updated_at": row["updated_at"],
            }
        )
    return entry


@router.get("/group-settings")
def list_group_settings():
    # Collect all known active group IDs from stats_tracker.
    from quickquip.app.message_pipeline import stats_tracker

    active_groups = set(stats_tracker.to_dict().keys())

    db_entries = {row["group_id"]: row for row in _store().list()}
    states = LLMStore(_DB).list_private_chat_states() if _DB.exists() else {}
    for scope in states:
        db_entries.setdefault(scope, None)

    result: list[dict] = []

    # Phase 1: known active groups first (with merged DB overrides if present).
    for group_id in sorted(active_groups):
        row = db_entries.pop(group_id, None)
        result.append(_format_group_entry(group_id, row))

    # Phase 2: remaining DB entries that are not in active groups.
    # Only include private chats and orphaned numeric groups (so admins can still
    # see pre-configured groups that haven't sent a message yet).
    for group_id, row in db_entries.items():
        result.append(_format_group_entry(group_id, row))

    for entry in result:
        if entry["type"] == "private":
            entry["session_active"] = states.get(entry["group_id"], False)
    return {"groups": result}


@router.get("/group-settings/{group_id}")
def get_group_settings(group_id: str):
    _validate_group_id(group_id)
    store = _store()
    override = store.get_group_settings(group_id)
    result = asdict(override)
    if group_id.startswith("private:"):
        result["session_active"] = LLMStore(_DB).private_chat_active(group_id.split(":", 1)[1])
    return result


@router.put("/group-settings/{group_id}")
def put_group_settings(group_id: str, body: GroupSettingsBody, request: Request):
    _validate_group_id(group_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    get_config_service().update_group_override(group_id, **payload)
    logger.info("group_settings updated: group=%s fields=%s", group_id, list(payload.keys()))
    audit_logger.log(
        request,
        action="update",
        target_type="group_setting",
        target_id=group_id,
        summary_after={"fields": list(payload.keys())},
    )
    return {"ok": True}


@router.delete("/group-settings/{group_id}")
def delete_group_settings(group_id: str, request: Request):
    _validate_group_id(group_id)
    deleted = get_config_service().delete_group_override(group_id)
    logger.warning("group_settings cleared: group=%s deleted=%d", group_id, deleted)
    audit_logger.log(
        request,
        action="delete",
        target_type="group_setting",
        target_id=group_id,
    )
    return {"deleted": deleted}


class PrivateSessionStateBody(BaseModel):
    active: bool


@router.get("/private-sessions/{user_id}/state")
def private_session_state(user_id: str):
    _validate_group_id(f"private:{user_id}")
    return {"active": LLMStore(_DB).private_chat_active(user_id)}


@router.put("/private-sessions/{user_id}/state")
def update_private_session_state(user_id: str, body: PrivateSessionStateBody, request: Request):
    _validate_group_id(f"private:{user_id}")
    LLMStore(_DB).set_private_chat_active(user_id, body.active)
    audit_logger.log(request, action="update", target_type="private_session", target_id=user_id,
                     summary_after={"active": body.active})
    return {"active": body.active}
