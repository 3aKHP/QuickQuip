"""Cron 调度状态的跨进程共享。

调度器活在 bot 进程内存里，web-admin 是独立进程，无法直接读取。
仿 mcp_status.json：bot 进程定时把任务快照与最近执行结果原子落盘，
web 端 cron-dashboard 路由只读该文件。
"""

import json
import logging
from datetime import datetime

from quickquip.common.paths import CRON_JOBS_JSON_PATH

logger = logging.getLogger(__name__)

CRON_STATUS_SYNC_JOB_ID = "cron_status_sync"


def sync_cron_status_file(scheduler, job_results: dict) -> None:
    """把调度器任务快照写入共享状态文件（供 web-admin 跨进程读取）。Best-effort。"""
    if not scheduler:
        return
    try:
        jobs = []
        for job in scheduler.get_jobs():
            job_id = getattr(job, "id", None)
            if not job_id or job_id == CRON_STATUS_SYNC_JOB_ID:
                continue
            next_run = getattr(job, "next_run_time", None)
            result = job_results.get(job_id, {})
            jobs.append({
                "id": job_id,
                "name": getattr(job, "name", None) or job_id,
                "trigger": str(getattr(job, "trigger", "")),
                "next_run": next_run.isoformat() if next_run else None,
                "last_run": result.get("last_run"),
                "last_status": result.get("last_status"),
                "last_error": result.get("last_error"),
            })
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "jobs": jobs,
        }
        path = CRON_JOBS_JSON_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
    except Exception:
        logger.warning("cron_status: failed to write status file", exc_info=True)


def register_cron_status_sync(scheduler, job_results: dict) -> None:
    """注册定时落盘 job（每 30 秒），驱动 web-admin 定时任务页的数据源。"""
    scheduler.add_job(
        lambda: sync_cron_status_file(scheduler, job_results),
        "interval",
        seconds=30,
        id=CRON_STATUS_SYNC_JOB_ID,
        replace_existing=True,
    )
    logger.info("cron_status: sync job registered (every 30s)")
