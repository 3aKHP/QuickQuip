from __future__ import annotations

from datetime import datetime
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
