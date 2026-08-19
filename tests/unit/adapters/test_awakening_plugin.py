"""Boredom scheduler / opt-in state tests for the awakening plugin (#75-B)."""

from __future__ import annotations

import json

from quickquip.adapters.nonebot import awakening_plugin
from quickquip.chat.awakening import AwakeningConfig, AwakeningDefaults, get_state


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, *, seconds, id, replace_existing):
        assert trigger == "interval"
        self.jobs[id] = {
            "func": func,
            "seconds": seconds,
            "replace_existing": replace_existing,
        }


def _use_config(monkeypatch, **defaults) -> None:
    cfg = AwakeningConfig(defaults=AwakeningDefaults(**defaults))
    monkeypatch.setattr(awakening_plugin, "get_config", lambda: cfg)


def test_register_uses_scan_interval(monkeypatch):
    sched = FakeScheduler()
    _use_config(monkeypatch, boredom_scan_interval=120, boredom_check_interval=600)

    used = awakening_plugin.register_boredom_scan_job(sched)

    assert used == 120
    assert sched.jobs[awakening_plugin.BOREDOM_SCAN_JOB_ID]["seconds"] == 120


def test_register_falls_back_to_check_interval(monkeypatch):
    sched = FakeScheduler()
    _use_config(monkeypatch, boredom_check_interval=600)

    used = awakening_plugin.register_boredom_scan_job(sched)

    assert used == 600
    assert sched.jobs[awakening_plugin.BOREDOM_SCAN_JOB_ID]["seconds"] == 600


def test_reregister_same_job_id_updates_interval(monkeypatch):
    """reload 路径复用同一 job ID 重注册，新扫描周期立即生效。"""
    sched = FakeScheduler()
    _use_config(monkeypatch, boredom_scan_interval=120)
    awakening_plugin.register_boredom_scan_job(sched)

    _use_config(monkeypatch, boredom_scan_interval=45)
    awakening_plugin.register_boredom_scan_job(sched)

    assert len(sched.jobs) == 1
    assert sched.jobs[awakening_plugin.BOREDOM_SCAN_JOB_ID]["seconds"] == 45
    assert sched.jobs[awakening_plugin.BOREDOM_SCAN_JOB_ID]["replace_existing"] is True


def test_register_without_scheduler_returns_none(monkeypatch):
    _use_config(monkeypatch, boredom_scan_interval=120)
    assert awakening_plugin.register_boredom_scan_job(sched=None) is None


def test_reload_boredom_groups_clears_state_for_removed_groups(monkeypatch, tmp_path):
    groups_path = tmp_path / "boredom_groups.json"
    groups_path.write_text(json.dumps({"enabled": ["123", "456"]}), encoding="utf-8")

    monkeypatch.setattr(awakening_plugin.boredom_enabled_groups, "path", groups_path)
    awakening_plugin.boredom_enabled_groups.load()

    state = get_state()
    for gid in ("123", "456"):
        state.record_message(gid, "u1")
        state.mark_boredom_triggered(gid)
    state.record_message("789", "u1")  # 非 opt-in 群不受影响

    groups_path.write_text(json.dumps({"enabled": ["123"]}), encoding="utf-8")
    awakening_plugin.reload_boredom_groups()

    assert state.get_group_silence_seconds("123") is not None
    assert state.get_group_silence_seconds("456") is None  # 取消 opt-in 清除
    assert state.can_trigger_boredom("456", 60) is True
    assert state.get_group_silence_seconds("789") is not None
