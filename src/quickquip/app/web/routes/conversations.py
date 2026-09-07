import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from quickquip.common.paths import LLM_DB_PATH

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = LLM_DB_PATH

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
        loop_counts = {
            stat["scope_key"]: int(stat["loop_count"])
            for stat in conn.execute(
                "SELECT scope_key, COUNT(*) AS loop_count FROM agent_loops GROUP BY scope_key"
            )
        }
    return {
        "conversations": [
            {
                "group_id": row["group_id"],
                "type": _classify(row["group_id"]),
                "count": int(row["count"]),
                "latest": row["latest"],
                "earliest": row["earliest"],
                "loop_count": loop_counts.get(row["group_id"], 0),
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


@router.get("/conversations/{group_key}/loops/{loop_id}")
def loop_detail(group_key: str, loop_id: str):
    """Loop 有界详情（§10）：按 Turn 展开正文、工具状态与 Chunk receipt。

    thinking/native 默认只显示是否存在及省略原因，不暴露签名正文。
    """
    _validate_group_key(group_key)
    with _connect() as conn:
        loop = conn.execute(
            "SELECT * FROM agent_loops WHERE scope_key = ? AND loop_id = ?",
            (group_key, loop_id),
        ).fetchone()
        if loop is None:
            raise HTTPException(status_code=404, detail="loop not found")
        turns = conn.execute(
            """
            SELECT t.turn_id, t.turn_index, t.text_policy, t.output_status,
                   t.finish_reason, t.committed_at, t.native_omission_reason,
                   (t.native_state_json IS NOT NULL) AS has_native,
                   m.content AS text
            FROM agent_turns t
            LEFT JOIN conversation_messages m ON m.id = t.message_row_id
            WHERE t.loop_id = ?
            ORDER BY t.turn_index ASC
            """,
            (loop_id,),
        ).fetchall()
        tools = conn.execute(
            """
            SELECT e.execution_id, e.turn_id, e.tool_name, e.status,
                   e.result_omission_reason, e.arguments_omission_reason
            FROM agent_tool_executions e
            JOIN agent_turns t ON t.turn_id = e.turn_id
            WHERE t.loop_id = ?
            ORDER BY e.turn_id, e.call_index
            """,
            (loop_id,),
        ).fetchall()
        deliveries = conn.execute(
            """
            SELECT d.delivery_id, d.turn_id, d.kind, d.chunk_index, d.status,
                   d.recall_status, d.source_start, d.source_end, d.notice_text
            FROM agent_deliveries d
            WHERE d.loop_id = ?
            ORDER BY d.delivery_index ASC
            """,
            (loop_id,),
        ).fetchall()
    turn_index: dict[str, dict] = {row["turn_id"]: dict(row) for row in turns}
    for tool in tools:
        turn_index.setdefault(tool["turn_id"], {}).setdefault("tools", []).append(dict(tool))
    for delivery in deliveries:
        turn_index.setdefault(delivery["turn_id"], {}).setdefault("deliveries", []).append(dict(delivery))
    ordered = sorted(turn_index.values(), key=lambda t: t.get("turn_index") or 0)
    return {
        "loop": {
            "loop_id": loop["loop_id"],
            "scope_key": loop["scope_key"],
            "trigger_kind": loop["trigger_kind"],
            "status": loop["status"],
            "terminal_reason": loop["terminal_reason"],
            "started_at": loop["started_at"],
            "closed_at": loop["closed_at"],
            "legacy": bool(loop["legacy"]),
            "replay_revision": int(loop["replay_revision"]),
        },
        "turns": ordered,
        "turn_count": len(turns),
        "delivery_count": len(deliveries),
    }


@router.delete("/conversations/{group_key}/messages/{msg_id}")
def delete_message(group_key: str, msg_id: int):
    """行删除走 action queue（§9.3/§10）：Bot 进程执行领域操作。

    assistant 主行 = 删除该 Turn 全部正文范围与交付内容；user 触发行 =
    整 Loop 删除。Web 侧不再直接执行原始单表 DELETE——侧表与主表必须
    在同一领域事务内收敛。
    """
    _validate_group_key(group_key)
    if group_key.startswith("archive:"):
        raise HTTPException(status_code=409, detail="archive scope deletions use the archive API")
    from quickquip.app.web.action_queue import action_queue

    queued = action_queue.enqueue(
        "delete_conversation_row", {"scope_key": group_key, "row_id": msg_id}
    )
    logger.warning(
        "conversation row deletion queued: group=%s id=%d action=%s",
        group_key, msg_id, queued.get("id"),
    )
    return {"ok": True, "action_id": queued.get("id"), "status": "queued"}
