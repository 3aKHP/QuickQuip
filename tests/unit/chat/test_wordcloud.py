from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quickquip.chat.wordcloud import WordCloudCollector, build_word_frequencies


HAS_JIEBA = importlib.util.find_spec("jieba") is not None
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def test_collector_rejects_non_numeric_group_id(tmp_path: Path):
    c = WordCloudCollector(base_dir=tmp_path / "wc")
    with pytest.raises(ValueError):
        c.record("not-a-number", "n", "hello")


def test_collector_round_trip(tmp_path: Path):
    c = WordCloudCollector(base_dir=tmp_path / "wc")
    group_id = "10001"
    base = datetime(2026, 4, 15, 9, 0, tzinfo=LOCAL_TZ).timestamp()
    texts = [
        (base, "张三", "今天启动原神"),
        (base + 60, "李四", "原神启动了"),
        (base + 120, "王五", "启动失败"),
    ]
    for ts, sender, text in texts:
        c.record(group_id, sender, text, ts=ts)

    window = c.read_window(group_id, start_ts=base - 1, end_ts=base + 600)
    assert len(window) == 3
    assert [m["text"] for m in window] == ["今天启动原神", "原神启动了", "启动失败"]


def test_collector_skips_blank(tmp_path: Path):
    c = WordCloudCollector(base_dir=tmp_path / "wc")
    c.record("1", "n", "   ")
    window = c.read_window("1", start_ts=0, end_ts=10_000_000_000)
    assert window == []


def test_collector_window_filter(tmp_path: Path):
    c = WordCloudCollector(base_dir=tmp_path / "wc")
    base = datetime(2026, 4, 15, 9, 0, tzinfo=LOCAL_TZ).timestamp()
    c.record("1", "n", "old", ts=base)
    c.record("1", "n", "new", ts=base + 3600)
    window = c.read_window("1", start_ts=base + 1800, end_ts=base + 7200)
    assert [m["text"] for m in window] == ["new"]


@pytest.mark.skipif(not HAS_JIEBA, reason="jieba not installed")
def test_build_word_frequencies_basic():
    messages = [
        {"text": "启动原神启动"},
        {"text": "原神是个好游戏"},
    ]
    freq = build_word_frequencies(messages, stopwords=frozenset({"是", "的"}))
    assert freq.get("原神", 0) >= 2
    assert freq.get("启动", 0) >= 2
    # single-char words excluded
    assert "是" not in freq


@pytest.mark.skipif(not HAS_JIEBA, reason="jieba not installed")
def test_build_word_frequencies_strips_bracketed_segments():
    messages = [{"text": "[图片] 这是文本内容 [CQ:at,qq=1]"}]
    freq = build_word_frequencies(messages, stopwords=frozenset())
    # 方括号段被剥离，不应作为词出现
    assert "图片" not in freq
    assert "CQ" not in freq


@pytest.mark.skipif(not HAS_JIEBA, reason="jieba not installed")
def test_build_word_frequencies_strips_qq_mention_placeholder():
    messages = [
        {"text": "@QQ123456789 今天天气不错"},
        {"text": "@QQ987654321 出来聊聊"},
        {"text": "@QQ 兜底占位"},
    ]
    freq = build_word_frequencies(messages, stopwords=frozenset())
    # 未登记成员的 @QQ<digits> 占位符（含裸 @QQ 边界）被清洗，明文 QQ 号不得进入词频
    assert all("123456789" not in word and "987654321" not in word for word in freq)
    assert not any(word.startswith("QQ") for word in freq)


@pytest.mark.skipif(not HAS_JIEBA, reason="jieba not installed")
def test_build_word_frequencies_keeps_registered_name_mentions():
    messages = [{"text": "@镜子 今天天气不错"}]
    freq = build_word_frequencies(messages, stopwords=frozenset())
    # 已登记成员的 @<规范名> 是正常社交信号，保留进词频
    assert freq.get("镜子", 0) >= 1
