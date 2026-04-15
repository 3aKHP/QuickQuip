import logging
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = Path("data/daily_summaries.db")

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


def _validate_date(summary_date: str) -> None:
    if not _DATE_RE.match(summary_date):
        raise HTTPException(status_code=422, detail="summary_date must be YYYY-MM-DD")


@router.get("/summaries/{group_id}")
def list_summaries(group_id: str):
    _validate_group_id(group_id)
    if not _DB.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT group_id, summary_date, generated_at, published_at, model_used, char_count
               FROM summaries WHERE group_id = ? ORDER BY summary_date DESC""",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/summaries/{group_id}/{summary_date}")
def get_summary(group_id: str, summary_date: str):
    _validate_group_id(group_id)
    _validate_date(summary_date)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM summaries WHERE group_id = ? AND summary_date = ?",
            (group_id, summary_date),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="summary not found")
        return dict(row)
    finally:
        conn.close()


@router.get("/summaries/{group_id}/{summary_date}/text", response_class=PlainTextResponse)
def get_summary_text(group_id: str, summary_date: str):
    _validate_group_id(group_id)
    _validate_date(summary_date)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT content FROM summaries WHERE group_id = ? AND summary_date = ?",
            (group_id, summary_date),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="summary not found")
        return row["content"]
    finally:
        conn.close()


@router.delete("/summaries/{group_id}/{summary_date}")
def delete_summary(group_id: str, summary_date: str):
    _validate_group_id(group_id)
    _validate_date(summary_date)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM summaries WHERE group_id = ? AND summary_date = ?",
            (group_id, summary_date),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="summary not found")
        logger.warning("summary deleted: group=%s date=%s", group_id, summary_date)
        return {"ok": True}
    finally:
        conn.close()


@router.get("/summaries-groups")
def list_summary_groups():
    if not _DB.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT group_id FROM summaries ORDER BY group_id"
        ).fetchall()
        return [r["group_id"] for r in rows]
    finally:
        conn.close()
