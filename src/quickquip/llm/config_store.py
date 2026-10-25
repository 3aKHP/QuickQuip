"""SQLite persistence for configuration documents and immutable local history."""

from __future__ import annotations

import json
import os
import re
import uuid
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from quickquip.configuration.database import DOMAIN_SCHEMA, SCHEMA_VERSION

# Snapshot-owned settings that do not require a relational lookup/index column.
# Keep the schema-2 projection compatible with databases from existing installations.
DOCUMENT_ONLY_SETTINGS = {"runtime": frozenset({"claude_code_device_id", "gemini_cli_install_id"})}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS config_meta (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
 draft_revision INTEGER NOT NULL,
 document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config_snapshots (
 revision INTEGER PRIMARY KEY, document TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS snapshots_immutable_update BEFORE UPDATE ON config_snapshots
 BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_immutable_delete BEFORE DELETE ON config_snapshots
 BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END;
CREATE TABLE IF NOT EXISTS providers (
 id TEXT PRIMARY KEY, position INTEGER NOT NULL, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_models (
 provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
 model TEXT NOT NULL, position INTEGER NOT NULL, document TEXT NOT NULL,
 PRIMARY KEY(provider_id,model));
CREATE TABLE IF NOT EXISTS model_aliases (
 provider_id TEXT NOT NULL, alias TEXT NOT NULL, model TEXT NOT NULL, position INTEGER NOT NULL,
 FOREIGN KEY(provider_id,model) REFERENCES provider_models(provider_id,model),
 PRIMARY KEY(provider_id,alias));
CREATE TABLE IF NOT EXISTS style_profiles (id TEXT PRIMARY KEY, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pricing_rules (position INTEGER PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_routes (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS route_entries (
 route_id TEXT REFERENCES model_routes(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(route_id,position));
CREATE TABLE IF NOT EXISTS config_settings (id TEXT PRIMARY KEY, document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config_migrations (
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, report TEXT NOT NULL, created_at REAL NOT NULL);
"""


# Schema 3: per-revision version label (saved time + operator note). Kept apart from the
# immutable snapshots so notes stay editable after a revision is published.
_REVISIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS config_revisions (
 revision INTEGER PRIMARY KEY, saved_at REAL, note TEXT NOT NULL DEFAULT '');
"""


def _columns(fields):
    sql_types = {"boolean": "INTEGER", "integer": "INTEGER", "number": "REAL"}
    return ", ".join(
        f'"{name}" {sql_types.get(spec["type"], "TEXT")}' for name, spec in fields.items()
    )


def declared_schema(*, legacy=False):
    from quickquip.llm.config_fields import field_registry

    registry = field_registry()
    columns = _columns(registry["parameters"])
    statements = [
        f"CREATE TABLE IF NOT EXISTS provider_parameters ("
        f"provider_id TEXT PRIMARY KEY REFERENCES providers(id) ON DELETE CASCADE, {columns});",
        f"CREATE TABLE IF NOT EXISTS model_parameters (provider_id TEXT NOT NULL,"
        f"model TEXT NOT NULL, {columns}, PRIMARY KEY(provider_id,model),"
        f"FOREIGN KEY(provider_id,model) REFERENCES provider_models(provider_id,model) "
        f"ON DELETE CASCADE);",
    ]
    for name, fields in registry["settings"].items():
        fields = {key: spec for key, spec in fields.items()
                  if key != "model_cascade" and key not in DOCUMENT_ONLY_SETTINGS.get(name, ())}
        if legacy and name == "runtime":
            fields.pop("client_cluster", None)
        if name == "mcp":
            fields["servers"] = {"type": "array"}
        statements.append(
            f'CREATE TABLE IF NOT EXISTS "{name}_settings" '
            f"(singleton INTEGER PRIMARY KEY CHECK(singleton=1), {_columns(fields)});"
        )
    return "\n".join(statements)


def _schema_tokens(sql):
    """Normalize spelling while retaining constraint, predicate and trigger tokens."""
    tokens = re.findall(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`|\[[^]]*\]|"
        r"[A-Za-z_][A-Za-z_0-9]*|[0-9.]+|\S",
        sql,
    )
    return tuple(
        token
        if token.startswith("'")
        else (
            token[1:-1].replace('""', '"').lower()
            if token.startswith(('"', "`", "["))
            else token.lower()
        )
        for token in tokens
    )


@lru_cache(maxsize=1)
def expected_schema_objects(version=SCHEMA_VERSION):
    """Use SQLite's own stored DDL as the schema version's reference contract."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            _SCHEMA
            + (_REVISIONS_SCHEMA if version >= 3 else "")
            + declared_schema(legacy=version == 1) + DOMAIN_SCHEMA
        )
        return {
            (row[0], row[1]): _schema_tokens(row[2])
            for row in conn.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
    finally:
        conn.close()


def _database_value(value):
    return dumps(value) if isinstance(value, (dict, list)) else value


def _insert_fields(conn, table, identity, values):
    fields = {**identity, **values}
    columns = ",".join(f'"{field}"' for field in fields)
    placeholders = ",".join("?" for _ in fields)
    conn.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES({placeholders})',
        tuple(_database_value(value) for value in fields.values()),
    )


def dumps(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class ConfigStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self, *, write=False):
        from quickquip.llm.config_document import ConfigError

        if not self.path.exists():
            raise ConfigError("not_initialized", "Configuration database is not initialized")
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=FULL")
            row = conn.execute(
                "SELECT schema_version FROM config_meta WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != SCHEMA_VERSION:
                raise ConfigError(
                    "unsupported_schema",
                    "Unsupported configuration schema",
                    details={"supported": SCHEMA_VERSION, "actual": row[0] if row else None},
                )
            if write:
                conn.execute("BEGIN IMMEDIATE")
                self._verify_schema(conn)
            yield conn
            if write:
                conn.commit()
        except sqlite3.OperationalError as exc:
            if conn.in_transaction:
                conn.rollback()
            if "locked" in str(exc):
                raise ConfigError("database_busy", "Configuration database is busy") from None
            raise ConfigError(
                "unsupported_schema", "Configuration database schema is invalid"
            ) from None
        except sqlite3.DatabaseError:
            if conn.in_transaction:
                conn.rollback()
            raise ConfigError("database_corrupt", "Configuration database is unreadable") from None
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _verify_schema(conn, version=SCHEMA_VERSION):
        from quickquip.llm.config_document import ConfigError

        expected = expected_schema_objects(version)
        actual = {
            (row[0], row[1]): _schema_tokens(row[2])
            for row in conn.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL")
        }
        missing = expected.keys() - actual.keys()
        changed = {key for key in expected.keys() & actual.keys() if expected[key] != actual[key]}
        if missing or changed:
            raise ConfigError(
                "unsupported_schema",
                "Configuration schema objects are invalid",
                details={
                    "missing": sorted(name for _, name in missing),
                    "changed": sorted(name for _, name in changed),
                },
            )

    def upgrade(self, *, services_stopped=False):
        """Layout changes are performed by the explicit offline migration."""
        self.verify()

    def verify(self):
        """Check a schema-compatible backup before it can replace live state."""
        from quickquip.llm.config_document import ConfigError

        with self.connect() as conn:
            self._verify_schema(conn)
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ConfigError(
                    "database_corrupt", "Configuration database integrity check failed"
                )
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ConfigError(
                    "database_corrupt", "Configuration database references are invalid"
                )

    def create(self, document, report=None, source=""):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.initializing")
        try:
            ConfigStore(temporary)._create(document, report, source)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            from quickquip.llm.config_durability import sync_directory

            sync_directory(self.path.parent)
        finally:
            for path in (temporary, Path(str(temporary) + "-wal"), Path(str(temporary) + "-shm")):
                path.unlink(missing_ok=True)

    def _create(self, document, report=None, source=""):
        import time

        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA + _REVISIONS_SCHEMA + declared_schema() + DOMAIN_SCHEMA)
            with conn:
                conn.execute(
                    "INSERT INTO config_meta VALUES (1,?,?,?)",
                    (SCHEMA_VERSION, 1, dumps(document)),
                )
                now = time.time()
                conn.execute(
                    "INSERT INTO config_snapshots VALUES (?,?,?)", (1, dumps(document), now)
                )
                conn.execute(
                    "INSERT INTO config_revisions(revision,saved_at) VALUES(1,?)", (now,)
                )
                project_document(conn, document)
                if report is not None:
                    conn.execute(
                        "INSERT INTO config_migrations(source,report,created_at) VALUES(?,?,?)",
                        (source, dumps(report), time.time()),
                    )
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()


def project_document(conn, document):
    """Maintain relational indexes in the same transaction as the draft."""
    from quickquip.llm.config_fields import field_registry

    registry = field_registry()
    for name in registry["settings"]:
        conn.execute(f'DELETE FROM "{name}_settings"')
    for table in (
        "model_aliases",
        "model_parameters",
        "provider_parameters",
        "provider_models",
        "providers",
        "style_profiles",
        "pricing_rules",
        "route_entries",
        "model_routes",
        "config_settings",
    ):
        conn.execute(f"DELETE FROM {table}")
    for position, provider in enumerate(document["providers"]):
        pid = provider["id"]
        conn.execute("INSERT INTO providers VALUES(?,?,?)", (pid, position, dumps(provider)))
        _insert_fields(
            conn, "provider_parameters", {"provider_id": pid}, provider.get("parameters", {})
        )
        for order, model in enumerate(provider.get("models", [])):
            conn.execute(
                "INSERT INTO provider_models VALUES(?,?,?,?)",
                (pid, model["model"], order, dumps(model)),
            )
            _insert_fields(
                conn,
                "model_parameters",
                {"provider_id": pid, "model": model["model"]},
                model.get("parameters", {}),
            )
        for order, alias in enumerate(provider.get("aliases", [])):
            conn.execute(
                "INSERT INTO model_aliases VALUES(?,?,?,?)",
                (pid, alias["alias"], alias["model"], order),
            )
    for name, text in document.get("style_profiles", {}).items():
        conn.execute("INSERT INTO style_profiles VALUES(?,?)", (name, text))
    for order, rule in enumerate(document.get("pricing", [])):
        conn.execute("INSERT INTO pricing_rules VALUES(?,?)", (order, dumps(rule)))
    for name, entries in document.get("routes", {}).items():
        conn.execute("INSERT INTO model_routes VALUES(?)", (name,))
        for order, entry in enumerate(entries):
            conn.execute("INSERT INTO route_entries VALUES(?,?,?)", (name, order, dumps(entry)))
    for name, settings in document.get("settings", {}).items():
        conn.execute("INSERT INTO config_settings VALUES(?,?)", (name, dumps(settings)))
        projected = {k: v for k, v in settings.items()
                     if k not in DOCUMENT_ONLY_SETTINGS.get(name, ())}
        _insert_fields(conn, f"{name}_settings", {"singleton": 1}, projected)


def projection_consistent(connection) -> None:
    """Compare stored projections against an independently projected draft in memory."""
    import sqlite3
    from quickquip.configuration.errors import ConfigError

    document = json.loads(connection.execute("SELECT document FROM config_meta").fetchone()[0])
    with sqlite3.connect(":memory:") as expected:
        expected.executescript(_SCHEMA + _REVISIONS_SCHEMA + declared_schema())
        project_document(expected, document)
        tables = [
            row[0]
            for row in expected.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("config_") and row[0] != "bot_runtime"
        ]
        tables.append("config_settings")
        for table in tables:
            actual_rows = sorted(
                tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')
            )
            expected_rows = sorted(expected.execute(f'SELECT * FROM "{table}"').fetchall())
            if actual_rows != expected_rows:
                raise ConfigError(
                    "projection_mismatch",
                    "Draft and relational projections differ; use ConfigService",
                    table,
                )
