from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock, MagicMock


from quickquip.llm.service import QuickJudgeResult
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
    effective_boredom_scan_interval,
    _llm_judge,
    _parse_judge_text,
    load_awakening_config,
    run_boredom_check,
    select_passive_trigger_image_urls,
)




def _qj(text: str, outcome: str = "ok", **kwargs) -> QuickJudgeResult:
    """构造 quick_judge_detailed 的 stub 返回值。"""
    return QuickJudgeResult(text=text, outcome=outcome, provider_id="p", model="m", **kwargs)


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

    def test_ttl_visible_before_30_minutes(self):
        c = BotMessageCache()
        c.add("g1", "fresh", now=1000.0)
        assert c.get_recent("g1", now=1000.0 + 30 * 60.0 - 1.0) == ["fresh"]

    def test_ttl_boundary_keeps_entry(self):
        c = BotMessageCache()
        c.add("g1", "edge", now=1000.0)
        assert c.get_recent("g1", now=1000.0 + 30 * 60.0) == ["edge"]

    def test_ttl_evicts_after_30_minutes(self):
        c = BotMessageCache()
        c.add("g1", "old", now=1000.0)
        c.add("g1", "new", now=1000.0 + 60.0)
        assert c.get_recent("g1", now=1000.0 + 30 * 60.0 + 1.0) == ["new"]

    def test_ttl_eviction_keeps_order(self):
        c = BotMessageCache()
        c.add("g1", "a", now=100.0)
        c.add("g1", "b", now=200.0)
        c.add("g1", "c", now=300.0)
        assert c.get_recent("g1", now=200.0 + 30 * 60.0 + 0.5) == ["c"]

    def test_all_expired_entry_removes_group(self):
        c = BotMessageCache()
        c.add("g1", "old", now=1000.0)
        assert c.get_recent("g1", now=1000.0 + 30 * 60.0 + 1.0) == []
        assert c.get_recent("g1", now=1000.0 + 30 * 60.0 + 2.0) == []


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
        assert s.get_group_silence_seconds("g1") is None
        s.record_message("g1", "u1")
        assert s.get_group_silence_seconds("g1") < 1.0

    def test_clear_boredom_state(self):
        s = AwakeningState()
        s.record_message("g1", "u1")
        s.mark_boredom_triggered("g1")
        s.clear_boredom_state("g1")
        assert s.get_group_silence_seconds("g1") is None
        assert s.can_trigger_boredom("g1", 60) is True

    def test_prune_stale_keeps_silence_and_cooldown_state(self):
        """沉寂/冷却状态不做固定时限淘汰：较大 boredom_silence_seconds
        不会因旧状态被清理而提前满足。"""
        s = AwakeningState()
        s.record_message("g1", "u1")
        s._last_message_times["g1"] = monotonic() - 7200  # 两小时前的消息
        s.mark_boredom_triggered("g1")
        s._last_boredom_trigger["g1"] = monotonic() - 7200
        s.prune_stale(max_age=7200)
        assert s.get_group_silence_seconds("g1") is not None
        assert s.get_group_silence_seconds("g1") >= 7200
        assert s.can_trigger_boredom("g1", 300) is True

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

    def test_english_words_normalized(self):
        words = _extract_words("Deploy the Kubernetes cluster")
        assert "deploy" in words
        assert "kubernetes" in words
        assert "cluster" in words

    def test_numbers_extracted(self):
        words = _extract_words("upgrade to python 3.12")
        assert "python" in words
        assert "3" in words
        assert "12" in words

    def test_code_identifiers_kept_intact(self):
        words = _extract_words("run pip_install_deps in GitHub Actions")
        assert "pip_install_deps" in words
        assert "github" in words
        assert "actions" in words

    def test_camel_case_identifier(self):
        words = _extract_words("fix WebSocketError retry")
        assert "websocketerror" in words
        assert "retry" in words

    def test_case_insensitive_overlap(self):
        assert "pytest" in _extract_words("use PYTEST fixtures")
        assert "pytest" in _extract_words("pytest.ini 配置")

    def test_url_fragments_not_tokenized(self):
        words = _extract_words("看这个 https://example.com/foo 很有意思")
        assert "https" not in words
        assert "example" not in words
        assert "com" not in words

    def test_voice_transcript_content_participates(self):
        words = _extract_words("[语音转文字：Kubernetes 部署又失败了]")
        assert "kubernetes" in words
        assert any("部署" in w or "失败" in w for w in words)

    def test_structural_placeholders_not_tokenized(self):
        assert _extract_words("[图片][语音][CQ:at,qq=123]") == set()

    def test_empty_text(self):
        assert _extract_words("") == set()

    def test_no_cjk_yields_latin_tokens(self):
        assert _extract_words("hello world 123") == {"hello", "world", "123"}

    def test_latin_stopwords_dropped(self):
        assert _extract_words("what is this") == set()


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

    def test_raw_user_text_preserves_voice_transcript(self):
        voice_only = AwakeningTriggerResult(
            rule_name=_RULE_RELEVANCE,
            prompt="[语音转文字：Kubernetes 部署又失败了]",
            trigger_reason="相关性唤醒",
        )
        assert build_passive_trigger_raw_user_text(voice_only, []) == "Kubernetes 部署又失败了"

        mixed = AwakeningTriggerResult(
            rule_name=_RULE_RELEVANCE,
            prompt="看这个\n[语音2转文字：第二段]",
            trigger_reason="相关性唤醒",
        )
        assert build_passive_trigger_raw_user_text(mixed, []) == "看这个 第二段"


class TestBoredomScanInterval:
    def test_scan_interval_from_toml(self, tmp_path: Path):
        path = tmp_path / "awakening.toml"
        path.write_text(
            "[awakening.defaults]\nboredom_scan_interval = 120\nboredom_check_interval = 600\n",
            encoding="utf-8",
        )
        cfg = load_awakening_config(path)
        assert cfg.defaults.boredom_scan_interval == 120
        assert effective_boredom_scan_interval(cfg) == 120

    def test_scan_interval_falls_back_to_check_interval(self, tmp_path: Path):
        path = tmp_path / "awakening.toml"
        path.write_text("[awakening.defaults]\nboredom_check_interval = 600\n", encoding="utf-8")
        cfg = load_awakening_config(path)
        assert cfg.defaults.boredom_scan_interval is None
        assert effective_boredom_scan_interval(cfg) == 600

    def test_scan_interval_invalid_falls_back_to_default_300(self, tmp_path: Path):
        cfg = AwakeningConfig(defaults=AwakeningDefaults(boredom_check_interval=0))
        assert effective_boredom_scan_interval(cfg) == 300


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

    def test_unknown_silence_never_triggers(self):
        """重启后未观察到群消息：沉寂未知，不允许无聊唤醒。"""
        s = AwakeningState()
        settings = _make_settings(boredom_silence_seconds=60, boredom_probability=1.0)
        assert check_boredom("g1", settings, s) is None

    def test_long_silence_threshold_not_prematurely_met(self):
        """沉寂 7200s 且门槛 10800s：prune 后状态保留且不提前触发。"""
        s = AwakeningState()
        s.record_message("g1", "u1")
        s._last_message_times["g1"] = monotonic() - 7200
        s.prune_stale(max_age=7200)
        settings = _make_settings(boredom_silence_seconds=10800, boredom_probability=1.0)
        assert check_boredom("g1", settings, s) is None

    def test_dnd_blocks_boredom(self):
        s = AwakeningState()
        s.record_message("g1", "u1")
        s._last_message_times["g1"] = monotonic() - 7200
        settings = _make_settings(
            boredom_silence_seconds=3600,
            boredom_probability=1.0,
            boredom_dnd_start="00:00",
            boredom_dnd_end="23:59",
        )
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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 1.0}'))
        result = asyncio.run(check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s))
        assert result is None
        svc.quick_judge_detailed.assert_not_called()

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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": true}'))
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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": false}'))
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is None

    def test_llm_score_below_threshold(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        settings = _make_settings(relevance_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 0.6}'))
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
        svc.quick_judge_detailed.assert_not_called()

    def test_cache_key_includes_threshold(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        s.llm_cache_set(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.3), True)
        settings = _make_settings(relevance_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 0.6}'))
        result = asyncio.run(
            check_relevance("g1", "u1", "今天天气怎么样", settings, svc, s)
        )
        assert result is None
        svc.quick_judge_detailed.assert_awaited_once()

    def test_english_overlap_enters_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "the Kubernetes deployment failed with ImagePullBackOff")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": true}'))
        result = asyncio.run(
            check_relevance("g1", "u1", "Kubernetes ImagePullBackOff again?", settings, svc, s)
        )
        assert result is not None
        svc.quick_judge_detailed.assert_awaited_once()

    def test_code_identifier_overlap_enters_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "跑 pip_install_deps 的时候 warnings 一堆")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": true}'))
        result = asyncio.run(
            check_relevance("g1", "u1", "pip_install_deps 又 warnings 了吗", settings, svc, s)
        )
        assert result is not None
        svc.quick_judge_detailed.assert_awaited_once()

    def test_non_overlapping_english_skips_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "the Kubernetes deployment failed with ImagePullBackOff")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        result = asyncio.run(
            check_relevance("g1", "u1", "lakers won the game last night", settings, svc, s)
        )
        assert result is None
        svc.quick_judge_detailed.assert_not_called()

    def test_shared_url_alone_does_not_pass_fast_filter(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "看这个 https://example.com/a 很有意思")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        result = asyncio.run(
            check_relevance("g1", "u1", "我上传到 https://example.com/b 了", settings, svc, s)
        )
        assert result is None
        svc.quick_judge_detailed.assert_not_called()

    def test_threshold_one_disables_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "Kubernetes ImagePullBackOff")
        settings = _make_settings(relevance_threshold=1.0)
        svc = MagicMock()
        result = asyncio.run(
            check_relevance("g1", "u1", "Kubernetes ImagePullBackOff?", settings, svc, s)
        )
        assert result is None
        svc.quick_judge_detailed.assert_not_called()

    def test_threshold_middle_value_uses_llm(self):
        s = AwakeningState()
        s.bot_messages.add("g1", "Kubernetes deployment failed")
        settings = _make_settings(relevance_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": true}'))
        result = asyncio.run(
            check_relevance("g1", "u1", "Kubernetes deployment again?", settings, svc, s)
        )
        assert result is not None
        svc.quick_judge_detailed.assert_awaited_once()


class TestLlmJudgeClassification:
    """#75-C：结果类别决定缓存与触发行为（技术失败 fail-closed 不缓存）。"""

    def _state_with_bot_msg(self) -> AwakeningState:
        s = AwakeningState()
        s.bot_messages.add("g1", "今天天气非常不错")
        return s

    def _run_relevance(self, svc, threshold=0.5, text="今天天气怎么样"):
        s = self._state_with_bot_msg()
        settings = _make_settings(relevance_threshold=threshold)
        result = asyncio.run(check_relevance("g1", "u1", text, settings, svc, s))
        return result, s

    def test_business_true_triggers_and_caches_true(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 0.9}'))
        result, s = self._run_relevance(svc)
        assert result is not None
        assert s.llm_cache_get(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.5)) is True

    def test_business_false_caches_false(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 0.2}'))
        result, s = self._run_relevance(svc)
        assert result is None
        assert s.llm_cache_get(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.5)) is False

    def _assert_technical_failure(self, svc):
        result, s = self._run_relevance(svc)
        assert result is None
        assert s.llm_cache_get(_RULE_RELEVANCE, "g1", _llm_cache_text("今天天气怎么样", 0.5)) is None

    def test_empty_result_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj("", outcome="empty"))
        self._assert_technical_failure(svc)

    def test_truncated_result_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(
            return_value=_qj('{"trig', outcome="length", finish_reason="length")
        )
        self._assert_technical_failure(svc)

    def test_provider_error_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj("", outcome="provider_error"))
        self._assert_technical_failure(svc)

    def test_no_provider_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(
            return_value=_qj('{"trigger": false}', outcome="no_provider")
        )
        self._assert_technical_failure(svc)

    def test_invalid_json_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj("这不是 JSON"))
        self._assert_technical_failure(svc)

    def test_timeout_fail_closed_no_cache(self):
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(side_effect=asyncio.TimeoutError())
        self._assert_technical_failure(svc)

    def test_timeout_diagnostic_carries_provider_and_model(self):
        from types import SimpleNamespace

        svc = SimpleNamespace(
            config=SimpleNamespace(
                quick_judge=SimpleNamespace(provider_id="minimax", model="MiniMax-M2.7"),
            ),
        )

        async def _timeout(prompt, max_tokens=64):
            raise asyncio.TimeoutError()

        svc.quick_judge_detailed = _timeout
        outcome = asyncio.run(
            _llm_judge(svc, "sys", "user", 0.5, timeout=0.05, max_tokens=64)
        )
        assert outcome.category == "timeout"
        assert outcome.triggered is None
        assert outcome.diagnostic["provider"] == "minimax"
        assert outcome.diagnostic["model"] == "MiniMax-M2.7"
        assert outcome.diagnostic["duration_ms"] >= 0

    def test_qa_technical_failure_no_cache(self):
        s = AwakeningState()
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj("", outcome="empty"))
        settings = _make_settings(qa_threshold=0.5)
        result = asyncio.run(
            check_qa("g1", "u1", "请问怎么解决这个问题？", settings, svc, s)
        )
        assert result is None
        assert s.llm_cache_get(_RULE_QA, "g1", _llm_cache_text("请问怎么解决这个问题？", 0.5)) is None

    def test_strict_parse_distinguishes_false_from_garbage(self):
        assert _parse_judge_text('{"trigger": false}', 0.5) is False
        assert _parse_judge_text("模型废话没有 JSON", 0.5) is None
        assert _parse_judge_text('{"trigger": true}', 0.5) is True
        assert _parse_judge_text('{"score": 0.7}', 0.8) is False
        assert _parse_judge_text('{"score": 0.9}', 0.8) is True

    def test_strict_parse_rejects_fragment_and_embedded_trigger_text(self):
        # 残缺 JSON 与正文中出现 "trigger" 字样的输出都不是业务判定
        assert _parse_judge_text('{"trigger": false', 0.5) is None
        assert _parse_judge_text('不要输出 "trigger": true 哦', 0.5) is None
        assert _parse_judge_text("前缀噪音 {\"trigger\": true} 后缀噪音", 0.5) is True


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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 1.0}'))
        result = asyncio.run(check_qa("g1", "u1", "请问这是什么？", settings, svc, s))
        assert result is None
        svc.quick_judge_detailed.assert_not_called()

    def test_no_question_marker(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        result = asyncio.run(check_qa("g1", "u1", "今天天气真好", settings, None, s))
        assert result is None

    def test_question_triggers_llm(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.5)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": true}'))
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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"trigger": false}'))
        result = asyncio.run(
            check_qa("g1", "u1", "怎么了？", settings, svc, s)
        )
        assert result is None

    def test_llm_score_below_threshold(self):
        s = AwakeningState()
        settings = _make_settings(qa_threshold=0.8)
        svc = MagicMock()
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 0.6}'))
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
        svc.quick_judge_detailed.assert_not_called()


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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 1.0}'))

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
            svc.quick_judge_detailed.assert_not_called()
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
        svc.quick_judge_detailed = AsyncMock(return_value=_qj('{"score": 1.0}'))

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
            svc.quick_judge_detailed.assert_not_called()
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
        # 沉寂状态需已知且已过门槛（boredom_silence_seconds=1）
        aw._state.record_message("123", "u1")
        aw._state._last_message_times["123"] = monotonic() - 2
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
        # 沉寂状态需已知且已过门槛（boredom_silence_seconds=1）
        aw._state.record_message("123", "u1")
        aw._state._last_message_times["123"] = monotonic() - 2
        try:
            asyncio.run(run_boredom_check(bot, groups, rule_switch, svc, stats_tracker=stats_tracker))
        finally:
            aw._config = old_cfg
            aw._state = old_state

        svc.generate_reply.assert_awaited_once()
        bot.send_group_msg.assert_awaited_once_with(group_id=123, message="冒个泡")
        stats_tracker.record_trigger.assert_called_once_with("123", "awakening_boredom")

    def test_sends_with_images_via_injected_reply_builder(self):
        """适配层注入 build_reply_message 时，带图回复经拼装器发送（不丢图）。"""
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
        svc.generate_reply = AsyncMock(
            return_value={"reply": "冒个泡", "images": ["cXctaW1n"]}
        )

        def _build_reply(result):
            return ("message", result["reply"], result.get("images"))

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
        # 沉寂状态需已知且已过门槛（boredom_silence_seconds=1）
        aw._state.record_message("123", "u1")
        aw._state._last_message_times["123"] = monotonic() - 2
        try:
            asyncio.run(
                run_boredom_check(bot, groups, rule_switch, svc, build_reply_message=_build_reply)
            )
        finally:
            aw._config = old_cfg
            aw._state = old_state

        bot.send_group_msg.assert_awaited_once_with(
            group_id=123, message=("message", "冒个泡", ["cXctaW1n"])
        )


class TestRunBoredomCheckFailures:
    """run_boredom_check 拒绝与异常路径的 characterization 测试（钉住现状，供 v1.12.1 重构对照）。

    钉住的现状要点：
    - 冷却标记 mark_boredom_triggered 在 send_group_msg 成功之后才执行，
      故 generate_reply / send 任一抛异常都不会标冷却，也不会写统计。
    - 单群异常被 try/except 吞掉（logger.warning），循环继续处理后续群。
    """

    @staticmethod
    def _triggerable_state(*gids: str) -> AwakeningState:
        """构造各群均已过沉寂门槛的 AwakeningState（boredom_silence_seconds=1）。"""
        st = AwakeningState()
        for gid in gids:
            st.record_message(gid, "u1")
            st._last_message_times[gid] = monotonic() - 2
        return st

    @staticmethod
    def _make_fakes(gids, *, generate_reply=None, send=None):
        from types import SimpleNamespace

        bot = MagicMock()
        bot.send_group_msg = send if send is not None else AsyncMock()
        groups = MagicMock()
        groups.all_groups.return_value = list(gids)
        rule_switch = MagicMock()
        rule_switch.is_enabled.return_value = True
        # spec 限定 svc 属性面，防止源码改名后 MagicMock 自动造属性而测试仍绿；
        # 被访问的值用 SimpleNamespace 给出真实形状（characterization 应钉住访问契约）
        svc = MagicMock(
            spec=["config", "get_group_settings", "recent_message_buffer", "generate_reply"]
        )
        svc.config = SimpleNamespace(load_error=None)
        svc.get_group_settings.return_value = SimpleNamespace(enabled=True)
        svc.recent_message_buffer.list_recent.return_value = []
        svc.generate_reply = (
            generate_reply if generate_reply is not None
            else AsyncMock(return_value={"reply": "冒个泡"})
        )
        return bot, groups, rule_switch, svc

    @staticmethod
    def _run(bot, groups, rule_switch, svc, state, **kwargs):
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
        aw._state = state
        try:
            asyncio.run(run_boredom_check(bot, groups, rule_switch, svc, **kwargs))
        finally:
            aw._config = old_cfg
            aw._state = old_state

    def test_rate_limiter_rejects_no_send_no_cooldown(self):
        st = self._triggerable_state("123")
        bot, groups, rule_switch, svc = self._make_fakes(["123"])
        rate_limiter = MagicMock()
        rate_limiter.allow.return_value = False

        self._run(bot, groups, rule_switch, svc, st, rate_limiter=rate_limiter)

        rate_limiter.allow.assert_called_once_with(
            _RULE_BOREDOM, "boredom_timer", group_id="123"
        )
        svc.generate_reply.assert_not_called()
        bot.send_group_msg.assert_not_called()
        assert "123" not in st._last_boredom_trigger

    def test_rule_switch_disabled_skips_group(self):
        st = self._triggerable_state("123")
        bot, groups, rule_switch, svc = self._make_fakes(["123"])
        rule_switch.is_enabled.return_value = False

        self._run(bot, groups, rule_switch, svc, st)

        # rule_switch 判定在 LLM 可用性检查之前：整个群被跳过
        svc.get_group_settings.assert_not_called()
        svc.generate_reply.assert_not_called()
        bot.send_group_msg.assert_not_called()
        assert "123" not in st._last_boredom_trigger

    def test_llm_config_load_error_skips_group(self):
        """svc.config.load_error 为真时 _is_group_llm_enabled 直接拒绝（位于 rule_switch
        之后、沉寂判定之前）：跳过该群，不生成、不发送、不标冷却。"""
        st = self._triggerable_state("123")
        bot, groups, rule_switch, svc = self._make_fakes(["123"])
        svc.config.load_error = "全部 provider 均被跳过"

        self._run(bot, groups, rule_switch, svc, st)

        svc.generate_reply.assert_not_called()
        bot.send_group_msg.assert_not_called()
        assert "123" not in st._last_boredom_trigger

    def test_generate_reply_exception_warns_and_continues(self, caplog):
        async def _gen(group_id, **_kwargs):
            if group_id == "123":
                raise RuntimeError("llm boom")
            return {"reply": f"reply-{group_id}"}

        st = self._triggerable_state("123", "456")
        bot, groups, rule_switch, svc = self._make_fakes(
            ["123", "456"], generate_reply=AsyncMock(side_effect=_gen)
        )
        stats_tracker = MagicMock()

        import logging
        with caplog.at_level(logging.WARNING, logger="quickquip.chat.awakening"):
            self._run(bot, groups, rule_switch, svc, st, stats_tracker=stats_tracker)

        # 失败群：warning 已记、不发送、不标冷却、不写统计
        assert any(
            r.levelno == logging.WARNING and "123" in r.getMessage()
            for r in caplog.records
        )
        # 后续群仍被正常处理
        bot.send_group_msg.assert_awaited_once_with(group_id=456, message="reply-456")
        assert "123" not in st._last_boredom_trigger
        assert "456" in st._last_boredom_trigger
        stats_tracker.record_trigger.assert_called_once_with("456", _RULE_BOREDOM)

    def test_send_exception_no_cooldown_no_stats(self):
        st = self._triggerable_state("123")
        bot, groups, rule_switch, svc = self._make_fakes(
            ["123"], send=AsyncMock(side_effect=RuntimeError("send boom"))
        )
        stats_tracker = MagicMock()

        self._run(bot, groups, rule_switch, svc, st, stats_tracker=stats_tracker)

        bot.send_group_msg.assert_awaited_once()
        # 冷却标记在 send 成功之后：send 抛异常 → 不标冷却、不写统计、不缓存 bot 消息
        assert "123" not in st._last_boredom_trigger
        stats_tracker.record_trigger.assert_not_called()
        assert st.bot_messages.get_recent("123") == []

    def test_mixed_groups_send_failure_states_independent(self):
        async def _send(group_id, message):
            if group_id == 456:  # send_group_msg 收到的是 int(gid)
                raise RuntimeError("send boom")

        st = self._triggerable_state("456", "789")
        bot, groups, rule_switch, svc = self._make_fakes(
            ["456", "789"], send=AsyncMock(side_effect=_send)
        )
        stats_tracker = MagicMock()

        self._run(bot, groups, rule_switch, svc, st, stats_tracker=stats_tracker)

        # 首群 send 失败不阻塞次群；两群状态各自独立
        assert bot.send_group_msg.await_count == 2
        assert "456" not in st._last_boredom_trigger
        assert "789" in st._last_boredom_trigger
        stats_tracker.record_trigger.assert_called_once_with("789", _RULE_BOREDOM)
