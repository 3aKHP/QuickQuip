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
    _hop_limits,
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


def test_hop_limits_derived_from_own_window():
    wide = _provider("a", "big", {"big": 1_048_576})
    budget, output = _hop_limits(wide, "big", max_output_tokens=16384)
    assert budget == 1_048_576 - 16384 - 8192
    assert output == 16384  # 宽窗口不钳制输出


def test_hop_limits_small_window_clamps_output_and_floors_budget():
    # 小窗口模型：输出按窗口//8 钳制，预算 flooring 到 8192（不按 unknown 回退 300k）。
    small = _provider("a", "s", {"s": 32_000})
    budget, output = _hop_limits(small, "s", max_output_tokens=16384)
    assert budget == 8192
    assert output == 4000


def test_hop_limits_capacity_unknown_falls_back():
    unknown = _provider("a", "mystery")
    budget, output = _hop_limits(unknown, "mystery", max_output_tokens=16384)
    assert budget == _FALLBACK_CHAT_LOG_CHARS
    assert output == 16384


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


@pytest.mark.asyncio
async def test_daily_summary_truncates_per_hop_for_narrow_fallback(monkeypatch):
    """宽窗口主跳吃全量；窄窗口回退跳按自己的窗口缩量，而不是必溢出。"""
    requests_by_model: dict[str, list] = {}

    def _builder(provider):
        class _Client:
            async def complete(self, request):
                requests_by_model.setdefault(request.model, []).append(request)
                if request.model == "big":
                    from quickquip.llm.provider import LLMProviderError
                    raise LLMProviderError("primary down")
                from plugins.llm_provider import LLMResponse
                return LLMResponse(text="窄窗日报", model=request.model, finish_reason="stop")
        return _Client()

    monkeypatch.setattr("quickquip.llm.summarize.build_provider_client", _builder)
    big_log = [{"ts": 1600000000.0 + i, "sender": f"u{i%10}", "text": "聊" * 100} for i in range(5000)]
    content, model_used = await generate_daily_summary(
        big_log,
        PersonaConfig(id="default", display_name="默认", system_prompt="s"),
        "10001", date_label="2026-09-09", name_table={},
        summary_config=DailySummaryConfig(model_cascade=["a/big", "b/small"]),
        llm_config=_llm_config([
            _provider("a", "big", {"big": 1_048_576}),
            _provider("b", "small", {"small": 200_000}),
        ]),
        default_provider_id="a", default_model="big", local_tz=LOCAL_TZ,
    )
    assert model_used == "b/small"
    assert content == "窄窗日报"
    big_req = requests_by_model["big"][0]
    small_req = requests_by_model["small"][0]
    assert len(big_req.messages[0].content) > 400_000  # 主跳全量
    assert len(small_req.messages[0].content) < 200_000  # 回退跳缩量（窗口推导）
    assert "已截取最近部分" in small_req.messages[0].content
