from datetime import datetime, timezone
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Annotated, Literal

from quickquip.llm.store import LLMStore
from quickquip.app.web.settings import PROJECT_ROOT

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = PROJECT_ROOT / "data" / "llm.db"

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")


def _store() -> LLMStore:
    return LLMStore(_DB)


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


class MemoryCreate(BaseModel):
    content: str = Field(max_length=4096)
    scope: Literal["group", "user"] = "group"
    user_id: str | None = None
    tags: list[Annotated[str, Field(max_length=64)]] = Field(default=[], max_length=32)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=4096)
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
def create_memory(group_id: str, body: MemoryCreate):
    _validate_group_id(group_id)
    store = _store()
    mem_id = store.add_memory(
        group_id,
        body.content,
        scope=body.scope,
        user_id=body.user_id,
        tags=body.tags,
        source="manual",
        confidence=body.confidence,
    )
    logger.info("memory created: group=%s id=%d scope=%s", group_id, mem_id, body.scope)
    return {"id": mem_id}


@router.put("/memory/{group_id}/{mem_id}")
def update_memory(group_id: str, mem_id: int, body: MemoryUpdate):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="memory not found")
        new_content = body.content if body.content is not None else row["content"]
        new_tags = json.dumps(body.tags, ensure_ascii=False) if body.tags is not None else row["tags_json"]
        new_conf = body.confidence if body.confidence is not None else row["confidence"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE memories SET content=?, tags_json=?, confidence=?, updated_at=? WHERE id=?",
            (new_content, new_tags, new_conf, now, mem_id),
        )
    logger.info("memory updated: group=%s id=%d", group_id, mem_id)
    return {"ok": True}


@router.delete("/memory/{group_id}/{mem_id}")
def delete_memory(group_id: str, mem_id: int):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        cur = conn.execute(
            "DELETE FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="memory not found")
    logger.warning("memory deleted: group=%s id=%d", group_id, mem_id)
    return {"ok": True}


@router.delete("/memory/{group_id}")
def clear_memories(group_id: str):
    _validate_group_id(group_id)
    store = _store()
    with store._connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE group_id = ?", (group_id,))
        count = cur.rowcount
    logger.warning("memory cleared: group=%s deleted=%d", group_id, count)
    return {"deleted": count}
