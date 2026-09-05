from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter

from quickquip.common.paths import CRON_JOBS_JSON_PATH

logger = logging.getLogger(__name__)

router = APIRouter()


def _read_status_file() -> dict | None:
    try:
        data = json.loads(CRON_JOBS_JSON_PATH.read_text(encoding="utf-8"))
    # UnicodeDecodeError（非 UTF-8 字节，如编辑器另存为 ANSI）同样按损坏回退，
    # 不让路由 500——与 cron_status_sync.load_job_results 的读取防御同口径
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


@router.get("/cron-dashboard")
def get_cron_dashboard():
    """Return all scheduled cron jobs with trigger, next run, and last execution status."""
    # 1) bot 进程写入的共享状态文件（生产部署：调度器在 bot 进程，跨进程只能读文件）
    data = _read_status_file()
    if data is not None and isinstance(data.get("jobs"), list):
        return {"jobs": data["jobs"], "updated_at": data.get("updated_at")}

    # 2) 同进程调度器回退（本地开发 / 状态文件尚未生成）
    jobs: list[dict[str, Any]] = []

    try:
        from nonebot_plugin_apscheduler import scheduler as apscheduler
    except (ModuleNotFoundError, ValueError):
        apscheduler = None

    try:
        from quickquip.adapters.nonebot.scheduler_plugin import get_job_results
    except (ModuleNotFoundError, ValueError):
        def get_job_results() -> dict:
            return {}

    if apscheduler is None:
        return {"jobs": jobs, "updated_at": None}

    job_results = get_job_results()

    try:
        aps_jobs = apscheduler.get_jobs()
    except Exception:
        logger.warning("cron_dashboard: failed to get jobs from scheduler", exc_info=True)
        aps_jobs = []

    for job in aps_jobs:
        job_data: dict[str, Any] = {
            "id": job.id,
            "name": job.name or job.id,
            "trigger": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }

        result = job_results.get(job.id, {})
        if result:
            job_data["last_run"] = result.get("last_run")
            job_data["last_status"] = result.get("last_status")
            job_data["last_error"] = result.get("last_error")
        else:
            job_data["last_run"] = None
            job_data["last_status"] = None
            job_data["last_error"] = None

        jobs.append(job_data)

    return {"jobs": jobs, "updated_at": None}
