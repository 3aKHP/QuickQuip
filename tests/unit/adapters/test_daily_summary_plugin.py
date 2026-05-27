from __future__ import annotations

from datetime import datetime
import types
from zoneinfo import ZoneInfo

import pytest

from quickquip.adapters.nonebot import daily_summary_plugin as daily_summary_plugin


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 5, 4, 6, 0, tzinfo=LOCAL_TZ)
        return current if tz is None else current.astimezone(tz)


@pytest.mark.asyncio
async def test_job_generate_summaries_dispatches_enabled_groups(monkeypatch):
    calls: list[tuple[str, float, float, str, str]] = []

    async def fake_generate_one(group_id, start_ts, end_ts, date_label, summary_date):
        calls.append((group_id, start_ts, end_ts, date_label, summary_date))

    class _EnabledGroups:
        @staticmethod
        def all_groups():
            return ["10001", "10002"]

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin, "_generate_one", fake_generate_one)

    await daily_summary_plugin._job_generate_summaries()

    assert [group_id for group_id, *_ in calls] == ["10001", "10002"]
    assert all(summary_date == "2026-05-03" for *_, summary_date in calls)
    assert all(
        date_label == "2026年05月03日 06:00 至 05月04日 06:00"
        for *_, date_label, _summary_date in calls
    )


@pytest.mark.asyncio
async def test_send_daily_summary_now_reuses_manual_generation(monkeypatch):
    calls: list[tuple[str, float, float, str]] = []

    class _EnabledGroups:
        @staticmethod
        def contains(group_id):
            return group_id == "123456"

    async def fake_run_generation(group_id, start_ts, end_ts, date_label):
        calls.append((group_id, start_ts, end_ts, date_label))
        return "summary text", "model-a"

    sent: list[tuple[int, str]] = []

    async def fake_send_long_message(_bot, group_id, content):
        sent.append((group_id, content))

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin.daily_collector, "read_window", lambda *args, **kwargs: ["m1", "m2"])
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=1))),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda group_id: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda group_id: None)
    monkeypatch.setattr(daily_summary_plugin, "_run_generation", fake_run_generation)
    monkeypatch.setattr(daily_summary_plugin, "_send_long_message", fake_send_long_message)
    before_generate_calls: list[str] = []

    async def before_generate():
        before_generate_calls.append("called")

    result = await daily_summary_plugin.send_daily_summary_now("123456", types.SimpleNamespace(), before_generate)

    assert result == {"model_used": "model-a", "char_count": len("summary text")}
    assert sent == [(123456, "summary text")]
    assert before_generate_calls == ["called"]
    assert calls[0][0] == "123456"
    assert calls[0][3] == "2026年05月03日 06:00 至 05月04日 06:00"


@pytest.mark.asyncio
async def test_send_daily_summary_now_reports_not_enough_messages(monkeypatch):
    class _EnabledGroups:
        @staticmethod
        def contains(group_id):
            return group_id == "123456"

    monkeypatch.setattr(daily_summary_plugin, "datetime", _FixedDateTime)
    monkeypatch.setattr(daily_summary_plugin, "daily_enabled_groups", _EnabledGroups())
    monkeypatch.setattr(daily_summary_plugin.daily_collector, "read_window", lambda *args, **kwargs: ["m1"])
    monkeypatch.setattr(
        daily_summary_plugin,
        "get_llm_service",
        lambda: types.SimpleNamespace(config=types.SimpleNamespace(daily_summary=types.SimpleNamespace(min_messages=2))),
    )
    monkeypatch.setattr(daily_summary_plugin, "_on_cooldown", lambda group_id: False)
    monkeypatch.setattr(daily_summary_plugin, "_mark_triggered", lambda group_id: None)

    with pytest.raises(RuntimeError, match="not enough messages: 1/2"):
        await daily_summary_plugin.send_daily_summary_now("123456", types.SimpleNamespace())
