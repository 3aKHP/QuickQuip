import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quickquip.app.message_pipeline import game_economy
from quickquip.app.web.audit import audit_logger
from quickquip.games.economy import GameEconomyStore

router = APIRouter()
logger = logging.getLogger(__name__)

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")
_UID_RE = re.compile(r"^\d{5,15}$")


class AdjustBody(BaseModel):
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(default="", max_length=200)


@router.get("/game-economy/groups")
async def list_groups(request: Request):
    """Return all group IDs that have gold accounts."""
    store: GameEconomyStore = game_economy
    with store._connect() as conn:
        rows = conn.execute(
            """
            SELECT group_id, COUNT(*) AS user_count, SUM(gold) AS total_gold
            FROM gold_accounts
            GROUP BY group_id
            ORDER BY total_gold DESC
            """
        ).fetchall()
    return {
        "groups": [
            {
                "group_id": r["group_id"],
                "user_count": r["user_count"],
                "total_gold": r["total_gold"],
            }
            for r in rows
        ]
    }


@router.get("/game-economy/rankings/{group_id}")
async def get_rankings(group_id: str, request: Request, top_n: int = 20):
    """Return top N gold holders in a group."""
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(422, "invalid group_id")
    store: GameEconomyStore = game_economy
    rank = store.get_rank(group_id, top_n=min(top_n, 100))
    return {"group_id": group_id, "rankings": rank}


@router.get("/game-economy/accounts/{group_id}")
async def list_accounts(
    group_id: str,
    request: Request,
    offset: int = 0,
    limit: int = 50,
    keyword: str = "",
):
    """Paginated account list for a group, with optional user_id keyword filter."""
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(422, "invalid group_id")
    limit = min(limit, 200)

    store: GameEconomyStore = game_economy
    with store._connect() as conn:
        if keyword and _UID_RE.match(keyword):
            rows = conn.execute(
                """
                SELECT user_id, gold, affection, sign_streak, last_sign_date, created_at
                FROM gold_accounts
                WHERE group_id = ? AND user_id = ?
                ORDER BY gold DESC
                LIMIT ? OFFSET ?
                """,
                (group_id, keyword, limit, offset),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM gold_accounts WHERE group_id = ? AND user_id = ?",
                (group_id, keyword),
            ).fetchone()
        else:
            rows = conn.execute(
                """
                SELECT user_id, gold, affection, sign_streak, last_sign_date, created_at
                FROM gold_accounts
                WHERE group_id = ?
                ORDER BY gold DESC
                LIMIT ? OFFSET ?
                """,
                (group_id, limit, offset),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM gold_accounts WHERE group_id = ?",
                (group_id,),
            ).fetchone()

    total = total_row["c"] if total_row else 0
    return {
        "group_id": group_id,
        "accounts": [dict(r) for r in rows],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/game-economy/accounts/{group_id}/{user_id}")
async def get_account(group_id: str, user_id: str, request: Request):
    """Return a single account's full detail."""
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(422, "invalid group_id")
    if not _UID_RE.match(user_id):
        raise HTTPException(422, "invalid user_id")

    store: GameEconomyStore = game_economy
    with store._connect() as conn:
        row = conn.execute(
            "SELECT user_id, gold, affection, sign_streak, last_sign_date FROM gold_accounts WHERE user_id = ? AND group_id = ?",
            (user_id, group_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "account not found")
    return {"user_id": user_id, "group_id": group_id, **dict(row)}


@router.post("/game-economy/accounts/{group_id}/{user_id}/adjust")
async def adjust_gold(group_id: str, user_id: str, body: AdjustBody, request: Request):
    """Manually adjust a user's gold balance (positive = add, negative = deduct)."""
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(422, "invalid group_id")
    if not _UID_RE.match(user_id):
        raise HTTPException(422, "invalid user_id")

    store: GameEconomyStore = game_economy
    if body.amount >= 0:
        new_balance = store.add_gold(user_id, group_id, body.amount)
    else:
        ok = store.deduct_gold(user_id, group_id, abs(body.amount))
        if not ok:
            raise HTTPException(400, "insufficient gold")
        new_balance = store.get_balance(user_id, group_id)["gold"]

    audit_logger.log(
        request,
        action="adjust_gold",
        target_type="gold_account",
        target_id=f"{group_id}/{user_id}",
        summary_after={"amount": body.amount, "reason": body.reason, "new_balance": new_balance},
    )
    logger.warning(
        "gold adjusted group=%s user=%s amount=%s reason=%s",
        group_id, user_id, body.amount, body.reason,
    )
    return {"ok": True, "new_balance": new_balance}
