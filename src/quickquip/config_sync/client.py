"""Two-endpoint reconciliation; journals survive SSH and client interruptions."""

import time
import uuid

from quickquip.config_sync.bundle import digest
from quickquip.config_sync.planning import plan
from quickquip.llm.config_errors import ConfigError


class Synchronizer:
    def __init__(self, local, remote):
        self.local, self.remote = local, remote

    def preview(self, mode="auto", overwrite=False, initial=None):
        local = self.local.capture()
        peer = local["identity"]["id"] if local["identity"] else None
        remote = self.remote.call("read", {"peer": peer})
        remote_id = remote["identity"]["id"] if remote["identity"] else None
        if peer and peer == remote_id:
            raise ConfigError(
                "endpoint_conflict", "Local and remote require distinct endpoint identities"
            )
        base = self.local.state.baseline(remote_id) if remote_id else None
        if initial:
            if initial not in ("local", "remote"):
                raise ConfigError("invalid_field", "Initial source must be local or remote")
            if base is not None:
                raise ConfigError("operation_conflict", "Synchronization is already initialized")
            mode = "push" if initial == "local" else "pull"
            base = remote["bundle"] if initial == "local" else local["bundle"]
        elif base is None or remote.get("base") is None:
            raise ConfigError(
                "baseline_required", "Initialize synchronization with --from local or remote"
            )
        elif digest(base) != digest(remote["base"]):
            raise ConfigError(
                "baseline_conflict", "Endpoint baselines differ; resume the last operation"
            )
        result = plan(base, local["bundle"], remote["bundle"], mode=mode, overwrite=overwrite)
        result["remote_draft"] = remote["dirty_draft"]
        result["restart"] = any(c["remote"] and c["unit"] != "document" for c in result["changes"])
        if not result["conflicts"]:
            result.update(self.remote.call("preflight", {"bundle": result["bundle"]}))
        return result, local, remote

    def prepare(self, *, mode="auto", overwrite=False, initial=None, deployment=False):
        result, local, remote = self.preview(mode, overwrite, initial)
        if result["conflicts"]:
            raise ConfigError(
                "sync_conflict",
                "Both endpoints changed the same configuration units",
                details={"units": result["conflicts"]},
            )
        local_id = self.local.initialize_identity()["id"]
        remote_id = self.remote.call("identity")["id"]
        if local_id == remote_id:
            raise ConfigError(
                "endpoint_conflict", "Local and remote require distinct endpoint identities"
            )
        # Pin transport destination to identity, including initial creation races.
        if remote["identity"] and remote["identity"]["id"] != remote_id:
            raise ConfigError("endpoint_changed", "Remote identity changed during planning")
        operation = uuid.uuid4().hex
        record = {
            "id": operation,
            "phase": "preparing",
            "local": local_id,
            "remote": remote_id,
            "bundle": result["bundle"],
            "deployment": deployment,
            "remote_expected": remote["version"],
            "local_expected": local["version"],
            "overwrite": overwrite,
            "destination": {
                "host": getattr(self.remote, "host", None),
                "root": getattr(self.remote, "root", None),
            },
        }
        self.local.state.write(f"clients/{operation}.json", record)
        # Retain uncertain preparation for resume: SSH failure does not imply no remote write.
        try:
            self.local.prepare(operation, result["bundle"], local["version"])
            self.remote.call(
                "prepare",
                {
                    "operation": operation,
                    "bundle": result["bundle"],
                    "expected": remote["version"],
                    "overwrite": overwrite,
                    "deployment": deployment,
                },
            )
        except ConfigError as exc:
            if exc.code != "transport_error":
                if self.local.state.read(f"operations/{operation}.json"):
                    self.local.recover(operation)
                record["phase"] = "rejected"
                self.local.state.write(f"clients/{operation}.json", record)
            exc.details = {"operation": operation, "cause": exc.details}
            raise
        record["phase"] = "prepared"
        self.local.state.write(f"clients/{operation}.json", record)
        return operation

    def wait_remote(self, operation, timeout=240):
        deadline = time.monotonic() + timeout
        while True:
            try:
                state = self.remote.call("inspect", {"operation": operation})
            except ConfigError as exc:
                if exc.code != "transport_error":
                    raise
                state = {"phase": "unavailable"}
            if state["phase"] == "confirmed":
                return state
            if state["phase"] == "committed":
                release = state.get("deployment")
                status = self.remote.deployment_status(release) if release else "0"
                if status == "0":
                    return state
                if status == "superseded":
                    raise ConfigError(
                        "deployment_changed",
                        "The committed release is no longer current",
                        details={"operation": operation},
                    )
            if state["phase"] == "recovered":
                self.remote.call("release-terminal", {"operation": operation})
                raise ConfigError(
                    "sync_recovered",
                    "Remote operation failed and was recovered",
                    details={"operation": operation},
                )
            if time.monotonic() >= deadline:
                raise ConfigError(
                    "sync_unconfirmed",
                    "Operation remains unconfirmed; resume its ID",
                    details={"operation": operation},
                )
            time.sleep(2)

    def finish(self, operation, timeout=240):
        record = self.local.state.read(f"clients/{operation}.json")
        if record is None:
            raise ConfigError("not_found", "Local synchronization operation not found")
        expected = {
            "host": getattr(self.remote, "host", None),
            "root": getattr(self.remote, "root", None),
        }
        if record["destination"] != expected:
            raise ConfigError("endpoint_changed", "Resume must use the original SSH destination")
        try:
            self.wait_remote(operation, timeout)
        except ConfigError as exc:
            if (
                exc.code == "sync_recovered"
                and self.local.state.operation(operation)["phase"] == "prepared"
            ):
                self.local.recover(operation)
            raise
        self.local.commit(operation)
        self.remote.call("confirm", {"operation": operation, "peer": record["local"]})
        self.local.confirm(operation, record["remote"])
        record["phase"] = "confirmed"
        self.local.state.write(f"clients/{operation}.json", record)
        return {"operation": operation, "phase": "confirmed", "hash": digest(record["bundle"])}

    def resume(self, operation, timeout=240):
        record = self.local.state.read(f"clients/{operation}.json")
        if record is None:
            raise ConfigError("not_found", "Synchronization operation not found")
        destination = {
            "host": getattr(self.remote, "host", None),
            "root": getattr(self.remote, "root", None),
        }
        if record["destination"] != destination:
            raise ConfigError("endpoint_changed", "Resume must use the original destination")
        if record["phase"] == "rejected":
            raise ConfigError("operation_conflict", "Rejected operation requires a new plan")
        if record["phase"] == "preparing":
            self.local.prepare(operation, record["bundle"], record["local_expected"])
            self.remote.call(
                "prepare",
                {
                    "operation": operation,
                    "bundle": record["bundle"],
                    "expected": record["remote_expected"],
                    "overwrite": record["overwrite"],
                    "deployment": record["deployment"],
                },
            )
            record["phase"] = "prepared"
            self.local.state.write(f"clients/{operation}.json", record)
        if record["deployment"]:
            state = self.remote.call("inspect", {"operation": operation})
            if not state.get("deployment") and state["phase"] not in (
                "committed",
                "confirmed",
                "recovered",
            ):
                raise ConfigError(
                    "deployment_not_started",
                    "Recover preparation before planning another deployment",
                    details={"operation": operation},
                )
        self.remote.start(operation)
        return self.finish(operation, timeout)

    def recover(self, operation, *, services_stopped=False, timeout=240):
        record = self.local.state.read(f"clients/{operation}.json")
        if record is None:
            raise ConfigError("not_found", "Synchronization operation not found")
        destination = {
            "host": getattr(self.remote, "host", None),
            "root": getattr(self.remote, "root", None),
        }
        if record["destination"] != destination:
            raise ConfigError("endpoint_changed", "Recovery must use the original destination")
        try:
            state = self.remote.call("inspect", {"operation": operation})
        except ConfigError as exc:
            if exc.code != "not_found" or record["phase"] != "preparing":
                raise
            state = self.remote.call(
                "cancel-preparation",
                {
                    "operation": operation,
                    "expected_endpoint": record["remote"],
                },
            )
        if state["phase"] == "confirmed" or (
            state.get("deployment") and self.remote.deployment_status(state["deployment"]) == "0"
        ):
            return self.finish(operation, timeout)
        if state["phase"] != "recovered":
            self.remote.start(operation, recover=True)
        deadline = time.monotonic() + timeout
        while True:
            state = self.remote.call("inspect", {"operation": operation})
            if state["phase"] == "confirmed":
                return self.finish(operation, timeout)
            if state["phase"] == "recovered":
                self.remote.call("release-terminal", {"operation": operation})
                break
            if time.monotonic() >= deadline:
                raise ConfigError(
                    "recovery_unconfirmed",
                    "Remote recovery is not verified",
                    details={"operation": operation},
                )
            time.sleep(2)
        local = self.local.state.read(f"operations/{operation}.json")
        if local and local["phase"] not in ("prepared", "recovered") and not services_stopped:
            raise ConfigError(
                "services_running",
                "Stop local services before restoring local changes",
                details={"operation": operation, "remote": "recovered"},
            )
        if local:
            self.local.recover(operation, services_stopped=services_stopped)
        record["phase"] = "recovered"
        self.local.state.write(f"clients/{operation}.json", record)
        return {"operation": operation, "phase": "recovered"}

    def run(self, *, timeout=240, **kwargs):
        operation = self.prepare(**kwargs)
        self.remote.start(operation)
        return self.finish(operation, timeout)
