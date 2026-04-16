import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from quickquip.app.web.settings import PROJECT_ROOT

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = PROJECT_ROOT / "data" / "llm.db"

# Accepts normal group ids (5-12 digits), private: and archive: synthetic keys,
# all restricted to URL-safe chars to avoid injection via path segment.
_GROUP_KEY_RE = re.compile(r"^(?:\d{5,12}|private:\d{5,15}|archive:\d{5,15}:\d{1,6})$")


def _validate_group_key(key: str) -> None:
    if not _GROUP_KEY_RE.match(key):
        raise HTTPException(status_code=422, detail="invalid conversation key")


def _connect() -> sqlite3.Connection:
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="llm.db not found")
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _classify(group_id: str) -> str:
    if group_id.startswith("private:"):
        return "private"
    if group_id.startswith("archive:"):
        return "archive"
    return "group"


@router.get("/conversations")
def list_conversations():
    if not _DB.exists():
        return {"conversations": []}
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT group_id,
                   COUNT(*) AS count,
                   MAX(created_at) AS latest,
                   MIN(created_at) AS earliest
            FROM conversation_messages
            GROUP BY group_id
            ORDER BY latest DESC
            """
        ).fetchall()
    return {
        "conversations": [
            {
                "group_id": row["group_id"],
                "type": _classify(row["group_id"]),
                "count": int(row["count"]),
                "latest": row["latest"],
                "earliest": row["earliest"],
            }
            for row in rows
        ]
    }


@router.get("/conversations/{group_key}/messages")
def list_messages(
    group_key: str,
    before_id: int | None = Query(default=None, ge=1),
    keyword: str | None = Query(default=None, max_length=256),
    limit: int = Query(default=50, ge=1, le=200),
):
    _validate_group_key(group_key)
    params: list[object] = [group_key]
    sql = """
        SELECT id, user_id, sender_name, canonical_name, role, content, message_id, created_at
        FROM conversation_messages
        WHERE group_id = ?
    """
    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)
    if keyword:
        sql += " AND content LIKE ?"
        params.append(f"%{keyword}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    messages = [
        {
            "id": int(row["id"]),
            "user_id": row["user_id"],
            "sender_name": row["sender_name"],
            "canonical_name": row["canonical_name"],
            "role": row["role"],
            "content": row["content"],
            "message_id": row["message_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return {
        "messages": messages,
        "has_more": len(messages) == limit,
    }


class DeleteResult(BaseModel):
    deleted: int


@router.delete("/conversations/{group_key}/messages/{msg_id}")
def delete_message(group_key: str, msg_id: int):
    _validate_group_key(group_key)
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM conversation_messages WHERE group_id = ? AND id = ?",
            (group_key, msg_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="message not found")
    logger.warning("conversation message deleted: group=%s id=%d", group_key, msg_id)
    return {"ok": True}
