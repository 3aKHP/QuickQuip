from __future__ import annotations

import types

import pytest

from quickquip.adapters.nonebot import daily_summary_plugin as plugin


class _FakeSummaryCmd:
    """捕获 finish/send 调用，记录最终回复。"""

    def __init__(self):
        self.finished: list[str] = []
        self.sent: list[str] = []

    async def finish(self, msg: str = "") -> None:
        self.finished.append(msg)
        raise _FinishSentinel()

    async def send(self, msg: str) -> None:
        self.sent.append(msg)


class _FinishSentinel(Exception):
    """模拟 nonebot 的 finish() 抛出异常终止 handler 的行为。"""


class _FakeEnabledGroups:
    def __init__(self):
        self._groups: set[str] = set()

    def add(self, gid):
        self._groups.add(str(gid))

    def remove(self, gid):
        self._groups.discard(str(gid))

    def contains(self, gid) -> bool:
        return str(gid) in self._groups

    def all_groups(self):
        return sorted(self._groups)


def _patch_env(monkeypatch, *, period_type="weekly"):
    """打桩周期报告的依赖（enabled groups / admin / service）。"""
    fake_enabled = _FakeEnabledGroups()

    if period_type == "weekly":
        monkeypatch.setattr(plugin, "weekly_enabled_groups", fake_enabled)
    else:
        monkeypatch.setattr(plugin, "monthly_enabled_groups", fake_enabled)

    monkeypatch.setattr(plugin, "_is_admin", lambda event: True)
    monkeypatch.setattr(plugin, "_ensure_llm_bindings", lambda: None)
    monkeypatch.setattr(plugin, "get_llm_service", lambda: types.SimpleNamespace(
        config=types.SimpleNamespace(
            weekly_report=types.SimpleNamespace(
                generate_cron="0 9 * * 1", publish_cron="0 10 * * 1",
            ),
            monthly_report=types.SimpleNamespace(
                generate_cron="0 9 1 * *", publish_cron="0 10 1 * *",
            ),
        )
    ))
    return fake_enabled


@pytest.mark.asyncio
async def test_period_subcommand_on_enables_group(monkeypatch):
    fake_enabled = _patch_env(monkeypatch, period_type="weekly")
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("weekly on", 10001, cmd, event=None)

    assert fake_enabled.contains(10001)
    assert len(cmd.finished) == 1
    assert "周报已开启" in cmd.finished[0]


@pytest.mark.asyncio
async def test_period_subcommand_off_disables_group(monkeypatch):
    fake_enabled = _patch_env(monkeypatch, period_type="weekly")
    fake_enabled.add(10001)
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("weekly off", 10001, cmd, event=None)

    assert not fake_enabled.contains(10001)
    assert "周报已关闭" in cmd.finished[0]


@pytest.mark.asyncio
async def test_period_subcommand_status_reports_state(monkeypatch):
    _patch_env(monkeypatch, period_type="monthly")
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("monthly status", 10001, cmd, event=None)

    assert "月报" in cmd.finished[0]
    assert "已关闭" in cmd.finished[0]


@pytest.mark.asyncio
async def test_period_subcommand_bare_prefix_defaults_to_status(monkeypatch):
    """不带子命令时（仅 /summary weekly）等价于 status。"""
    _patch_env(monkeypatch, period_type="weekly")
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("weekly", 10001, cmd, event=None)

    assert len(cmd.finished) == 1


@pytest.mark.asyncio
async def test_period_subcommand_chinese_aliases(monkeypatch):
    """中文别名 周报/月报 也应被识别。"""
    fake_enabled = _patch_env(monkeypatch, period_type="weekly")
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("周报 on", 10001, cmd, event=None)

    assert fake_enabled.contains(10001)
    assert "周报已开启" in cmd.finished[0]


@pytest.mark.asyncio
async def test_period_subcommand_returns_false_for_daily_args(monkeypatch):
    """日报子命令（on/off/status/now 无前缀）不应被周期分发捕获。"""
    _patch_env(monkeypatch, period_type="weekly")
    cmd = _FakeSummaryCmd()

    handled = await plugin._handle_period_subcommand("on", 10001, cmd, event=None)
    assert handled is False
    handled = await plugin._handle_period_subcommand("status", 10001, cmd, event=None)
    assert handled is False
    handled = await plugin._handle_period_subcommand("", 10001, cmd, event=None)
    assert handled is False


@pytest.mark.asyncio
async def test_period_subcommand_monthly_uses_month_label(monkeypatch):
    _patch_env(monkeypatch, period_type="monthly")
    fake_enabled = plugin.monthly_enabled_groups
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("monthly on", 10001, cmd, event=None)

    assert fake_enabled.contains(10001)
    assert "月报已开启" in cmd.finished[0]


@pytest.mark.asyncio
async def test_period_subcommand_unknown_sub_shows_usage(monkeypatch):
    _patch_env(monkeypatch, period_type="weekly")
    cmd = _FakeSummaryCmd()

    with pytest.raises(_FinishSentinel):
        await plugin._handle_period_subcommand("weekly foobar", 10001, cmd, event=None)

    assert len(cmd.finished) == 1
    assert "用法" in cmd.finished[0]
    assert "weekly" in cmd.finished[0]
