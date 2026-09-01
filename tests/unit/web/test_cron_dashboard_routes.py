from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import cron_dashboard  # noqa: E402


def _write_status_file(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_dashboard_reads_shared_status_file(tmp_path, monkeypatch):
    """生产形态：web 进程读 bot 进程落盘的 cron_jobs.json，无需同进程调度器。"""
    status_file = tmp_path / "cron_jobs.json"
    _write_status_file(status_file, {
        "updated_at": "2026-09-02T06:30:00+08:00",
        "jobs": [
            {
                "id": "scheduled_msg_sm_abc",
                "name": "scheduled_msg_sm_abc",
                "trigger": "cron[minute='30', hour='7']",
                "next_run": "2026-09-03T07:30:00+08:00",
                "last_run": "2026-09-02T07:30:01+08:00",
                "last_status": "ok",
                "last_error": None,
            }
        ],
    })
    monkeypatch.setattr(cron_dashboard, "CRON_JOBS_JSON_PATH", status_file)

    result = cron_dashboard.get_cron_dashboard()

    assert result["updated_at"] == "2026-09-02T06:30:00+08:00"
    job = result["jobs"][0]
    assert job["id"] == "scheduled_msg_sm_abc"
    assert job["last_status"] == "ok"
    assert job["next_run"] == "2026-09-03T07:30:00+08:00"


def test_dashboard_status_file_empty_jobs_is_authoritative(tmp_path, monkeypatch):
    """状态文件存在且 jobs 为空时如实返回空（bot 进程已确认无任务），不回退。"""
    status_file = tmp_path / "cron_jobs.json"
    _write_status_file(status_file, {"updated_at": "2026-09-02T06:30:00+08:00", "jobs": []})
    monkeypatch.setattr(cron_dashboard, "CRON_JOBS_JSON_PATH", status_file)

    result = cron_dashboard.get_cron_dashboard()

    assert result["jobs"] == []


def test_dashboard_missing_status_file_falls_back(tmp_path, monkeypatch):
    """状态文件缺失（本地开发、bot 未启动）时回退同进程调度器，最终返回空列表。"""
    monkeypatch.setattr(cron_dashboard, "CRON_JOBS_JSON_PATH", tmp_path / "cron_jobs.json")

    result = cron_dashboard.get_cron_dashboard()

    assert result == {"jobs": [], "updated_at": None}


def test_dashboard_malformed_status_file_falls_back(tmp_path, monkeypatch):
    """状态文件写到一半/损坏时回退而不是 500。"""
    status_file = tmp_path / "cron_jobs.json"
    status_file.write_text('{"jobs": [', encoding="utf-8")
    monkeypatch.setattr(cron_dashboard, "CRON_JOBS_JSON_PATH", status_file)

    result = cron_dashboard.get_cron_dashboard()

    assert result == {"jobs": [], "updated_at": None}


def test_dashboard_non_dict_status_file_falls_back(tmp_path, monkeypatch):
    """状态文件是合法 JSON 但顶层非对象（如数组）时回退而不是 500。"""
    status_file = tmp_path / "cron_jobs.json"
    status_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cron_dashboard, "CRON_JOBS_JSON_PATH", status_file)

    result = cron_dashboard.get_cron_dashboard()

    assert result == {"jobs": [], "updated_at": None}
