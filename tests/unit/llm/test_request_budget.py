"""请求预算（§8.3）单测：原生块计量、预算解析优先级与重放预算推导。"""
from __future__ import annotations

import pytest

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.context_windows import (
    lookup_builtin_context_window,
    resolve_context_window,
)
from quickquip.llm.provider import LLMRequest
from quickquip.llm.request_budget import (
    RequestBudgetExceeded,
    check_request_budget,
    count_wire_items,
    derive_replay_budget,
    enforce_request_budget,
    estimate_request_tokens,
    resolve_input_budget,
)
from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.token_estimate import (
    NATIVE_MEDIA_FLAT_TOKENS,
    estimate_native_blocks_tokens,
    estimate_tokens,
)


def _provider(**overrides) -> ProviderConfig:
    defaults = dict(
        id="p1",
        protocol="openai",
        base_url="https://example.test",
        api_key_env="K",
        default_model="custom-model-x",
        models=["custom-model-x"],
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def _request(messages, *, model: str = "custom-model-x", max_output: int = 800) -> LLMRequest:
    return LLMRequest(
        model=model,
        system_prompt="",
        messages=messages,
        temperature=0.8,
        max_output_tokens=max_output,
    )


# ── 原生块计量 ───────────────────────────────────────────────────


def test_estimate_request_tokens_counts_native_content():
    thinking = "思" * 4000
    native_msg = LLMConversationMessage(
        role="assistant",
        content="",
        native_content=[{"type": "thinking", "thinking": thinking, "signature": "sig"}],
    )
    plain_msg = LLMConversationMessage(role="assistant", content="")
    with_native = estimate_request_tokens(_request([native_msg]))
    without_native = estimate_request_tokens(_request([plain_msg]))
    assert with_native >= without_native + estimate_tokens(thinking)


def test_estimate_request_tokens_counts_thinking_blocks():
    thinking = "理" * 2000
    msg = LLMConversationMessage(
        role="assistant", content="", thinking_blocks=[{"type": "reasoning", "reasoning_content": thinking}]
    )
    base = estimate_request_tokens(_request([LLMConversationMessage(role="assistant", content="")]))
    assert estimate_request_tokens(_request([msg])) >= base + estimate_tokens(thinking)


def test_estimate_request_tokens_media_not_double_counted_in_native():
    media_block = {"inlineData": {"mimeType": "image/png", "data": "A" * 100_000}}
    msg = LLMConversationMessage(role="user", content="", native_content=[media_block])
    assert estimate_request_tokens(_request([msg])) <= NATIVE_MEDIA_FLAT_TOKENS + 64


def test_count_wire_items_counts_native_and_thinking_parts():
    msg = LLMConversationMessage(
        role="assistant",
        content="",
        thinking_blocks=[{"type": "reasoning", "reasoning_content": "x"}],
        native_content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
    )
    assert count_wire_items(_request([msg])) == 4  # 1 消息 + 1 thinking + 2 native parts


# ── 窗口解析 ─────────────────────────────────────────────────────


def test_resolve_context_window_explicit_beats_builtin():
    explicit = {"gpt-4o": 60_000}
    assert resolve_context_window(explicit, "gpt-4o") == 60_000
    assert lookup_builtin_context_window("gpt-4o-mini") == 128_000


def test_resolve_context_window_builtin_prefix_and_unknown():
    assert resolve_context_window({}, "claude-sonnet-4-5-20260101") == 200_000
    assert resolve_context_window({}, "GEMINI-2.5-PRO") == 1_000_000
    assert resolve_context_window({}, "relay-private-model") is None


# ── 输入预算（仲裁者）解析 ────────────────────────────────────────


def test_resolve_input_budget_provider_explicit_wins():
    config = LLMConfig()
    provider = _provider(request_input_token_budget=50_000)
    assert resolve_input_budget(config, provider, "custom-model-x") == 50_000


def test_resolve_input_budget_window_derived_when_known():
    config = LLMConfig()
    provider = _provider(model_context_windows={"custom-model-x": 262_144})
    # 窗口 − (max_output 800 + 1024)
    assert resolve_input_budget(config, provider, "custom-model-x") == 262_144 - 800 - 1024


def test_resolve_input_budget_runtime_default_when_unknown():
    config = LLMConfig()
    provider = _provider()
    assert resolve_input_budget(config, provider, "custom-model-x") == 96_000


def test_resolve_input_budget_window_can_shrink_below_runtime_default():
    config = LLMConfig()
    provider = _provider(model_context_windows={"custom-model-x": 60_000})
    assert resolve_input_budget(config, provider, "custom-model-x") == 60_000 - 800 - 1024


# ── 重放预算推导 ─────────────────────────────────────────────────


def test_derive_replay_budget_provider_override_verbatim():
    config = LLMConfig()
    provider = _provider(agent_replay_loop_tokens=8_192)
    assert derive_replay_budget(config, provider, "custom-model-x") == 8_192


def test_derive_replay_budget_unknown_window_keeps_runtime_value():
    config = LLMConfig()
    provider = _provider()
    # capacity unknown：推导耗尽后落在 runtime 下限（4096），与旧行为一致。
    assert derive_replay_budget(config, provider, "custom-model-x") == 4_096


def test_derive_replay_budget_scales_with_window():
    config = LLMConfig()
    provider_256k = _provider(model_context_windows={"custom-model-x": 262_144})
    assert derive_replay_budget(config, provider_256k, "custom-model-x") > 100_000
    provider_1m = _provider(model_context_windows={"custom-model-x": 1_000_000})
    assert derive_replay_budget(config, provider_1m, "custom-model-x") > 500_000


def test_derive_replay_budget_smaller_epoch_cap_frees_replay():
    config = LLMConfig()
    wide = _provider(
        model_context_windows={"custom-model-x": 262_144},
        epoch_hot_target_tokens=32_000,
        epoch_cap_tokens=64_000,
    )
    narrow = _provider(
        model_context_windows={"custom-model-x": 262_144},
        epoch_hot_target_tokens=16_000,
        epoch_cap_tokens=32_000,
    )
    assert derive_replay_budget(config, narrow, "custom-model-x") > derive_replay_budget(
        config, wide, "custom-model-x"
    )


def test_derive_replay_budget_runtime_value_is_floor():
    config = LLMConfig()
    config.runtime.agent_replay_loop_tokens = 200_000
    provider = _provider()  # capacity unknown：仲裁者 96000，推导值更小
    assert derive_replay_budget(config, provider, "custom-model-x") == 200_000


# ── 检查与拒绝 ───────────────────────────────────────────────────


def test_check_request_budget_capacity_flag_and_margin():
    config = LLMConfig()
    unknown = _request(
        [LLMConversationMessage(role="user", content="a" * 10_000)]
    )
    check = check_request_budget(config, _provider(), unknown)
    assert check.capacity_unknown is True
    assert check.context_window is None

    known_provider = _provider(model_context_windows={"custom-model-x": 200_000})
    check = check_request_budget(config, known_provider, unknown)
    assert check.capacity_unknown is False
    # 比例余量：窗口 − 输出预留 − max(1024, 10% 估算)
    margin = max(1024, int(check.estimated_input_tokens * 0.10))
    assert check.context_window == 200_000 - 800 - 1024 - margin


def test_enforce_rejects_over_budget_payload():
    config = LLMConfig()
    provider = _provider(request_input_token_budget=2_000)
    request = _request([LLMConversationMessage(role="user", content="a" * 100_000)])
    with pytest.raises(RequestBudgetExceeded, match="超出应用输入预算"):
        enforce_request_budget(config, provider, request)


def test_enforce_rejects_native_payload_over_window():
    config = LLMConfig()
    # 窗口 8k + 显式预算放宽到 50k：原生块计量后超窗口，走窗口拒绝路径。
    provider = _provider(
        request_input_token_budget=50_000,
        model_context_windows={"custom-model-x": 8_000},
    )
    request = _request(
        [
            LLMConversationMessage(
                role="assistant",
                content="",
                native_content=[
                    {"type": "thinking", "thinking": "思" * 60_000, "signature": "sig"}
                ],
            )
        ]
    )
    with pytest.raises(RequestBudgetExceeded, match="模型上下文余量"):
        enforce_request_budget(config, provider, request)


def test_native_block_unknown_shape_still_counted():
    blocks = [{"type": "future_kind", "payload": "x" * 2_000}]
    assert estimate_native_blocks_tokens(blocks) > 0
