"""Reverse a completed layout change while retaining activity since application startup."""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from quickquip.configuration.database import DOMAIN_SCHEMA
from quickquip.llm.config_execution_store import ConfigExecutionStore
from quickquip.llm.config_store import ConfigStore
from quickquip.llm.config_durability import durable_write, sync_directory


def _copy_table(source, target, table, rows):
    sql = source.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    target.execute(sql.replace("execution_snapshots", "config_snapshots"))
    for row in rows:
        target.execute(f"INSERT INTO {table} VALUES({','.join('?' for _ in row)})", tuple(row))


def reverse(paths):
    configuration = ConfigStore(paths.configuration)
    execution = ConfigExecutionStore(paths.runtime)
    configuration.verify()
    execution.verify()
    with TemporaryDirectory(prefix=".storage-rollback-", dir=paths.root / "data") as directory:
        temporary = Path(directory) / "llm_config.db"
        with configuration.connect() as source, closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
        with closing(sqlite3.connect(temporary)) as target, target, execution.connect() as runtime:
            publication = runtime.execute("SELECT published_revision FROM publication").fetchone()[
                0
            ]
            target.executescript("""
                DROP TABLE scope_settings;
                DROP TABLE niuniu_group_text;
                ALTER TABLE config_meta RENAME TO new_config_meta;
                CREATE TABLE config_meta (
                 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
                 draft_revision INTEGER NOT NULL, published_revision INTEGER NOT NULL,
                 document TEXT NOT NULL);
            """)
            target.execute(
                "INSERT INTO config_meta SELECT singleton,3,draft_revision,?,document "
                "FROM new_config_meta",
                (publication,),
            )
            target.execute("DROP TABLE new_config_meta")
            target.executemany(
                "INSERT OR IGNORE INTO config_snapshots VALUES(?,?,?)",
                runtime.execute("SELECT * FROM execution_snapshots"),
            )
            for table in ("config_operations", "bot_runtime"):
                _copy_table(runtime, target, table, runtime.execute(f"SELECT * FROM {table}"))
            sql = runtime.execute("SELECT sql FROM sqlite_master WHERE name='one_pending_apply'")
            target.execute(sql.fetchone()[0])

        with configuration.connect() as config:
            _restore_scopes(paths.root / "data/llm.db", config)
            _restore_text_modes(paths.root / "data/niuniu.db", config)
        from quickquip.chat.scheduled_messages import ScheduledMessageStore

        schedules = ScheduledMessageStore(paths.recurring, pending_path=paths.pending)
        jobs = [job.to_dict() for job in schedules.list()]
        durable_write(
            paths.root / "data/scheduled_messages.json",
            (json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        destination = paths.root / "data/llm_config.db"
        os.replace(temporary, destination)
        sync_directory(destination.parent)


def _restore_scopes(path, configuration):
    with closing(sqlite3.connect(path)) as target, target:
        target.row_factory = sqlite3.Row
        schema = DOMAIN_SCHEMA.split("CREATE TABLE IF NOT EXISTS niuniu_group_text")[0]
        schema = schema.replace("scope_settings", "group_settings").replace(
            ",\n CHECK(group_id NOT LIKE 'private:%' OR enabled IS NULL)", ""
        )
        target.execute("DROP TABLE IF EXISTS group_settings")
        target.executescript(schema)
        rows = configuration.execute("SELECT * FROM scope_settings").fetchall()
        for row in rows:
            target.execute(
                f"INSERT INTO group_settings VALUES({','.join('?' for _ in row)})", tuple(row)
            )
        exists = target.execute("SELECT 1 FROM sqlite_master WHERE name='agent_scopes'").fetchone()
        if exists:
            for state in target.execute(
                "SELECT scope_key,private_chat_active FROM agent_scopes "
                "WHERE scope_key LIKE 'private:%'"
            ).fetchall():
                target.execute(
                    "INSERT INTO group_settings(group_id,enabled,updated_at) "
                    "VALUES(?,?,?) ON CONFLICT(group_id) "
                    "DO UPDATE SET enabled=excluded.enabled",
                    (*state, datetime.now(timezone.utc).isoformat()),
                )


def _restore_text_modes(path, configuration):
    with closing(sqlite3.connect(path)) as target, target:
        target.execute("DROP TABLE IF EXISTS niuniu_group_text")
        target.execute(
            "CREATE TABLE niuniu_group_text(group_id TEXT PRIMARY KEY, "
            "text_mode TEXT NOT NULL DEFAULT 'default')"
        )
        target.executemany(
            "INSERT INTO niuniu_group_text VALUES(?,?)",
            configuration.execute("SELECT * FROM niuniu_group_text"),
        )


def remove_new_stores(paths):
    for path in (paths.configuration, paths.runtime, paths.recurring, paths.pending):
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
