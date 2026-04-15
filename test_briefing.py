import asyncio
import importlib.util
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


ARTIFACT_DIR = Path("dev/sandbox/test_artifacts/test_briefing")
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
HAS_JIEBA = importlib.util.find_spec("jieba") is not None


def _reset_artifact_dir() -> None:
    if ARTIFACT_DIR.exists():
        shutil.rmtree(ARTIFACT_DIR)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    _reset_artifact_dir()

    collector = DailyMessageCollector(base_dir=ARTIFACT_DIR / "daily_msgs")
    wordcloud_collector = WordCloudCollector(base_dir=ARTIFACT_DIR / "wordcloud_msgs")
    enabled_groups = DailyBriefingEnabledGroups(path=ARTIFACT_DIR / "daily_briefing_groups.json")
    config = DailyBriefingConfig(
        enabled=True,
        active_users_limit=3,
        hot_words_limit=3,
        sample_messages_limit=6,
        max_output_chars=80,
    )

    assert normalize_period("早报") == "morning"
    assert normalize_period("noon") == "noon"
    assert normalize_period("晚上") == "evening"
    assert normalize_period("unknown") is None

    now_morning = datetime(2026, 4, 15, 8, 0, tzinfo=LOCAL_TZ)
    morning_start, morning_end, morning_label = get_briefing_window("morning", now_morning)
    assert morning_start == datetime(2026, 4, 14, 0, 0, tzinfo=LOCAL_TZ)
    assert morning_end == datetime(2026, 4, 15, 0, 0, tzinfo=LOCAL_TZ)
    assert "2026-04-14 00:00" in morning_label

    now_noon = datetime(2026, 4, 15, 12, 30, tzinfo=LOCAL_TZ)
    noon_start, noon_end, noon_label = get_briefing_window("noon", now_noon)
    assert noon_start == datetime(2026, 4, 15, 0, 0, tzinfo=LOCAL_TZ)
    assert noon_end == now_noon
    assert "04-15 12:30" in noon_label

    group_id = "10001"

    # 昨日消息，供早报使用
    yesterday_msgs = [
        (datetime(2026, 4, 14, 9, 0, tzinfo=LOCAL_TZ), "u1", "张三", "今天原神启动了吗"),
        (datetime(2026, 4, 14, 10, 0, tzinfo=LOCAL_TZ), "u2", "李四", "原神启动了两次"),
        (datetime(2026, 4, 14, 11, 0, tzinfo=LOCAL_TZ), "u1", "张三", "启动失败，继续启动"),
        (datetime(2026, 4, 14, 18, 0, tzinfo=LOCAL_TZ), "u3", "王五", "晚上吃什么"),
    ]
    for ts, user_id, sender, text in yesterday_msgs:
        collector.record(group_id, sender, text, ts=ts.timestamp(), user_id=user_id)
        wordcloud_collector.record(group_id, sender, text, ts=ts.timestamp())

    # 今日消息，供午报/晚报使用
    today_msgs = [
        (datetime(2026, 4, 15, 8, 10, tzinfo=LOCAL_TZ), "u1", "张三", "今天也要启动原神"),
        (datetime(2026, 4, 15, 9, 15, tzinfo=LOCAL_TZ), "u2", "李四", "原神和午饭都得启动"),
        (datetime(2026, 4, 15, 11, 30, tzinfo=LOCAL_TZ), "u2", "李四", "午饭先启动"),
        (datetime(2026, 4, 15, 12, 5, tzinfo=LOCAL_TZ), "u3", "王五", "吃完饭继续聊"),
    ]
    for ts, user_id, sender, text in today_msgs:
        collector.record(group_id, sender, text, ts=ts.timestamp(), user_id=user_id)
        wordcloud_collector.record(group_id, sender, text, ts=ts.timestamp())

    morning_context = await build_briefing_context(
        group_id=group_id,
        period="morning",
        now=now_morning,
        daily_collector=collector,
        wordcloud_collector=wordcloud_collector,
        briefing_config=config,
    )
    assert morning_context.period_label == "早报"
    assert morning_context.message_count == 4
    assert morning_context.active_users[0].display_name == "张三"
    assert morning_context.active_users[0].message_count == 2
    if HAS_JIEBA:
        assert "启动" in morning_context.hot_words
    else:
        assert morning_context.hot_words == []
    assert len(morning_context.sample_messages) <= config.sample_messages_limit
    assert all("time_label" in item for item in morning_context.sample_messages)

    noon_context = await build_briefing_context(
        group_id=group_id,
        period="noon",
        now=now_noon,
        daily_collector=collector,
        wordcloud_collector=wordcloud_collector,
        briefing_config=config,
    )
    assert noon_context.period_label == "午报"
    assert noon_context.message_count == 4
    assert noon_context.active_users[0].display_name == "李四"
    assert noon_context.active_users[0].message_count == 2
    assert noon_context.window_label.endswith("12:30")

    fallback = build_fallback_briefing(noon_context)
    assert "午报" in fallback
    assert "消息总数：4" in fallback
    assert "活跃用户：" in fallback
    if noon_context.hot_words:
        assert "热词：" in fallback

    trimmed = _trim_output("第一句。第二句。第三句。第四句。", max_chars=8)
    assert trimmed.endswith("……") or len(trimmed) <= 8

    enabled_groups.add(group_id)
    assert enabled_groups.contains(group_id) is True
    reloaded_groups = DailyBriefingEnabledGroups(path=ARTIFACT_DIR / "daily_briefing_groups.json")
    assert reloaded_groups.contains(group_id) is True
    reloaded_groups.remove(group_id)
    assert reloaded_groups.contains(group_id) is False

    print("all pass")


if __name__ == "__main__":
    asyncio.run(main())
