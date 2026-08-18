from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from quickquip.llm.usage_store import LLMUsageStore, window_start


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
    """与路由 _cutoff 同源：window_start 对齐下界。"""
    return window_start(days).isoformat()


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


def test_summary_filters_and_canonical_buckets(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "claude", "model": "m", "feature": "chat", "group_id": "g", "stream": 1, "input_tokens": 100, "fresh_input_tokens": 30, "total_tokens": 150, "input_token_semantics": "inclusive", "cache_read_tokens": 70, "output_tokens": 50, "cost_usd": 0.01, "priced": 1, "state": "ok", "duration_ms": 100})
    store.record({"provider_id": "q", "protocol": "openai", "model": "n", "feature": "other", "stream": 1, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.02, "priced": 1, "state": "ok"})
    summary = store.summary(_cutoff(7), provider_id="p", feature="chat")
    assert summary["request_count"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["total_fresh_input_tokens"] == 30
    assert summary["cache_hit_rate"] == 0.7


def test_timeline_zero_fills_and_selects_metric(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "openai", "model": "m", "stream": 1, "input_tokens": 2, "output_tokens": 3, "cost_usd": 0.01, "priced": 1, "state": "ok"})
    timeline = store.timeline(_cutoff(7), range_days=7, metric="requests")
    assert len(timeline) == 7
    assert sum(point["value"] for point in timeline) == 1


def test_timeline_1d_returns_24_hourly_buckets(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    timeline = store.timeline(_cutoff(1), range_days=1, metric="requests")
    assert len(timeline) == 24
    assert all(point["date"].endswith("T00:00:00Z") or ":00:00Z" in point["date"] for point in timeline)


def test_summary_and_timeline_share_aligned_window(tmp_path):
    """Issue #111 #5：summary 与 timeline 共用 window_start 下界，
    网格起点外的行被两者一致排除，趋势合计 == 总成本卡片。"""
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "openai", "model": "m", "stream": 1,
                  "input_tokens": 2, "output_tokens": 3, "cost_usd": 0.01, "priced": 1, "state": "ok"})
    store.record({"provider_id": "out", "protocol": "openai", "model": "m", "stream": 1,
                  "input_tokens": 2, "output_tokens": 3, "cost_usd": 99.0, "priced": 1, "state": "ok"})
    boundary = (window_start(7) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE llm_usage_events SET ts = ? WHERE provider_id = 'out'", (boundary,))

    cutoff = _cutoff(7)
    summary = store.summary(cutoff)
    timeline = store.timeline(cutoff, range_days=7, metric="cost")
    assert summary["total_calls"] == 1  # 网格外旧行不被汇总计入
    assert abs(sum(point["cost"] for point in timeline) - summary["total_cost"]) < 1e-9


def test_events_cursor_pagination(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    for index in range(3):
        store.record({"provider_id": "p", "protocol": "openai", "model": "m", "stream": 1, "state": "ok", "error_message": None})
    first = store.events(cutoff=_cutoff(7), limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    second = store.events(cutoff=_cutoff(7), limit=2, cursor=int(first["next_cursor"]))
    assert len(second["items"]) == 1
