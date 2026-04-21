from __future__ import annotations

import re

import pytest

from quickquip.chat.config import CONTEXT_REPLY_RULES
from quickquip.chat.context_rules import (
    _LLM_JUDGE_CACHE,
    _check_regex_context,
    match_context_rule,
)


@pytest.fixture(autouse=True)
def _clear_llm_judge_cache():
    _LLM_JUDGE_CACHE.clear()
    yield
    _LLM_JUDGE_CACHE.clear()


def test_empty_conditions_dont_pass():
    assert _check_regex_context([], [{"text": "任意"}], context_window=5) is False


def test_conditions_hit_and_miss():
    cond = [re.compile("请假|调休")]
    assert _check_regex_context(
        cond, [{"text": "我想请假一天"}, {"text": "其他无关"}], context_window=5
    ) is True
    assert _check_regex_context(
        cond, [{"text": "今天天气不错"}, {"text": "吃饭了吗"}], context_window=5
    ) is False


def test_context_window_truncates_old_messages():
    cond = [re.compile("请假|调休")]
    # 命中只出现在窗口外
    assert _check_regex_context(
        cond,
        [{"text": "我想请假"}, {"text": "x"}, {"text": "y"}, {"text": "z"}],
        context_window=2,
    ) is False


@pytest.mark.skipif(
    not any(rule.get("name") == "ntk_jingranbuxu" for rule in CONTEXT_REPLY_RULES),
    reason="ntk_jingranbuxu rule not present in current chat_rules config",
)
async def test_regex_context_rule_end_to_end(frozen_now):
    history_hit = [{"text": "我想请假一天", "sender_name": "张三"}]
    hit = await match_context_rule(
        text="竟然不许",
        user_id=1,
        sender_name="李四",
        recent_messages=history_hit,
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert hit is not None
    assert hit["rule_name"] == "ntk_jingranbuxu"
    assert hit["reply"] == "竟然不许！？"

    history_miss = [{"text": "今天吃啥", "sender_name": "张三"}]
    miss = await match_context_rule(
        text="竟然不许",
        user_id=1,
        sender_name="李四",
        recent_messages=history_miss,
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert miss is None


@pytest.mark.skipif(
    not any(
        rule.get("name") == "ntk_haoa" and rule.get("type") == "llm_context"
        for rule in CONTEXT_REPLY_RULES
    ),
    reason="ntk_haoa llm_context rule not present",
)
async def test_llm_context_skipped_without_service(frozen_now):
    result = await match_context_rule(
        text="好啊",
        user_id=1,
        sender_name="李四",
        recent_messages=[{"text": "他过江了", "sender_name": "张三"}],
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert result is None


async def test_no_pattern_match_returns_none(frozen_now):
    result = await match_context_rule(
        text="今天天气不错",
        user_id=1,
        sender_name="李四",
        recent_messages=[{"text": "我想请假"}],
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert result is None
