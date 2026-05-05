import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quickquip.app.message_pipeline import niuniu_store
from quickquip.app.web.audit import audit_logger
from quickquip.games.niuniu import NiuNiuStore

router = APIRouter()
logger = logging.getLogger(__name__)

_UID_RE = re.compile(r"^\d{5,15}$")


class AdjustLengthBody(BaseModel):
    length: float = Field(ge=-1000, le=100000)
    reason: str = Field(default="", max_length=200)


@router.get("/niuniu/rankings")
async def get_rankings(request: Request, type: str = "length", top_n: int = 20):
    """Return global length or depth rankings."""
    if type not in ("length", "depth"):
        raise HTTPException(422, "type must be 'length' or 'depth'")
    top_n = min(top_n, 100)

    store: NiuNiuStore = niuniu_store
    if type == "length":
        entries = store.rank_by_length(limit=top_n)
    else:
        entries = store.rank_by_depth(limit=top_n)
    return {"type": type, "rankings": entries, "total_users": store.count()}


@router.get("/niuniu/users")
async def list_users(request: Request, offset: int = 0, limit: int = 50, keyword: str = ""):
    """Paginated niuniu user list."""
    limit = min(limit, 200)

    store: NiuNiuStore = niuniu_store
    with store._connect() as conn:
        if keyword and _UID_RE.match(keyword):
            rows = conn.execute(
                """
                SELECT uid, length, created_at, updated_at
                FROM niuniu_users
                WHERE uid = ?
                ORDER BY length DESC
                LIMIT ? OFFSET ?
                """,
                (keyword, limit, offset),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM niuniu_users WHERE uid = ?",
                (keyword,),
            ).fetchone()
        else:
            rows = conn.execute(
                """
                SELECT uid, length, created_at, updated_at
                FROM niuniu_users
                ORDER BY length DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM niuniu_users"
            ).fetchone()

    total = total_row["c"] if total_row else 0
    return {
        "users": [dict(r) for r in rows],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/niuniu/users/{uid}")
async def get_user(uid: str, request: Request):
    """Return a single niuniu user's detail + recent records."""
    if not _UID_RE.match(uid):
        raise HTTPException(422, "invalid uid")

    store: NiuNiuStore = niuniu_store
    length = store.get_length(uid)
    if length is None:
        raise HTTPException(404, "user not found")

    rank = store.get_rank_position(uid)
    records = store.get_records(uid, limit=30)

    return {
        "uid": uid,
        "length": length,
        "rank": rank,
        "records": records,
    }


@router.post("/niuniu/users/{uid}/adjust")
async def adjust_length(uid: str, body: AdjustLengthBody, request: Request):
    """Manually set a user's niuniu length."""
    if not _UID_RE.match(uid):
        raise HTTPException(422, "invalid uid")

    store: NiuNiuStore = niuniu_store
    old_length = store.get_length(uid)
    if old_length is None:
        raise HTTPException(404, "user not found")

    store.update_length(uid, body.length)
    store._add_record(uid, "admin_adjust", old_length, body.length)

    audit_logger.log(
        request,
        action="adjust_length",
        target_type="niuniu_user",
        target_id=uid,
        summary_before={"length": old_length},
        summary_after={"length": body.length, "reason": body.reason},
    )
    logger.warning(
        "niuniu length adjusted uid=%s old=%.2f new=%.2f reason=%s",
        uid, old_length, body.length, body.reason,
    )
    return {"ok": True, "old_length": old_length, "new_length": body.length}
