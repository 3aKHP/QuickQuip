"""summaries-health 路由：总结族生成健康度聚合（1.15.2 CE 线）。"""
from __future__ import annotations


import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import summaries as summaries_route  # noqa: E402
from quickquip.llm.usage_store import LLMUsageStore  # noqa: E402


@pytest.fixture()
def temp_usage_store(monkeypatch, tmp_path):
    import quickquip.llm.usage_store as usage_store_module

    fake = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr(usage_store_module, "usage_store", fake)
    return fake


def _insert_event(
    store: LLMUsageStore, *, feature: str, state: str, finish: str | None,
    outcome: str | None = None, model: str = "m1",
):
    store.record({
        "provider_id": "p", "protocol": "openai", "model": model, "feature": feature,
        "group_id": "10001", "state": state, "finish_reason": finish, "stream": 0,
        "response_outcome": outcome, "cost_usd": 0.01, "duration_ms": 1000.0,
    })


def test_summaries_health_aggregates_features_and_finish_reasons(temp_usage_store):
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP", outcome="accepted")
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="MAX_TOKENS", outcome="discarded_finish", model="flash")
    _insert_event(temp_usage_store, feature="summary", state="error", finish=None, outcome="provider_error")
    _insert_event(temp_usage_store, feature="summary", state="cancelled", finish=None, outcome="cancelled")
    _insert_event(temp_usage_store, feature="briefing", state="ok", finish="STOP")
    _insert_event(temp_usage_store, feature="chat", state="ok", finish="STOP")  # 不在总结族，排除

    result = summaries_route.summaries_health(days=7)

    by_key = {(row["feature"], row["outcome"]): row["calls"] for row in result["features"]}
    assert by_key == {
        ("briefing", "unknown"): 1,
        ("summary", "accepted"): 1,
        ("summary", "discarded_finish"): 1,
        ("summary", "provider_error"): 1,
        ("summary", "cancelled"): 1,
    }
    finishes = {
        (row["model"], row["finish_reason"]): row["calls"]
        for row in result["finish_reasons"]
    }
    assert finishes == {("m1", "STOP"): 1, ("flash", "MAX_TOKENS"): 1}
    summary_group = next(row for row in result["groups"] if row["feature"] == "summary")
    assert summary_group["accepted"] == 1
    assert summary_group["failed"] == 2
    assert summary_group["cancelled"] == 1
    assert summary_group["unknown"] == 0
    assert summary_group["calls"] == sum(summary_group[key] for key in ("accepted", "failed", "cancelled", "unknown"))


def test_summaries_health_works_before_any_llm_call(temp_usage_store):
    """升级窗口场景：库刚建（无任何事件、迁移仅由本路由触发）不 500。"""
    result = summaries_route.summaries_health(days=7)
    assert result["features"] == []
    assert result["finish_reasons"] == []
    assert result["groups"] == []


async def test_real_cascade_persists_discarded_and_accepted_hops(temp_usage_store, monkeypatch):
    from quickquip.llm.config import PricingRates, ProviderConfig
    from quickquip.llm.summarize import _run_summary_cascade
    from quickquip.llm.usage import drain_usage_tasks, usage_scope
    from tests.fixtures.provider_fakes import FakeClaudeClient

    config = ProviderConfig(
        id="p", protocol="claude", base_url="https://example.com/v1",
        api_key_env="K", default_model="m", models=["m"],
    )
    responses = iter([
        {"content": [{"type": "text", "text": "残稿"}], "stop_reason": "max_tokens",
         "usage": {"input_tokens": 100, "output_tokens": 50}},
        {"content": [{"type": "text", "text": "完整日报"}], "stop_reason": "end_turn",
         "usage": {"input_tokens": 100, "output_tokens": 50}},
    ])
    monkeypatch.setattr(
        "quickquip.llm.summarize.build_provider_client",
        lambda effective: FakeClaudeClient(effective, next(responses)),
    )
    monkeypatch.setattr(
        "quickquip.llm.usage._configured_pricing",
        lambda: {"m": PricingRates(input_per_mtok=1.0, output_per_mtok=2.0)},
    )
    with usage_scope("summary", group_id="10001"):
        text, model = await _run_summary_cascade(
            "summary", "10001", [("p", "m", config)] * 2,
            "system", "chat", lambda log, truncated: log,
            temperature=0.2, max_output_tokens=100,
        )
    await drain_usage_tasks()
    assert (text, model) == ("完整日报", "p/m")
    result = summaries_route.summaries_health(days=7)
    rows = {row["outcome"]: row for row in result["features"]}
    assert set(rows) == {"accepted", "discarded_finish"}
    assert rows["accepted"]["calls"] == rows["discarded_finish"]["calls"] == 1
    assert rows["accepted"]["cost_usd"] == rows["discarded_finish"]["cost_usd"] > 0
    assert result["groups"][0]["calls"] == 2
    assert result["groups"][0]["accepted"] == result["groups"][0]["failed"] == 1
