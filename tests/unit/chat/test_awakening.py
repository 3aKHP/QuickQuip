from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


from quickquip.chat.awakening import (
    AwakeningConfig,
    AwakeningDefaults,
    AwakeningGroupOverride,
    AwakeningState,
    AwakeningTriggerResult,
    BotMessageCache,
    ResolvedAwakeningSettings,
    _QA_FAST_PATTERNS,
    _RULE_BOREDOM,
    _RULE_EXTEND,
    _RULE_FALLBACK,
    _RULE_INTEREST,
    _RULE_QA,
    _RULE_RELEVANCE,
    _extract_json_trigger,
    _extract_words,
    _is_extend_eligible_message,
    _is_in_dnd_window,
    _llm_cache_text,
    _word_overlap_ratio,
    allows_recent_images,
    build_awakening_prompt,
    build_passive_trigger_raw_user_text,
    check_awakening_triggers,
    check_boredom,
    check_extend,
    check_fallback,
    check_interest,
    check_qa,
    check_relevance,
    load_awakening_config,
    run_boredom_check,
    select_passive_trigger_image_urls,
)


# =========================================================================
# Recent-image gating
# =========================================================================


def test_allows_recent_images_rules():
    assert allows_recent_images(_RULE_BOREDOM) is True
    assert allows_recent_images(_RULE_EXTEND) is True
    assert allows_recent_images(_RULE_INTEREST) is True
    assert allows_recent_images(_RULE_RELEVANCE) is True
    assert allows_recent_images(_RULE_QA) is True
    assert allows_recent_images(_RULE_FALLBACK) is False
    assert allows_recent_images("explicit_llm") is False
    assert allows_recent_images("llm_chat") is False


# =========================================================================
# Config loading
# =========================================================================


class TestAwakeningDefaults:
    def test_from_dict_none(self):
        d = AwakeningDefaults.from_dict(None)
        assert d.extend_duration == 0
        assert d.relevance_threshold == 1.0
        assert d.qa_threshold == 1.0

    def test_from_dict_with_values(self):
        d = AwakeningDefaults.from_dict({
            "extend_duration": 10,
            "relevance_threshold": 0.5,
            "qa_threshold": 0.88,
            "interest_topics": ["a", "b"],
        })
        assert d.extend_duration == 10
        assert d.relevance_threshold == 0.5
        assert d.qa_threshold == 0.88
        assert d.interest_topics == ["a", "b"]

    def test_from_dict_ignores_unknown_keys(self):
        d = AwakeningDefaults.from_dict({"unknown_key": 42, "extend_duration": 5})
        assert d.extend_duration == 5
        assert not hasattr(d, "unknown_key")

    def test_from_dict_strips_empty_topics(self):
        d = AwakeningDefaults.from_dict({"interest_topics": ["a", "", "  ", "b"]})
        assert d.interest_topics == ["a", "b"]


class TestAwakeningGroupOverride:
    def test_from_dict_none(self):
        assert AwakeningGroupOverride.from_dict(None) is None

    def test_from_dict_empty_group_id(self):
        assert AwakeningGroupOverride.from_dict({"group_id": ""}) is None

    def test_from_dict_valid(self):
        ov = AwakeningGroupOverride.from_dict({
            "group_id": "123",
            "extend_duration": 15,
            "relevance_threshold": 0.3,
        })
        assert ov is not None
        assert ov.group_id == "123"
        assert ov.extend_duration == 15
        assert ov.relevance_threshold == 0.3
        assert ov.qa_threshold is None  # not set

    def test_from_dict_strips_empty_topics(self):
        ov = AwakeningGroupOverride.from_dict({
            "group_id": "1",
            "interest_topics": ["x", ""],
        })
        assert ov is not None
        assert ov.interest_topics == ["x"]


class TestAwakeningConfig:
    def test_resolve_group_no_override(self):
        cfg = AwakeningConfig(defaults=AwakeningDefaults(extend_duration=5))
        s = cfg.resolve_group("999")
        assert s.extend_duration == 5

    def test_resolve_group_with_override(self):
        cfg = AwakeningConfig(
            defaults=AwakeningDefaults(extend_duration=5, interest_topics=["global"]),
            group_overrides={
                "123": AwakeningGroupOverride(
                    group_id="123", extend_duration=10, interest_topics=["local"]
                ),
            },
        )
        s123 = cfg.resolve_group("123")
        assert s123.extend_duration == 10
        assert s123.interest_topics == ["local"]

        s456 = cfg.resolve_group("456")
        assert s456.extend_duration == 5
        assert s456.interest_topics == ["global"]

    def test_resolve_group_partial_override(self):
        cfg = AwakeningConfig(
            defaults=AwakeningDefaults(extend_duration=5, relevance_threshold=0.5),
            group_overrides={
                "1": AwakeningGroupOverride(group_id="1", extend_duration=20),
            },
        )
        s = cfg.resolve_group("1")
        assert s.extend_duration == 20
        assert s.relevance_threshold == 0.5  # inherited from defaults


class TestLoadAwakeningConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path):
        cfg = load_awakening_config(tmp_path / "missing.toml")
        assert cfg.load_error is None
        assert cfg.defaults.extend_duration == 0

    def test_loads_valid_toml(self, tmp_path: Path):
        p = tmp_path / "awakening.toml"
        p.write_text(
            '[awakening.defaults]\nextend_duration = 15\nrelevance_threshold = 0.4\n',
            encoding="utf-8",
        )
        cfg = load_awakening_config(p)
        assert cfg.load_error is None
        assert cfg.defaults.extend_duration == 15
        assert cfg.defaults.relevance_threshold == 0.4

    def test_malformed_toml_sets_load_error(self, tmp_path: Path):
        p = tmp_path / "bad.toml"
        p.write_text("this is not valid toml [[[", encoding="utf-8")
        cfg = load_awakening_config(p)
        assert cfg.load_error is not None

    def test_group_overrides(self, tmp_path: Path):
        p = tmp_path / "awakening.toml"
        p.write_text(
            '[awakening.defaults]\nextend_duration = 5\n\n'
            '[[awakening.group_overrides]]\ngroup_id = "100"\nextend_duration = 30\n',
            encoding="utf-8",
        )
        cfg = load_awakening_config(p)
        assert cfg.resolve_group("100").extend_duration == 30
        assert cfg.resolve_group("200").extend_duration == 5


# =========================================================================
# BotMessageCache
# =========================================================================


class TestBotMessageCache:
    def test_add_and_get(self):
        c = BotMessageCache()
        c.add("g1", "hello")
        c.add("g1", "world")
        assert c.get_recent("g1") == ["hello", "world"]

    def test_empty_group(self):
        c = BotMessageCache()
        assert c.get_recent("g1") == []

    def test_group_isolation(self):
        c = BotMessageCache()
        c.add("g1", "a")
        c.add("g2", "b")
        assert c.get_recent("g1") == ["a"]
        assert c.get_recent("g2") == ["b"]

    def test_maxlen_eviction(self):
        c = BotMessageCache()
        for i in range(10):
            c.add("g1", str(i))
        msgs = c.get_recent("g1")
        assert len(msgs) == 5
        assert msgs[0] == "5"

    def test_skips_empty_text(self):
        c = BotMessageCache()
        c.add("g1", "")
        c.add("g1", "  ")
        c.add("g1", "real")
        assert c.get_recent("g1") == ["real"]

    def test_clear_group(self):
        c = BotMessageCache()
        c.add("g1", "a")
        c.clear_group("g1")
        assert c.get_recent("g1") == []


# =========================================================================
# AwakeningState
# =========================================================================


class TestAwakeningState:
    def test_extend_window(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        assert s.is_in_extend_window("g1", "u1", 30) is True
        assert s.is_in_extend_window("g1", "u1", 0) is False
        assert s.is_in_extend_window("g1", "u2", 30) is False
        assert s.is_in_extend_window("g2", "u1", 30) is False

    def test_extend_window_requires_explicit_source(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1", source="awakening_interest")
        assert s.is_in_extend_window("g1", "u1", 30) is False
        s.mark_awakened("g1", "u1", source="explicit_llm")
        assert s.is_in_extend_window("g1", "u1", 30) is True

    def test_silence_seconds(self):
        s = AwakeningState()
        assert s.get_group_silence_seconds("g1") == float("inf")
        s.record_message("g1", "u1")
        assert s.get_group_silence_seconds("g1") < 1.0

    def test_boredom_trigger_guard(self):
        s = AwakeningState()
        assert s.can_trigger_boredom("g1", 60) is True
        s.mark_boredom_triggered("g1")
        assert s.can_trigger_boredom("g1", 60) is False

    def test_llm_cache(self):
        s = AwakeningState()
        assert s.llm_cache_get("r1", "g1", "text") is None
        s.llm_cache_set("r1", "g1", "text", True)
        assert s.llm_cache_get("r1", "g1", "text") is True
        s.llm_cache_set("r1", "g1", "text", False)
        assert s.llm_cache_get("r1", "g1", "text") is False

    def test_llm_cache_different_keys(self):
        s = AwakeningState()
        s.llm_cache_set("r1", "g1", "a", True)
        s.llm_cache_set("r2", "g1", "a", False)
        assert s.llm_cache_get("r1", "g1", "a") is True
        assert s.llm_cache_get("r2", "g1", "a") is False


# =========================================================================
# Helpers
# =========================================================================


class TestExtractWords:
    def test_chinese_text(self):
        words = _extract_words("今天天气怎么样")
        assert len(words) > 0
        assert any("天气" in w for w in words)

    def test_empty_text(self):
        assert _extract_words("") == set()

    def test_no_cjk(self):
        assert _extract_words("hello world 123") == set()


class TestWordOverlapRatio:
    def test_identical_texts(self):
        r = _word_overlap_ratio("今天天气怎么样", ["今天天气怎么样"])
        assert r > 0.8

    def test_related_texts(self):
        r = _word_overlap_ratio("今天天气怎么样", ["今天天气很好啊"])
        assert r > 0.3

    def test_unrelated_texts(self):
        r = _word_overlap_ratio("完全无关的内容", ["今天天气很好"])
        assert r < 0.2

    def test_empty_texts(self):
        assert _word_overlap_ratio("", ["hello"]) == 0.0
        assert _word_overlap_ratio("hello", []) == 0.0

    def test_max_across_multiple_bot_msgs(self):
        r = _word_overlap_ratio(
            "今天天气怎么样",
            ["完全无关", "今天天气很好"],
        )
        assert r > 0.3


class TestDndWindow:
    def test_empty_strings(self):
        assert _is_in_dnd_window("", "") is False

    def test_same_day_range(self):
        assert _is_in_dnd_window("08:00", "20:00", now=datetime(2026, 5, 27, 12, 0)) is True
        assert _is_in_dnd_window("08:00", "20:00", now=datetime(2026, 5, 27, 21, 0)) is False

    def test_overnight_range(self):
        assert _is_in_dnd_window("23:00", "08:00", now=datetime(2026, 5, 27, 4, 0)) is True
        assert _is_in_dnd_window("23:00", "08:00", now=datetime(2026, 5, 27, 12, 0)) is False

    def test_invalid_format(self):
        assert _is_in_dnd_window("bad", "08:00") is False


class TestQAFastPattern:
    def test_matches_question_marks(self):
        assert _QA_FAST_PATTERNS.search("这是什么？")
        assert _QA_FAST_PATTERNS.search("what?")

    def test_matches_question_keywords(self):
        assert _QA_FAST_PATTERNS.search("请问怎么解决")
        assert _QA_FAST_PATTERNS.search("为什么这样")
        assert _QA_FAST_PATTERNS.search("能不能帮我看看")

    def test_no_match_on_plain_text(self):
        assert not _QA_FAST_PATTERNS.search("今天天气真好")
        assert not _QA_FAST_PATTERNS.search("哈哈哈笑死")


class TestExtractJsonTrigger:
    def test_score_uses_threshold(self):
        assert _extract_json_trigger('{"score": 0.7}', threshold=0.5) is True
        assert _extract_json_trigger('{"score": 0.4}', threshold=0.5) is False

    def test_trigger_boolean_fallback(self):
        assert _extract_json_trigger('```json\n{"trigger": true}\n```', threshold=0.9) is True

    def test_trigger_string_false_is_false(self):
        assert _extract_json_trigger('{"trigger": "false"}') is False


class TestExtendEligibility:
    def test_rejects_image_only_and_cq_only(self):
        assert _is_extend_eligible_message("[图片]") is False
        assert _is_extend_eligible_message("[CQ:image,file=abc]") is False

    def test_rejects_short_interjections(self):
        assert _is_extend_eligible_message("哈哈") is False
        assert _is_extend_eligible_message("草") is False
        assert _is_extend_eligible_message("嗯") is False

    def test_accepts_substantive_short_question(self):
        assert _is_extend_eligible_message("是吗") is True
        assert _is_extend_eligible_message("为啥？") is True

    def test_accepts_substantive_text(self):
        assert _is_extend_eligible_message("下午没课可以继续聊") is True


class TestPassiveTriggerImages:
    def test_selects_images_for_interest_with_limit_and_dedupe(self):
        result = AwakeningTriggerResult(
            rule_name=_RULE_INTEREST,
            prompt="这张图里的Python代码",
            trigger_reason="兴趣话题匹配：Python",
        )

        selected = select_passive_trigger_image_urls(
            result,
            [
                "https://example.test/a.png",
                "https://example.test/a.png",
                "https://example.test/b.png",
                "https://example.test/c.png",
            ],
        )

        assert selected == [
            "https://example.test/a.png",
            "https://example.test/b.png",
        ]

    def test_rejects_images_for_fallback(self):
        result = AwakeningTriggerResult(
            rule_name=_RULE_FALLBACK,
            prompt="[图片] 马头蒸菜",
            trigger_reason="兜底概率触发",
        )

        assert select_passive_trigger_image_urls(result, ["https://example.test/a.png"]) == []
        assert build_passive_trigger_raw_user_text(result, []) == "马头蒸菜"

    def test_prompt_mentions_images_only_when_selected(self):
        result = AwakeningTriggerResult(
            rule_name=_RULE_QA,
            prompt="[图片] 这是什么？",
            trigger_reason="答疑唤醒：LLM确认",
            trigger_instruction="判定结果显示用户提出了可能需要你回答的问题。",
        )

        with_image = build_awakening_prompt(result, ["https://example.test/a.png"])
        without_image = build_awakening_prompt(result, [])

        assert "这条触发消息包含图片" in with_image
        assert "不要编造具体图像细节" in with_image
        assert "这条触发消息包含图片" not in without_image
        assert build_passive_trigger_raw_user_text(result, ["https://example.test/a.png"]) == "[图片] 这是什么？"


# =========================================================================
# Trigger checks (sync)
# =========================================================================


def _make_settings(**kwargs) -> ResolvedAwakeningSettings:
    defaults = dict(
        extend_duration=0,
        fallback_probability=0.0,
        boredom_silence_seconds=0,
        boredom_probability=0.0,
        boredom_check_interval=300,
        boredom_dnd_start="",
        boredom_dnd_end="",
        interest_topics=[],
        relevance_threshold=1.0,
        qa_threshold=1.0,
    )
    defaults.update(kwargs)
    return ResolvedAwakeningSettings(**defaults)


class TestCheckExtend:
    def test_disabled(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        settings = _make_settings(extend_duration=0)
        assert check_extend("g1", "u1", "hello", settings, s) is None

    def test_in_window(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        settings = _make_settings(extend_duration=30)
        result = check_extend("g1", "u1", "hello", settings, s)
        assert result is not None
        assert result.rule_name == _RULE_EXTEND
        assert result.opens_extend_window is False
        assert "唤醒延长" in result.trigger_instruction

    def test_not_in_window(self):
        s = AwakeningState()
        settings = _make_settings(extend_duration=30)
        assert check_extend("g1", "u1", "hello", settings, s) is None

    def test_empty_text(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        settings = _make_settings(extend_duration=30)
        assert check_extend("g1", "u1", "", settings, s) is None

    def test_in_window_rejects_noise(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        settings = _make_settings(extend_duration=30)
        assert check_extend("g1", "u1", "[图片]", settings, s) is None
        assert check_extend("g1", "u1", "哈哈", settings, s) is None

    def test_non_explicit_source_does_not_extend(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1", source="awakening_interest")
        settings = _make_settings(extend_duration=30)
        assert check_extend("g1", "u1", "这句话值得继续聊", settings, s) is None


class TestCheckInterest:
    def test_disabled_empty_topics(self):
        settings = _make_settings(interest_topics=[])
        svc = MagicMock()
        assert check_interest("g1", "u1", "hello", settings, "", svc) is None

    def test_match(self):
        settings = _make_settings(interest_topics=["Python", "编程"])
        svc = MagicMock()
        svc.config.personas = {}
        result = check_interest("g1", "u1", "我在学Python", settings, "", svc)
        assert result is not None
        assert result.rule_name == _RULE_INTEREST
        assert result.matched_topic == "Python"
        assert result.opens_extend_window is False
        assert "Python" in result.trigger_instruction
        assert "唤醒机制" in result.trigger_instruction
        assert "我在学Python" in build_awakening_prompt(result)

    def test_no_match(self):
        settings = _make_settings(interest_topics=["Python"])
        svc = MagicMock()
        svc.config.personas = {}
        assert check_interest("g1", "u1", "今天天气好", settings, "", svc) is None

    def test_persona_topics_merged(self):
        settings = _make_settings(interest_topics=["global_topic"])
        persona = MagicMock()
        persona.extras = {"awakening": {"interest_topics": ["persona_topic"]}}
        svc = MagicMock()
        svc.config.personas = {"p1": persona}
        result = check_interest("g1", "u1", "persona_topic在这里", settings, "p1", svc)
        assert result is not None


class TestCheckFallback:
    def test_disabled(self):
        settings = _make_settings(fallback_probability=0.0)
        assert check_fallback("g1", "u1", "hello", settings) is None

    def test_empty_text(self):
        settings = _make_settings(fallback_probability=1.0)
        assert check_fallback("g1", "u1", "", settings) is None

    def test_trigger_uses_conservative_instruction(self, monkeypatch):
        monkeypatch.setattr("quickquip.chat.awakening.random.random", lambda: 0.0)
        settings = _make_settings(fallback_probability=1.0)
        result = check_fallback("g1", "u1", "马头蒸菜", settings)
        assert result is not None
        assert result.opens_extend_window is False
        assert "低概率" in result.trigger_instruction
        assert "不要说明" in result.trigger_instruction


class TestCheckBoredom:
    def test_disabled(self):
        settings = _make_settings(boredom_silence_seconds=0)
        assert check_boredom("g1", settings) is None

    def test_insufficient_silence(self):
        s = AwakeningState()
        s.record_message("g1", "u1")
        settings = _make_settings(boredom_silence_seconds=60, boredom_probability=1.0)
        assert check_boredom("g1", settings, s) is None


# =========================================================================
# Trigger checks (async)
# =========================================================================


class TestCheckRelevance:
    def test_disabled_threshold(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "hello")
        settings = _make_settings(relevance_threshold=1.0)
        result = asyncio.run(check_relevance("g1", "u1", "hello", settings, None, s))
        assert result is None

    def test_zero_threshold_disabled(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.0)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"score": 1.0}')
        result = asyncio.run(check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s))
        assert result is None
        svc.quick_judge.assert_not_called()

    def test_no_bot_messages(self):
        s = AwakeningState()
        settings = _make_settings(relevance_threshold=0.5)
        result = asyncio.run(check_relevance("g1", "u1", "hello", settings, None, s))
        assert result is None

    def test_low_overlap_skips_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气很好")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        result = asyncio.run(
            check_relevance("g1", "u1", "完全无关XYZ", settings, svc, s)
        )
        assert result is None

    def test_high_overlap_triggers_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.3)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"trigger": true}')
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is not None
        assert result.rule_name == _RULE_RELEVANCE
        assert result.opens_extend_window is False
        assert "相关性判定" in result.trigger_instruction

    def test_llm_returns_false(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.3)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"trigger": false}')
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is None

    def test_llm_score_below_threshold(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"score": 0.6}')
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is None

    def test_cache_hit(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.3)
        s.llm_cache_set(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.3), True)
        svc = MagicMock()
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is not None
        svc.quick_judge.assert_not_called()

    def test_cache_key_includes_threshold(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        s.llm_cache_set(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.3), True)
        settings = _make_settings(relevance_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"score": 0.6}')
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is None
        svc.quick_judge.assert_awaited_once()


class TestCheckQA:
    def test_disabled_threshold(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=1.0)
        result = asyncio.run(check_qa("g1", "u1", "请问这是什么？", settings, None, s))
        assert result is None

    def test_zero_threshold_disabled(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.0)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"score": 1.0}')
        result = asyncio.run(check_qa("g1", "u1", "请问这是什么？", settings, svc, s))
        assert result is None
        svc.quick_judge.assert_not_called()

    def test_no_question_marker(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        result = asyncio.run(check_qa("g1", "u1", "今天天气真好", settings, None, s))
        assert result is None

    def test_question_triggers_llm(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"trigger": true}')
        result = asyncio.run(
            check_qa("g1", "u1", "请问怎么解决这个问题？", settings, svc, s)
        )
        assert result is not None
        assert result.rule_name == _RULE_QA
        assert result.opens_extend_window is False
        assert "答疑判定" in result.trigger_instruction

    def test_llm_returns_false(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"trigger": false}')
        result = asyncio.run(
            check_qa("g1", "u1", "怎么了？", settings, svc, s)
        )
        assert result is None

    def test_llm_score_below_threshold(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge = AsyncMock(return_value='{"score": 0.6}')
        result = asyncio.run(
            check_qa("g1", "u1", "请问怎么解决这个问题？", settings, svc, s)
        )
        assert result is None

    def test_cache_hit(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        s.llm_cache_set(_RULE_QA, "g1", _llm_cache_text("cached q?", 0.5), True)
        svc = MagicMock()
        result = asyncio.run(
            check_qa("g1", "u1", "cached q?", settings, svc, s)
        )
        assert result is not None
        svc.quick_judge.assert_not_called()


# =========================================================================
# Orchestrator
# =========================================================================


class TestCheckAwakeningTriggers:
    def test_llm_disabled_returns_none(self):
        s = AwakeningState()
        llm_settings = MagicMock()
        llm_settings.enabled = False
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(interest_topics=["test"]),
        )
        try:
            result = asyncio.run(
                check_awakening_triggers("g1", "u1", "test message", llm_settings, svc, state=s)
            )
            assert result is None
        finally:
            aw._config = old_cfg

    def test_disabled_rule_skips_quick_judge(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        llm_settings = MagicMock()
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}
        svc.quick_judge = AsyncMock(return_value='{"score": 1.0}')

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(relevance_threshold=0.3),
        )
        try:
            result = asyncio.run(
                check_awakening_triggers(
                    "g1",
                    "u1",
                    "今天天气怎么样",
                    llm_settings,
                    svc,
                    state=s,
                    rule_enabled=lambda rule_name: rule_name != _RULE_RELEVANCE,
                )
            )
            assert result is None
            svc.quick_judge.assert_not_called()
        finally:
            aw._config = old_cfg

    def test_rate_unavailable_skips_quick_judge(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        llm_settings = MagicMock()
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}
        svc.quick_judge = AsyncMock(return_value='{"score": 1.0}')

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(relevance_threshold=0.3),
        )
        try:
            result = asyncio.run(
                check_awakening_triggers(
                    "g1",
                    "u1",
                    "今天天气怎么样",
                    llm_settings,
                    svc,
                    state=s,
                    rate_available=lambda rule_name: rule_name != _RULE_RELEVANCE,
                )
            )
            assert result is None
            svc.quick_judge.assert_not_called()
        finally:
            aw._config = old_cfg

    def test_extend_takes_priority(self):
        s = AwakeningState()
        s.mark_awakened("g1", "u1")
        llm_settings = MagicMock()
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}

        # Create a config with extend enabled and interest topics
        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(
                extend_duration=30,
                interest_topics=["test"],
            ),
        )
        try:
            result = asyncio.run(
                check_awakening_triggers("g1", "u1", "test message", llm_settings, svc, state=s)
            )
            assert result is not None
            assert result.rule_name == _RULE_EXTEND
        finally:
            aw._config = old_cfg

    def test_interest_does_not_open_extend_window(self):
        s = AwakeningState()
        llm_settings = MagicMock()
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(
                extend_duration=30,
                interest_topics=["Python"],
            ),
        )
        try:
            first = asyncio.run(
                check_awakening_triggers("g1", "u1", "我在学Python", llm_settings, svc, state=s)
            )
            assert first is not None
            assert first.rule_name == _RULE_INTEREST
            assert first.opens_extend_window is False

            second = asyncio.run(
                check_awakening_triggers("g1", "u1", "后续普通聊天内容", llm_settings, svc, state=s)
            )
            assert second is None
        finally:
            aw._config = old_cfg

    def test_all_disabled_returns_none(self):
        s = AwakeningState()
        s.record_message("g1", "u1")
        llm_settings = MagicMock()
        llm_settings.persona_id = ""
        svc = MagicMock()
        svc.config = MagicMock()
        svc.config.quick_judge = MagicMock(timeout=2.0, max_tokens=64)
        svc.config.personas = {}

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        aw._config = AwakeningConfig()  # all defaults = disabled
        try:
            result = asyncio.run(
                check_awakening_triggers("g1", "u1", "hello", llm_settings, svc, state=s)
            )
            assert result is None
        finally:
            aw._config = old_cfg


class TestRunBoredomCheck:
    def test_skips_when_group_llm_disabled(self):
        bot = MagicMock()
        bot.send_group_msg = AsyncMock()
        groups = MagicMock()
        groups.all_groups.return_value = ["123"]
        rule_switch = MagicMock()
        rule_switch.is_enabled.return_value = True
        svc = MagicMock()
        svc.config.load_error = None
        svc.get_group_settings.return_value = MagicMock(enabled=False)
        svc.generate_reply = AsyncMock(return_value={"reply": "本群 LLM 已关闭。"})

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        old_state = aw._state
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(
                boredom_silence_seconds=1,
                boredom_probability=1.0,
                boredom_check_interval=1,
            ),
        )
        aw._state = AwakeningState()
        try:
            asyncio.run(run_boredom_check(bot, groups, rule_switch, svc))
        finally:
            aw._config = old_cfg
            aw._state = old_state

        svc.generate_reply.assert_not_called()
        bot.send_group_msg.assert_not_called()

    def test_sends_when_group_llm_enabled(self):
        bot = MagicMock()
        bot.send_group_msg = AsyncMock()
        groups = MagicMock()
        groups.all_groups.return_value = ["123"]
        rule_switch = MagicMock()
        rule_switch.is_enabled.return_value = True
        svc = MagicMock()
        svc.config.load_error = None
        svc.get_group_settings.return_value = MagicMock(enabled=True)
        svc.recent_message_buffer.list_recent.return_value = []
        svc.generate_reply = AsyncMock(return_value={"reply": "冒个泡"})
        stats_tracker = MagicMock()

        import quickquip.chat.awakening as aw
        old_cfg = aw._config
        old_state = aw._state
        aw._config = AwakeningConfig(
            defaults=AwakeningDefaults(
                boredom_silence_seconds=1,
                boredom_probability=1.0,
                boredom_check_interval=1,
            ),
        )
        aw._state = AwakeningState()
        try:
            asyncio.run(run_boredom_check(bot, groups, rule_switch, svc, stats_tracker=stats_tracker))
        finally:
            aw._config = old_cfg
            aw._state = old_state

        svc.generate_reply.assert_awaited_once()
        bot.send_group_msg.assert_awaited_once_with(group_id=123, message="冒个泡")
        stats_tracker.record_trigger.assert_called_once_with("123", "awakening_boredom")
