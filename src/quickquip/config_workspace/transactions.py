"""Apply and recover a workspace refresh without modifying its source configuration."""

from quickquip.llm.config_errors import ConfigError


def check_source(record, endpoint, storage):
    if record["source"] != str(endpoint.root):
        raise ConfigError("endpoint_changed", "Recovery must use the original configuration root")
    if record.get("workspace") != str(storage.directory):
        raise ConfigError(
            "endpoint_changed",
            "Resume or recover from the original workspace directory",
            details={"workspace": record.get("workspace"), "operation": record["id"]},
        )


def advance(storage, endpoint, record):
    check_source(record, endpoint, storage)
    if record["phase"] in ("confirmed", "recovered"):
        storage.finish(record, record["phase"])
        return summary(record)
    if record["phase"] == "recovering":
        return rollback(storage, endpoint, record)
    storage.check_files(record)
    if endpoint.version() != record["source_version"]:
        raise ConfigError("revision_conflict", "Source configuration changed after planning")
    record["phase"] = "writing"
    storage.save(record)
    storage.install(record)
    if endpoint.version() != record["source_version"]:
        raise ConfigError("revision_conflict", "Source changed during workspace refresh")
    storage.finish(record, "confirmed")
    return summary(record)


def rollback(storage, endpoint, record):
    check_source(record, endpoint, storage)
    if record["phase"] == "confirmed":
        raise ConfigError("operation_conflict", "Confirmed workspace operation cannot be recovered")
    if record["phase"] == "recovered":
        storage.finish(record, "recovered")
        return summary(record)
    storage.check_files(record)
    record["phase"] = "recovering"
    storage.save(record)
    storage.install(record, restore=True)
    storage.finish(record, "recovered")
    return summary(record)


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
