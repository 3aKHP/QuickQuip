import logging
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.settings import PROJECT_ROOT
from quickquip.llm.config import load_llm_config
from quickquip.llm.store import LLMStore

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = PROJECT_ROOT / "data" / "llm.db"
_LLM_TOML = PROJECT_ROOT / "config" / "llm.toml"

# group_settings is keyed by LLMService.build_chat_scope_key output, which is
# the raw numeric group_id for groups and "private:USER_ID" for private chats.
# Both forms must be accepted; everything else is rejected to stop path-ish
# inputs from reaching SQL.
_SCOPE_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15})$")


def _validate_group_id(group_id: str) -> None:
    if not _SCOPE_KEY_RE.match(group_id):
        raise HTTPException(status_code=422, detail="scope key must be 5-12 digits or 'private:USER_ID'")


def _store() -> LLMStore:
    return LLMStore(_DB)


class GroupSettingsBody(BaseModel):
    # Each field is optional. Pydantic model_dump(exclude_unset=True) is used
    # to distinguish "client omitted" from "client sent null". Sending null
    # clears the override; omitting leaves the field untouched.
    enabled: bool | None = None
    memory_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    provider_id: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    persona_id: str | None = Field(default=None, max_length=64)
    trigger_prefix: str | None = Field(default=None, max_length=32)
    allow_prefix: bool | None = None
    allow_at: bool | None = None
    history_limit: int | None = Field(default=None, ge=0, le=200)


@router.get("/group-settings/options")
def get_options():
    try:
        cfg = load_llm_config(_LLM_TOML)
    except Exception as e:
        logger.warning("failed to load llm.toml for options: %s", e)
        return {"providers": [], "personas": [], "defaults": {}, "load_error": str(e)}

    providers = [
        {
            "id": p.id,
            "default_model": p.default_model,
            "models": list(p.models),
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


@router.get("/group-settings")
def list_group_settings():
    if not _DB.exists():
        return {"groups": []}
    store = _store()
    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT group_id, enabled, memory_enabled, auto_memory_enabled, provider_id, model, persona_id,
                   trigger_prefix, allow_prefix, allow_at, history_limit, updated_at
            FROM group_settings
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return {
        "groups": [
            {
                "group_id": row["group_id"],
                "type": "private" if row["group_id"].startswith("private:") else "group",
                "enabled": None if row["enabled"] is None else bool(row["enabled"]),
                "memory_enabled": None if row["memory_enabled"] is None else bool(row["memory_enabled"]),
                "auto_memory_enabled": None if row["auto_memory_enabled"] is None else bool(row["auto_memory_enabled"]),
                "provider_id": row["provider_id"],
                "model": row["model"],
                "persona_id": row["persona_id"],
                "trigger_prefix": row["trigger_prefix"],
                "allow_prefix": None if row["allow_prefix"] is None else bool(row["allow_prefix"]),
                "allow_at": None if row["allow_at"] is None else bool(row["allow_at"]),
                "history_limit": row["history_limit"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


@router.get("/group-settings/{group_id}")
def get_group_settings(group_id: str):
    _validate_group_id(group_id)
    store = _store()
    override = store.get_group_settings(group_id)
    return asdict(override)


@router.put("/group-settings/{group_id}")
def put_group_settings(group_id: str, body: GroupSettingsBody, request: Request):
    _validate_group_id(group_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    store = _store()
    store.update_group_settings(group_id, **payload)
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
    store = _store()
    with store._connect() as conn:
        cursor = conn.execute(
            "DELETE FROM group_settings WHERE group_id = ?",
            (group_id,),
        )
    logger.warning("group_settings cleared: group=%s deleted=%d", group_id, cursor.rowcount)
    audit_logger.log(
        request,
        action="delete",
        target_type="group_setting",
        target_id=group_id,
    )
    return {"deleted": cursor.rowcount}
