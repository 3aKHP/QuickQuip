from __future__ import annotations

import importlib.util

import pytest

from quickquip.chat.wordcloud import build_word_frequencies


HAS_JIEBA = importlib.util.find_spec("jieba") is not None


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
