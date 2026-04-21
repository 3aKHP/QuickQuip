from __future__ import annotations

import random

from quickquip.chat.text_rules import match_text_rule, select_reply_template


def test_match_divine_arrival_uses_nickname(frozen_now):
    result = match_text_rule("神临", user_id=123456, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "divine_arrival"
    assert result["rate_limit_key"] == "divine_arrival"
    assert result["reply"] == "2026-03-16 09:19，@测试用户 区从天降"


def test_match_divine_arrival_alias(frozen_now):
    result = match_text_rule("他要降临了吗", user_id=123456, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["reply"] == "2026-03-16 09:19，@测试用户 区从天降"


def test_match_regex_play_target(frozen_now):
    result = match_text_rule("玩原神玩的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "play_target"
    assert result["rate_limit_key"] == "play_target"
    assert result["reply"] == "原神怎么你了"


def test_priority_divine_over_play_target(frozen_now):
    result = match_text_rule("神临，启动！", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "divine_arrival"
    assert result["priority"] == 100


def test_priority_district_high(frozen_now):
    result = match_text_rule("区来了，启动！", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["priority"] > 90


def test_double_char_ni_de(frozen_now):
    result = match_text_rule("牛牛你的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "double_char_ni_de"
    assert result["reply"] == "牛牛魔"


def test_sandwich_de(frozen_now):
    result = match_text_rule("冰红茶冰的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "sandwich_de"
    assert result["reply"] == "红茶怎么你了！"


def test_like_reply(frozen_now):
    hit = match_text_rule("我喜欢苹果", user_id=1, sender_name="n", now=frozen_now)
    assert hit is not None
    assert hit["rule_name"] == "like_reply"
    assert hit["reply"].startswith("还在")
    # 第二人称不应触发
    assert match_text_rule("你喜欢苹果", user_id=1, sender_name="n", now=frozen_now) is None


def test_i_do_requires_action_verb(frozen_now):
    hit = match_text_rule("我闭嘴", user_id=1, sender_name="n", now=frozen_now)
    assert hit is not None
    assert hit["rule_name"] == "i_do"
    assert hit["reply"] == "不准闭嘴"
    assert match_text_rule("我知道", user_id=1, sender_name="n", now=frozen_now) is None
    assert match_text_rule("我觉得", user_id=1, sender_name="n", now=frozen_now) is None


def test_select_reply_template_single():
    assert select_reply_template({"reply_template": "固定回复"}) == "固定回复"


def test_select_reply_template_multi(rng, monkeypatch):
    # Use a local Random so global state isn't polluted
    monkeypatch.setattr(random, "random", rng.random)
    monkeypatch.setattr(random, "choices", rng.choices)
    multi = {
        "reply_templates": [
            {"template": "A", "weight": 1},
            {"template": "B", "weight": 1},
            {"template": "C", "weight": 1},
        ]
    }
    results = {select_reply_template(multi) for _ in range(50)}
    assert results == {"A", "B", "C"}


def test_select_reply_template_weighted_skew(monkeypatch):
    local = random.Random(0)
    monkeypatch.setattr(random, "random", local.random)
    monkeypatch.setattr(random, "choices", local.choices)
    rule = {
        "reply_templates": [
            {"template": "常见", "weight": 100},
            {"template": "罕见", "weight": 1},
        ]
    }
    hits = [select_reply_template(rule) for _ in range(200)]
    assert hits.count("常见") > 180


def test_reply_templates_takes_precedence():
    rule = {
        "reply_template": "不该被选",
        "reply_templates": [{"template": "应该被选", "weight": 1}],
    }
    assert select_reply_template(rule) == "应该被选"
