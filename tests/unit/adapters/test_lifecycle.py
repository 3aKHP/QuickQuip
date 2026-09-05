from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from quickquip.adapters.nonebot import lifecycle


def _bump_mtime(path: Path) -> None:
    """Force a distinct mtime after writing. Some filesystems (notably WSL2)
    don't update mtime on rapid successive writes, which would hide the change
    from lifecycle._reload_if_changed (an mtime-based watcher)."""
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 10))


class _FakeDriver:
    def __init__(self):
        self.startup = None
        self.shutdown = None

    def on_startup(self, func):
        self.startup = func
        return func

    def on_shutdown(self, func):
        self.shutdown = func
        return func


@pytest.mark.asyncio
async def test_shutdown_closes_stores_even_if_save_all_fails(monkeypatch):
    driver = _FakeDriver()
    calls: list[str] = []

    async def fake_tieba_shutdown():
        calls.append("tieba")

    async def fake_llm_shutdown():
        calls.append("llm")

    def fake_save_all():
        calls.append("save")
        raise RuntimeError("boom")

    async def fake_close_persistent_stores():
        calls.append("close")

    fake_scheduler_module = types.ModuleType("nonebot_plugin_apscheduler")
    fake_scheduler_module.scheduler = types.SimpleNamespace(add_job=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", fake_scheduler_module)
    monkeypatch.setattr(lifecycle, "tieba_service", types.SimpleNamespace(shutdown=fake_tieba_shutdown))
    monkeypatch.setattr(
        lifecycle,
        "get_llm_service",
        lambda: types.SimpleNamespace(shutdown=fake_llm_shutdown, startup=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(lifecycle, "save_all", fake_save_all)
    monkeypatch.setattr(lifecycle, "close_persistent_stores", fake_close_persistent_stores)

    lifecycle.register_lifecycle(driver)

    with pytest.raises(RuntimeError, match="boom"):
        await driver.shutdown()

    assert calls == ["tieba", "llm", "save", "close"]


def test_reload_if_changed_watches_awakening_config(monkeypatch, tmp_path):
    rule_path = tmp_path / "rule_switch.json"
    awakening_path = tmp_path / "awakening.toml"
    daily_path = tmp_path / "daily.json"
    briefing_path = tmp_path / "briefing.json"
    boredom_path = tmp_path / "boredom.json"
    for path in (rule_path, awakening_path, daily_path, briefing_path, boredom_path):
        path.write_text("{}", encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "RULE_SWITCH_PATH", rule_path)
    monkeypatch.setattr(lifecycle, "CONFIG_AWAKENING_TOML", awakening_path)
    monkeypatch.setattr(lifecycle.rule_switch, "load", lambda path: calls.append(f"rule:{Path(path).name}"))
    monkeypatch.setattr(lifecycle, "reload_awakening_and_reschedule", lambda: calls.append("awakening"))
    monkeypatch.setattr(lifecycle.daily_enabled_groups, "path", daily_path)
    monkeypatch.setattr(lifecycle.daily_enabled_groups, "load", lambda: calls.append("daily"))
    monkeypatch.setattr(lifecycle.daily_briefing_enabled_groups, "path", briefing_path)
    monkeypatch.setattr(lifecycle.daily_briefing_enabled_groups, "load", lambda: calls.append("briefing"))
    monkeypatch.setattr(lifecycle.boredom_enabled_groups, "path", boredom_path)
    monkeypatch.setattr(lifecycle.boredom_enabled_groups, "load", lambda: calls.append("boredom"))

    lifecycle._watched.clear()
    lifecycle._init_mtimes()
    awakening_path.write_text("{\"changed\": true}", encoding="utf-8")
    _bump_mtime(awakening_path)

    lifecycle._reload_if_changed()

    assert calls == ["awakening"]


def test_reload_if_changed_watches_period_report_groups(monkeypatch, tmp_path):
    """回归 B1：weekly/monthly enabled 群文件必须被 web_admin_state_sync 监听，
    否则 Web Admin 双进程部署下开关与立即生成对 bot 进程不可见。"""
    rule_path = tmp_path / "rule_switch.json"
    awakening_path = tmp_path / "awakening.toml"
    daily_path = tmp_path / "daily.json"
    briefing_path = tmp_path / "briefing.json"
    boredom_path = tmp_path / "boredom.json"
    weekly_path = tmp_path / "weekly.json"
    monthly_path = tmp_path / "monthly.json"
    for path in (rule_path, awakening_path, daily_path, briefing_path, boredom_path, weekly_path, monthly_path):
        path.write_text("{}", encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(lifecycle, "RULE_SWITCH_PATH", rule_path)
    monkeypatch.setattr(lifecycle, "CONFIG_AWAKENING_TOML", awakening_path)
    monkeypatch.setattr(lifecycle.rule_switch, "load", lambda path: calls.append("rule"))
    monkeypatch.setattr(lifecycle, "reload_awakening_and_reschedule", lambda: calls.append("awakening"))
    monkeypatch.setattr(lifecycle.daily_enabled_groups, "path", daily_path)
    monkeypatch.setattr(lifecycle.daily_enabled_groups, "load", lambda: calls.append("daily"))
    monkeypatch.setattr(lifecycle.daily_briefing_enabled_groups, "path", briefing_path)
    monkeypatch.setattr(lifecycle.daily_briefing_enabled_groups, "load", lambda: calls.append("briefing"))
    monkeypatch.setattr(lifecycle.boredom_enabled_groups, "path", boredom_path)
    monkeypatch.setattr(lifecycle.boredom_enabled_groups, "load", lambda: calls.append("boredom"))
    monkeypatch.setattr(lifecycle.weekly_enabled_groups, "path", weekly_path)
    monkeypatch.setattr(lifecycle.weekly_enabled_groups, "load", lambda: calls.append("weekly"))
    monkeypatch.setattr(lifecycle.monthly_enabled_groups, "path", monthly_path)
    monkeypatch.setattr(lifecycle.monthly_enabled_groups, "load", lambda: calls.append("monthly"))

    lifecycle._watched.clear()
    lifecycle._init_mtimes()
    weekly_path.write_text('{"changed": true}', encoding="utf-8")
    monthly_path.write_text('{"changed": true}', encoding="utf-8")
    _bump_mtime(weekly_path)
    _bump_mtime(monthly_path)

    lifecycle._reload_if_changed()

    assert calls == ["weekly", "monthly"]


@pytest.mark.asyncio
async def test_lifecycle_jobs_record_results(monkeypatch):
    """#199：三个维护任务接入执行记录——ok/error 双路，异常原样 re-raise。"""
    from quickquip.adapters.nonebot import scheduler_plugin

    driver = _FakeDriver()
    captured: dict[str, object] = {}
    fake_scheduler_module = types.ModuleType("nonebot_plugin_apscheduler")
    fake_scheduler_module.scheduler = types.SimpleNamespace(
        add_job=lambda fn, *args, **kwargs: captured.__setitem__(kwargs["id"], fn)
    )
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", fake_scheduler_module)
    monkeypatch.setattr(scheduler_plugin, "_job_run_results", {})

    lifecycle.register_lifecycle(driver)
    assert set(captured) == {
        "persistence_auto_save", "web_admin_state_sync", "web_admin_action_queue",
    }

    # ok 路径：三个任务全部记录 success
    monkeypatch.setattr(lifecycle, "save_all", lambda: None)
    monkeypatch.setattr(lifecycle, "_reload_if_changed", lambda: None)

    async def fake_process():
        return None

    monkeypatch.setattr(lifecycle, "process_web_admin_actions", fake_process)
    captured["persistence_auto_save"]()
    captured["web_admin_state_sync"]()
    await captured["web_admin_action_queue"]()
    results = scheduler_plugin.get_job_results()
    assert all(results[job]["last_status"] == "ok" for job in captured)
    assert all(results[job]["last_error"] is None for job in captured)

    # error 路径：re-raise 原异常 + 记录 error 与摘要
    def boom():
        raise RuntimeError("boom-500")

    async def async_boom():
        raise RuntimeError("async-boom")

    monkeypatch.setattr(lifecycle, "save_all", boom)
    monkeypatch.setattr(lifecycle, "_reload_if_changed", boom)
    monkeypatch.setattr(lifecycle, "process_web_admin_actions", async_boom)
    with pytest.raises(RuntimeError, match="boom-500"):
        captured["persistence_auto_save"]()
    with pytest.raises(RuntimeError, match="boom-500"):
        captured["web_admin_state_sync"]()
    with pytest.raises(RuntimeError, match="async-boom"):
        await captured["web_admin_action_queue"]()
    results = scheduler_plugin.get_job_results()
    for job in ("persistence_auto_save", "web_admin_state_sync"):
        assert results[job]["last_status"] == "error"
        assert "boom-500" in results[job]["last_error"]
    assert results["web_admin_action_queue"]["last_status"] == "error"
    assert "async-boom" in results["web_admin_action_queue"]["last_error"]
