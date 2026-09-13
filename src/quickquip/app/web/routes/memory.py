from datetime import datetime, timezone
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from typing import Annotated, Literal

from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import LLM_DB_PATH
from quickquip.llm.store import LLMStore
from quickquip.app.identities import web_identities
from quickquip.common.record_content import QQ, plain, render, save_parts, validate

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = LLM_DB_PATH

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


def _store() -> LLMStore:
    store = LLMStore(_DB)
    store.identity_repository = web_identities
    return store


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


class MemoryCreate(BaseModel):
    content: str = Field(default="", max_length=4096)
    content_parts: dict | None = None
    scope: Literal["group", "user"] = "group"
    user_id: str | None = None
    tags: list[Annotated[str, Field(max_length=64)]] = Field(default=[], max_length=32)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_body(self):
        if self.content_parts is None and "content" not in self.model_fields_set:
            raise ValueError("content or content_parts is required")
        return self


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=4096)
    content_parts: dict | None = None
    tags: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@router.get("/memory/{group_id}")
def list_memories(
    group_id: str,
    keyword: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=200, ge=1, le=500),
):
    _validate_group_id(group_id)
    store = _store()
    return store.list_memories(group_id, keyword=keyword, limit=limit)


@router.post("/memory/{group_id}", status_code=201)
def create_memory(group_id: str, body: MemoryCreate, request: Request):
    _validate_group_id(group_id)
    store = _store()
    parts = _validated_parts(body.content_parts)
    mem_id = store.add_memory(
        group_id,
        body.content,
        scope=body.scope,
        user_id=body.user_id,
        tags=body.tags,
        source="manual",
        confidence=body.confidence,
        content_parts=parts,
    )
    logger.info("memory created: group=%s id=%d scope=%s", group_id, mem_id, body.scope)
    audit_logger.log(
        request,
        action="create",
        target_type="memory",
        target_id=f"{group_id}:{mem_id}",
        summary_after={"scope": body.scope, "content": (render(parts) if parts is not None else body.content)[:100]},
    )
    return {"id": mem_id}


@router.put("/memory/{group_id}/{mem_id}")
def update_memory(group_id: str, mem_id: int, body: MemoryUpdate, request: Request):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="memory not found")
        old_content = row["content"]
        old_tags = row["tags_json"]
        old_conf = row["confidence"]
        parts = _validated_parts(body.content_parts)
        new_content = render(parts) if parts is not None else body.content if body.content is not None else old_content
        new_tags = json.dumps(body.tags, ensure_ascii=False) if body.tags is not None else old_tags
        new_conf = body.confidence if body.confidence is not None else old_conf
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE memories SET content=?, tags_json=?, confidence=?, updated_at=? WHERE id=?",
            (new_content, new_tags, new_conf, now, mem_id),
        )
        if parts is not None or body.content is not None:
            save_parts(conn, "memories", mem_id, group_id, parts if parts is not None else plain(new_content))
    logger.info("memory updated: group=%s id=%d", group_id, mem_id)
    audit_logger.log(
        request,
        action="update",
        target_type="memory",
        target_id=f"{group_id}:{mem_id}",
        summary_before={"content": old_content[:100], "tags": old_tags, "confidence": old_conf},
        summary_after={"content": new_content[:100], "tags": new_tags, "confidence": new_conf},
    )
    return {"ok": True}


@router.delete("/memory/{group_id}/{mem_id}")
def delete_memory(group_id: str, mem_id: int, request: Request):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="memory not found")
        summary_before = {"content": row["content"][:100], "tags": row["tags_json"], "confidence": row["confidence"]}
        cur = conn.execute(
            "DELETE FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="memory not found")
    logger.warning("memory deleted: group=%s id=%d", group_id, mem_id)
    audit_logger.log(
        request,
        action="delete",
        target_type="memory",
        target_id=f"{group_id}:{mem_id}",
        summary_before=summary_before,
    )
    return {"ok": True}


@router.delete("/memory/{group_id}")
def clear_memories(group_id: str, request: Request):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE group_id = ?", (group_id,))
        count = cur.rowcount
    logger.warning("memory cleared: group=%s deleted=%d", group_id, count)
    audit_logger.log(
        request,
        action="delete",
        target_type="memory",
        target_id=f"{group_id}:*",
        summary_before={"deleted": count},
    )
    return {"deleted": count}


def _validated_parts(parts):
    if parts is None:
        return None
    try:
        return validate(parts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/members/{group_id}")
def search_members(group_id: str, query: str = Query(default="", max_length=256)):
    _validate_group_id(group_id)
    snapshot = web_identities.snapshot(group_id)
    ids = set(snapshot.names) | set(snapshot.index.by_qq)
    result = []
    for qq in sorted(ids):
        if not QQ.fullmatch(qq):
            continue
        entry = snapshot.index.by_qq.get(qq)
        aliases = entry.aliases if entry else []
        name = snapshot.name(qq)
        if not query or any(query.casefold() in value.casefold() for value in [qq, name, snapshot.names.get(qq, ""), *aliases]):
            result.append({"qq": qq, "name": name, "aliases": aliases})
    return result[:100]
