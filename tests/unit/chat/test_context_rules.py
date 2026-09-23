from __future__ import annotations

import re

import pytest

from quickquip.chat import context_rules
from quickquip.chat.config import CONTEXT_REPLY_RULES
from quickquip.chat.context_rules import (
    _LLM_JUDGE_CACHE,
    _check_regex_context,
    match_context_rule,
)


@pytest.fixture(autouse=True)
def _isolate_context_rules():
    original = list(CONTEXT_REPLY_RULES)
    CONTEXT_REPLY_RULES[:] = [
        {
            "name": "utest_regex_context",
            "type": "regex_context",
            "patterns": ["触发"],
            "context_conditions": ["请假"],
            "reply_template": "{sender_name}",
        },
        {
            "name": "utest_llm_context",
            "type": "llm_context",
            "patterns": ["判断"],
            "reply_template": "{sender_name}",
        },
    ]
    _LLM_JUDGE_CACHE.clear()
    try:
        context_rules.recompile_patterns()
        yield
    finally:
        CONTEXT_REPLY_RULES[:] = original
        context_rules.recompile_patterns()
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


async def test_regex_context_rule_end_to_end(frozen_now):
    history_hit = [{"text": "我想请假一天", "sender_name": "张三"}]
    hit = await match_context_rule(
        text="触发",
        user_id=1,
        sender_name="李四",
        recent_messages=history_hit,
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert hit is not None
    assert hit["rule_name"] == "utest_regex_context"
    assert hit["reply"] == "李四"

    history_miss = [{"text": "今天吃啥", "sender_name": "张三"}]
    miss = await match_context_rule(
        text="触发",
        user_id=1,
        sender_name="李四",
        recent_messages=history_miss,
        now=frozen_now,
        llm_service=None,
        group_id=12345,
    )
    assert miss is None


async def test_llm_context_skipped_without_service(frozen_now):
    result = await match_context_rule(
        text="判断",
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


class _StubJudgeService:
    """quick_judge_detailed 的最小 stub。"""

    def __init__(self, judge):
        self._judge = judge
        self.calls: list[tuple] = []

    async def quick_judge_detailed(self, prompt, max_tokens=None):
        self.calls.append((prompt, max_tokens))
        return self._judge


def _qj(text: str, outcome: str = "ok", **kwargs):
    from quickquip.llm.quick_judge import QuickJudgeResult

    return QuickJudgeResult(text=text, outcome=outcome, provider_id="p", model="m", **kwargs)


async def test_llm_context_ok_verdict_triggers(frozen_now):
    service = _StubJudgeService(_qj('{"trigger": true}'))
    result = await match_context_rule(
        text="判断",
        user_id=1,
        sender_name="李四",
        recent_messages=[{"text": "他过江了", "sender_name": "张三"}],
        now=frozen_now,
        llm_service=service,
        group_id=12345,
    )
    assert result is not None
    assert result["rule_name"] == "utest_llm_context"
    # 判定预算不在调用方写死，缺省交由 [triggers.quick_judge] 配置决定
    assert service.calls and service.calls[0][1] is None


async def test_llm_context_length_outcome_fails_closed_quietly(frozen_now, caplog):
    import logging

    service = _StubJudgeService(_qj("", outcome="length", finish_reason="length"))
    with caplog.at_level(logging.DEBUG):
        result = await match_context_rule(
            text="判断",
            user_id=1,
            sender_name="李四",
            recent_messages=[{"text": "他过江了", "sender_name": "张三"}],
            now=frozen_now,
            llm_service=service,
            group_id=23456,
        )
    assert result is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
