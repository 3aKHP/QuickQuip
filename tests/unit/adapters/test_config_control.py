"""Owned report jobs and rollback preserve scheduling without sending missed reports."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import sys
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from quickquip.adapters.nonebot.config_control import replace_report_schedules
from quickquip.llm.config import LLMConfig


async def test_disabling_report_removes_owned_jobs_and_rollback_preserves_next_run(monkeypatch):
    from quickquip.adapters.nonebot import daily_briefing_plugin as briefing
    from quickquip.adapters.nonebot import daily_summary_plugin as summary
    scheduler = AsyncIOScheduler()
    monkeypatch.setitem(
        sys.modules, "nonebot_plugin_apscheduler", SimpleNamespace(scheduler=scheduler)
    )
    monkeypatch.setattr(summary, "scheduler", scheduler)
    monkeypatch.setattr(briefing, "scheduler", scheduler)
    monkeypatch.setattr(summary, "_ensure_llm_bindings", lambda: None)
    old = LLMConfig()
    old.daily_summary.enabled = True
    new = replace(old, daily_summary=replace(old.daily_summary, enabled=False))
    monkeypatch.setattr(summary, "get_llm_service", lambda: SimpleNamespace(config=new))
    calls = []
    def send():
        calls.append("sent")
    scheduler.add_job(send, "cron", hour=23, id="daily_summary_generate")
    scheduler.add_job(send, "cron", hour=23, id="daily_summary_publish")
    scheduler.add_job(send, "cron", hour=23, id="other_domain")
    scheduler.start(paused=True)
    saved = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    try:
        rollback = replace_report_schedules(old, new)
        assert [job.id for job in scheduler.get_jobs()] == ["other_domain"]
        assert calls == []
        rollback()
        assert {job.id: job.next_run_time for job in scheduler.get_jobs()} == saved
        assert calls == []
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)


async def test_unrelated_change_does_not_reconnect_or_reschedule(monkeypatch):
    old = LLMConfig()
    new = replace(old, runtime=replace(old.runtime, max_prompt_chars=2200))
    class Scheduler:
        def get_jobs(self):
            raise AssertionError("Report scheduler must remain untouched")
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler",
                        SimpleNamespace(scheduler=Scheduler()))
    replace_report_schedules(old, new)()
