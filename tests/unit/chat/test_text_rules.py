from __future__ import annotations

import random

import pytest

from quickquip.chat import config as chat_config
from quickquip.chat import text_rules as text_rules_module
from quickquip.chat.text_rules import match_text_rule, select_reply_template

# 合成规则集：引擎语义（正则匹配、别名、优先级仲裁、模板替换、捕获组黑名单）
# 是本文件的测试契约；部署在 config/chat_rules.toml 里的梗文案是配置数据，
# 部署者自定义后不应让引擎测试变红。合成规则的 rate_limit_key 均不对应真实
# 限流桶，走 resolve_probability 的默认 1.0（命中必回），保证测试确定性。
SYNTHETIC_RULES: list[dict] = [
    # 字面触发词 + 别名 pattern；模板替换 {current_time} 与 @{sender_name}
    {
        "name": "utest_arrival",
        "patterns": ["灵光一闪", "驾到"],
        "reply_template": "{current_time} @{sender_name} 灵光乍现",
        "rate_limit_key": "utest_arrival_bucket",
        "priority": 100,
    },
    # 命名捕获组 → {target} 模板变量
    {
        "name": "utest_play_target",
        "patterns": ["玩(?P<target>.+?)玩的"],
        "reply_template": "别再玩{target}了",
        "rate_limit_key": "utest_play_bucket",
        "priority": 85,
    },
    # 与 utest_priority_high 重叠，用于优先级仲裁
    {
        "name": "utest_priority_low",
        "patterns": ["^(.+?)，出炉！$"],
        "reply_template": "$1出炉啦",
        "priority": 95,
    },
    # 叠字句式：位置捕获组 $1 替换；不写 rate_limit_key，验证默认回落为规则名
    # （raw string：\1 需原样传给正则引擎，与 TOML 字面量字符串语义一致）
    {
        "name": "utest_double_char",
        "patterns": [r"^([一-龥])(\1)你的$"],
        "reply_template": "叠字是$1",
        "priority": 80,
    },
    # 首尾同字夹内容：反向引用 + $2 位置捕获组替换
    {
        "name": "utest_sandwich",
        "patterns": [r"^([一-龥])(.{2,})\1的$"],
        "reply_template": "夹在中间的是$2",
        "priority": 75,
    },
    # 多 pattern 或关系；锚定句式天然排除第二人称（"你中意…"不命中任何 pattern）
    {
        "name": "utest_like",
        "patterns": ["^我中意(.+)$", "^中意(.+)$"],
        "reply_template": "还在$1",
        "priority": 60,
    },
    # 命名捕获组黑名单（blocked_named_groups）：动词命中黑名单时不触发
    {
        "name": "utest_i_do",
        "patterns": ["^我(?P<verb>[一-龥]{2})[！!。，,？?]*$"],
        "reply_template": "不许$1",
        "priority": 20,
        "blocked_named_groups": {"verb": ["知道", "觉得", "明白"]},
    },
    # 高优先级字面规则：与 utest_priority_low 同时命中时应胜出
    {
        "name": "utest_priority_high",
        "patterns": ["蜜糖"],
        "reply_template": "甜",
        "priority": 100,
    },
]


@pytest.fixture
def synthetic_rules():
    """用合成规则替换部署配置加载态，测试结束后恢复并重编译正则。

    仿照 test_config_reload.py 的 restore_chat_rules：_COMPILED_PATTERNS 是
    模块级全局状态，必须成对保存/恢复，避免污染同目录其他测试模块。
    """
    snapshot = list(chat_config.TEXT_REPLY_RULES)
    chat_config.TEXT_REPLY_RULES[:] = SYNTHETIC_RULES
    text_rules_module.recompile_patterns()
    try:
        yield
    finally:
        chat_config.TEXT_REPLY_RULES[:] = snapshot
        text_rules_module.recompile_patterns()


def test_literal_trigger_renders_time_and_nickname(synthetic_rules, frozen_now):
    result = match_text_rule("灵光一闪", user_id=123456, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_arrival"
    # rate_limit_key 透传规则配置值
    assert result["rate_limit_key"] == "utest_arrival_bucket"
    # 模板引擎契约：{current_time} 与 @{sender_name} 由事件上下文渲染
    assert result["reply"] == "2026-03-16 09:19 @测试用户 灵光乍现"


def test_alias_pattern_matches_same_rule(synthetic_rules, frozen_now):
    result = match_text_rule("他要驾到了吗", user_id=123456, sender_name="测试用户", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_arrival"
    assert result["reply"] == "2026-03-16 09:19 @测试用户 灵光乍现"


def test_regex_named_group_renders_into_template(synthetic_rules, frozen_now):
    result = match_text_rule("玩魔方玩的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_play_target"
    assert result["rate_limit_key"] == "utest_play_bucket"
    assert result["reply"] == "别再玩魔方了"


def test_priority_high_rule_wins_over_overlapping_low(synthetic_rules, frozen_now):
    # 「蜜糖，出炉！」同时命中 utest_priority_high（100）与 utest_priority_low（95）
    result = match_text_rule("蜜糖，出炉！", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_priority_high"
    assert result["priority"] == 100


def test_priority_low_rule_matches_alone(synthetic_rules, frozen_now):
    result = match_text_rule("面包，出炉！", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_priority_low"
    assert result["priority"] == 95


def test_positional_group_substitution(synthetic_rules, frozen_now):
    result = match_text_rule("团团你的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_double_char"
    assert result["reply"] == "叠字是团"
    # 未配置 rate_limit_key 时回落为规则名
    assert result["rate_limit_key"] == "utest_double_char"


def test_backreference_and_second_positional_group(synthetic_rules, frozen_now):
    result = match_text_rule("辣火锅辣的", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "utest_sandwich"
    assert result["reply"] == "夹在中间的是火锅"


def test_anchored_patterns_exclude_second_person(synthetic_rules, frozen_now):
    hit = match_text_rule("我中意叉烧", user_id=1, sender_name="n", now=frozen_now)
    assert hit is not None
    assert hit["rule_name"] == "utest_like"
    assert hit["reply"].startswith("还在")
    # 第二人称不应触发（锚定句式排除，属 pattern 级语义而非引擎代码）
    assert match_text_rule("你中意叉烧", user_id=1, sender_name="n", now=frozen_now) is None


def test_blocked_named_groups_filter_verbs(synthetic_rules, frozen_now):
    hit = match_text_rule("我鼓掌", user_id=1, sender_name="n", now=frozen_now)
    assert hit is not None
    assert hit["rule_name"] == "utest_i_do"
    assert hit["reply"] == "不许鼓掌"
    # 捕获组命中黑名单时不触发（引擎级 is_rule_match_allowed 过滤）
    assert match_text_rule("我知道", user_id=1, sender_name="n", now=frozen_now) is None
    assert match_text_rule("我觉得", user_id=1, sender_name="n", now=frozen_now) is None


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
