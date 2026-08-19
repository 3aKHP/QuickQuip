from __future__ import annotations

from datetime import datetime

import pytest

from quickquip.chat.daily_briefing import DailyBriefingContext
from quickquip.llm.briefing import generate_daily_briefing
from quickquip.llm.config import DailyBriefingConfig, LLMConfig, PersonaConfig, ProviderConfig, RuntimeConfig
from quickquip.llm.provider import LLMResponse


class _StubClient:
    def __init__(self, response: LLMResponse):
        self.response = response
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return self.response


def _context() -> DailyBriefingContext:
    return DailyBriefingContext(
        period="noon",
        period_label="午报",
        now=datetime(2026, 5, 9, 12, 0),
        date_label="2026-05-09",
        weekday_label="六",
        current_time_label="12:00",
        window_label="2026-05-09 00:00 至 05-09 12:00",
        message_count=12,
        active_users=[],
        hot_words=[],
        sample_messages=[],
        news_items=[],
    )


def _llm_config() -> LLMConfig:
    provider_a = ProviderConfig(
        id="a",
        protocol="openai",
        base_url="https://example.test/v1",
        api_key_env="A_KEY",
        default_model="m1",
        models=["m1"],
    )
    provider_b = ProviderConfig(
        id="b",
        protocol="openai",
        base_url="https://example.test/v1",
        api_key_env="B_KEY",
        default_model="m2",
        models=["m2"],
    )
    runtime = RuntimeConfig(default_provider="a", default_persona="default")
    return LLMConfig(
        runtime=runtime,
        providers={"a": provider_a, "b": provider_b},
        personas={"default": PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。")},
        daily_briefing=DailyBriefingConfig(model_cascade=["a/m1", "b/m2"], max_output_chars=320),
    )


@pytest.mark.asyncio
async def test_daily_briefing_retries_on_max_tokens(monkeypatch):
    responses = [
        _StubClient(LLMResponse(text="第一条残稿", model="m1", finish_reason="MAX_TOKENS")),
        _StubClient(LLMResponse(text="第二条完整播报", model="m2", finish_reason="stop")),
    ]

    def _builder(provider):
        if provider.id == "a":
            return responses[0]
        return responses[1]

    monkeypatch.setattr("quickquip.llm.briefing.build_provider_client", _builder)

    content, model_used = await generate_daily_briefing(
        context=_context(),
        persona=PersonaConfig(id="default", display_name="默认", system_prompt="你是测试人格。"),
        group_id="1001",
        briefing_config=_llm_config().daily_briefing,
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
    )

    assert content == "第二条完整播报"
    assert model_used == "b/m2"
    assert responses[0].requests[0].max_output_tokens == 8192
    assert responses[1].requests[0].max_output_tokens == 8192


@pytest.mark.asyncio
async def test_daily_briefing_usage_scope_carries_persona(monkeypatch):
    calls: list[tuple] = []

    def _record(feature, **kwargs):
        calls.append((feature, kwargs))

    monkeypatch.setattr("quickquip.llm.briefing.set_usage_scope", _record)
    monkeypatch.setattr(
        "quickquip.llm.briefing.build_provider_client",
        lambda provider: _StubClient(LLMResponse(text="播报", model="m1", finish_reason="stop")),
    )

    await generate_daily_briefing(
        context=_context(),
        persona=PersonaConfig(id="nightwatch", display_name="守夜人", system_prompt="你是测试人格。"),
        group_id="1001",
        briefing_config=_llm_config().daily_briefing,
        llm_config=_llm_config(),
        default_provider_id="a",
        default_model="m1",
    )

    assert ("briefing", {"group_id": "1001", "persona_id": "nightwatch"}) in calls
