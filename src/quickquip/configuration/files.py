"""Durable configuration files and same-environment SQLite rollback images."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.inventory import body, entry, safe_path
from quickquip.configuration.images import read_only, checked_path
from quickquip.llm.config_durability import durable_write, sync_directory


def write_json(path, value):
    durable_write(
        Path(path), (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode()
    )
    Path(path).chmod(0o600)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError("invalid_workspace", "Workspace metadata cannot be read") from None


def observed(root, names):
    result = {}
    for name in names:
        path = safe_path(root, name)
        if path.exists():
            mode = (path.stat().st_mode & 0o777) if os.name != "nt" else 0o600
            result[name] = entry(path.read_bytes(), mode)
    return result


def install(root, before, after):
    """Check the recorded bytes before each mutation; remove aliases before adding names."""

    def checked(name):
        current = observed(root, {name}).get(name)
        if current not in (before.get(name), after.get(name)):
            raise ConfigError("configuration_conflict", "External edit prevents recovery", name)
        return current

    current = observed(root, before.keys() | after.keys())
    for name in sorted(before.keys() | after.keys()):
        if current.get(name) not in (before.get(name), after.get(name)):
            raise ConfigError("configuration_conflict", "External edit prevents recovery", name)
    for name in sorted(before.keys() - after.keys()):
        checked(name)
        path = safe_path(root, name)
        path.unlink(missing_ok=True)
        sync_directory(path.parent)
    for name in sorted(after):
        if checked(name) == after[name]:
            continue
        path = safe_path(root, name)
        durable_write(path, body(after[name]))
        path.chmod(after[name]["mode"])



def sqlite_bytes(path):
    """Include committed WAL data in a self-contained rollback image."""
    with tempfile.TemporaryDirectory(prefix="qqconf-sqlite-") as directory:
        target = Path(directory) / "backup.db"
        with read_only(path) as source, closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
        return target.read_bytes()


def install_database(path, content):
    # SQLite backup replaces pages through SQLite, preserving live WAL/SHM semantics.
    with tempfile.TemporaryDirectory(prefix="qqconf-restore-") as directory:
        source_path = Path(directory) / "source.db"
        source_path.write_bytes(content)
        path = checked_path(path)
        for suffix in ("-wal", "-journal", "-shm"):
            checked_path(str(path) + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect(source_path)) as source,
            closing(sqlite3.connect(path)) as target,
        ):
            source.backup(target)
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())
        sync_directory(path.parent)
