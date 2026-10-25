"""Environment-local publication, pinned operation inputs and bot execution state."""

from contextlib import contextmanager, closing
import os
from pathlib import Path
import sqlite3
from functools import lru_cache

from quickquip.llm.config_errors import ConfigError

RUNTIME_SCHEMA = """
CREATE TABLE runtime_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 schema_version INTEGER NOT NULL);
INSERT INTO runtime_meta VALUES(1,1);
CREATE TABLE execution_snapshots (
 revision INTEGER PRIMARY KEY, document TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TRIGGER execution_snapshots_immutable BEFORE UPDATE ON execution_snapshots
 BEGIN SELECT RAISE(ABORT, 'immutable execution input'); END;
CREATE TABLE publication (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 published_revision INTEGER NOT NULL REFERENCES execution_snapshots(revision));
CREATE TABLE config_operations (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
 target_revision INTEGER NOT NULL REFERENCES execution_snapshots(revision),
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
 stage TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, owner TEXT,
 claim_token TEXT, lease_until REAL);
CREATE UNIQUE INDEX one_pending_apply ON config_operations(kind)
 WHERE kind='apply' AND status IN ('queued','running');
CREATE TABLE bot_runtime (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), boot_id TEXT NOT NULL,
 loaded_revision INTEGER NOT NULL, application_version TEXT NOT NULL,
 heartbeat_at REAL NOT NULL, components TEXT NOT NULL);
"""


@lru_cache(maxsize=1)
def _expected_objects():
    from quickquip.llm.config_store import _schema_tokens

    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(RUNTIME_SCHEMA)
        return {
            (row[0], row[1]): _schema_tokens(row[2])
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL"
            )
        }


class ConfigExecutionStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self, *, write=False):
        if not self.path.is_file():
            raise ConfigError("not_initialized", "Configuration execution storage is missing")
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("SELECT schema_version FROM runtime_meta").fetchone()
            if version is None or version[0] != 1:
                raise ConfigError("unsupported_schema", "Unsupported execution storage schema")
            if write:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_schema(connection)
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def create(self, revision, document, created_at):
        from quickquip.llm.config_durability import ensure_directory, sync_directory

        ensure_directory(self.path.parent)
        temporary = self.path.with_suffix(".initializing")
        try:
            with closing(sqlite3.connect(temporary)) as connection, connection:
                connection.execute("PRAGMA synchronous=FULL")
                connection.executescript(RUNTIME_SCHEMA)
                connection.execute(
                    "INSERT INTO execution_snapshots VALUES(?,?,?)",
                    (revision, document, created_at),
                )
                connection.execute("INSERT INTO publication VALUES(1,?)", (revision,))
            os.replace(temporary, self.path)
            sync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def read_published(self):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT revision,document FROM execution_snapshots JOIN publication "
                "ON revision=published_revision"
            ).fetchone()
        if row is None:
            raise ConfigError("database_corrupt", "Published configuration pointer is missing")
        return dict(row)

    @staticmethod
    def _verify_schema(connection):
        from quickquip.llm.config_store import _schema_tokens

        expected = _expected_objects()
        actual = {
            (row[0], row[1]): _schema_tokens(row[2])
            for row in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL"
            )
        }
        missing = expected.keys() - actual.keys()
        changed = {key for key in expected.keys() & actual.keys() if expected[key] != actual[key]}
        if missing or changed:
            raise ConfigError(
                "unsupported_schema",
                "Execution schema objects are invalid",
                details={
                    "missing": sorted(name for _, name in missing),
                    "changed": sorted(name for _, name in changed),
                },
            )

    def verify(self):
        with self.connect() as connection:
            self._verify_schema(connection)
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ConfigError("database_corrupt", "Execution storage is corrupt")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ConfigError("database_corrupt", "Execution snapshot references are invalid")
