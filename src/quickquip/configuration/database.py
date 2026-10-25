"""Connections and domain-independent tables in the shared configuration database."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from quickquip.configuration.errors import ConfigError

SCHEMA_VERSION = 4

DOMAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS scope_settings (
 group_id TEXT PRIMARY KEY, enabled INTEGER, memory_enabled INTEGER,
 auto_memory_enabled INTEGER, agent_delivery_intermediate_enabled INTEGER,
 agent_delivery_final_enabled INTEGER, provider_id TEXT, model TEXT, persona_id TEXT,
 trigger_prefix TEXT, allow_prefix INTEGER, allow_at INTEGER, history_limit INTEGER,
 reasoning_effort TEXT, updated_at TEXT NOT NULL,
 CHECK(group_id NOT LIKE 'private:%' OR enabled IS NULL));
CREATE TABLE IF NOT EXISTS niuniu_group_text (
 group_id TEXT PRIMARY KEY, text_mode TEXT NOT NULL DEFAULT 'default');
"""


@contextmanager
def connect(path: Path, *, write=False):
    """Open existing configuration; domain reads never create an empty database."""
    if not path.is_file():
        raise ConfigError("not_initialized", "Initialize or migrate configuration storage first")
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        version = connection.execute("SELECT schema_version FROM config_meta").fetchone()
        if version is None or version[0] != SCHEMA_VERSION:
            raise ConfigError("migration_required", "Configuration storage requires migration")
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
