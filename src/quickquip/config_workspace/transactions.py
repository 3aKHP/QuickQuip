"""Coordinate a workspace journal with a local configuration endpoint transaction."""

from quickquip.config_sync.bundle import digest, validate_bundle
from quickquip.config_workspace.storage import baseline
from quickquip.llm.config_errors import ConfigError


def require_stopped(endpoint, stopped):
    if not stopped:
        raise ConfigError("services_running", "Stop Bot and Web, then pass --services-stopped")
    bot = endpoint.service.status()["bot"]
    if bot and not bot["stale"]:
        raise ConfigError("services_running", "Bot heartbeat is still fresh; wait for it to expire")


def check_source(record, endpoint, storage):
    if record["source"] != str(endpoint.root):
        raise ConfigError("endpoint_changed", "Recovery must use the original configuration root")
    if record.get("workspace") != str(storage.directory):
        raise ConfigError(
            "endpoint_changed",
            "Resume or recover from the original workspace directory",
            details={"workspace": record.get("workspace"), "operation": record["id"]},
        )


def advance(storage, endpoint, record, *, services_stopped=False):
    check_source(record, endpoint, storage)
    if record["phase"] in ("confirmed", "recovered"):
        storage.finish(record, record["phase"])
        return summary(record)
    if record["phase"] == "recovering":
        return rollback(storage, endpoint, record, services_stopped=services_stopped)
    existing = (
        endpoint.state.read(f"operations/{record['id']}.json") if record.get("root_write") else None
    )
    if existing and existing.get("local_only") and existing["phase"] == "confirmed":
        # Source confirmation follows durable workspace installation. Later source or
        # working-file edits are new work; repairing this receipt must leave them alone.
        if storage.read("state.json") != record["target_state"]:
            raise ConfigError("revision_conflict", "Committed workspace baseline changed")
        endpoint.release_terminal(record["id"])
        storage.finish(record, "confirmed")
        return summary(record)
    storage.check_files(record)
    if record.get("root_write"):
        if existing is None:
            if record["assets_changed"]:
                require_stopped(endpoint, services_stopped)
            endpoint.prepare(
                record["id"],
                record["target_state"]["base"],
                record["source_version"],
                local_only=True,
            )
        elif not existing.get("local_only"):
            raise ConfigError(
                "operation_conflict", "Operation belongs to configuration synchronization"
            )
        if record["assets_changed"]:
            require_stopped(endpoint, services_stopped)
        endpoint.commit(record["id"])
        with endpoint.owned_operation(record["id"]):
            captured = endpoint.capture()
            if digest(captured["bundle"]) != record["target_state"]["base_hash"]:
                raise ConfigError(
                    "revision_conflict", "Committed draft differs from the workspace plan"
                )
            record["target_state"] = baseline(endpoint.root, captured)
        record["phase"] = "root_committed"
        storage.save(record)
    else:
        # Refresh and no-op pack must not commit an obsolete source snapshot.
        if endpoint.version() != record["source_version"]:
            raise ConfigError("revision_conflict", "Source configuration changed after planning")
    record["phase"] = "writing"
    storage.save(record)
    storage.install(record)
    if record.get("root_write"):
        endpoint.complete_local(record["id"])
    elif endpoint.version() != record["source_version"]:
        raise ConfigError("revision_conflict", "Source changed during workspace refresh")
    storage.finish(record, "confirmed")
    return summary(record)


def rollback(storage, endpoint, record, *, services_stopped=False):
    check_source(record, endpoint, storage)
    if record["phase"] == "confirmed":
        raise ConfigError("operation_conflict", "Confirmed workspace operation cannot be recovered")
    if record["phase"] == "recovered":
        storage.finish(record, "recovered")
        return summary(record)
    storage.check_files(record)
    operation = (
        endpoint.state.read(f"operations/{record['id']}.json") if record.get("root_write") else None
    )
    if operation is not None:
        if operation["phase"] == "confirmed":
            raise ConfigError(
                "operation_conflict", "Local transaction committed; resume its receipt"
            )
        if operation["phase"] not in ("prepared", "recovered"):
            require_stopped(endpoint, services_stopped)
        endpoint.recover(record["id"], services_stopped=services_stopped)
    record["phase"] = "recovering"
    storage.save(record)
    storage.install(record, restore=True)
    storage.finish(record, "recovered")
    return summary(record)


def validate_target(result, captured):
    if captured["pending"]:
        raise ConfigError("operation_conflict", "Finish pending configuration tasks first")
    if result["assets_changed"]:
        validate_bundle({**result["bundle"], "document": captured["published"]})


def summary(record):
    return {
        "operation": record["id"],
        "action": record["action"],
        "phase": record["phase"],
        "baseline_hash": record["target_state"]["base_hash"]
        if record["phase"] != "recovered"
        else record["before_state"]["base_hash"],
        "draft_revision": record["target_state"]["version"]["draft_revision"]
        if record["phase"] != "recovered"
        else record["before_state"]["version"]["draft_revision"],
    }
