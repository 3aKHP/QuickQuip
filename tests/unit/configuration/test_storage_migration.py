"""Offline extraction preserves business records, publication inputs and private sessions."""

import json
from contextlib import closing
import sqlite3

import pytest

from quickquip.configuration import legacy_storage
from quickquip.configuration.database import DOMAIN_SCHEMA
from quickquip.configuration.migration import migrate, rollback
from quickquip.configuration.paths import StoragePaths
from quickquip.llm.config_service import ConfigService
from quickquip.llm.store import LLMStore


def legacy_installation(root):
    paths = StoragePaths(root)
    source = root / "data/llm_config.db"
    service = ConfigService(source, config_dir=root / "config")
    service.initialize()
    draft = service.read()
    draft["document"]["settings"]["runtime"]["history_limit"] = 37
    service.replace(draft["document"], 1, note="unpublished change")
    task = service.apply(2, "pending-before-migration")
    runtime = LLMStore(root / "data/llm.db")
    runtime.append_conversation_message("12345", "42", "user", "business message")
    with closing(runtime._connect()) as connection, connection:
        schema = DOMAIN_SCHEMA.split("CREATE TABLE IF NOT EXISTS niuniu_group_text")[0]
        schema = schema.replace("scope_settings", "group_settings").replace(
            ",\n CHECK(group_id NOT LIKE 'private:%' OR enabled IS NULL)", ""
        )
        connection.executescript(schema)
        connection.executemany(
            "INSERT INTO group_settings(group_id,enabled,history_limit,updated_at) VALUES(?,?,?,?)",
            [("12345", 0, 0, "before"), ("private:67890", 1, 12, "before")],
        )
    with closing(sqlite3.connect(root / "data/niuniu.db")) as connection, connection:
        connection.executescript(
            "CREATE TABLE players(uid TEXT PRIMARY KEY,score INTEGER);"
            "INSERT INTO players VALUES('player',99);"
            "CREATE TABLE niuniu_group_text(group_id TEXT PRIMARY KEY,"
            "text_mode TEXT NOT NULL DEFAULT 'default');"
            "INSERT INTO niuniu_group_text VALUES('12345','safe');"
        )
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("ATTACH DATABASE ? AS execution", (str(service.execution.path),))
        connection.executescript(
            "CREATE TABLE config_operations AS SELECT * FROM "
            "execution.config_operations;"
            "CREATE TABLE bot_runtime AS SELECT * FROM execution.bot_runtime;"
            "ALTER TABLE config_meta ADD COLUMN published_revision "
            "INTEGER NOT NULL DEFAULT 1;"
            "UPDATE config_meta SET schema_version=3;"
            "DROP TABLE scope_settings; DROP TABLE niuniu_group_text;"
        )
    jobs = [
        {
            "id": name,
            "cron": "0 8 * * *",
            "group_ids": ["12345"],
            "message": name,
            "enabled": True,
            "recurring": recurring,
            "kind": "text",
            "origin": "web",
            "created_at": "before",
            "updated_at": "before",
        }
        for name, recurring in [("repeat", True), ("once", False)]
    ]
    (root / "data/scheduled_messages.json").write_text(json.dumps({"jobs": jobs}))
    # Offline migration follows service exit, which closes legacy SQLite connection cycles.
    import gc

    gc.collect()
    return paths, task


def test_migration_separates_preferences_without_replacing_business_data(tmp_path):
    paths, task = legacy_installation(tmp_path)
    result = migrate(tmp_path, services_stopped=True)
    assert result["status"] == "complete"
    service = ConfigService(paths.configuration, config_dir=tmp_path / "config")
    assert service.read()["revision"] == 2
    assert service.read("published")["revision"] == 1
    assert service.version()["note"] == "unpublished change"
    assert service.tasks.get(task["id"])["status"] == "queued"
    assert service.read_execution(2)["document"]["settings"]["runtime"]["history_limit"] == 37
    assert service.scope_settings.get_group_settings("12345").enabled is False
    assert service.scope_settings.get_group_settings("12345").history_limit == 0
    assert service.scope_settings.get_group_settings("private:67890").enabled is None
    store = LLMStore(tmp_path / "data/llm.db")
    assert store.private_chat_active("67890") is True
    assert (
        store.list_recent_conversation_messages("12345", limit=5)[0]["content"]
        == "business message"
    )
    with store._connect() as connection:
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='group_settings'"
        ).fetchone()
    with sqlite3.connect(tmp_path / "data/niuniu.db") as connection:
        assert connection.execute("SELECT score FROM players").fetchone()[0] == 99
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='niuniu_group_text'"
        ).fetchone()
    assert json.loads(paths.recurring.read_text())["jobs"][0]["id"] == "repeat"
    assert json.loads(paths.pending.read_text())["jobs"][0]["id"] == "once"
    assert not (tmp_path / "data/llm_config.db").exists()
    assert migrate(tmp_path, services_stopped=True)["backup"] == result["backup"]


def test_failed_extraction_restores_sources_and_can_be_retried(tmp_path, monkeypatch):
    paths, _ = legacy_installation(tmp_path)

    def fail(_paths):
        raise OSError("injected storage failure")

    monkeypatch.setattr(legacy_storage, "text_modes", fail)
    with pytest.raises(OSError, match="injected"):
        migrate(tmp_path, services_stopped=True)
    assert not paths.configuration.exists()
    with sqlite3.connect(tmp_path / "data/llm.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM group_settings").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 1
    with sqlite3.connect(tmp_path / "data/llm_config.db") as connection:
        assert connection.execute("SELECT schema_version FROM config_meta").fetchone()[0] == 3
    monkeypatch.undo()
    result = migrate(tmp_path, services_stopped=True)
    rollback(tmp_path, result["backup"], services_stopped=True)
    assert (tmp_path / "data/scheduled_messages.json").exists()
    assert not paths.pending.exists()


def test_completed_migration_rollback_keeps_new_activity_and_consumed_tasks(tmp_path):
    paths, task = legacy_installation(tmp_path)
    result = migrate(tmp_path, services_stopped=True)
    store = LLMStore(tmp_path / "data/llm.db")
    store.append_conversation_message("12345", "42", "user", "arrived after migration")
    store.set_private_chat_active("67890", False)
    service = ConfigService(paths.configuration, config_dir=tmp_path / "config")
    claim = service.tasks.claim("candidate")
    service.tasks.finish(claim["id"], claim["claim_token"])
    from quickquip.chat.scheduled_messages import ScheduledMessageStore

    schedules = ScheduledMessageStore(paths.recurring, pending_path=paths.pending)
    schedules.remove("once")
    rollback(tmp_path, result["backup"], services_stopped=True)
    with closing(sqlite3.connect(tmp_path / "data/llm.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT enabled FROM group_settings WHERE group_id=?", ("private:67890",)
            ).fetchone()[0]
            == 0
        )
    with closing(sqlite3.connect(tmp_path / "data/llm_config.db")) as connection:
        assert connection.execute("SELECT schema_version FROM config_meta").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT status FROM config_operations WHERE id=?", (task["id"],)
            ).fetchone()[0]
            == "succeeded"
        )
    assert [
        job["id"]
        for job in json.loads((tmp_path / "data/scheduled_messages.json").read_text())["jobs"]
    ] == ["repeat"]
    assert not paths.configuration.exists()


def test_rollback_recovers_interrupted_schedule_transfer(tmp_path, monkeypatch):
    from quickquip.chat.scheduled_messages import ScheduledMessageStore

    paths, _ = legacy_installation(tmp_path)
    result = migrate(tmp_path, services_stopped=True)
    schedules = ScheduledMessageStore(paths.recurring, pending_path=paths.pending)
    assert schedules.intent_path == paths.schedule_transfer
    write = schedules._write_file

    def interrupt(path, jobs):
        if path == paths.pending:
            raise OSError("interrupted pending write")
        return write(path, jobs)

    monkeypatch.setattr(schedules, "_write_file", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        schedules.update("repeat", recurring=False)
    assert paths.schedule_transfer.exists()
    rollback(tmp_path, result["backup"], services_stopped=True)
    jobs = json.loads((tmp_path / "data/scheduled_messages.json").read_text())["jobs"]
    assert {job["id"] for job in jobs} == {"repeat", "once"}
    assert all(not job["recurring"] for job in jobs)
    assert not paths.schedule_transfer.exists()
