"""Carry completed baselines and interrupted transactions forward from config-v1."""

from contextlib import ExitStack
from copy import deepcopy

from quickquip.config_sync.bundle import in_scope as legacy_scope
from quickquip.config_sync.native import Native
from quickquip.configuration.activity import stopped_service
from quickquip.configuration.errors import ConfigError


def baseline(state, identity, receiving):
    if not identity:
        return None
    legacy = state.baseline(identity["id"])
    if legacy is None:
        return None
    result = deepcopy(receiving)
    result["document"] = legacy["document"]
    result["files"] = {
        name: value for name, value in result["files"].items() if not legacy_scope(name)
    }
    result["files"].update(legacy["assets"])
    return result


def pending(state):
    folder = state.directory / "clients"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        record = state.read("clients/" + path.name)
        if record.get("phase") not in ("confirmed", "recovered", "rejected"):
            return record
    return None


def resume(root, record):
    from quickquip.config_sync.client import Synchronizer
    from quickquip.config_sync.endpoint import Endpoint
    from quickquip.config_sync.transport import SSHRemote

    destination = record["destination"]
    remote = SSHRemote(destination["host"], destination["root"])
    sync = Synchronizer(Endpoint(root), remote)
    controller = Native(root)
    original = controller.inspect()
    controller.pause(original)
    try:
        with ExitStack() as leases:
            for role in ("bot", "web"):
                leases.enter_context(stopped_service(root, role))
            try:
                result = sync.resume(record["id"])
            except ConfigError as error:
                if error.code not in ("deployment_not_started", "sync_recovered"):
                    raise
                result = sync.recover(record["id"], services_stopped=True)
    finally:
        controller.restore(original)
        controller.verify(original)
    return {"phase": result["phase"], "message": "Previous configuration transaction completed"}
