from datetime import datetime, timedelta, timezone

from quickquip.app.web.routes import llm_usage as route
from quickquip.llm.usage_store import LLMUsageStore


def _seed(store: LLMUsageStore) -> None:
    store.record({"provider_id": "claude-main", "protocol": "claude", "model": "sonnet",
                  "feature": "chat", "group_id": "g1", "stream": 1,
                  "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001,
                  "priced": 1, "state": "ok"})
    store.record({"provider_id": "gemini-main", "protocol": "gemini", "model": "pro",
                  "feature": "vision", "group_id": None, "stream": 1,
                  "input_tokens": 200, "output_tokens": 30, "cost_usd": 0.0005,
                  "priced": 1, "state": "ok"})
    store.record({"provider_id": "kimi", "protocol": "claude", "model": "kimi-k2",
                  "feature": "chat", "group_id": "g1", "stream": 1,
                  "input_tokens": 300, "output_tokens": 40, "cost_usd": 0.0,
                  "priced": 0, "state": "ok"})
    store.record({"provider_id": "claude-main", "protocol": "claude", "model": "sonnet",
                  "feature": "chat", "group_id": "g1", "stream": 1,
                  "cost_usd": 0.0, "priced": 1, "state": "error", "error_message": "boom"})


def _cutoff_days(days: int = 7) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_summary_aggregates_cost_tokens_unpriced_errors(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    s = route._summary(store, _cutoff_days(7))
    assert s["total_cost"] == round(0.001 + 0.0005, 6)  # 仅 ok 行
    assert s["total_calls"] == 3  # 3 行 ok（error 不计）
    assert s["total_tokens"] == 100 + 50 + 200 + 30 + 300 + 40
    assert s["unpriced_calls_count"] == 1
    assert s["unpriced_tokens_total"] == 300 + 40
    assert s["error_count"] == 1
    assert s["cancelled_count"] == 0
    assert "下界" in s["bounds_note"]


def test_summary_group_by_provider_orders_by_cost(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    s = route._summary(store, _cutoff_days(7))
    keys = [b["key"] for b in s["by_provider"]]
    assert keys[0] == "claude-main"  # 0.001 最高
    assert "gemini-main" in keys
    # 未归因 group：vision 行 group_id=None → "(未归因)"
    group_keys = [b["key"] for b in s["by_group"]]
    assert "(未归因)" in group_keys


def test_timeline_buckets_by_day(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    tl = route._timeline(store, _cutoff_days(7))
    assert len(tl) == 1  # 全部今天
    assert tl[0]["date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert tl[0]["cost"] == round(0.001 + 0.0005, 6)


def test_summary_empty_store(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    s = route._summary(store, _cutoff_days(7))
    assert s["total_cost"] == 0.0
    assert s["total_calls"] == 0
    assert s["by_provider"] == []
