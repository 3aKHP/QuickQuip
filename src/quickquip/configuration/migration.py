"""One offline layout migration with local backups and whole-operation recovery."""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3

from filelock import FileLock

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.paths import StoragePaths
from quickquip.llm.config_durability import durable_write


def _write(path, value):
    durable_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def require_fresh_layout(root):
    paths = StoragePaths(Path(root))
    if paths.migration.exists():
        state = json.loads(paths.migration.read_text(encoding="utf-8"))
        if state["status"] == "in_progress":
            raise ConfigError(
                "migration_required", "Recover the interrupted storage migration first"
            )
    if (paths.root / "data/llm_config.db").exists():
        raise ConfigError("migration_required", "Stop services and run migrate-storage")
    for filename, table in (("llm.db", "group_settings"), ("niuniu.db", "niuniu_group_text")):
        path = paths.root / "data" / filename
        if path.exists():
            with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    raise ConfigError("migration_required", "Stop services and run migrate-storage")
    if (paths.root / "data/scheduled_messages.json").exists():
        raise ConfigError(
            "migration_required", "Split legacy scheduled messages with migrate-storage"
        )


def _backup_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".db":
        with (
            closing(sqlite3.connect(source)) as origin,
            closing(sqlite3.connect(destination)) as backup,
        ):
            origin.backup(backup)
    else:
        shutil.copyfile(source, destination)


def rollback(root, backup, *, services_stopped=False):
    if not services_stopped:
        raise ConfigError("services_running", "Stop Bot and Web before storage recovery")
    paths = StoragePaths(Path(root))
    backup = Path(backup)
    record = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if record["status"] == "complete":
        from quickquip.configuration.rollback_storage import reverse, remove_new_stores

        current = json.loads(paths.migration.read_text(encoding="utf-8"))
        if not current.get("reverse_complete"):
            reverse(paths)
            _write(paths.migration, {**record, "status": "rolled_back", "reverse_complete": True})
        remove_new_stores(paths)
        return {"status": "rolled_back", "backup": str(backup), "business_data_retained": True}
    for name, existed in record["files"].items():
        target = paths.root / name
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        if existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".restoring")
            shutil.copyfile(backup / name, temporary)
            os.replace(temporary, target)
        else:
            target.unlink(missing_ok=True)
    _write(paths.migration, {**record, "status": "rolled_back", "backup": str(backup)})
    return {"status": "rolled_back", "backup": str(backup)}


def migrate(root, *, services_stopped=False):
    if not services_stopped:
        raise ConfigError("services_running", "Stop Bot and Web before storage migration")
    paths = StoragePaths(Path(root).resolve())
    paths.migration.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(paths.migration) + ".lock", timeout=10):
        if paths.migration.exists():
            previous = json.loads(paths.migration.read_text(encoding="utf-8"))
            if previous["status"] == "complete":
                from quickquip.llm.config_store import ConfigStore

                ConfigStore(paths.configuration).verify()
                return {**previous, "changed": False}
            if previous.get("reverse_complete"):
                from quickquip.configuration.rollback_storage import remove_new_stores

                remove_new_stores(paths)
            if previous["status"] == "in_progress":
                rollback(paths.root, previous["backup"], services_stopped=True)
        if any(
            path.exists()
            for path in (paths.configuration, paths.runtime, paths.pending, paths.recurring)
        ):
            raise ConfigError(
                "configuration_conflict", "New storage already exists; inspect it first"
            )
        names = [
            "data/llm_config.db",
            "data/llm.db",
            "data/niuniu.db",
            "data/scheduled_messages.json",
            "config/managed/config.db",
            "config/managed/scheduled_messages.json",
            "data/config_runtime.db",
            "data/pending_scheduled_messages.json",
        ]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = paths.root / "data" / "storage-backups" / stamp
        from quickquip.llm.config_durability import ensure_directory

        ensure_directory(backup)
        record = {
            "root": str(paths.root),
            "backup": str(backup),
            "status": "in_progress",
            "files": {name: (paths.root / name).exists() for name in names},
        }
        for name, exists in record["files"].items():
            if exists:
                _backup_file(paths.root / name, backup / name)
        _write(backup / "manifest.json", record)
        _write(paths.migration, record)
        try:
            from quickquip.configuration import legacy_storage
            from quickquip.llm.config_store import ConfigStore
            from quickquip.llm.config_execution_store import ConfigExecutionStore

            legacy_storage.configuration(paths)
            counts = {
                "scope_settings": legacy_storage.scope_settings(paths),
                "text_modes": legacy_storage.text_modes(paths),
                "schedules": legacy_storage.scheduled_messages(paths),
            }
            ConfigStore(paths.configuration).verify()
            ConfigExecutionStore(paths.runtime).verify()
            for name in ("data/llm.db", "data/niuniu.db"):
                path = paths.root / name
                if path.exists():
                    with sqlite3.connect(path) as connection:
                        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ConfigError("database_corrupt", "Business storage check failed")
            for name in ("data/llm_config.db", "data/scheduled_messages.json"):
                path = paths.root / name
                for suffix in ("", "-wal", "-shm"):
                    Path(str(path) + suffix).unlink(missing_ok=True)
            record.update(status="complete", changed=True, migrated=counts)
            _write(backup / "manifest.json", record)
            _write(paths.migration, record)
            return record
        except BaseException:
            rollback(paths.root, backup, services_stopped=True)
            raise
