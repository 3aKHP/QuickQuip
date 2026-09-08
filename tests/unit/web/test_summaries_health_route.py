"""summaries-health 路由：总结族生成健康度聚合（1.15.2 CE 线）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

fastapi = pytest.importorskip("fastapi")

from quickquip.app.web.routes import summaries as summaries_route  # noqa: E402


@pytest.fixture()
def temp_usage_db(monkeypatch, tmp_path):
    path = tmp_path / "llm_usage.db"
    monkeypatch.setattr(summaries_route, "LLM_USAGE_DB_PATH", path)
    return path


def _insert_event(db_path, *, feature: str, state: str, finish: str | None, model: str = "m1"):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            provider_id TEXT, protocol TEXT, model TEXT, feature TEXT,
            group_id TEXT, persona_id TEXT, agent_loop_id TEXT,
            stream INTEGER, duration_ms REAL,
            input_tokens INTEGER, output_tokens INTEGER,
            cache_creation_tokens INTEGER, cache_read_tokens INTEGER,
            thinking_tokens INTEGER, cost_usd REAL, priced INTEGER,
            state TEXT NOT NULL, error_message TEXT,
            finish_reason TEXT
        )
        """,
    )
    conn.execute(
        "INSERT INTO llm_usage_events (ts, provider_id, protocol, model, feature, group_id,"
        " state, finish_reason, cost_usd, duration_ms) VALUES (?, 'p', 'openai', ?, ?, '10001', ?, ?, 0.01, 1000.0)",
        (datetime.now(tz=timezone.utc).isoformat(), model, feature, state, finish),
    )
    conn.commit()
    conn.close()


def test_summaries_health_aggregates_features_and_finish_reasons(temp_usage_db):
    _insert_event(temp_usage_db, feature="summary", state="ok", finish="STOP")
    _insert_event(temp_usage_db, feature="summary", state="ok", finish="MAX_TOKENS", model="flash")
    _insert_event(temp_usage_db, feature="summary", state="error", finish=None)
    _insert_event(temp_usage_db, feature="chat", state="ok", finish="STOP")  # 不在总结族，排除

    result = summaries_route.summaries_health(days=7)

    by_key = {(row["feature"], row["state"]): row["calls"] for row in result["features"]}
    assert by_key == {("summary", "ok"): 2, ("summary", "error"): 1}
    finishes = {
        (row["model"], row["finish_reason"]): row["calls"]
        for row in result["finish_reasons"]
    }
    assert finishes == {("m1", "STOP"): 1, ("flash", "MAX_TOKENS"): 1}
    assert result["groups"][0]["failed"] == 1


def test_summaries_health_missing_db_returns_empty(temp_usage_db):
    result = summaries_route.summaries_health(days=7)
    assert result["features"] == []
    assert result["finish_reasons"] == []
