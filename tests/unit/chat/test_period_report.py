from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from quickquip.chat.period_report import (
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    PeriodReportEnabledGroups,
    PeriodReportStore,
    compute_period_window,
    period_key_for,
    period_label_for,
    sample_messages_by_day,
)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


# ── period_key_for ────────────────────────────────────────────────────────

def test_period_key_weekly_iso_week():
    # 2026-06-10 是周三，属 ISO 第 24 周
    assert period_key_for(PERIOD_WEEKLY, date(2026, 6, 10)) == "2026-W24"
    # 跨年边界：2024-12-30（周一）属 2025 第 1 周
    assert period_key_for(PERIOD_WEEKLY, date(2024, 12, 30)) == "2025-W01"


def test_period_key_monthly():
    assert period_key_for(PERIOD_MONTHLY, date(2026, 6, 15)) == "2026-06"
    assert period_key_for(PERIOD_MONTHLY, date(2026, 1, 1)) == "2026-01"


def test_period_key_invalid_type():
    with pytest.raises(ValueError):
        period_key_for("quarterly", date(2026, 6, 10))


# ── period_label_for ──────────────────────────────────────────────────────

def test_period_label_weekly():
    assert period_label_for(PERIOD_WEEKLY, "2026-W24", LOCAL_TZ) == "2026 年第 24 周"


def test_period_label_monthly():
    assert period_label_for(PERIOD_MONTHLY, "2026-06", LOCAL_TZ) == "2026 年 6 月"


# ── compute_period_window ─────────────────────────────────────────────────

def test_compute_weekly_window_returns_previous_week():
    # 2026-06-15 是周一 09:00，上周窗口应为 06-08 到 06-15
    now = datetime(2026, 6, 15, 9, 0, tzinfo=LOCAL_TZ)
    start_ts, end_ts, key, label = compute_period_window(PERIOD_WEEKLY, now)
    start = datetime.fromtimestamp(start_ts, tz=LOCAL_TZ)
    end = datetime.fromtimestamp(end_ts, tz=LOCAL_TZ)
    assert start.strftime("%Y-%m-%d %H:%M") == "2026-06-08 00:00"
    assert end.strftime("%Y-%m-%d %H:%M") == "2026-06-15 00:00"
    assert key == "2026-W24"
    assert label == "2026 年第 24 周"


def test_compute_monthly_window_returns_previous_month():
    # 2026-07-01 09:00，上月窗口应为 06-01 到 07-01
    now = datetime(2026, 7, 1, 9, 0, tzinfo=LOCAL_TZ)
    start_ts, end_ts, key, label = compute_period_window(PERIOD_MONTHLY, now)
    start = datetime.fromtimestamp(start_ts, tz=LOCAL_TZ)
    end = datetime.fromtimestamp(end_ts, tz=LOCAL_TZ)
    assert start.strftime("%Y-%m-%d %H:%M") == "2026-06-01 00:00"
    assert end.strftime("%Y-%m-%d %H:%M") == "2026-07-01 00:00"
    assert key == "2026-06"
    assert label == "2026 年 6 月"


def test_compute_window_invalid_type():
    with pytest.raises(ValueError):
        compute_period_window("quarterly", datetime(2026, 6, 15, tzinfo=LOCAL_TZ))


# ── sample_messages_by_day ────────────────────────────────────────────────

def _make_messages(day: date, count: int) -> list[dict]:
    """生成某天 count 条消息（每小时一条）。"""
    base_ts = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ).timestamp()
    return [{"ts": base_ts + h * 3600, "text": f"m{h}", "sender": "u"} for h in range(count)]


def test_sample_under_limit_returns_all():
    msgs = _make_messages(date(2026, 6, 10), 3)
    assert len(sample_messages_by_day(msgs, 5)) == 3


def test_sample_over_limit_caps_per_day():
    msgs = _make_messages(date(2026, 6, 10), 24)
    sampled = sample_messages_by_day(msgs, 3)
    assert len(sampled) == 3


def test_sample_multi_day_each_day_capped():
    msgs = _make_messages(date(2026, 6, 10), 10) + _make_messages(date(2026, 6, 11), 10)
    sampled = sample_messages_by_day(msgs, 2)
    assert len(sampled) == 4  # 每天 2 条 × 2 天
    # 两天都被采到
    days = {datetime.fromtimestamp(m["ts"], tz=LOCAL_TZ).day for m in sampled}
    assert days == {10, 11}


def test_sample_result_sorted_by_ts():
    msgs = _make_messages(date(2026, 6, 11), 5) + _make_messages(date(2026, 6, 10), 5)
    sampled = sample_messages_by_day(msgs, 10)
    timestamps = [m["ts"] for m in sampled]
    assert timestamps == sorted(timestamps)


def test_sample_empty_or_zero_per_day():
    assert sample_messages_by_day([], 5) == []
    assert sample_messages_by_day(_make_messages(date(2026, 6, 10), 5), 0) == []


# ── PeriodReportStore ─────────────────────────────────────────────────────

def test_store_upsert_get_unpublished_mark_published(tmp_path):
    store = PeriodReportStore(tmp_path / "test.db")
    store.upsert("10001", PERIOD_WEEKLY, "2026-W24", "周报内容", "model-a")

    got = store.get("10001", PERIOD_WEEKLY, "2026-W24")
    assert got is not None
    assert got["content"] == "周报内容"
    assert got["model_used"] == "model-a"
    assert got["char_count"] == len("周报内容")

    # 初始未发布
    unpublished = store.get_unpublished(PERIOD_WEEKLY)
    assert len(unpublished) == 1

    # 标记发布后不再出现在未发布列表
    store.mark_published("10001", PERIOD_WEEKLY, "2026-W24")
    assert store.get_unpublished(PERIOD_WEEKLY) == []


def test_store_upsert_same_key_overwrites_and_resets_published(tmp_path):
    store = PeriodReportStore(tmp_path / "test.db")
    store.upsert("10001", PERIOD_WEEKLY, "2026-W24", "v1", "m1")
    store.mark_published("10001", PERIOD_WEEKLY, "2026-W24")
    assert store.get_unpublished(PERIOD_WEEKLY) == []

    # 同 key 重新生成应覆盖并重置为未发布
    store.upsert("10001", PERIOD_WEEKLY, "2026-W24", "v2", "m2")
    unpublished = store.get_unpublished(PERIOD_WEEKLY)
    assert len(unpublished) == 1
    assert unpublished[0]["content"] == "v2"


def test_store_separates_weekly_and_monthly(tmp_path):
    store = PeriodReportStore(tmp_path / "test.db")
    store.upsert("10001", PERIOD_WEEKLY, "2026-W24", "周报")
    store.upsert("10001", PERIOD_MONTHLY, "2026-06", "月报")

    assert len(store.get_unpublished(PERIOD_WEEKLY)) == 1
    assert len(store.get_unpublished(PERIOD_MONTHLY)) == 1
    # 不同 period_type 互不干扰
    assert store.get("10001", PERIOD_WEEKLY, "2026-06") is None


def test_store_upsert_rejects_invalid_period_type(tmp_path):
    store = PeriodReportStore(tmp_path / "test.db")
    with pytest.raises(ValueError):
        store.upsert("10001", "quarterly", "2026-Q2", "x")


# ── PeriodReportEnabledGroups ─────────────────────────────────────────────

def test_enabled_groups_add_remove_contains(tmp_path):
    eg = PeriodReportEnabledGroups(PERIOD_WEEKLY, tmp_path / "weekly.json")
    assert not eg.contains("10001")
    eg.add(10001)
    assert eg.contains("10001")
    assert eg.all_groups() == ["10001"]
    eg.remove("10001")
    assert not eg.contains("10001")


def test_enabled_groups_persist_across_instances(tmp_path):
    path = tmp_path / "weekly.json"
    eg1 = PeriodReportEnabledGroups(PERIOD_WEEKLY, path)
    eg1.add(10001)
    eg1.add(10002)

    eg2 = PeriodReportEnabledGroups(PERIOD_WEEKLY, path)
    assert eg2.contains("10001")
    assert eg2.contains("10002")
    assert eg2.all_groups() == ["10001", "10002"]


def test_enabled_groups_weekly_and_monthly_independent(tmp_path):
    weekly = PeriodReportEnabledGroups(PERIOD_WEEKLY, tmp_path / "w.json")
    monthly = PeriodReportEnabledGroups(PERIOD_MONTHLY, tmp_path / "m.json")
    weekly.add(10001)
    assert not monthly.contains("10001")
    assert weekly.contains("10001")


def test_enabled_groups_rejects_invalid_type(tmp_path):
    with pytest.raises(ValueError):
        PeriodReportEnabledGroups("quarterly", tmp_path / "q.json")
