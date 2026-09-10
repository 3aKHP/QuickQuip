"""period_serializer 单测：清洗 + 三级压缩序列化规格钉住。

规格（2026-09-09 与人类协作者定案）：
- 日分节【MM-DD 周X】→ 分钟块（块首行带 [HH:MM]，续行裸 sender）→
  块内相邻同身份（user_id 优先、sender 回退）合并为行，以 / 连接
- 相邻相同文本 ≥3 折叠 ×N；单行至多 8 段后拆行
- URL 只留域名；单条正文 400 字符截断；换行折叠；sender 规整截 24
- bot 自产消息按 user_id 匹配，显示名后缀 (bot)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.chat.period_serializer import (
    PeriodSerializeStats,
    bot_user_ids_from_env,
    build_monthly_chat_input,
    serialize_period_chat,
)

TZ = ZoneInfo("Asia/Shanghai")


def _ts(day: int = 8, hh: int = 8, mm: int = 12, ss: int = 0) -> float:
    return datetime(2026, 9, day, hh, mm, ss, tzinfo=TZ).timestamp()


def _msg(sender: str, text: str, ts: float, user_id: str | None = None) -> dict:
    return {"sender": sender, "text": text, "ts": ts, "user_id": user_id}


def test_user_example_structure_pinned():
    """钉住设计讨论中的示例呈现（含跨说话人续行与复读折叠）。"""
    messages = [
        _msg("张三", "早", _ts(ss=0), "1001"),
        _msg("张三", "都起了没", _ts(ss=30), "1001"),
        _msg("张四", "起了", _ts(ss=35), "1002"),
        _msg("张五", "还没", _ts(ss=40), "1003"),
        _msg("张三", "有猪", _ts(ss=45), "1001"),
        _msg("张三", "给你睡爽了", _ts(ss=50), "1001"),
        _msg("李四", "起了", _ts(mm=15), "1004"),
        *[_msg("王五", "哈哈哈哈哈", _ts(hh=21, mm=33, ss=i), "1005") for i in range(12)],
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] 张三：早 / 都起了没",
        "张四：起了",
        "张五：还没",
        "张三：有猪 / 给你睡爽了",
        "[08:15] 李四：起了",
        "[21:33] 王五：哈哈哈哈哈 ×12",
    ])
    assert stats.messages_in == 19
    assert stats.messages_skipped == 0
    assert stats.lines == 6
    assert stats.day_sections == 1
    assert stats.minute_blocks == 3
    assert stats.merged_runs == 3
    assert stats.repeat_collapses == 1
    assert stats.bot_lines == 0
    assert stats.chars == len(text)


def test_day_sections_with_weekdays_and_midnight_split():
    """跨天分节带星期；跨日界/跨分钟的连发串切开各自起块。"""
    messages = [
        _msg("甲", "晚安", _ts(day=7, hh=23, mm=59, ss=58)),
        _msg("甲", "啊又醒了", _ts(day=8, hh=0, mm=0, ss=5)),
        _msg("乙", "早", _ts(day=8, hh=7, mm=30)),
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-07 周一】",
        "[23:59] 甲：晚安",
        "【09-08 周二】",
        "[00:00] 甲：啊又醒了",
        "[07:30] 乙：早",
    ])
    assert stats.day_sections == 2
    assert stats.minute_blocks == 3
    assert stats.merged_runs == 0


def test_identity_prefers_user_id_over_sender_name():
    """同昵称不同 user_id 不合并；同 user_id 相邻消息合并（身份按 user_id）。"""
    messages = [
        _msg("小明", "我是A", _ts(ss=0), user_id="111"),
        _msg("小明", "我是B", _ts(ss=10), user_id="222"),  # 同名不同人：另起行
        _msg("小明", "我是A2", _ts(ss=20), user_id="111"),  # A 回来：再起行
    ]

    text, _ = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] 小明：我是A",
        "小明：我是B",
        "小明：我是A2",
    ])


def test_identity_falls_back_to_sender_name_when_no_user_id():
    """无 user_id（回灌历史数据形态）时按 sender 合并。"""
    messages = [
        _msg("路人", "第一句", _ts(ss=0)),
        _msg("路人", "第二句", _ts(ss=5)),
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert "[08:12] 路人：第一句 / 第二句" in text
    assert stats.merged_runs == 1


def test_repeat_collapse_thresholds():
    """恰好 2 条相同保留原文；≥3 折叠 ×N；非相邻重复不折叠。"""
    messages = [
        _msg("甲", "一样的", _ts(ss=0)),
        _msg("甲", "一样的", _ts(ss=1)),
        _msg("乙", "插话", _ts(ss=2)),
        _msg("甲", "一样的", _ts(ss=3)),  # 与前一条甲消息不相邻
        _msg("乙", "刷屏", _ts(mm=13, ss=0)),
        _msg("乙", "刷屏", _ts(mm=13, ss=1)),
        _msg("乙", "刷屏", _ts(mm=13, ss=2)),
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] 甲：一样的 / 一样的",
        "乙：插话",
        "甲：一样的",
        "[08:13] 乙：刷屏 ×3",
    ])
    assert stats.repeat_collapses == 1


def test_line_part_cap_splits_bare_continuation():
    """同身份同分钟超过 8 段：8 段一行，余量另起裸行（不带时间戳）。"""
    messages = [
        _msg("甲", f"第{i}句", _ts(ss=i)) for i in range(10)
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] 甲：" + " / ".join(f"第{i}句" for i in range(8)),
        "甲：" + " / ".join(f"第{i}句" for i in (8, 9)),
    ])
    assert stats.lines == 2
    assert stats.merged_runs == 1


def test_url_replaced_by_domain():
    messages = [
        _msg("甲", "看 https://www.bilibili.com/video/BV1xx 很好", _ts(ss=0)),
        _msg("甲", "还有 http://Github.com/a/b?c=1 和 https://news.ycombinator.com/item?id=1", _ts(ss=1)),
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert "[bilibili.com]" in text
    assert "[github.com]" in text
    assert "[news.ycombinator.com]" in text
    assert "https://" not in text
    assert "http://" not in text
    assert stats.urls_replaced == 3


def test_body_truncation():
    long_text = "字" * 500
    messages = [_msg("甲", long_text, _ts(ss=0))]

    text, stats = serialize_period_chat(messages, local_tz=TZ, max_body_chars=400)

    line = text.splitlines()[-1]
    assert line == "[08:12] 甲：" + "字" * 400 + "…"
    assert stats.messages_truncated == 1


def test_whitespace_folding_and_empty_skip():
    messages = [
        _msg("甲", "第一行\n第二行   多空格", _ts(ss=0)),
        _msg("甲", "   \n\t  ", _ts(ss=1)),
        _msg("甲", "", _ts(ss=2)),
        _msg("甲", "有效", _ts(ss=3)),
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ)

    assert "[08:12] 甲：第一行 第二行 多空格 / 有效" in text
    assert stats.messages_skipped == 2
    assert stats.messages_in == 4


def test_sender_sanitization():
    messages = [
        _msg("带\n换行的名字", "内容", _ts(ss=0)),
        _msg("x" * 40, "内容2", _ts(ss=1)),
        _msg("", "内容3", _ts(ss=2)),
    ]

    text, _ = serialize_period_chat(messages, local_tz=TZ)

    lines = text.splitlines()
    assert lines[1] == "[08:12] 带 换行的名字：内容"
    assert lines[2] == f"{'x' * 24}：内容2"
    assert lines[3] == "未知：内容3"


def test_bot_marking_by_user_id():
    messages = [
        _msg("QuickQuip", "我来回答", _ts(ss=0), user_id="999"),
        _msg("QuickQuip", "补充", _ts(ss=5), user_id="999"),
        _msg("张三", "谢谢", _ts(ss=6)),
        _msg("李四", "被改名也没用", _ts(ss=7), user_id="999"),  # 同账号换昵称仍标记
    ]

    text, stats = serialize_period_chat(messages, local_tz=TZ, bot_user_ids={"999"})

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] QuickQuip(bot)：我来回答 / 补充",
        "张三：谢谢",
        "李四(bot)：被改名也没用",
    ])
    assert stats.bot_lines == 2


def test_unsorted_input_is_sorted_stably():
    messages = [
        _msg("乙", "后发", _ts(ss=30)),
        _msg("甲", "先发", _ts(ss=0)),
    ]

    text, _ = serialize_period_chat(messages, local_tz=TZ)

    assert text == "\n".join([
        "【09-08 周二】",
        "[08:12] 甲：先发",
        "乙：后发",
    ])


def test_empty_input():
    text, stats = serialize_period_chat([], local_tz=TZ)

    assert text == ""
    assert stats == PeriodSerializeStats()


def test_bot_user_ids_from_env_parsing():
    assert bot_user_ids_from_env({}) == frozenset()
    assert bot_user_ids_from_env({"QQ_ACCOUNT": ""}) == frozenset()
    assert bot_user_ids_from_env({"QQ_ACCOUNT": "your_qq_account_here"}) == frozenset()
    assert bot_user_ids_from_env({"QQ_ACCOUNT": "12345"}) == frozenset({"12345"})
    assert bot_user_ids_from_env({"QQ_ACCOUNT": "123, 456"}) == frozenset({"123", "456"})
    assert bot_user_ids_from_env({"QQ_ACCOUNT": "123\t456\n789"}) == frozenset(
        {"123", "456", "789"}
    )


# ── build_monthly_chat_input ───────────────────────────────────────────────


def _month_msgs(day: int, n: int, *, hour: int = 10) -> list[dict]:
    return [
        _msg(f"u{day}-{i}", f"第{day}日消息{i}", _ts(day=day, hh=hour, mm=i % 60, ss=i // 60))
        for i in range(n)
    ]


def test_monthly_input_week_headers_and_chronological_days():
    """跨两周的月份：输出带周节标题，周内按日历序。"""
    # 2026-09-07 周一、09-08 周二 → 第1周；09-14 周一 → 第2周
    messages = _month_msgs(7, 2) + _month_msgs(8, 2) + _month_msgs(14, 2)

    text, stats = build_monthly_chat_input(messages, local_tz=TZ, target_chars=50_000)

    assert stats.weeks == 2
    assert stats.days_full == 3
    assert text.splitlines()[0].startswith("【第1周 09-07–09-08】")
    assert "【09-07 周一】" in text
    assert "【09-08 周二】" in text
    assert "【第2周 09-14–09-14】" in text
    assert "【09-14 周一】" in text
    # 周内日历序：09-07 在 09-08 之前
    assert text.index("【09-07") < text.index("【09-08")


def test_monthly_input_quiet_days_kept_full_under_tight_budget():
    """预算偏紧时平静日仍整日保留，活跃日竞争剩余预算。"""
    quiet = _month_msgs(7, 2)          # 小体量
    busy = _month_msgs(8, 40)          # 大体量
    messages = quiet + busy

    # 给足能装下平静日、但装不下整日活跃日的预算
    full_text, full_stats = serialize_period_chat(messages, local_tz=TZ)
    budget = len(full_text) // 2
    text, stats = build_monthly_chat_input(messages, local_tz=TZ, target_chars=budget)

    assert stats.chars <= budget
    assert stats.days_full >= 1  # 平静日整日保留
    assert "【09-07 周一】" in text
    # 活跃日要么整日/抽稀进入，消息量应显著少于全量
    assert stats.messages_selected < full_stats.messages_in


def test_monthly_input_empty():
    text, stats = build_monthly_chat_input([], local_tz=TZ)

    assert text == ""
    assert stats.messages_in == 0
    assert stats.weeks == 0


def test_monthly_input_deterministic():
    messages = _month_msgs(7, 15) + _month_msgs(8, 30) + _month_msgs(9, 5)
    budget = 2_000

    text_a, stats_a = build_monthly_chat_input(messages, local_tz=TZ, target_chars=budget)
    text_b, stats_b = build_monthly_chat_input(messages, local_tz=TZ, target_chars=budget)

    assert text_a == text_b
    assert stats_a == stats_b
