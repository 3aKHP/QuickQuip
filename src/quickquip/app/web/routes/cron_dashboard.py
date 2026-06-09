from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/cron-dashboard")
def get_cron_dashboard():
    """Return all scheduled cron jobs with trigger, next run, and last execution status."""
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
        return {"jobs": []}

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

    return {"jobs": jobs}
