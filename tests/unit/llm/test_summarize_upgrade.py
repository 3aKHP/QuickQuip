"""1.15.2 B/C 线：宽输出窗口、窗口推导的聊天记录预算、级联留档语义。"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from quickquip.llm.config import (
    DailySummaryConfig,
    LLMConfig,
    PersonaConfig,
    ProviderConfig,
    RuntimeConfig,
)
from quickquip.llm.provider import LLMResponse
from quickquip.llm.summarize import (
    _FALLBACK_CHAT_LOG_CHARS,
    _chat_log_char_budget,
    _resolve_cascade,
    generate_daily_summary,
)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class _StubClient:
    def __init__(self, response: LLMResponse):
        self.response = response
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        return self.response


def _provider(pid: str, model: str, windows: dict | None = None) -> ProviderConfig:
    return ProviderConfig(
        id=pid, protocol="openai", base_url="https://example.test/v1",
        api_key_env="KEY", default_model=model, models=[model],
        model_context_windows=windows or {},
    )


def _llm_config(providers: list[ProviderConfig]) -> LLMConfig:
    return LLMConfig(
        runtime=RuntimeConfig(default_provider=providers[0].id, default_persona="default"),
        providers={p.id: p for p in providers},
        personas={"default": PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。")},
    )


def test_chat_log_budget_derived_from_largest_window():
    wide = _provider("a", "big", {"big": 1_048_576})
    narrow = _provider("b", "small", {"small": 128_000})
    resolved = _resolve_cascade(["a/big", "b/small"], _llm_config([wide, narrow]), "a", "big")
    budget = _chat_log_char_budget(resolved, max_output_tokens=16384)
    assert budget == 1_048_576 - 16384 - 8192


def test_chat_log_budget_falls_back_when_capacity_unknown():
    unknown = _provider("a", "mystery")
    resolved = _resolve_cascade(["a/mystery"], _llm_config([unknown]), "a", "mystery")
    assert _chat_log_char_budget(resolved, max_output_tokens=16384) == _FALLBACK_CHAT_LOG_CHARS


def test_resolve_cascade_skips_invalid_and_disabled():
    disabled = ProviderConfig(
        id="b", protocol="openai", base_url="https://example.test/v1",
        api_key_env="KEY", default_model="m2", models=["m2"], enabled=False,
    )
    cfg = _llm_config([_provider("a", "m1"), disabled])
    resolved = _resolve_cascade(["bad-entry", "missing/m9", "b/m2", "a/m1"], cfg, "a", "m1")
    assert [(pid, model) for pid, model, _ in resolved] == [("a", "m1")]


def test_resolve_cascade_at_default_placeholder():
    resolved = _resolve_cascade(["@default"], _llm_config([_provider("a", "m1")]), "a", "m1")
    assert [(pid, model) for pid, model, _ in resolved] == [("a", "m1")]


@pytest.mark.asyncio
async def test_daily_summary_uses_16384_output_window(monkeypatch):
    stub = _StubClient(LLMResponse(text="日报正文", model="m1", finish_reason="stop"))
    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", lambda p: stub)
    await generate_daily_summary(
        [{"ts": 1600000000.0, "sender": "u", "text": "消息"}],
        PersonaConfig(id="default", display_name="默认", system_prompt="s"),
        "10001", date_label="2026-09-09", name_table={},
        summary_config=DailySummaryConfig(),
        llm_config=_llm_config([_provider("a", "m1")]),
        default_provider_id="a", default_model="m1", local_tz=LOCAL_TZ,
    )
    assert stub.requests[0].max_output_tokens == 16384


@pytest.mark.asyncio
async def test_daily_summary_wide_window_log_not_truncated(monkeypatch):
    stub = _StubClient(LLMResponse(text="日报", model="big", finish_reason="stop"))
    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", lambda p: stub)
    # 40 万字符日志：旧 300k 上限会截断，1M 窗口推导后应完整进入。
    big_log = [{"ts": 1600000000.0 + i, "sender": f"u{i%10}", "text": "聊" * 100} for i in range(4000)]
    await generate_daily_summary(
        big_log,
        PersonaConfig(id="default", display_name="默认", system_prompt="s"),
        "10001", date_label="2026-09-09", name_table={},
        summary_config=DailySummaryConfig(),
        llm_config=_llm_config([_provider("a", "big", {"big": 1_048_576})]),
        default_provider_id="a", default_model="big", local_tz=LOCAL_TZ,
    )
    content = stub.requests[0].messages[0].content
    assert "已截取最近部分" not in content
    assert len(content) > 300_000


@pytest.mark.asyncio
async def test_daily_summary_all_models_unresolvable_raises():
    with pytest.raises(RuntimeError, match="级联无可用模型"):
        await generate_daily_summary(
            [{"ts": 1600000000.0, "sender": "u", "text": "m"}],
            PersonaConfig(id="default", display_name="默认", system_prompt="s"),
            "10001", date_label="2026-09-09", name_table={},
            summary_config=DailySummaryConfig(model_cascade=["missing/m1"]),
            llm_config=_llm_config([_provider("a", "m1")]),
            default_provider_id="a", default_model="m1", local_tz=LOCAL_TZ,
        )
