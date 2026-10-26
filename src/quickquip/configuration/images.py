"""Configuration-only database preparation, retaining local history and projections."""

import os
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import shutil
import tempfile
from pathlib import Path
import sqlite3
import time

from quickquip.configuration.merge import same
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_store import ConfigStore, dumps, next_revision, project_document
from quickquip.llm.scope_types import GroupSettingsOverride
from dataclasses import asdict

DB_NAME = "config/managed/config.db"


def checked_path(path):
    path = Path(path)
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise ConfigError("invalid_configuration", "Configuration database path is redirected")
    return path


@contextmanager
def read_only(path):
    """Copy a stable SQLite/WAL view so inspection creates no source sidecars."""
    path = checked_path(path)
    sources = [path, Path(str(path) + "-wal"), Path(str(path) + "-journal")]
    for source in [*sources, Path(str(path) + "-shm")]:
        checked_path(source)

    def versions():
        result = []
        for source in sources:
            try:
                info = source.stat()
                result.append((info.st_ino, info.st_size, info.st_mtime_ns))
            except FileNotFoundError:
                result.append(None)
        return result

    with tempfile.TemporaryDirectory(prefix="qqconf-read-") as directory:
        target = Path(directory) / "config.db"
        for attempt in range(3):
            before = versions()
            if before[0] is None:
                raise FileNotFoundError(path)
            try:
                for source, suffix, state in zip(sources, ("", "-wal", "-journal"), before):
                    destination = Path(str(target) + suffix)
                    if state is not None:
                        shutil.copyfile(source, destination)
                    else:
                        destination.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
            if before == versions():
                break
        else:
            from quickquip.configuration.errors import ConfigError

            raise ConfigError("configuration_busy", "Configuration changed during snapshot; retry")
        with closing(sqlite3.connect(target)) as connection:
            yield connection


def backup(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        read_only(source) as origin,
        closing(sqlite3.connect(destination)) as target,
    ):
        origin.backup(target)
    with destination.open("r+b") as stream:
        os.fsync(stream.fileno())


def prepare(source, destination, snapshot):
    backup(source, destination)
    store = ConfigStore(destination)
    with store.connect(write=True) as connection:
        meta = connection.execute("SELECT * FROM config_meta").fetchone()
        document = snapshot["document"]
        if not same(json.loads(meta["document"]), document):
            revision = next_revision(connection)
            connection.execute(
                "UPDATE config_meta SET draft_revision=?,document=?", (revision, dumps(document))
            )
            connection.execute(
                "INSERT INTO config_revisions VALUES(?,?,?)", (revision, time.time(), "qqconf pack")
            )
            project_document(connection, document)
        write_settings(connection, snapshot)


def write_settings(connection, snapshot):
    """Install only managed scope and game settings inside the caller's transaction."""
    current = {
        row["group_id"]: dict(row) for row in connection.execute("SELECT * FROM scope_settings")
    }
    fields = asdict(GroupSettingsOverride())
    for key in current.keys() - snapshot["scopes"].keys():
        connection.execute("DELETE FROM scope_settings WHERE group_id=?", (key,))
    for key, settings in snapshot["scopes"].items():
        values = {**fields, **settings}
        old = {field: current[key][field] for field in fields} if key in current else None
        if old == values:
            continue
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        columns = ["group_id", *values]
        connection.execute(
            f"INSERT INTO scope_settings({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)}) ON CONFLICT(group_id) DO UPDATE SET "
            + ",".join(f"{column}=excluded.{column}" for column in values),
            (key, *values.values()),
        )
    modes = dict(connection.execute("SELECT group_id,text_mode FROM niuniu_group_text"))
    for key in modes.keys() - snapshot["text_modes"].keys():
        connection.execute("DELETE FROM niuniu_group_text WHERE group_id=?", (key,))
    for key, mode in snapshot["text_modes"].items():
        if modes.get(key) != mode:
            connection.execute(
                "INSERT INTO niuniu_group_text VALUES(?,?) "
                "ON CONFLICT(group_id) DO UPDATE SET text_mode=excluded.text_mode",
                (key, mode),
            )


def same_image(left, right):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="qqconf-compare-") as directory:
        paths = [Path(directory) / name for name in ("before.db", "after.db")]
        for path, data in zip(paths, (left, right)):
            path.write_bytes(data)
        with closing(sqlite3.connect(paths[0])) as a, closing(sqlite3.connect(paths[1])) as b:
            return tuple(a.iterdump()) == tuple(b.iterdump())
