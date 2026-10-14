"""Configuration worker lifecycle and rollback-capable report scheduling."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

from quickquip.llm.config_runtime import ConfigRuntimeWorker

logger = logging.getLogger(__name__)
_worker_task: asyncio.Task | None = None


def replace_report_schedules(old, new):
    from nonebot_plugin_apscheduler import scheduler
    from quickquip.adapters.nonebot import daily_briefing_plugin as briefing
    from quickquip.adapters.nonebot import daily_summary_plugin as summary

    groups = {
        "daily_briefing": ([f"daily_briefing_{p}" for p in ("morning", "noon", "evening")],
                           briefing._register_scheduler_jobs),
        "daily_summary": (["daily_summary_generate", "daily_summary_publish"],
                          summary._register_scheduler_jobs),
        "weekly_report": (["weekly_report_generate", "weekly_report_publish"],
                          partial(summary._register_period_jobs, period_types=("weekly",))),
        "monthly_report": (["monthly_report_generate", "monthly_report_publish"],
                           partial(summary._register_period_jobs, period_types=("monthly",))),
    }
    changed = []
    for name in groups:
        previous, target = getattr(old, name), getattr(new, name)
        attributes = ["enabled", *(k for k in previous.__dataclass_fields__ if k.endswith("_cron"))]
        if any(getattr(previous, k) != getattr(target, k) for k in attributes):
            changed.append(name)
    identifiers = {identifier for name in changed for identifier in groups[name][0]}
    if not identifiers:
        return lambda: None
    saved = []
    for job in scheduler.get_jobs():
        if job.id in identifiers:
            values = {key: getattr(job, key) for key in (
                "id", "name", "trigger", "args", "kwargs", "executor", "misfire_grace_time",
                "coalesce", "max_instances",
            ) if hasattr(job, key)}
            if hasattr(job, "next_run_time"):
                values["next_run_time"] = job.next_run_time
            saved.append((job.func, values))

    def remove_owned():
        for job in scheduler.get_jobs():
            if job.id in identifiers:
                scheduler.remove_job(job.id)

    def rollback():
        remove_owned()
        for function, values in saved:
            scheduler.add_job(function, **values, replace_existing=True)

    try:
        remove_owned()
        registered = set()
        for name in changed:
            register = groups[name][1]
            if register not in registered:
                register()
                registered.add(register)
    except Exception:
        rollback()
        raise
    return rollback


def start_configuration_control(runtime):
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    if runtime.config_service is None:
        return
    worker = ConfigRuntimeWorker(
        runtime.config_service, runtime, schedules=replace_report_schedules
    )

    async def poll():
        while True:
            try:
                await worker.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Error contents may originate from expanded configuration; log type-free context.
                logger.error("Configuration control iteration failed")
            if runtime._configuration_fenced:
                return
            await asyncio.sleep(5)
    _worker_task = asyncio.create_task(poll(), name="quickquip-configuration-control")


async def stop_configuration_control():
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        await asyncio.gather(_worker_task, return_exceptions=True)
        _worker_task = None
