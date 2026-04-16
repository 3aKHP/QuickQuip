import logging
import re
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quickquip.app.web.settings import PROJECT_ROOT
from quickquip.llm.config import load_llm_config
from quickquip.llm.store import LLMStore

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = PROJECT_ROOT / "data" / "llm.db"
_LLM_TOML = PROJECT_ROOT / "config" / "llm.toml"
_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


def _store() -> LLMStore:
    return LLMStore(_DB)


class GroupSettingsBody(BaseModel):
    # Each field is optional. Pydantic model_dump(exclude_unset=True) is used
    # to distinguish "client omitted" from "client sent null". Sending null
    # clears the override; omitting leaves the field untouched.
    enabled: bool | None = None
    memory_enabled: bool | None = None
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
            SELECT group_id, enabled, memory_enabled, provider_id, model, persona_id,
                   trigger_prefix, allow_prefix, allow_at, history_limit, updated_at
            FROM group_settings
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return {
        "groups": [
            {
                "group_id": row["group_id"],
                "enabled": None if row["enabled"] is None else bool(row["enabled"]),
                "memory_enabled": None if row["memory_enabled"] is None else bool(row["memory_enabled"]),
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
def put_group_settings(group_id: str, body: GroupSettingsBody):
    _validate_group_id(group_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    store = _store()
    store.update_group_settings(group_id, **payload)
    logger.info("group_settings updated: group=%s fields=%s", group_id, list(payload.keys()))
    return {"ok": True}


@router.delete("/group-settings/{group_id}")
def delete_group_settings(group_id: str):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        cursor = conn.execute(
            "DELETE FROM group_settings WHERE group_id = ?",
            (group_id,),
        )
    logger.warning("group_settings cleared: group=%s deleted=%d", group_id, cursor.rowcount)
    return {"deleted": cursor.rowcount}
