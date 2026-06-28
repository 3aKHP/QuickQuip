import logging
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import PERIOD_REPORTS_DB_PATH

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = PERIOD_REPORTS_DB_PATH

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")
# period_key：周报 YYYY-Www（2026-W24），月报 YYYY-MM（2026-06）
_PERIOD_KEY_RE = re.compile(r"^\d{4}-(?:W\d{2}|\d{2})$")
_VALID_PERIOD_TYPES = {"weekly", "monthly"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


def _validate_period_type(period_type: str) -> None:
    if period_type not in _VALID_PERIOD_TYPES:
        raise HTTPException(status_code=422, detail="period_type must be weekly or monthly")


def _validate_period_key(period_key: str) -> None:
    if not _PERIOD_KEY_RE.match(period_key):
        raise HTTPException(status_code=422, detail="period_key must be YYYY-Www or YYYY-MM")


@router.get("/period-reports/{group_id}/{period_type}")
def list_period_reports(group_id: str, period_type: str):
    _validate_group_id(group_id)
    _validate_period_type(period_type)
    if not _DB.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT group_id, period_type, period_key, generated_at, published_at, model_used, char_count
               FROM period_reports
               WHERE group_id = ? AND period_type = ?
               ORDER BY period_key DESC""",
            (group_id, period_type),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/period-reports/{group_id}/{period_type}/{period_key}")
def get_period_report(group_id: str, period_type: str, period_key: str):
    _validate_group_id(group_id)
    _validate_period_type(period_type)
    _validate_period_key(period_key)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM period_reports WHERE group_id = ? AND period_type = ? AND period_key = ?",
            (group_id, period_type, period_key),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="period report not found")
        return dict(row)
    finally:
        conn.close()


@router.get("/period-reports/{group_id}/{period_type}/{period_key}/text", response_class=PlainTextResponse)
def get_period_report_text(group_id: str, period_type: str, period_key: str):
    _validate_group_id(group_id)
    _validate_period_type(period_type)
    _validate_period_key(period_key)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT content FROM period_reports WHERE group_id = ? AND period_type = ? AND period_key = ?",
            (group_id, period_type, period_key),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="period report not found")
        return row["content"]
    finally:
        conn.close()


@router.delete("/period-reports/{group_id}/{period_type}/{period_key}")
def delete_period_report(group_id: str, period_type: str, period_key: str, request: Request):
    _validate_group_id(group_id)
    _validate_period_type(period_type)
    _validate_period_key(period_key)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM period_reports WHERE group_id = ? AND period_type = ? AND period_key = ?",
            (group_id, period_type, period_key),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="period report not found")
        logger.warning(
            "period report deleted: group=%s type=%s key=%s", group_id, period_type, period_key,
        )
        audit_logger.log(
            request,
            action="delete",
            target_type="period_report",
            target_id=f"{group_id}:{period_type}:{period_key}",
        )
        return {"ok": True}
    finally:
        conn.close()


@router.get("/period-reports-groups/{period_type}")
def list_period_report_groups(period_type: str):
    _validate_period_type(period_type)
    if not _DB.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT group_id FROM period_reports WHERE period_type = ? ORDER BY group_id",
            (period_type,),
        ).fetchall()
        return [r["group_id"] for r in rows]
    finally:
        conn.close()
