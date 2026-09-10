import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from quickquip.app.web.audit import audit_logger
from quickquip.app.web.generation_log import generation_log_response
from quickquip.common.paths import DAILY_SUMMARIES_DB_PATH

router = APIRouter()
logger = logging.getLogger(__name__)

_DB = DAILY_SUMMARIES_DB_PATH

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@lru_cache(maxsize=None)
def _ensure_store_schema(db_path: str) -> None:
    """实例化一次 store 以触发惰性迁移（run_id 列）。web 进程平时不实例化
    报文 store，generation-log 直接 SELECT run_id，须先确保列存在。"""
    from quickquip.chat.daily_summary import DailySummaryStore

    DailySummaryStore(db_path)


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
    """总结族（日报/简报/周月报）各跳模型尝试的接受结果与成本。

    经 usage_store 读取以确保惰性 schema 迁移先于查询执行；历史调用的
    正文接受结果保留为 unknown。明细级诊断（每跳的 finish/token/耗时）
    在报文详情的「生成日志」里按 run_id/时间窗归因。
    """
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
                SELECT feature,
                       COALESCE(response_outcome, 'unknown') AS outcome,
                       COUNT(*) AS calls,
                       SUM(COALESCE(cost_usd, 0)) AS cost_usd,
                       AVG(COALESCE(duration_ms, 0)) AS avg_duration_ms
                FROM llm_usage_events
                WHERE feature IN ('summary', 'briefing', 'period_report')
                  AND ts >= ?
                GROUP BY feature, outcome ORDER BY feature, outcome
                """,
                (since,),
            ).fetchall()
        return {
            "days": days,
            "features": [dict(r) for r in features],
        }
    except sqlite3.Error:
        logger.warning("summaries-health: 用量库暂不可用")
        return {"days": days, "features": []}


@router.get("/summaries/{group_id}/{summary_date}/generation-log")
def summary_generation_log(group_id: str, summary_date: str):
    """一份日报的生成日志：为得到它经历的级联各跳（耗时/token/finish 等）。"""
    _validate_group_id(group_id)
    _validate_date(summary_date)
    if not _DB.exists():
        raise HTTPException(status_code=404, detail="db not found")
    _ensure_store_schema(str(_DB))
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT group_id, summary_date, generated_at, run_id FROM summaries WHERE group_id = ? AND summary_date = ?",
            (group_id, summary_date),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="summary not found")
        prev = conn.execute(
            """SELECT generated_at FROM summaries
               WHERE group_id = ? AND summary_date < ?
               ORDER BY summary_date DESC LIMIT 1""",
            (group_id, summary_date),
        ).fetchone()
    finally:
        conn.close()
    return generation_log_response(
        dict(row), prev["generated_at"] if prev else None, feature="summary",
    )
