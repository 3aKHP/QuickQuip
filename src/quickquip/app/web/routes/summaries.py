import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from quickquip.app.web.audit import audit_logger
from quickquip.common.paths import DAILY_SUMMARIES_DB_PATH

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = DAILY_SUMMARIES_DB_PATH

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
def delete_summary(group_id: str, summary_date: str, request: Request):
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
        audit_logger.log(
            request,
            action="delete",
            target_type="daily_summary",
            target_id=f"{group_id}:{summary_date}",
        )
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


@router.get("/summaries-health")
def summaries_health(days: int = 7):
    """总结族（日报/简报/周月报）生成健康度：成功/失败/跳过、finish_reason
    分布、级联跳数与成本（1.15.2 CE 线）。经 usage_store 读取以确保惰性
    schema 迁移先于查询执行（升级窗口内旧库无 finish_reason 列）。"""
    days = max(1, min(days, 90))
    since = (
        datetime.now(tz=timezone.utc) - timedelta(days=days)
    ).isoformat()
    from quickquip.llm.usage_store import usage_store

    try:
        usage_store._ensure_schema()
        with usage_store.connect() as conn:
            features = conn.execute(
                """
                SELECT feature, state,
                       COUNT(*) AS calls,
                       SUM(COALESCE(cost_usd, 0)) AS cost_usd,
                       AVG(COALESCE(duration_ms, 0)) AS avg_duration_ms
                FROM llm_usage_events
                WHERE feature IN ('summary', 'briefing', 'period_report')
                  AND ts >= ?
                GROUP BY feature, state ORDER BY feature, state
                """,
                (since,),
            ).fetchall()
            finish_reasons = conn.execute(
                """
                SELECT feature, provider_id, model,
                       COALESCE(finish_reason, '') AS finish_reason,
                       COUNT(*) AS calls
                FROM llm_usage_events
                WHERE feature IN ('summary', 'briefing', 'period_report')
                  AND state = 'ok' AND ts >= ?
                GROUP BY feature, provider_id, model, finish_reason
                ORDER BY calls DESC LIMIT 50
                """,
                (since,),
            ).fetchall()
            groups = conn.execute(
                """
                SELECT feature, group_id, COUNT(*) AS calls,
                       SUM(CASE WHEN state != 'ok' THEN 1 ELSE 0 END) AS failed
                FROM llm_usage_events
                WHERE feature IN ('summary', 'briefing', 'period_report')
                  AND ts >= ? AND group_id IS NOT NULL
                GROUP BY feature, group_id ORDER BY calls DESC LIMIT 50
                """,
                (since,),
            ).fetchall()
        return {
            "days": days,
            "features": [dict(r) for r in features],
            "finish_reasons": [dict(r) for r in finish_reasons],
            "groups": [dict(r) for r in groups],
        }
    except sqlite3.Error:
        logger.warning("summaries-health: 用量库暂不可用")
        return {"days": days, "features": [], "finish_reasons": [], "groups": []}
