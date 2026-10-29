import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from typing import Annotated, Literal

from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import LLM_DB_PATH
from quickquip.llm.store import LLMStore
from quickquip.llm.config_service import get_config_service
from quickquip.llm.memory_content import DEFAULT_CAPACITY
from quickquip.app.identities import web_identities
from quickquip.common.record_content import QQ, render, validate

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = LLM_DB_PATH

_GROUP_ID_RE = re.compile(r"^(?:private:)?\d{5,12}$")


def _store() -> LLMStore:
    return LLMStore(_DB, identity_repository=web_identities)


def _capacity() -> int:
    published = get_config_service().read('published')['document']
    return int(published['settings']['runtime'].get(
        'memory_max_items_per_group', DEFAULT_CAPACITY))


@router.get('/memory/{group_id}/status')
def memory_status(group_id: str):
    _validate_group_id(group_id)
    return {'count': _store().count_memories(group_id), 'capacity': _capacity()}


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


class MemoryCreate(BaseModel):
    content: str = Field(default="", max_length=4096)
    content_parts: dict | None = None
    scope: Literal["group"] = "group"
    user_id: None = None
    title: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=160)
    tags: list[Annotated[str, Field(max_length=64)]] = Field(default=[], max_length=32)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_body(self):
        if self.content_parts is None and "content" not in self.model_fields_set:
            raise ValueError("content or content_parts is required")
        return self


class MemoryUpdate(BaseModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=160)
    content: str | None = Field(default=None, max_length=4096)
    content_parts: dict | None = None
    tags: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=32)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@router.get("/memory/{group_id}")
def list_memories(
    group_id: str,
    keyword: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    _validate_group_id(group_id)
    store = _store()
    return store.list_memories(group_id, keyword=keyword, limit=limit, offset=offset)


@router.post("/memory/{group_id}", status_code=201)
def create_memory(group_id: str, body: MemoryCreate, request: Request):
    _validate_group_id(group_id)
    store = _store()
    parts = _validated_parts(body.content_parts)
    try:
        mem_id = store.add_memory(
            group_id,
            body.content,
            max_items=_capacity(),
            writer="web",
            title=body.title,
            description=body.description,
            scope=body.scope,
            user_id=body.user_id,
            tags=body.tags,
            source="manual",
            confidence=body.confidence,
            content_parts=parts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("memory created: group=%s id=%d scope=%s", group_id, mem_id, body.scope)
    audit_logger.log(
        request,
        action="create",
        target_type="memory",
        target_id=f"{group_id}:{mem_id}",
        summary_after={
            "scope": body.scope,
            "content": (render(parts) if parts is not None else body.content)[:100],
        },
    )
    return {"id": mem_id}


@router.put("/memory/{group_id}/{mem_id}")
def update_memory(group_id: str, mem_id: int, body: MemoryUpdate, request: Request):
    _validate_group_id(group_id)
    store = _store()
    try:
        result = store.update_memory(
            group_id, mem_id, version=body.version, content=body.content,
            content_parts=_validated_parts(body.content_parts), title=body.title,
            description=body.description, tags=body.tags, confidence=body.confidence,
            provenance={"writer": "web"})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_logger.log(request, action="update", target_type="memory",
                     target_id=f"{group_id}:{mem_id}",
                     summary_after={"content": result['content'][:100]})
    return result


@router.delete("/memory/{group_id}/{mem_id}")
def delete_memory(group_id: str, mem_id: int, request: Request,
                  version: int = Query(ge=1)):
    _validate_group_id(group_id)
    store = _store()
    try:
        store.delete_memory(group_id, mem_id, version=version)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_logger.log(request, action="delete", target_type="memory",
                     target_id=f"{group_id}:{mem_id}")
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
def search_members(
    group_id: str, query: str = Query(default="", max_length=256),
    offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
):
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
        if not query or any(
            query.casefold() in value.casefold()
            for value in [qq, name, snapshot.names.get(qq, ""), *aliases]
        ):
            result.append({"qq": qq, "name": name, "aliases": aliases})
    return result[offset:offset + limit]
