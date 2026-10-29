"""Recover configuration installations and candidate publication from local receipts."""

import os
from pathlib import Path
import shutil
from uuid import uuid4

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.images import DB_NAME, same_image
from quickquip.configuration.inventory import body, entry
from quickquip.configuration.files import (
    install,
    install_database,
    read_json,
    sqlite_bytes,
    write_json,
)
from quickquip.llm.config_durability import sync_directory


def _committed(record, storage):
    path = storage.private / "state.json"
    return path.exists() and read_json(path) == record["state_after"]


def recover_source(root, storage):
    root = Path(root)
    marker = root / "data/qqconf/active.json"
    if not marker.exists():
        return
    record = read_json(marker)
    if record["workspace"] != str(storage.directory):
        raise ConfigError("recovery_required", "Recover using the original workspace")
    if not _committed(record, storage):
        current = sqlite_bytes(root / DB_NAME)
        if not any(same_image(current, body(record[name])) for name in ("db_before", "db_after")):
            raise ConfigError("configuration_conflict", "External database edit prevents recovery")
        install(root, record["files_after"], record["files_before"])
        install_database(root / DB_NAME, body(record["db_before"]))
    storage.recover()
    marker.unlink()
    sync_directory(marker.parent)


def commit_source(root, storage, before, target, prepared_db, work_before, work_after, state):
    state["receipt"] = uuid4().hex
    root = Path(root)
    marker = root / "data/qqconf/active.json"
    record = {
        "workspace": str(storage.directory),
        "state_after": state,
        "files_before": before["files"],
        "files_after": target["files"],
        "db_before": entry(sqlite_bytes(root / DB_NAME)),
        "db_after": entry(Path(prepared_db).read_bytes()),
    }
    write_json(marker, record)
    try:
        install(root, before["files"], target["files"])
        install_database(root / DB_NAME, body(record["db_after"]))
        storage.save(work_before, work_after, state)
    except BaseException:
        recover_source(root, storage)
        raise
    marker.unlink()
    sync_directory(marker.parent)


def recover_candidate(root, storage):
    root = Path(root)
    marker = root / "data/qqconf/staging.json"
    if not marker.exists():
        return
    record = read_json(marker)
    if record["workspace"] != str(storage.directory):
        raise ConfigError("recovery_required", "Recover the candidate using its original workspace")
    candidate, building, previous = [
        root / name
        for name in (
            ".config-staging",
            ".config-staging.new",
            ".config-staging.previous",
        )
    ]
    if not _committed(record, storage):
        if previous.exists():
            shutil.rmtree(candidate, ignore_errors=True)
            previous.rename(candidate)
        elif not record["existed"]:
            shutil.rmtree(candidate, ignore_errors=True)
    for path in (building, previous):
        if path.exists():
            shutil.rmtree(path)
    storage.recover()
    marker.unlink()
    sync_directory(root)
    sync_directory(marker.parent)


def commit_candidate(root, storage, before, target, prepared_db, work_before, work_after, state):
    state["receipt"] = uuid4().hex
    root = Path(root)
    candidate, building, previous = [
        root / name
        for name in (
            ".config-staging",
            ".config-staging.new",
            ".config-staging.previous",
        )
    ]
    if candidate.exists():
        manifest = candidate / "candidate.json"
        if not manifest.is_file() or read_json(manifest).get("source_root") != str(root):
            raise ConfigError(
                "candidate_conflict", "Existing candidate belongs to a different source"
            )
    if building.exists() or previous.exists():
        raise ConfigError("recovery_required", "Unfinished candidate files require recovery")
    marker = root / "data/qqconf/staging.json"
    write_json(
        marker,
        {"workspace": str(storage.directory), "state_after": state, "existed": candidate.exists()},
    )
    try:
        building.mkdir(mode=0o700)
        install(building, {}, target["files"])
        path = building / DB_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prepared_db, path)
        path.chmod(0o600)
        with path.open("r+b") as stream:
            os.fsync(stream.fileno())
        write_json(
            building / "candidate.json",
            {
                "format": 1,
                "source_root": str(root),
                "base": before,
                "managed_files": sorted([DB_NAME, *target["files"]]),
                "deleted_files": sorted(before["files"].keys() - target["files"].keys()),
            },
        )
        for directory in sorted(
            (p for p in building.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True
        ):
            sync_directory(directory)
        sync_directory(building)
        if candidate.exists():
            candidate.rename(previous)
            sync_directory(root)
        building.rename(candidate)
        sync_directory(root)
        storage.save(work_before, work_after, state)
    except BaseException:
        recover_candidate(root, storage)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    marker.unlink()
    sync_directory(root)
    sync_directory(marker.parent)
