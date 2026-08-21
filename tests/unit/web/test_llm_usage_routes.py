from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from quickquip.llm.usage_store import LLMUsageStore, window_start

_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


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
    assert tl7[0]["date"] == datetime.now(_BUSINESS_TZ).strftime("%Y-%m-%d")
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
    start = window_start(1).astimezone(_BUSINESS_TZ)
    assert timeline[0]["date"] == start.strftime("%Y-%m-%dT%H:00:00+08:00")
    assert timeline[-1]["date"] == (start + timedelta(hours=23)).strftime("%Y-%m-%dT%H:00:00+08:00")


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


def _seed_personas(store: LLMUsageStore) -> None:
    """chat 行带 persona（p1/p2），vision 行无 persona（NULL）。"""
    store.record({"provider_id": "claude-main", "protocol": "claude", "model": "sonnet",
                  "feature": "chat", "group_id": "g1", "persona_id": "p1", "stream": 1,
                  "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001,
                  "priced": 1, "state": "ok"})
    store.record({"provider_id": "kimi", "protocol": "claude", "model": "kimi-k2",
                  "feature": "chat", "group_id": "g1", "persona_id": "p2", "stream": 1,
                  "input_tokens": 300, "output_tokens": 40, "cost_usd": 0.002,
                  "priced": 1, "state": "ok"})
    store.record({"provider_id": "gemini-main", "protocol": "gemini", "model": "pro",
                  "feature": "vision", "group_id": None, "persona_id": None, "stream": 1,
                  "input_tokens": 200, "output_tokens": 30, "cost_usd": 0.0005,
                  "priced": 1, "state": "ok"})


def test_summary_by_persona_aggregates_and_labels_null(tmp_path):
    from quickquip.llm.usage_store import UNATTRIBUTED_LABEL

    store = LLMUsageStore(tmp_path / "u.db")
    _seed_personas(store)
    s = store.summary(_cutoff(7))
    keys = [b["key"] for b in s["by_persona"]]
    assert "p1" in keys and "p2" in keys
    assert UNATTRIBUTED_LABEL in keys
    assert s["unattributed_label"] == UNATTRIBUTED_LABEL
    # unattributed 桶只包含 NULL 行（vision 1 次），不会吞并已知人格
    bucket = next(b for b in s["by_persona"] if b["key"] == UNATTRIBUTED_LABEL)
    assert bucket["calls"] == 1


def test_persona_filter_across_summary_timeline_events(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed_personas(store)
    cutoff = _cutoff(7)
    assert store.summary(cutoff, persona_id="p1")["total_calls"] == 1
    assert store.summary(cutoff, persona_id="p2")["total_calls"] == 1
    tl = store.timeline(cutoff, range_days=7, metric="requests", persona_id="p2")
    assert sum(p["value"] for p in tl) == 1
    ev = store.events(cutoff=cutoff, persona_id="p1")
    assert len(ev["items"]) == 1
    assert ev["items"][0]["persona_id"] == "p1"


def test_dimensions_returns_all_values_within_range_only(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed_personas(store)
    _seed_old(store)
    d = store.dimensions(_cutoff(7))
    assert d["providers"] == ["claude-main", "gemini-main", "kimi"]  # old-prov 被 range 排除
    assert sorted(d["personas"]) == ["p1", "p2"]  # NULL 不作为可筛选值返回
    assert d["groups"] == ["g1"]  # NULL group 不返回
    assert d["unattributed_label"]
    # 30d 窗口包含旧行
    d30 = store.dimensions(_cutoff(30))
    assert "old-prov" in d30["providers"]


def test_persona_index_created_and_idempotent(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _seed_personas(store)
    with sqlite3.connect(store.path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert "idx_usage_persona" in names
    store._ensure_schema()  # 再次初始化幂等，不重建、不清空
    with sqlite3.connect(store.path) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM llm_usage_events").fetchone()
    assert rows[0] == 3


def _route_store(monkeypatch, tmp_path):
    from quickquip.app.web.routes import llm_usage as route

    store = LLMUsageStore(tmp_path / "route.db")
    monkeypatch.setattr(route, "usage_store", store)
    return route, store


async def test_route_summary_passes_persona_filter(monkeypatch, tmp_path):
    route, store = _route_store(monkeypatch, tmp_path)
    _seed_personas(store)
    result = await route.get_summary(
        range_="7d", provider=None, model=None, feature=None, group=None, persona="p1", state=None,
    )
    assert result["total_calls"] == 1
    assert [b["key"] for b in result["by_persona"]] == ["p1"]


async def test_route_dimensions_only_accepts_range(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")

    route, store = _route_store(monkeypatch, tmp_path)
    _seed_personas(store)
    d = await route.get_dimensions(range_="7d")
    assert sorted(d["personas"]) == ["p1", "p2"]
    with pytest.raises(fastapi.HTTPException) as exc_info:
        await route.get_dimensions(range_="3d")
    assert exc_info.value.status_code == 422


def test_events_cursor_pagination(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    for index in range(3):
        store.record({"provider_id": "p", "protocol": "openai", "model": "m", "stream": 1, "state": "ok", "error_message": None})
    first = store.events(cutoff=_cutoff(7), limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    second = store.events(cutoff=_cutoff(7), limit=2, cursor=int(first["next_cursor"]))
    assert len(second["items"]) == 1


def _set_row_ts(store: LLMUsageStore, provider_id: str, ts: datetime) -> None:
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE llm_usage_events SET ts = ? WHERE provider_id = ?",
            (ts.isoformat(), provider_id),
        )


def test_utc8_early_morning_row_lands_on_business_day(tmp_path):
    """UTC+8 凌晨（UTC 前一日 17:00 后）的记录计入业务时区当日日桶。"""
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "early", "protocol": "openai", "model": "m", "stream": 1,
                  "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.01, "priced": 1, "state": "ok"})
    now_business = datetime.now(_BUSINESS_TZ)
    # 业务时区今日 01:30 = UTC 前一日 17:30（跨业务日界的凌晨记录）
    early_business = now_business.replace(hour=1, minute=30, second=0, microsecond=0)
    if early_business > now_business:
        early_business -= timedelta(days=1)
    _set_row_ts(store, "early", early_business.astimezone(timezone.utc))

    timeline = store.timeline(_cutoff(7), range_days=7, metric="cost")
    expected_day = early_business.strftime("%Y-%m-%d")
    bucket = next(point for point in timeline if point["date"] == expected_day)
    assert bucket["cost"] == 0.01
    # 01:30 (+08:00) 的 UTC 日期必为业务日期的前一天，且该 UTC 日桶成本为零
    utc_day = early_business.astimezone(timezone.utc).strftime("%Y-%m-%d")
    assert utc_day != expected_day
    assert all(point["date"] != utc_day or point["cost"] == 0.0 for point in timeline)


def test_1d_hourly_bucket_lands_on_business_hour(tmp_path):
    """业务时区 00:30（UTC 前一日 16:30）的行落入 T00:00:00+08:00 小时桶。"""
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "early-hour", "protocol": "openai", "model": "m", "stream": 1,
                  "cost_usd": 0.05, "priced": 1, "state": "ok"})
    now_business = datetime.now(_BUSINESS_TZ)
    early_business = now_business.replace(hour=0, minute=30, second=0, microsecond=0)
    if early_business > now_business:
        early_business -= timedelta(days=1)
    _set_row_ts(store, "early-hour", early_business.astimezone(timezone.utc))

    timeline = store.timeline(_cutoff(1), range_days=1, metric="cost")
    assert len(timeline) == 24
    midnight_bucket = early_business.replace(minute=0).strftime("%Y-%m-%dT%H:00:00+08:00")
    by_date = {point["date"]: point["cost"] for point in timeline}
    assert by_date[midnight_bucket] == 0.05
    assert sum(by_date.values()) == 0.05  # 只有一行，其余 23 桶全为零


def test_multi_day_window_uses_business_midnight_boundary(tmp_path):
    """7 天窗口下界是业务时区零点：边界前一秒排除、边界内包含。"""
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "edge-in", "protocol": "openai", "model": "m", "stream": 1,
                  "cost_usd": 1.0, "priced": 1, "state": "ok"})
    store.record({"provider_id": "edge-out", "protocol": "openai", "model": "m", "stream": 1,
                  "cost_usd": 99.0, "priced": 1, "state": "ok"})

    start_business = window_start(7).astimezone(_BUSINESS_TZ)
    assert start_business.hour == 0 and start_business.minute == 0
    _set_row_ts(store, "edge-in", start_business.astimezone(timezone.utc))
    _set_row_ts(store, "edge-out", start_business.astimezone(timezone.utc) - timedelta(seconds=1))

    summary = store.summary(_cutoff(7))
    assert summary["total_cost"] == 1.0  # 边界外一行被排除


def test_summary_timeline_events_share_business_window(tmp_path):
    """summary / timeline / events 在业务时区窗口下口径一致。"""
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "openai", "model": "m", "stream": 1,
                  "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.02, "priced": 1, "state": "ok"})
    store.record({"provider_id": "q", "protocol": "openai", "model": "m", "stream": 1,
                  "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.03, "priced": 1, "state": "ok"})
    cutoff = _cutoff(7)
    summary = store.summary(cutoff)
    timeline = store.timeline(cutoff, range_days=7, metric="cost")
    events = store.events(cutoff=cutoff)

    assert summary["total_calls"] == 2
    assert abs(sum(point["cost"] for point in timeline) - summary["total_cost"]) < 1e-9
    assert len(events["items"]) == 2
