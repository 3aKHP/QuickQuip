"""cron_status_sync 跨进程状态落盘测试。"""

from __future__ import annotations

import json
import types
from datetime import datetime, timedelta, timezone

from quickquip.adapters.nonebot import cron_status_sync, scheduler_plugin


class _FakeApsJob:
    def __init__(self, job_id, trigger, next_run_time):
        self.id = job_id
        self.name = None
        self.trigger = trigger
        self.next_run_time = next_run_time


def test_sync_writes_shared_file(monkeypatch, tmp_path):
    """bot 进程把调度器快照与执行结果原子落盘，并排除同步 job 自身。"""
    tz = timezone(timedelta(hours=8))
    next_run = datetime(2026, 9, 3, 7, 30, tzinfo=tz)
    sched = types.SimpleNamespace(
        get_jobs=lambda: [
            _FakeApsJob("scheduled_msg_sm_abc", "cron[minute='30', hour='7']", next_run),
            _FakeApsJob("cron_status_sync", "interval[0:00:30]", next_run),
        ]
    )
    status_file = tmp_path / "cron_jobs.json"
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)
    # 隔离模块级全局结果表，避免残留污染其他用例
    monkeypatch.setattr(scheduler_plugin, "_job_run_results", {})

    scheduler_plugin.record_job_result("scheduled_msg_sm_abc", True)
    cron_status_sync.sync_cron_status_file(sched, scheduler_plugin.get_job_results())

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["updated_at"]
    assert [j["id"] for j in payload["jobs"]] == ["scheduled_msg_sm_abc"]
    job = payload["jobs"][0]
    assert job["name"] == "scheduled_msg_sm_abc"
    assert job["trigger"] == "cron[minute='30', hour='7']"
    assert job["next_run"] == next_run.isoformat()
    assert job["last_status"] == "ok"
    # last_run 带时区偏移，web 端按浏览器时区渲染不受容器 TZ 影响
    assert datetime.fromisoformat(job["last_run"]).tzinfo is not None


def test_sync_no_scheduler_is_noop(monkeypatch, tmp_path):
    """调度器不可用（测试环境优雅降级）时不写文件也不抛错。"""
    status_file = tmp_path / "cron_jobs.json"
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)

    cron_status_sync.sync_cron_status_file(None, {})

    assert not status_file.exists()
