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
