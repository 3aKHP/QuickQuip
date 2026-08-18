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
    monkeypatch.setattr(lifecycle, "reload_awakening_config", lambda: calls.append("awakening"))
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
    monkeypatch.setattr(lifecycle, "reload_awakening_config", lambda: calls.append("awakening"))
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
