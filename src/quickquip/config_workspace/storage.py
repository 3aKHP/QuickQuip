"""Private baselines and durable file-set installation without user-managed tokens."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from filelock import FileLock

from quickquip.configuration.errors import ConfigError
from quickquip.config_workspace.inventory import body, entry, safe_path
from quickquip.config_workspace.database import read_only, checked_path
from quickquip.llm.config_durability import durable_write, sync_directory

FORMAT = 2


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


class Storage:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        if any(path.is_symlink() for path in (self.directory, *self.directory.parents)):
            raise ConfigError("invalid_workspace", "Workspace path is redirected")
        self.directory = self.directory.resolve()
        self.private = self.directory / ".qqconf"
        if self.private.is_symlink():
            raise ConfigError("invalid_workspace", "Workspace metadata is redirected")

    def state(self):
        state = read_json(self.private / "state.json")
        if state.get("format") != FORMAT:
            raise ConfigError("legacy_workspace", "Unpack into a new workspace")
        return state

    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.directory.chmod(0o700)
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileLock(str(self.private / "write.lock"), timeout=10)

    def pending(self):
        return (self.private / "transaction.json").exists()

    def recover(self):
        if not self.pending():
            return
        record = read_json(self.private / "transaction.json")
        if (self.private / "state.json").exists() and self.state() == record["state_after"]:
            (self.private / "transaction.json").unlink()
            sync_directory(self.private)
            return
        install(self.directory, record["after"], record["before"])
        if record["state_before"] is None:
            (self.private / "state.json").unlink(missing_ok=True)
        else:
            write_json(self.private / "state.json", record["state_before"])
        (self.private / "transaction.json").unlink()
        sync_directory(self.private)

    def save(self, before, after, state):
        previous = self.state() if (self.private / "state.json").exists() else None
        if before == after and previous == state:
            return
        if previous is not None and previous.get("receipt") == state.get("receipt"):
            state["receipt"] = uuid4().hex
        write_json(
            self.private / "transaction.json",
            {
                "before": before,
                "after": after,
                "state_before": previous,
                "state_after": state,
            },
        )
        try:
            install(self.directory, before, after)
            write_json(self.private / "state.json", state)
        except BaseException:
            self.recover()
            raise
        (self.private / "transaction.json").unlink()
        sync_directory(self.private)


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
