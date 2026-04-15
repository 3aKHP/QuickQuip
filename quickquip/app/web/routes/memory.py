from datetime import datetime, timezone
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from quickquip.llm.store import LLMStore

router = APIRouter()

_DB = "data/llm.db"


def _store() -> LLMStore:
    return LLMStore(_DB)


class MemoryCreate(BaseModel):
    content: str
    scope: str = "group"
    user_id: str | None = None
    tags: list[str] = []
    confidence: float = 1.0


class MemoryUpdate(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    confidence: float | None = None


@router.get("/memory/{group_id}")
def list_memories(group_id: str, keyword: str | None = None, limit: int = 200):
    store = _store()
    return store.list_memories(group_id, keyword=keyword, limit=limit)


@router.post("/memory/{group_id}", status_code=201)
def create_memory(group_id: str, body: MemoryCreate):
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
    return {"id": mem_id}


@router.put("/memory/{group_id}/{mem_id}")
def update_memory(group_id: str, mem_id: int, body: MemoryUpdate):
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
    return {"ok": True}


@router.delete("/memory/{group_id}/{mem_id}")
def delete_memory(group_id: str, mem_id: int):
    store = _store()
    with store._connect() as conn:
        cur = conn.execute(
            "DELETE FROM memories WHERE id = ? AND group_id = ?",
            (mem_id, group_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="memory not found")
    return {"ok": True}


@router.delete("/memory/{group_id}")
def clear_memories(group_id: str):
    store = _store()
    with store._connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE group_id = ?", (group_id,))
        return {"deleted": cur.rowcount}
