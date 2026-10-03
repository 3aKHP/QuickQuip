"""思考档位归一化层单测：家族识别、协议映射、钳制与 fail-visible。"""
from __future__ import annotations

import logging

import pytest

from quickquip.llm.config import ProviderConfig
from quickquip.llm.thinking import resolve_thinking


def _provider(protocol: str, **overrides) -> ProviderConfig:
    defaults = dict(
        id="p1",
        protocol=protocol,
        base_url="https://e.test/v1",
        api_key_env="K",
        default_model="m",
        models=["m"],
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def test_empty_tier_sends_nothing():
    assert resolve_thinking("", _provider("openai"), "gpt-5.5") is None
    assert resolve_thinking(None, _provider("claude"), "claude-opus-4-7") is None
    assert resolve_thinking("  ", _provider("gemini"), "gemini-3.7-flash") is None


def test_invalid_tier_raises():
    with pytest.raises(ValueError):
        resolve_thinking("extreme", _provider("openai"), "gpt-5.5")


def test_openai_responses_not_in_this_layer():
    # openai_responses 的档位走 profile 词表层（request.reasoning_control）。
    assert resolve_thinking("high", _provider("openai_responses"), "gpt-6-astra") is None


# ── openai chat：家族钳制表 ──────────────────────────────────────


@pytest.mark.parametrize(
    ("tier", "wire"),
    [
        ("low", "low"),
        ("medium", "high"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "max"),
        ("ultra", "max"),
    ],
)
def test_openai_three_tier_families(tier, wire):
    for model in ("deepseek-v4-pro", "glm-5.3", "kimi-k3"):
        directive = resolve_thinking(tier, _provider("openai"), model)
        assert directive.kind == "openai_effort"
        assert directive.effort == wire
        assert directive.requested_tier == tier
        assert directive.clamped == (wire != tier)


def test_openai_deepseek_carries_thinking_switch():
    directive = resolve_thinking("high", _provider("openai"), "deepseek-v4-pro")
    assert directive.thinking_type_enabled is True
    # GLM/Kimi 恒思考或仅需档位字段，不附带开关
    assert resolve_thinking("high", _provider("openai"), "glm-5.3").thinking_type_enabled is False


@pytest.mark.parametrize(
    ("tier", "wire"),
    [("low", "low"), ("medium", "medium"), ("xhigh", "xhigh"), ("max", "max"), ("ultra", "max")],
)
def test_openai_minimax_five_tier(tier, wire):
    directive = resolve_thinking(tier, _provider("openai"), "MiniMax-M3")
    assert directive.effort == wire


def test_openai_xai_caps_at_xhigh():
    assert resolve_thinking("xhigh", _provider("openai"), "grok-4.5").effort == "xhigh"
    capped = resolve_thinking("max", _provider("openai"), "grok-4.5")
    assert capped.effort == "xhigh"
    assert capped.clamped is True


def test_openai_unknown_backend_passthrough_ultra_to_max():
    directive = resolve_thinking("high", _provider("openai"), "gpt-5.6-luna")
    assert directive.effort == "high"
    assert directive.clamped is False
    ultra = resolve_thinking("ultra", _provider("openai"), "qwen3.8-max")
    assert ultra.effort == "max"
    assert ultra.clamped is True


def test_openai_family_detection_strips_router_prefix():
    # openrouter 形态：x-ai/grok-4.20 → grok 家族钳制
    directive = resolve_thinking("max", _provider("openai"), "x-ai/grok-4.20")
    assert directive.effort == "xhigh"


# ── claude：代际分派 ─────────────────────────────────────────────


def test_claude_47_adaptive_full_vocab():
    directive = resolve_thinking("xhigh", _provider("claude"), "claude-opus-4-7")
    assert directive.kind == "claude_adaptive"
    assert directive.effort == "xhigh"
    ultra = resolve_thinking("ultra", _provider("claude"), "claude-opus-4-8")
    assert ultra.effort == "max"
    assert ultra.clamped is True


def test_claude_46_has_max_but_no_xhigh():
    clamped = resolve_thinking("xhigh", _provider("claude"), "claude-sonnet-4-6")
    assert clamped.kind == "claude_adaptive"
    assert clamped.effort == "high"
    assert clamped.clamped is True
    assert resolve_thinking("max", _provider("claude"), "claude-opus-4-6").effort == "max"


@pytest.mark.parametrize(
    ("tier", "budget"),
    [
        ("low", 1024),  # 表值 1000 受 Anthropic ≥1024 约束收 1024
        ("medium", 2000),
        ("high", 8000),
        ("xhigh", 16000),
        ("max", 32000),
        ("ultra", 32000),
    ],
)
def test_claude_45_legacy_budget_table(tier, budget):
    directive = resolve_thinking(
        tier, _provider("claude"), "claude-haiku-4-5-20251001", max_output_tokens=64000
    )
    assert directive.kind == "claude_budget"
    assert directive.budget_tokens == budget
    assert directive.clamped is False


def test_claude_budget_clamped_below_max_tokens():
    directive = resolve_thinking(
        "high", _provider("claude"), "claude-sonnet-4-5", max_output_tokens=4000
    )
    assert directive.budget_tokens == 3999
    assert directive.clamped is True


def test_claude_budget_unsatisfiable_floor_sends_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.thinking"):
        directive = resolve_thinking(
            "low", _provider("claude", id="p-floor"), "claude-sonnet-4-5",
            max_output_tokens=1024,
        )
    assert directive is None
    assert any("放弃发送" in record.message for record in caplog.records)


def test_claude_non_anthropic_backend_sends_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger="quickquip.llm.thinking"):
        directive = resolve_thinking(
            "high", _provider("claude", id="p-kimi"), "kimi-for-coding"
        )
    assert directive is None
    assert any("不发送" in record.message for record in caplog.records)


def test_claude_unparseable_model_treated_as_current_shape():
    directive = resolve_thinking("xhigh", _provider("claude"), "claude-latest")
    assert directive.kind == "claude_adaptive"
    assert directive.effort == "xhigh"


# ── gemini：代际分派 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tier", "level"),
    [
        ("low", "LOW"),
        ("medium", "MEDIUM"),
        ("high", "HIGH"),
        ("xhigh", "HIGH"),
        ("max", "HIGH"),
        ("ultra", "HIGH"),
    ],
)
def test_gemini_3x_thinking_level(tier, level):
    directive = resolve_thinking(tier, _provider("gemini"), "gemini-3.7-flash")
    assert directive.kind == "gemini_level"
    assert directive.effort == level


def test_gemini_25_thinking_budget():
    directive = resolve_thinking("medium", _provider("gemini"), "gemini-2.5-flash")
    assert directive.kind == "gemini_budget"
    assert directive.budget_tokens == 2000
    assert resolve_thinking("ultra", _provider("gemini"), "gemini-2.5-pro").budget_tokens == 32000


def test_gemini_non_gemini_model_sends_nothing():
    assert resolve_thinking("high", _provider("gemini"), "gpt-5.5") is None
