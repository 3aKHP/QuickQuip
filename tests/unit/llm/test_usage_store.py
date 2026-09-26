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
        conn.execute(
            "CREATE TABLE llm_usage_events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, "
            "provider_id TEXT NOT NULL, protocol TEXT NOT NULL, model TEXT NOT NULL, "
            "stream INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER, "
            "cost_usd REAL NOT NULL DEFAULT 0, priced INTEGER NOT NULL DEFAULT 0, "
            "state TEXT NOT NULL DEFAULT 'ok')"
        )
        conn.execute(
            "INSERT INTO llm_usage_events (id, ts, provider_id, protocol, model, stream, "
            "input_tokens, output_tokens) VALUES (1, '2026-08-11T00:00:00+00:00', "
            "'p', 'claude', 'm', 1, 10, 5)"
        )
    store = LLMUsageStore(path)
    store.record({"provider_id": "p2", "protocol": "openai", "model": "m2",
                  "stream": 0, "state": "ok"})
    with store.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage_events)")}
        old = conn.execute(
            "SELECT input_tokens, output_tokens FROM llm_usage_events WHERE id = 1"
        ).fetchone()
    assert {"fresh_input_tokens", "total_tokens", "pricing_confidence"} <= columns
    assert (old[0], old[1]) == (10, 5)


def test_context_meter_columns_migrate_and_aggregate(tmp_path):
    from quickquip.llm.usage_store import window_start

    path = tmp_path / "old.db"
    _create_legacy_usage_db(path)
    import sqlite3

    with sqlite3.connect(path) as conn:
        for column in ("input_tokens", "output_tokens", "cache_creation_tokens",
                       "cache_read_tokens", "thinking_tokens"):
            conn.execute(f"ALTER TABLE llm_usage_events ADD COLUMN {column} INTEGER")
    store = LLMUsageStore(path)
    fields = ("envelope_tokens", "epoch_history_tokens", "media_image_count", "patch_tokens")
    for values in ((400, 4000, 1, 300), (600, 4400, 3, 500), (None, None, None, None)):
        store.record({
            "provider_id": "p", "protocol": "claude", "model": "m", "stream": 1,
            "state": "ok", **dict(zip(fields, values)),
        })
    summary = store.summary(window_start(7).isoformat())
    for average, coverage, expected in (
        ("avg_envelope_tokens", "envelope_coverage", 500),
        ("avg_epoch_history_tokens", "epoch_coverage", 4200),
        ("avg_media_image_count", "media_coverage", 2),
        ("avg_patch_tokens", "patch_coverage", 400),
    ):
        assert summary[average] == expected
        assert summary[coverage] == round(2 / 3, 4)


def _create_legacy_usage_db(path):
    import sqlite3

    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE llm_usage_events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, "
            "provider_id TEXT NOT NULL, protocol TEXT NOT NULL, model TEXT NOT NULL, "
            "stream INTEGER NOT NULL, cost_usd REAL NOT NULL DEFAULT 0, "
            "priced INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'ok')"
        )


def test_concurrent_first_open_migration_is_race_safe(tmp_path):
    """两容器并发首开同一旧库（发版场景）：两边迁移都不抛，行都在。

    无守护时后完成快照的一方会撞 `duplicate column name`——迁移循环的
    重查 + duplicate 兜底保证该交错下依然全部成功。
    """
    import threading

    path = tmp_path / "race.db"
    _create_legacy_usage_db(path)

    stores = [LLMUsageStore(path), LLMUsageStore(path)]
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _worker(store: LLMUsageStore, provider_id: str) -> None:
        try:
            barrier.wait()
            store.record({"provider_id": provider_id, "protocol": "openai",
                          "model": "m", "stream": 0, "state": "ok"})
        except Exception as error:  # noqa: BLE001 - 测试收集任意失败
            errors.append(error)

    threads = [
        threading.Thread(target=_worker, args=(store, provider))
        for store, provider in zip(stores, ("p1", "p2"))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with stores[0].connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM llm_usage_events"
        ).fetchone()["c"]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage_events)")}
    assert count == 2
    assert {"feature", "pricing_confidence", "response_outcome"} <= columns


def test_half_migrated_schema_is_completed(tmp_path):
    """半迁移态（部分迁移列已存在）：补齐剩余列且不抛、不重写已有列。"""
    import sqlite3

    path = tmp_path / "half.db"
    _create_legacy_usage_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE llm_usage_events ADD COLUMN feature TEXT")
        conn.execute(
            "INSERT INTO llm_usage_events (ts, provider_id, protocol, model, stream, feature) "
            "VALUES ('2026-08-11T00:00:00+00:00', 'p', 'claude', 'm', 1, 'chat')"
        )

    store = LLMUsageStore(path)
    store.record({"provider_id": "p2", "protocol": "openai", "model": "m2",
                  "stream": 0, "state": "ok"})

    with store.connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage_events)")}
        kept = conn.execute(
            "SELECT feature FROM llm_usage_events WHERE provider_id = 'p'"
        ).fetchone()
    assert {"group_id", "total_tokens", "pricing_confidence"} <= columns
    assert kept["feature"] == "chat"


def test_claude_input_semantics_backfill_migration(tmp_path):
    """issue #202：_ensure_schema 把历史 claude 行的 inclusive 标签 backfill 为
    exclusive（input_tokens 列自始存 exclusive 原始值）；非 claude 行不动；
    重跑幂等。"""
    import sqlite3

    path = tmp_path / "u.db"
    store = LLMUsageStore(path)
    for i, protocol in enumerate(("claude", "claude", "openai")):
        store.record({
            "provider_id": f"p{i}", "protocol": protocol, "model": "m",
            "stream": 1, "input_tokens": 10, "cache_read_tokens": 200,
            "input_token_semantics": "inclusive", "state": "ok",
        })
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE llm_usage_events SET input_token_semantics = 'inclusive'"
        )  # 模拟 backfill 前的历史库（新代码已派生 exclusive，手工还原成旧形态）

    reopened = LLMUsageStore(path)  # 触发 _ensure_schema backfill
    reopened._ensure_schema()
    with reopened.connect() as conn:
        rows = conn.execute(
            "SELECT protocol, input_token_semantics FROM llm_usage_events"
            " ORDER BY protocol, provider_id"
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("claude", "exclusive"), ("claude", "exclusive"), ("openai", "inclusive"),
    ]
    reopened._ensure_schema()  # 二跑幂等：0 行受影响，标签不再变化
    with reopened.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM llm_usage_events"
            " WHERE protocol = 'claude' AND input_token_semantics != 'exclusive'"
        ).fetchone()[0] == 0


def test_claude_backfill_keeps_summary_values_stable(tmp_path):
    """issue #202 回归锚定：backfill 只翻标签列，summary 聚合数值前后一致
    （ok 行的存储列 COALESCE 优先，CASE 分支翻转不改变任何行形态的取值）。"""
    import sqlite3

    from quickquip.llm.usage_store import window_start

    path = tmp_path / "u.db"
    store = LLMUsageStore(path)
    # claude 行：input=100（exclusive 原始值）、read=200、creation=80、
    # 存储列 fresh=100 / total=430（normalize 后写入，聚合只看这里）
    store.record({
        "provider_id": "p", "protocol": "claude", "model": "m", "feature": "chat",
        "stream": 1, "input_tokens": 100, "cache_read_tokens": 200,
        "cache_creation_tokens": 80, "output_tokens": 50,
        "fresh_input_tokens": 100, "total_tokens": 430,
        "input_token_semantics": "exclusive", "cost_usd": 0.01, "priced": 1,
        "state": "ok",
    })
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE llm_usage_events SET input_token_semantics = 'inclusive'")

    cutoff = window_start(7).isoformat()
    # 同一实例 _schema_ready 已置位 → 取的是 backfill 前口径
    before = store.summary(cutoff)
    # 新实例首开触发 backfill → 标签翻 exclusive
    reopened = LLMUsageStore(path)
    after = reopened.summary(cutoff)

    # 存储列 total_tokens=430（canonical，含 output）COALESCE 短路优先
    assert after["total_tokens"] == before["total_tokens"] == 430
    assert after["total_fresh_input_tokens"] == before["total_fresh_input_tokens"] == 100
    assert after["total_calls"] == before["total_calls"] == 1
    assert after["cache_hit_rate"] == before["cache_hit_rate"] == round(200 / 380, 4)
    with reopened.connect() as conn:
        sem = conn.execute("SELECT input_token_semantics FROM llm_usage_events").fetchone()[0]
    assert sem == "exclusive"
