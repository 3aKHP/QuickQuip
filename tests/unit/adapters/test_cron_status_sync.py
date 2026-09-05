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


def test_load_job_results_roundtrip(monkeypatch, tmp_path):
    """#200 回环：sync 落盘 → load 读回，字段一致、tz 保留。"""
    tz = timezone(timedelta(hours=8))
    next_run = datetime(2026, 9, 5, 7, 30, tzinfo=tz)
    sched = types.SimpleNamespace(
        get_jobs=lambda: [_FakeApsJob("festival_check", "cron[hour='1']", next_run)]
    )
    status_file = tmp_path / "cron_jobs.json"
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)
    monkeypatch.setattr(scheduler_plugin, "_job_run_results", {})

    scheduler_plugin.record_job_result("festival_check", False, "生成失败：boom")
    cron_status_sync.sync_cron_status_file(sched, scheduler_plugin._job_run_results)

    restored = cron_status_sync.load_job_results()
    assert set(restored) == {"festival_check"}
    entry = restored["festival_check"]
    assert entry["last_status"] == "error"
    assert "boom" in entry["last_error"]
    assert datetime.fromisoformat(entry["last_run"]).tzinfo is not None


def test_load_job_results_missing_file_is_silent(monkeypatch, tmp_path, caplog):
    """文件缺失 = 首次启动：空恢复且无告警。"""
    import logging

    monkeypatch.setattr(
        cron_status_sync, "CRON_JOBS_JSON_PATH", tmp_path / "absent.json"
    )
    with caplog.at_level(logging.WARNING, logger="quickquip.adapters.nonebot.cron_status_sync"):
        assert cron_status_sync.load_job_results() == {}
    assert not caplog.records


def test_load_job_results_corrupt_file_warns(monkeypatch, tmp_path, caplog):
    """损坏 JSON = 告警 + 空恢复（不抛、不阻塞调度）。"""
    import logging

    status_file = tmp_path / "cron_jobs.json"
    status_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)
    with caplog.at_level(logging.WARNING, logger="quickquip.adapters.nonebot.cron_status_sync"):
        assert cron_status_sync.load_job_results() == {}
    assert any("failed to read" in r.message for r in caplog.records)


def test_load_job_results_skips_never_run_and_bad_time(monkeypatch, tmp_path):
    """未执行行（last_run=null）不灌——重启后仍是未执行；naive/垃圾时间、
    非 dict 行、非 str id 一律跳过。"""
    status_file = tmp_path / "cron_jobs.json"
    status_file.write_text(
        json.dumps({
            "updated_at": "2026-09-05T08:00:00+08:00",
            "jobs": [
                {"id": "ran_ok", "last_run": "2026-09-05T07:59:00+08:00",
                 "last_status": "ok", "last_error": None},
                {"id": "never_ran", "last_run": None, "last_status": None, "last_error": None},
                {"id": "naive_time", "last_run": "2026-09-05T07:59:00", "last_status": "ok"},
                {"id": "garbage_time", "last_run": "not-a-time", "last_status": "ok"},
                {"id": 12345, "last_run": "2026-09-05T07:59:00+08:00"},
                "not-a-dict",
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)

    restored = cron_status_sync.load_job_results()
    assert set(restored) == {"ran_ok"}


def test_restore_writes_into_live_results_dict(monkeypatch, tmp_path):
    """恢复集成：真实 record_job_result 写的 dict 与恢复灌入的是同一个对象——
    模拟重启后 sync 闭包捕获的表被原地填充（rebind 会静默失效）。"""
    status_file = tmp_path / "cron_jobs.json"
    status_file.write_text(
        json.dumps({
            "updated_at": "2026-09-05T08:00:00+08:00",
            "jobs": [
                {"id": "festival_check", "last_run": "2026-09-05T01:00:05+08:00",
                 "last_status": "ok", "last_error": None},
                {"id": "scheduled_msg_sm_x", "last_run": "2026-09-05T07:00:02+08:00",
                 "last_status": "error", "last_error": "send failed"},
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(cron_status_sync, "CRON_JOBS_JSON_PATH", status_file)
    results = {}  # 即 sync 闭包捕获的对象

    for job_id, entry in cron_status_sync.load_job_results().items():
        results[job_id] = entry

    assert results["festival_check"]["last_status"] == "ok"
    assert results["scheduled_msg_sm_x"]["last_error"] == "send failed"
    # 序列化路径取到恢复后的值（与生产 sync tick 同一查表逻辑）
    sched = types.SimpleNamespace(
        get_jobs=lambda: [_FakeApsJob("festival_check", "cron[hour='1']", None)]
    )
    cron_status_sync.sync_cron_status_file(sched, results)
    on_disk = json.loads(status_file.read_text(encoding="utf-8"))
    assert on_disk["jobs"][0]["last_run"] == "2026-09-05T01:00:05+08:00"
