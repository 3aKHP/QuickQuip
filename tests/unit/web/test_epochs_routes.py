"""epochs 路由测试：锯齿 points 的每轮去重、窗口元数据读取与快照入队。

store 层（epoch_series）与路由层（直调路由函数 + monkeypatch store/_DB）
两层结构，照 test_llm_usage_routes.py 范式。
"""

from __future__ import annotations

import pytest

from quickquip.app.web.routes import epochs as route
from quickquip.llm.epoch import ROW_OVERHEAD_TOKENS
from quickquip.llm.store import LLMStore
from quickquip.llm.usage_store import LLMUsageStore

_GROUP = "123456789"


def _route_usage(monkeypatch, tmp_path) -> LLMUsageStore:
    store = LLMUsageStore(tmp_path / "usage.db")
    monkeypatch.setattr(route, "usage_store", store)
    return store


def _route_llm_db(monkeypatch, tmp_path) -> LLMStore:
    store = LLMStore(tmp_path / "llm.db")
    monkeypatch.setattr(route, "_DB", store.path)
    return store


def _usage_row(store: LLMUsageStore, **overrides) -> None:
    row = {
        "provider_id": "p1",
        "protocol": "openai",
        "model": "m1",
        "feature": "chat",
        "group_id": _GROUP,
        "agent_loop_id": None,
        "epoch_history_tokens": 1000,
        "epoch_history_rows": 20,
        "envelope_tokens": 300,
        "stream": 1,
        "state": "ok",
    }
    row.update(overrides)
    store.record(row)


# ── store 层：epoch_series ──────────────────────────────────────────────


def test_epoch_series_orders_and_filters(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _usage_row(store, agent_loop_id="loop-1")
    _usage_row(store, agent_loop_id="loop-1")  # 同 loop 重复行：SQL 端按 loop 去重取首行
    _usage_row(store, agent_loop_id="loop-2", group_id="1000000001")
    _usage_row(store, agent_loop_id="loop-3", provider_id="other")
    rows = store.epoch_series(cutoff="2000-01-01", group_id=_GROUP, provider_id="p1")
    assert [r["agent_loop_id"] for r in rows] == ["loop-1"]
    assert rows[0]["epoch_history_rows"] == 20


def test_epoch_series_respects_cutoff(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    _usage_row(store, agent_loop_id="loop-1")
    rows = store.epoch_series(cutoff="2999-01-01", group_id=_GROUP)
    assert rows == []


# ── 路由层：timeline ────────────────────────────────────────────────────


async def test_timeline_dedups_per_loop_and_merges_events(monkeypatch, tmp_path):
    usage = _route_usage(monkeypatch, tmp_path)
    _usage_row(usage, agent_loop_id="loop-1", epoch_history_tokens=1000)
    _usage_row(usage, agent_loop_id="loop-1", epoch_history_tokens=1000)
    _usage_row(usage, agent_loop_id="loop-2", epoch_history_tokens=400)
    # 非 chat 特性行（纪元三项全 NULL）：不产生点，也不推进时间轴尾巴
    _usage_row(
        usage,
        agent_loop_id=None,
        feature="briefing",
        epoch_history_tokens=None,
        epoch_history_rows=None,
        envelope_tokens=None,
    )

    llm_store = _route_llm_db(monkeypatch, tmp_path)
    llm_store.record_epoch_event(
        scope_key=_GROUP,
        provider_id="p1",
        model="m1",
        reason="hot",
        old_anchor_id=10,
        new_anchor_id=42,
        epoch_tokens=5000,
        evicted_rows=6,
        evicted_tokens=1200,
    )

    result = await route.epoch_timeline(group_key=_GROUP)
    assert [p["epoch_tokens"] for p in result["points"]] == [1000, 400]
    assert result["points"][0]["epoch_rows"] == 20
    assert len(result["events"]) == 1
    assert result["events"][0]["reason"] == "hot"
    assert result["events"][0]["new_anchor_id"] == 42


async def test_timeline_filters_events_by_provider(monkeypatch, tmp_path):
    _route_usage(monkeypatch, tmp_path)
    llm_store = _route_llm_db(monkeypatch, tmp_path)
    llm_store.record_epoch_event(
        scope_key=_GROUP, provider_id="p1", model="m1", reason="cold",
        old_anchor_id=1, new_anchor_id=2,
    )
    llm_store.record_epoch_event(
        scope_key=_GROUP, provider_id="p2", model="m1", reason="hot",
        old_anchor_id=3, new_anchor_id=4,
    )
    result = await route.epoch_timeline(group_key=_GROUP, provider="p2")
    assert [e["reason"] for e in result["events"]] == ["hot"]


async def test_timeline_missing_db_returns_empty_events(monkeypatch, tmp_path):
    _route_usage(monkeypatch, tmp_path)
    monkeypatch.setattr(route, "_DB", tmp_path / "nonexistent.db")
    result = await route.epoch_timeline(group_key=_GROUP)
    assert result["events"] == []


async def test_timeline_rejects_bad_group_key_and_range(monkeypatch, tmp_path):
    _route_usage(monkeypatch, tmp_path)
    fastapi = pytest.importorskip("fastapi")
    with pytest.raises(fastapi.HTTPException) as exc:
        await route.epoch_timeline(group_key="archive:123456789:1")
    assert exc.value.status_code == 422
    with pytest.raises(fastapi.HTTPException) as exc:
        await route.epoch_timeline(group_key=_GROUP, range_="2h")
    assert exc.value.status_code == 422


# ── 路由层：window ──────────────────────────────────────────────────────


def _seed_conversation(store: LLMStore, count: int) -> None:
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        store.append_conversation_message(_GROUP, "u1", role, f"消息正文{i}" * 3)


async def test_window_returns_metadata_only(monkeypatch, tmp_path):
    store = _route_llm_db(monkeypatch, tmp_path)
    _seed_conversation(store, 10)

    result = await route.epoch_window(group_key=_GROUP, anchor_id=5)
    assert [m["id"] for m in result["window"]] == [5, 6, 7, 8, 9, 10]
    assert result["window"][0]["role"] in {"user", "bot"}
    assert result["window"][0]["tokens"] >= ROW_OVERHEAD_TOKENS
    # 只含元数据键：不得带 content/raw_content 正文
    assert set(result["window"][0]) == {"id", "role", "tokens", "ts"}
    # 锚点前采样：DESC 取最近 26 条
    assert [m["id"] for m in result["out"]] == [4, 3, 2, 1]
    assert result["out_total_rows"] == 4
    assert result["out_total_tokens"] > 0
    assert result["out_tokens_approx"] is False


async def test_window_maps_roles_and_caps_before(monkeypatch, tmp_path):
    store = _route_llm_db(monkeypatch, tmp_path)
    _seed_conversation(store, 8)
    store.append_conversation_message(_GROUP, "u1", "system", "系统行")

    result = await route.epoch_window(group_key=_GROUP, anchor_id=1, before=2)
    roles = {m["role"] for m in result["window"]}
    assert "bot" in roles and "user" in roles and "other" in roles
    assert len(result["out"]) == 0  # 锚点 = 1，锚点前无行
    assert result["out_total_rows"] == 0


async def test_window_before_ts_bounds_head(monkeypatch, tmp_path):
    store = _route_llm_db(monkeypatch, tmp_path)
    _seed_conversation(store, 6)
    import sqlite3

    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE conversation_messages SET created_at = ? WHERE id <= 3",
            ("2000-01-01T00:00:00+00:00",),
        )

    result = await route.epoch_window(
        group_key=_GROUP, anchor_id=1, before_ts="2000-06-01T00:00:00+00:00"
    )
    assert [m["id"] for m in result["window"]] == [1, 2, 3]
    assert result["out_total_rows"] == 0


async def test_window_clamps_negative_params(monkeypatch, tmp_path):
    store = _route_llm_db(monkeypatch, tmp_path)
    _seed_conversation(store, 5)

    result = await route.epoch_window(group_key=_GROUP, anchor_id=3, before=-1, limit=0)
    # before 钳到 0：出窗采样为空，但 COUNT 仍给真实总量
    assert result["out"] == []
    assert result["out_total_rows"] == 2
    # limit 钳到 1
    assert [m["id"] for m in result["window"]] == [3]


async def test_window_before_ts_accepts_z_suffix(monkeypatch, tmp_path):
    store = _route_llm_db(monkeypatch, tmp_path)
    _seed_conversation(store, 6)

    # 前端 toISOString() 的 "Z" 后缀须与落库的 "+00:00" 格式等价参与比较
    result = await route.epoch_window(
        group_key=_GROUP, anchor_id=1, before_ts="2999-01-01T00:00:00.000Z"
    )
    assert len(result["window"]) == 6


async def test_window_rejects_bad_before_ts(monkeypatch, tmp_path):
    _route_llm_db(monkeypatch, tmp_path)
    fastapi = pytest.importorskip("fastapi")
    with pytest.raises(fastapi.HTTPException) as exc:
        await route.epoch_window(group_key=_GROUP, anchor_id=1, before_ts="not-a-date")
    assert exc.value.status_code == 422


async def test_window_rejects_bad_group_key(monkeypatch, tmp_path):
    _route_llm_db(monkeypatch, tmp_path)
    fastapi = pytest.importorskip("fastapi")
    with pytest.raises(fastapi.HTTPException) as exc:
        await route.epoch_window(group_key="bad", anchor_id=1)
    assert exc.value.status_code == 422


async def test_window_missing_db_404(monkeypatch, tmp_path):
    monkeypatch.setattr(route, "_DB", tmp_path / "nonexistent.db")
    fastapi = pytest.importorskip("fastapi")
    with pytest.raises(fastapi.HTTPException) as exc:
        await route.epoch_window(group_key=_GROUP, anchor_id=1)
    assert exc.value.status_code == 404


# ── 路由层：snapshot 入队 ───────────────────────────────────────────────


def test_snapshot_enqueues_action(monkeypatch):
    captured: list[tuple[str, dict]] = []

    def fake_enqueue(action_type, payload=None):
        captured.append((action_type, payload or {}))
        return {"id": "act-1", "action_type": action_type, "status": "queued"}

    monkeypatch.setattr(route.action_queue, "enqueue", fake_enqueue)

    # 只读 RPC 不记审计（看板 60s 自动轮询，避免每天上千条噪音日志）
    result = route.queue_epoch_snapshot()
    assert captured == [("epoch_snapshot", {})]
    assert result["queued"] is True
    assert result["action"]["id"] == "act-1"
