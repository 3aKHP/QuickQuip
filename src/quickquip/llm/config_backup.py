"""Paired, environment-local backups of configuration and publication execution state."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import time

from quickquip.llm.config_document import validate_document
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_execution_store import ConfigExecutionStore
from quickquip.llm.config_store import ConfigStore, dumps


def runtime_backup(path):
    path = Path(path)
    return path.with_name(path.name + ".runtime.db")


def copy_database(source, target):
    target = Path(target)
    from quickquip.llm.config_durability import ensure_directory, sync_directory

    ensure_directory(target.parent)
    with closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
    with target.open("r+b") as stream:
        os.fsync(stream.fileno())
    sync_directory(target.parent)


def backup(service, destination):
    destination = Path(destination)
    targets = (destination, runtime_backup(destination))
    if any(
        path.resolve() in (service.path.resolve(), service.execution.path.resolve())
        for path in targets
    ):
        raise ConfigError("invalid_field", "Backup must use separate files")
    with service.shared_lock:
        for store, target in zip((service.store, service.execution), targets):
            with store.connect() as source:
                copy_database(source, target)
    return destination


def restore(service, source, *, stopped=False):
    if not stopped:
        raise ConfigError("services_running", "Stop Bot and Web before database restore")
    source = Path(source)
    runtime_source = runtime_backup(source)
    if not source.is_file() or not runtime_source.is_file():
        raise ConfigError("not_found", "Restore requires configuration and .runtime.db backups")
    if source.resolve() == service.path.resolve():
        raise ConfigError("invalid_field", "Restore must use separate backup files")
    candidate = ConfigStore(source)
    execution = ConfigExecutionStore(runtime_source)
    candidate.verify()
    execution.verify()
    with candidate.connect() as connection:
        import json

        document = json.loads(connection.execute("SELECT document FROM config_meta").fetchone()[0])
    validate_document(document, config_dir=service.config_dir)
    import json

    validate_document(
        json.loads(execution.read_published()["document"]), config_dir=service.config_dir
    )
    previous = service.path.with_name(f"{service.path.name}.{time.time_ns()}.backup")
    with service.shared_lock:
        backup(service, previous)
        for origin_store, destination in (
            (candidate, service.path),
            (execution, service.execution.path),
        ):
            with origin_store.connect() as origin:
                copy_database(origin, destination)
        with service.execution.connect(write=True) as connection:
            connection.execute("DELETE FROM bot_runtime")
            connection.execute(
                "UPDATE config_operations SET status='failed',stage='restored',"
                "claim_token=NULL,lease_until=NULL,error=? WHERE status IN ('queued','running')",
                (dumps({"code": "database_restored", "message": "Operation cleared by restore"}),),
            )
    return {"backup": str(previous), **service.status()}
