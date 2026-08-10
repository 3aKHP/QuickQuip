from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

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


def _seed_old(store: LLMUsageStore) -> None:
    """落一行并把 ts 改到 10 天前（cutoff 7d 应排除、30d 应包含）。"""
    store.record({"provider_id": "old-prov", "protocol": "claude", "model": "old",
                  "feature": "chat", "group_id": "g9", "stream": 1,
                  "input_tokens": 50, "output_tokens": 10, "cost_usd": 0.002,
                  "priced": 1, "state": "ok"})
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE llm_usage_events SET ts = ? WHERE provider_id = ?", (old_ts, "old-prov"))


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_summary_aggregates_cost_tokens_unpriced_errors(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    s = store.summary(_cutoff(7))
    assert s["total_cost"] == round(0.001 + 0.0005, 6)
    assert s["total_calls"] == 3
    assert s["total_tokens"] == 100 + 50 + 200 + 30 + 300 + 40
    assert s["unpriced_calls_count"] == 1
    assert s["error_count"] == 1
    assert s["cancelled_count"] == 0
    assert "下界" in s["bounds_note"]


def test_summary_group_by_orders_and_null_group(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    s = store.summary(_cutoff(7))
    assert s["by_provider"][0]["key"] == "claude-main"
    assert "(未归因)" in [b["key"] for b in s["by_group"]]


def test_summary_range_filter_excludes_old(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    _seed_old(store)
    assert store.summary(_cutoff(7))["total_calls"] == 3   # 旧行被排除
    assert store.summary(_cutoff(30))["total_calls"] == 4  # 旧行被纳入


def test_timeline_range_filter_and_date(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed(store)
    _seed_old(store)
    tl7 = store.timeline(_cutoff(7))
    assert len(tl7) == 1
    assert tl7[0]["date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tl30 = store.timeline(_cutoff(30))
    assert len(tl30) == 2  # 今天 + 10 天前


def test_summary_empty_store(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    s = store.summary(_cutoff(7))
    assert s["total_cost"] == 0.0
    assert s["total_calls"] == 0
    assert s["by_provider"] == []
