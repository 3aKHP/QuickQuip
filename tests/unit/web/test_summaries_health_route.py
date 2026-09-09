"""summaries-health 路由与报文「生成日志」归因（1.15.3 线）。"""
from __future__ import annotations


import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import summaries as summaries_route  # noqa: E402
from quickquip.chat.daily_summary import DailySummaryStore  # noqa: E402
from quickquip.llm.usage_store import LLMUsageStore  # noqa: E402


@pytest.fixture()
def temp_usage_store(monkeypatch, tmp_path):
    import quickquip.llm.usage_store as usage_store_module

    fake = LLMUsageStore(tmp_path / "u.db")
    monkeypatch.setattr(usage_store_module, "usage_store", fake)
    return fake


@pytest.fixture()
def temp_summaries_db(monkeypatch, tmp_path):
    store = DailySummaryStore(tmp_path / "s.db")
    monkeypatch.setattr(summaries_route, "_DB", tmp_path / "s.db")
    return store


def _insert_event(
    store: LLMUsageStore, *, feature: str, state: str, finish: str | None,
    outcome: str | None = None, model: str = "m1", run_id: str | None = None,
    group_id: str = "10001", ts: str | None = None,
):
    store.record({
        "provider_id": "p", "protocol": "openai", "model": model, "feature": feature,
        "group_id": group_id, "state": state, "finish_reason": finish, "stream": 0,
        "response_outcome": outcome, "cost_usd": 0.01, "duration_ms": 1000.0,
        "run_id": run_id, **({"ts": ts} if ts else {}),
    })


def test_summaries_health_aggregates_features(temp_usage_store):
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


def test_summaries_health_works_before_any_llm_call(temp_usage_store):
    """升级窗口场景：库刚建（无任何事件、迁移仅由本路由触发）不 500。"""
    result = summaries_route.summaries_health(days=7)
    assert result["features"] == []


def test_generation_log_prefers_run_id(temp_usage_store, temp_summaries_db):
    store = temp_summaries_db
    store.upsert("10001", "2026-05-03", "正文", "m1", run_id="run-1")
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="MAX_TOKENS",
                  outcome="discarded_finish", model="flash", run_id="run-1")
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", run_id="run-1")
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", run_id="run-other")

    result = summaries_route.summary_generation_log("10001", "2026-05-03")

    assert result["attribution"] == "run_id"
    assert result["run_id"] == "run-1"
    assert [h["response_outcome"] for h in result["hops"]] == ["discarded_finish", "accepted"]


def test_generation_log_falls_back_to_time_window(temp_usage_store, temp_summaries_db):
    """历史报文（无 run_id）按 (上一条报文, 本报文] 窗口归因。"""
    store = temp_summaries_db
    store.upsert("10001", "2026-05-02", "前一篇", "m1")  # 历史行，无 run_id
    store.upsert("10001", "2026-05-03", "本报文", "m1")
    prev = store.get("10001", "2026-05-02")["generated_at"]
    curr = store.get("10001", "2026-05-03")["generated_at"]

    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", ts=curr)                       # 窗口内（含边界）
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", ts=prev)                       # 上一条报文的跳，排除
    _insert_event(temp_usage_store, feature="chat", state="ok", finish="STOP", ts=curr)  # 非总结族
    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", group_id="20002", ts=curr)     # 别的群

    result = summaries_route.summary_generation_log("10001", "2026-05-03")

    assert result["attribution"] == "time_window"
    assert result["run_id"] is None
    assert len(result["hops"]) == 1
    assert result["hops"][0]["response_outcome"] == "accepted"


def test_generation_log_first_artifact_window_capped(temp_usage_store, temp_summaries_db):
    """首条报文没有上一条：窗口封顶 6 小时，更久之前的事件不归入。"""
    store = temp_summaries_db
    store.upsert("10001", "2026-05-03", "正文", "m1")
    curr = store.get("10001", "2026-05-03")["generated_at"]
    from datetime import datetime, timedelta
    old = (datetime.fromisoformat(curr) - timedelta(hours=7)).isoformat()

    _insert_event(temp_usage_store, feature="summary", state="ok", finish="STOP",
                  outcome="accepted", ts=old)

    result = summaries_route.summary_generation_log("10001", "2026-05-03")

    assert result["attribution"] == "time_window"
    assert result["hops"] == []


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
    with usage_scope("summary", group_id="10001", run_id="run-x"):
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
    # scope 里的 run_id 传播到级联每一跳的用量事件
    hops = temp_usage_store.list_generation_hops(run_id="run-x")
    assert len(hops) == 2
    assert [h["response_outcome"] for h in hops] == ["discarded_finish", "accepted"]
