"""summaries-health 路由：总结族生成健康度聚合（1.15.2 CE 线）。"""
from __future__ import annotations

from datetime import datetime, timezone

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


def _insert_event(store: LLMUsageStore, *, feature: str, state: str, finish: str | None, model: str = "m1"):
    store.record({
        "provider_id": "p", "protocol": "openai", "model": model, "feature": feature,
        "group_id": "10001", "state": state, "finish_reason": finish, "stream": 0,
        "cost_usd": 0.01, "duration_ms": 1000.0,
    })


def test_summaries_health_aggregates_features_and_finish_reasons(temp_usage_store):
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP")
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="MAX_TOKENS", model="flash")
    _insert_event(temp_usage_store, feature="summary", state="error", finish=None)
    _insert_event(temp_usage_store, feature="chat", state="ok", finish="STOP")  # 不在总结族，排除

    result = summaries_route.summaries_health(days=7)

    by_key = {(row["feature"], row["state"]): row["calls"] for row in result["features"]}
    assert by_key == {("summary", "ok"): 2, ("summary", "error"): 1}
    finishes = {
        (row["model"], row["finish_reason"]): row["calls"]
        for row in result["finish_reasons"]
    }
    assert finishes == {("m1", "STOP"): 1, ("flash", "MAX_TOKENS"): 1}
    assert result["groups"][0]["failed"] == 1


def test_summaries_health_works_before_any_llm_call(temp_usage_store):
    """升级窗口场景：库刚建（无任何事件、迁移仅由本路由触发）不 500。"""
    result = summaries_route.summaries_health(days=7)
    assert result["features"] == []
    assert result["finish_reasons"] == []
    assert result["groups"] == []
