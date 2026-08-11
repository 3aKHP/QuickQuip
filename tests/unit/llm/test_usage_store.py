import os

from quickquip.llm.usage_store import LLMUsageStore


def test_record_creates_schema_and_row(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({
        "provider_id": "p", "protocol": "claude", "model": "m",
        "feature": "chat", "group_id": "g", "stream": 1,
        "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001,
        "priced": 1, "state": "ok",
    })
    with store.connect() as conn:
        row = conn.execute(
            "SELECT provider_id, state, cost_usd FROM llm_usage_events"
        ).fetchone()
    assert row["provider_id"] == "p"
    assert row["state"] == "ok"
    assert row["cost_usd"] == 0.001


def test_storage_bytes_positive(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "claude", "model": "m",
                  "stream": 1, "state": "ok"})
    assert store.storage_bytes() > 0


def test_db_file_chmod_0600(tmp_path):
    store = LLMUsageStore(tmp_path / "u.db")
    store.record({"provider_id": "p", "protocol": "claude", "model": "m",
                  "stream": 1, "state": "ok"})
    mode = os.stat(tmp_path / "u.db").st_mode & 0o777
    assert mode == 0o600


def test_existing_schema_is_migrated_without_rewriting_rows(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE llm_usage_events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, provider_id TEXT NOT NULL, protocol TEXT NOT NULL, model TEXT NOT NULL, stream INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL NOT NULL DEFAULT 0, priced INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'ok')")
        conn.execute("INSERT INTO llm_usage_events (id, ts, provider_id, protocol, model, stream, input_tokens, output_tokens) VALUES (1, '2026-08-11T00:00:00+00:00', 'p', 'claude', 'm', 1, 10, 5)")
    store = LLMUsageStore(path)
    store.record({"provider_id": "p2", "protocol": "openai", "model": "m2", "stream": 0, "state": "ok"})
    with store.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage_events)")}
        old = conn.execute("SELECT input_tokens, output_tokens FROM llm_usage_events WHERE id = 1").fetchone()
    assert {"fresh_input_tokens", "total_tokens", "pricing_confidence"} <= columns
    assert (old[0], old[1]) == (10, 5)
