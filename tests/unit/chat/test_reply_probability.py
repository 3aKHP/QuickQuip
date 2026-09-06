from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from quickquip.chat import config as chat_config
from quickquip.chat import context_rules as context_rules_module
from quickquip.chat import reply_probability as reply_probability_module
from quickquip.chat import text_rules as text_rules_module
from quickquip.chat.context_rules import match_context_rule
from quickquip.chat.reply_probability import (
    PROBABILITY_CHECKED,
    resolve_probability,
    roll_reply,
)
from quickquip.chat.text_rules import match_text_rule


@pytest.fixture(autouse=True)
def _clean_roll_state():
    reply_probability_module.reset_state()
    yield
    reply_probability_module.reset_state()


@contextmanager
def _chdir(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


@pytest.fixture
def restore_chat_rules():
    """Snapshot + restore module-level chat rule state so tests stay isolated."""
    text_snapshot = list(chat_config.TEXT_REPLY_RULES)
    ctx_snapshot = list(chat_config.CONTEXT_REPLY_RULES)
    rate_snapshot = dict(chat_config.RATE_LIMIT_RULES)
    try:
        yield
    finally:
        chat_config.TEXT_REPLY_RULES[:] = text_snapshot
        chat_config.CONTEXT_REPLY_RULES[:] = ctx_snapshot
        chat_config.RATE_LIMIT_RULES.clear()
        chat_config.RATE_LIMIT_RULES.update(rate_snapshot)
        text_rules_module.recompile_patterns()
        context_rules_module.recompile_patterns()


def _install_rules(rules: list[dict], context_rules: list[dict] | None = None):
    chat_config.TEXT_REPLY_RULES[:] = rules
    chat_config.CONTEXT_REPLY_RULES[:] = context_rules or []
    text_rules_module.recompile_patterns()
    context_rules_module.recompile_patterns()


# ── 概率解析顺序 ──────────────────────────────────────────────


def test_resolve_defaults_to_always_reply(restore_chat_rules):
    chat_config.RATE_LIMIT_RULES.pop("no_prob_key", None)
    assert resolve_probability("no_prob_key") == 1.0
    assert resolve_probability("no_prob_key", {"name": "x"}) == 1.0


def test_key_level_probability_used_as_fallback(restore_chat_rules):
    chat_config.RATE_LIMIT_RULES["prob_key"] = {"global_limit": 1, "user_limit": 1, "probability": 0.25}
    assert resolve_probability("prob_key") == 0.25
    assert resolve_probability("prob_key", {"name": "x"}) == 0.25


def test_rule_level_overrides_key_level(restore_chat_rules):
    chat_config.RATE_LIMIT_RULES["prob_key"] = {"global_limit": 1, "user_limit": 1, "probability": 0.25}
    rule = {"name": "x", "probability": 0.75}
    assert resolve_probability("prob_key", rule) == 0.75


# ── 掷骰语义 ──────────────────────────────────────────────────


def test_roll_always_true_at_full_probability(monkeypatch):
    consumed = []

    def _random():
        consumed.append(1)
        raise AssertionError("p=1 不应消耗随机数")

    monkeypatch.setattr("quickquip.chat.reply_probability.random.random", _random)
    assert roll_reply("any_key") is True
    assert consumed == []


def test_roll_never_true_at_zero_probability(monkeypatch):
    monkeypatch.setattr("quickquip.chat.reply_probability.random.random", lambda: 0.999999)
    assert roll_reply("zero_key", {"probability": 0.0}) is False


def test_roll_boundaries(monkeypatch):
    # random() ∈ [0, 1)：严格小于 p 才通过
    monkeypatch.setattr("quickquip.chat.reply_probability.random.random", lambda: 0.49)
    assert roll_reply("half_key", {"probability": 0.5}) is True
    monkeypatch.setattr("quickquip.chat.reply_probability.random.random", lambda: 0.5)
    assert roll_reply("half_key", {"probability": 0.5}) is False


# ── 载入归一化 ────────────────────────────────────────────────


def test_reload_normalizes_probability(tmp_path: Path, restore_chat_rules):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "chat_rules.toml").write_text(
        """
[[rules]]
name = "p_rule"
patterns = ["x"]
reply_template = "y"
probability = 0.5

[[rules]]
name = "clamp_rule"
patterns = ["x"]
reply_template = "y"
probability = 1.7

[[rules]]
name = "bad_rule"
patterns = ["x"]
reply_template = "y"
probability = "多半"

[rate_limit_rules.p_bucket]
global_limit = 1
user_limit = 1
probability = 0.25
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        assert chat_config.reload_chat_rules() is True

    by_name = {r["name"]: r for r in chat_config.TEXT_REPLY_RULES}
    assert by_name["p_rule"]["probability"] == 0.5
    assert by_name["clamp_rule"]["probability"] == 1.0
    assert "probability" not in by_name["bad_rule"]
    assert chat_config.RATE_LIMIT_RULES["p_bucket"]["probability"] == 0.25


# ── 文本规则匹配器内掷骰 ─────────────────────────────────────


def test_silenced_high_priority_rule_lets_fallback_win(restore_chat_rules, frozen_now):
    _install_rules(
        [
            {
                "name": "prob_high",
                "patterns": ["你好"],
                "reply_template": "高位回复",
                "priority": 100,
                "probability": 0.0,
            },
            {
                "name": "prob_low",
                "patterns": ["你好"],
                "reply_template": "低位回复",
                "priority": 10,
            },
        ]
    )
    result = match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "prob_low"
    assert result[PROBABILITY_CHECKED] is True


def test_rule_level_probability_beats_key_level_in_matcher(
    restore_chat_rules, frozen_now
):
    chat_config.RATE_LIMIT_RULES["shared_bucket"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 0.0,
    }
    _install_rules(
        [
            {
                "name": "escape_rule",
                "patterns": ["你好"],
                "reply_template": "回复",
                "rate_limit_key": "shared_bucket",
                "probability": 1.0,
            }
        ]
    )
    result = match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rule_name"] == "escape_rule"


def test_key_level_probability_silences_rule(restore_chat_rules, frozen_now):
    chat_config.RATE_LIMIT_RULES["silent_bucket"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 0.0,
    }
    _install_rules(
        [
            {
                "name": "quiet_rule",
                "patterns": ["你好"],
                "reply_template": "回复",
                "rate_limit_key": "silent_bucket",
            }
        ]
    )
    assert match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now) is None


# ── 语境规则：掷骰先于 LLM 判定 ───────────────────────────────


class _CountingJudge:
    def __init__(self, trigger: bool = True):
        self.calls = 0
        self._trigger = trigger

    async def quick_judge(self, prompt: str, max_tokens: int = 64) -> str:
        self.calls += 1
        return '{"trigger": true}' if self._trigger else '{"trigger": false}'


async def test_context_rule_skips_llm_when_roll_fails(restore_chat_rules, frozen_now):
    context_rules_module._LLM_JUDGE_CACHE.clear()
    _install_rules(
        [],
        [
            {
                "name": "llm_ctx",
                "type": "llm_context",
                "patterns": ["竟然不许"],
                "reply_template": "竟然不许！？",
                "context_window": 5,
                "probability": 0.0,
            }
        ],
    )
    judge = _CountingJudge()
    result = await match_context_rule(
        text="竟然不许",
        user_id=1,
        sender_name="n",
        recent_messages=[{"text": "我想请假", "sender_name": "张三"}],
        now=frozen_now,
        llm_service=judge,
        group_id=123,
    )
    assert result is None
    assert judge.calls == 0


async def test_context_rule_passes_when_roll_wins(restore_chat_rules, frozen_now):
    context_rules_module._LLM_JUDGE_CACHE.clear()
    _install_rules(
        [],
        [
            {
                "name": "llm_ctx",
                "type": "llm_context",
                "patterns": ["竟然不许"],
                "reply_template": "竟然不许！？",
                "context_window": 5,
            }
        ],
    )
    judge = _CountingJudge()
    result = await match_context_rule(
        text="竟然不许",
        user_id=1,
        sender_name="n",
        recent_messages=[{"text": "我想请假", "sender_name": "张三"}],
        now=frozen_now,
        llm_service=judge,
        group_id=123,
    )
    assert result is not None
    assert result[PROBABILITY_CHECKED] is True
    assert judge.calls == 1
    context_rules_module._LLM_JUDGE_CACHE.clear()


# ── resolve_reply 出口闸口（时区等内置路径走桶级概率）────────


async def test_resolve_reply_exit_gate_blocks_timezone(restore_chat_rules, frozen_now):
    from quickquip.app.message_pipeline import resolve_reply

    chat_config.RATE_LIMIT_RULES["timezone_wake"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 0.0,
    }
    result = await resolve_reply("早安", user_id=1, sender_name="n", now=frozen_now)
    assert result is None


async def test_resolve_reply_exit_gate_allows_timezone_by_default(
    restore_chat_rules, frozen_now
):
    from quickquip.app.message_pipeline import resolve_reply

    result = await resolve_reply("早安", user_id=1, sender_name="n", now=frozen_now)
    assert result is not None
    assert result["rate_limit_key"] == "timezone_wake"


# ── 防连发（suppress_after_hit）──────────────────────────────


def test_suppress_after_hit_forces_one_silent(restore_chat_rules, monkeypatch):
    chat_config.RATE_LIMIT_RULES["burst_key"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 1.0,
        "suppress_after_hit": 1,
    }
    monkeypatch.setattr(
        "quickquip.chat.reply_probability.random.random",
        lambda: (_ for _ in ()).throw(AssertionError("压制段不应消耗随机数")),
    )
    # 第一次命中（p=1 短路，不消耗随机数）
    assert roll_reply("burst_key", group_id=1) is True
    # 命中后的下一次被防连发强制沉默，同样不消耗随机数
    assert roll_reply("burst_key", group_id=1) is False
    # 压制消耗完毕，p=1 恢复必中
    assert roll_reply("burst_key", group_id=1) is True


def test_suppress_state_isolated_per_group_and_identity(restore_chat_rules):
    chat_config.RATE_LIMIT_RULES["burst_key"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 1.0,
        "suppress_after_hit": 1,
    }
    assert roll_reply("burst_key", identity="rule_a", group_id=1) is True
    # 同群同身份被压制
    assert roll_reply("burst_key", identity="rule_a", group_id=1) is False
    # 同群不同身份不受影响（同一桶下各规则独立）
    assert roll_reply("burst_key", identity="rule_b", group_id=1) is True
    # 不同群完全独立
    assert roll_reply("burst_key", identity="rule_a", group_id=2) is True


# ── 保底（pity_step）─────────────────────────────────────────


def test_pity_step_raises_probability_until_hit(restore_chat_rules, monkeypatch):
    chat_config.RATE_LIMIT_RULES["pity_key"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 0.5,
        "pity_step": 0.2,
    }
    monkeypatch.setattr(
        "quickquip.chat.reply_probability.random.random", lambda: 0.9
    )
    # p_eff 依次 0.5 / 0.6 / 0.7 / 0.8 / 0.9，全部不敌 0.9 → 连哑
    for _ in range(5):
        assert roll_reply("pity_key", group_id=1) is False
    # 第 6 次 p_eff = 0.5 × (1 + 5 × 0.2) = 1.5 → 封顶 1.0，强制命中
    assert roll_reply("pity_key", group_id=1) is True
    # 命中后连哑清零
    assert reply_probability_module._ROLL_STATE[("pity_key", "1")]["miss_streak"] == 0


def test_suppressed_rolls_do_not_count_toward_pity(
    restore_chat_rules, monkeypatch
):
    chat_config.RATE_LIMIT_RULES["mixed_key"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 0.5,
        "suppress_after_hit": 1,
        "pity_step": 0.5,
    }
    monkeypatch.setattr(
        "quickquip.chat.reply_probability.random.random", lambda: 0.4
    )
    assert roll_reply("mixed_key", group_id=1) is True  # streak=0, suppress=1
    # 被压制的这一次不计入连哑
    assert roll_reply("mixed_key", group_id=1) is False
    monkeypatch.setattr(
        "quickquip.chat.reply_probability.random.random", lambda: 0.6
    )
    # streak 仍为 0 → p_eff = 0.5 → 0.6 不中小于 0.5 → 未中；
    # 若被错误计入连哑，p_eff = 0.75 → 0.6 < 0.75 会命中
    assert roll_reply("mixed_key", group_id=1) is False


def test_no_state_tracked_without_opt_in(restore_chat_rules):
    chat_config.RATE_LIMIT_RULES["plain_key"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 1.0,
    }
    for _ in range(3):
        assert roll_reply("plain_key", group_id=1) is True
    assert ("plain_key", "1") not in reply_probability_module._ROLL_STATE


# ── 防连发/保底字段的载入归一化 ─────────────────────────────


def test_reload_normalizes_streak_knobs(tmp_path: Path, restore_chat_rules):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "chat_rules.toml").write_text(
        """
[rate_limit_rules.knob_bucket]
global_limit = 1
user_limit = 1
suppress_after_hit = 2
pity_step = 0.25

[rate_limit_rules.bad_int]
global_limit = 1
user_limit = 1
suppress_after_hit = -1

[rate_limit_rules.bad_type]
global_limit = 1
user_limit = 1
suppress_after_hit = "两次"
pity_step = "很多"
""",
        encoding="utf-8",
    )
    with _chdir(tmp_path):
        assert chat_config.reload_chat_rules() is True

    assert chat_config.RATE_LIMIT_RULES["knob_bucket"]["suppress_after_hit"] == 2
    assert chat_config.RATE_LIMIT_RULES["knob_bucket"]["pity_step"] == 0.25
    # 非法/关闭值不落字段，条目保持干净
    assert "suppress_after_hit" not in chat_config.RATE_LIMIT_RULES["bad_int"]
    assert "suppress_after_hit" not in chat_config.RATE_LIMIT_RULES["bad_type"]
    assert "pity_step" not in chat_config.RATE_LIMIT_RULES["bad_type"]


# ── 文本规则匹配器：按群隔离的防连发 ─────────────────────────


def test_matcher_suppress_scoped_per_group(restore_chat_rules, frozen_now):
    chat_config.RATE_LIMIT_RULES["matcher_bucket"] = {
        "global_limit": 9,
        "user_limit": 9,
        "probability": 1.0,
        "suppress_after_hit": 1,
    }
    _install_rules(
        [
            {
                "name": "burst_rule",
                "patterns": ["你好"],
                "reply_template": "回复",
                "rate_limit_key": "matcher_bucket",
            }
        ]
    )
    assert match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now, group_id=1001) is not None
    # 同群第二次被防连发压制 → 无候选规则
    assert match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now, group_id=1001) is None
    # 另一个群不受影响
    assert match_text_rule("你好", user_id=1, sender_name="n", now=frozen_now, group_id=1002) is not None
