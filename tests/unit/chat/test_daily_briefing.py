from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quickquip.chat.daily_briefing import (
    DailyBriefingEnabledGroups,
    build_briefing_context,
    build_fallback_briefing,
    get_briefing_window,
    normalize_period,
)
from quickquip.chat.daily_summary import DailyMessageCollector
from quickquip.chat.wordcloud import WordCloudCollector
from quickquip.llm.briefing import _trim_output
from quickquip.llm.config import DailyBriefingConfig


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
HAS_JIEBA = importlib.util.find_spec("jieba") is not None


@pytest.fixture
def briefing_config() -> DailyBriefingConfig:
    return DailyBriefingConfig(
        enabled=True,
        active_users_limit=3,
        hot_words_limit=3,
        sample_messages_limit=6,
        max_output_chars=80,
    )


def test_normalize_period():
    assert normalize_period("早报") == "morning"
    assert normalize_period("noon") == "noon"
    assert normalize_period("晚上") == "evening"
    assert normalize_period("unknown") is None


def test_morning_window_covers_yesterday():
    now = datetime(2026, 4, 15, 8, 0, tzinfo=LOCAL_TZ)
    start, end, label = get_briefing_window("morning", now)
    assert start == datetime(2026, 4, 14, 0, 0, tzinfo=LOCAL_TZ)
    assert end == datetime(2026, 4, 15, 0, 0, tzinfo=LOCAL_TZ)
    assert "2026-04-14 00:00" in label


def test_noon_window_covers_today_so_far():
    now = datetime(2026, 4, 15, 12, 30, tzinfo=LOCAL_TZ)
    start, end, label = get_briefing_window("noon", now)
    assert start == datetime(2026, 4, 15, 0, 0, tzinfo=LOCAL_TZ)
    assert end == now
    assert "04-15 12:30" in label


async def test_build_morning_briefing_context(tmp_path: Path, briefing_config):
    collector = DailyMessageCollector(base_dir=tmp_path / "daily_msgs")
    wc_collector = WordCloudCollector(base_dir=tmp_path / "wordcloud_msgs")
    group_id = "10001"

    yesterday = [
        (datetime(2026, 4, 14, 9, 0, tzinfo=LOCAL_TZ), "u1", "张三", "今天原神启动了吗"),
        (datetime(2026, 4, 14, 10, 0, tzinfo=LOCAL_TZ), "u2", "李四", "原神启动了两次"),
        (datetime(2026, 4, 14, 11, 0, tzinfo=LOCAL_TZ), "u1", "张三", "启动失败，继续启动"),
        (datetime(2026, 4, 14, 18, 0, tzinfo=LOCAL_TZ), "u3", "王五", "晚上吃什么"),
    ]
    for ts, user_id, sender, text in yesterday:
        collector.record(group_id, sender, text, ts=ts.timestamp(), user_id=user_id)
        wc_collector.record(group_id, sender, text, ts=ts.timestamp())

    now = datetime(2026, 4, 15, 8, 0, tzinfo=LOCAL_TZ)
    context = await build_briefing_context(
        group_id=group_id,
        period="morning",
        now=now,
        daily_collector=collector,
        wordcloud_collector=wc_collector,
        briefing_config=briefing_config,
    )
    assert context.period_label == "早报"
    assert context.message_count == 4
    assert context.active_users[0].display_name == "张三"
    assert context.active_users[0].message_count == 2
    if HAS_JIEBA:
        assert "启动" in context.hot_words
    else:
        assert context.hot_words == []
    assert len(context.sample_messages) <= briefing_config.sample_messages_limit
    assert all("time_label" in item for item in context.sample_messages)


async def test_build_noon_briefing_and_fallback(tmp_path: Path, briefing_config):
    collector = DailyMessageCollector(base_dir=tmp_path / "daily_msgs")
    wc_collector = WordCloudCollector(base_dir=tmp_path / "wordcloud_msgs")
    group_id = "10001"

    today = [
        (datetime(2026, 4, 15, 8, 10, tzinfo=LOCAL_TZ), "u1", "张三", "今天也要启动原神"),
        (datetime(2026, 4, 15, 9, 15, tzinfo=LOCAL_TZ), "u2", "李四", "原神和午饭都得启动"),
        (datetime(2026, 4, 15, 11, 30, tzinfo=LOCAL_TZ), "u2", "李四", "午饭先启动"),
        (datetime(2026, 4, 15, 12, 5, tzinfo=LOCAL_TZ), "u3", "王五", "吃完饭继续聊"),
    ]
    for ts, user_id, sender, text in today:
        collector.record(group_id, sender, text, ts=ts.timestamp(), user_id=user_id)
        wc_collector.record(group_id, sender, text, ts=ts.timestamp())

    now = datetime(2026, 4, 15, 12, 30, tzinfo=LOCAL_TZ)
    context = await build_briefing_context(
        group_id=group_id,
        period="noon",
        now=now,
        daily_collector=collector,
        wordcloud_collector=wc_collector,
        briefing_config=briefing_config,
    )
    assert context.period_label == "午报"
    assert context.message_count == 4
    assert context.active_users[0].display_name == "李四"
    assert context.active_users[0].message_count == 2
    assert context.window_label.endswith("12:30")

    fallback = build_fallback_briefing(context)
    assert "午报" in fallback
    assert "消息总数：4" in fallback
    assert "活跃用户：" in fallback
    if context.hot_words:
        assert "热词：" in fallback


def test_trim_output_respects_max_chars():
    out = _trim_output("第一句。第二句。第三句。第四句。", max_chars=8)
    assert out.endswith("……") or len(out) <= 8


def test_enabled_groups_persist(tmp_path: Path):
    path = tmp_path / "briefing_groups.json"
    groups = DailyBriefingEnabledGroups(path=path)
    groups.add("10001")
    assert groups.contains("10001") is True

    reloaded = DailyBriefingEnabledGroups(path=path)
    assert reloaded.contains("10001") is True
    reloaded.remove("10001")
    assert reloaded.contains("10001") is False
