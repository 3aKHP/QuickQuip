"""Extract schema-3 configuration and split preferences from business databases."""

import json
import sqlite3
import time
from contextlib import contextmanager, closing

from quickquip.configuration.database import DOMAIN_SCHEMA
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_document import empty_document, validate_document
from quickquip.llm.config_execution_store import ConfigExecutionStore
from quickquip.llm.config_store import ConfigStore, dumps


@contextmanager
def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def configuration(paths):
    """Create both new stores, preserving local revision and operation identities."""
    legacy = paths.root / "data" / "llm_config.db"
    paths.managed.mkdir(parents=True, exist_ok=True)
    if not legacy.exists():
        document = empty_document()
        ConfigStore(paths.configuration).create(document)
        ConfigExecutionStore(paths.runtime).create(1, dumps(document), time.time())
        return
    with _connect(legacy) as source:
        meta = source.execute("SELECT * FROM config_meta").fetchone()
        if meta is None or meta["schema_version"] != 3:
            raise ConfigError(
                "unsupported_schema", "Upgrade the old configuration to schema 3 first"
            )
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ConfigError("database_corrupt", "Legacy configuration is corrupt")
        validate_document(json.loads(meta["document"]), config_dir=paths.root / "config")
        with closing(sqlite3.connect(paths.configuration)) as target, target:
            source.backup(target)
            target.executescript(
                """
                DROP TABLE config_operations;
                DROP TABLE bot_runtime;
                ALTER TABLE config_meta RENAME TO old_config_meta;
                CREATE TABLE config_meta (
                 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
                 draft_revision INTEGER NOT NULL, document TEXT NOT NULL);
                INSERT INTO config_meta SELECT singleton,4,draft_revision,document
                 FROM old_config_meta;
                DROP TABLE old_config_meta;
            """
                + DOMAIN_SCHEMA
            )
        published = source.execute(
            "SELECT * FROM config_snapshots WHERE revision=?", (meta["published_revision"],)
        ).fetchone()
        if published is None:
            raise ConfigError("database_corrupt", "Published configuration snapshot is missing")
        runtime = ConfigExecutionStore(paths.runtime)
        runtime.create(published["revision"], published["document"], published["created_at"])
        with runtime.connect(write=True) as target:
            for row in source.execute("SELECT * FROM config_snapshots"):
                target.execute(
                    "INSERT OR IGNORE INTO execution_snapshots VALUES(?,?,?)", tuple(row)
                )
            for row in source.execute("SELECT * FROM config_operations"):
                columns = ",".join(row.keys())
                placeholders = ",".join("?" for _ in row)
                target.execute(
                    f"INSERT INTO config_operations ({columns}) VALUES({placeholders})", tuple(row)
                )


def _tables(connection):
    return {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def scope_settings(paths):
    source_path = paths.root / "data" / "llm.db"
    if not source_path.exists():
        return 0
    with _connect(source_path) as source, _connect(paths.configuration) as target:
        if "group_settings" not in _tables(source):
            return 0
        rows = source.execute("SELECT * FROM group_settings").fetchall()
        columns = [row[1] for row in target.execute("PRAGMA table_info(scope_settings)")]
        source.execute("""CREATE TABLE IF NOT EXISTS agent_scopes (
            scope_key TEXT PRIMARY KEY, generation INTEGER NOT NULL DEFAULT 0,
            history_revision INTEGER NOT NULL DEFAULT 0, session_id TEXT, session_created_at TEXT,
            private_chat_active INTEGER NOT NULL DEFAULT 0)""")
        existing = {row[1] for row in source.execute("PRAGMA table_info(agent_scopes)")}
        if "private_chat_active" not in existing:
            source.execute(
                "ALTER TABLE agent_scopes ADD COLUMN private_chat_active INTEGER NOT NULL DEFAULT 0"
            )
        for row in rows:
            record = dict(row)
            if record["group_id"].startswith("private:"):
                source.execute(
                    "INSERT OR IGNORE INTO agent_scopes(scope_key) VALUES(?)", (record["group_id"],)
                )
                source.execute(
                    "UPDATE agent_scopes SET private_chat_active=? WHERE scope_key=?",
                    (bool(record.get("enabled")), record["group_id"]),
                )
                record["enabled"] = None
            for field in ("agent_delivery_intermediate_enabled", "agent_delivery_final_enabled"):
                if field not in record:
                    record[field] = record.get("agent_delivery_enabled")
            values = [record.get(field) for field in columns]
            target.execute(
                f"INSERT INTO scope_settings ({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                values,
            )
        target.commit()
        source.execute("DROP TABLE group_settings")
        return len(rows)


def text_modes(paths):
    source_path = paths.root / "data" / "niuniu.db"
    if not source_path.exists():
        return 0
    with _connect(source_path) as source, _connect(paths.configuration) as target:
        if "niuniu_group_text" not in _tables(source):
            return 0
        rows = source.execute("SELECT group_id,text_mode FROM niuniu_group_text").fetchall()
        target.executemany("INSERT INTO niuniu_group_text VALUES(?,?)", rows)
        target.commit()
        source.execute("DROP TABLE niuniu_group_text")
        return len(rows)


def scheduled_messages(paths):
    from quickquip.chat.scheduled_messages import ScheduledMessage
    from quickquip.llm.config_durability import durable_write

    legacy = paths.root / "data" / "scheduled_messages.json"
    if not legacy.exists():
        return {"recurring": 0, "pending": 0}
    raw = json.loads(legacy.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("jobs"), list):
        raise ConfigError("invalid_configuration", "Legacy scheduled messages must contain jobs")
    jobs = [ScheduledMessage.from_dict(item) for item in raw["jobs"]]
    if len({job.id for job in jobs}) != len(jobs):
        raise ConfigError("invalid_configuration", "Scheduled message IDs must be unique")
    for path, recurring in ((paths.recurring, True), (paths.pending, False)):
        content = {"jobs": [job.to_dict() for job in jobs if job.recurring == recurring]}
        durable_write(path, (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode())
    return {
        "recurring": sum(job.recurring for job in jobs),
        "pending": sum(not job.recurring for job in jobs),
    }
