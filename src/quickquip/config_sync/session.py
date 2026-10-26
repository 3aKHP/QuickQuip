"""Directional configuration sessions with automatic continuation from a frozen route."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import shutil
import uuid

from filelock import FileLock

from quickquip.config_sync import reconciliation, compatibility
from quickquip.config_sync.peers import Local, Remote
from quickquip.config_sync.state import State
from quickquip.configuration import snapshot
from quickquip.configuration.deployment import Deployment, read as deployment_mode
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.files import read_json
from quickquip.configuration.merge import same


class Session:
    def __init__(self, root, *, remote_factory=Remote, host=None, remote_dir=None):
        self.root = Path(root).resolve()
        self.state = State(self.root / "data")
        self.remote_factory = remote_factory
        self.host, self.remote_dir = host, remote_dir

    def mode(self, *, required=False):
        mode = deployment_mode(self.root, required=required)
        return replace(
            mode, host=self.host or mode.host, remote_dir=self.remote_dir or mode.remote_dir
        )

    def pending(self):
        record = self.state.read("qqsync/client.json")
        return record if record and record["phase"] not in ("confirmed", "recovered") else None

    def _peers(self, mode):
        if mode.location == "local":
            return Local(self.root, mode.runtime), None
        return Local(self.root), self.remote_factory(mode.host, mode.remote_dir, mode.runtime)

    def _base(self, mode):
        route = {"host": mode.host, "root": mode.remote_dir, "runtime": mode.runtime}
        for peer in self.state.read("qqsync/peers.json", []):
            if peer["route"] == route:
                return peer["base"]
        return None

    def _acknowledge(self, record):
        if record["route"]["location"] == "local" or record["source_kind"] == "draft":
            return
        mode = Deployment(**record["route"])
        route = {"host": mode.host, "root": mode.remote_dir, "runtime": mode.runtime}
        peers = [
            peer for peer in self.state.read("qqsync/peers.json", []) if peer["route"] != route
        ]
        peers.append(
            {
                "route": route,
                "base": reconciliation.acknowledge(
                    record["base"],
                    record["source"],
                    record["target"],
                ),
            }
        )
        self.state.write("qqsync/peers.json", peers)

    def preview(
        self,
        direction="push",
        *,
        source="published",
        prefer=None,
        overwrite=False,
        show_secrets=False,
        required=False,
    ):
        legacy = compatibility.pending(self.state)
        if legacy:
            return {
                "phase": "pending",
                "message": "Repeat qqsync push or pull to finish previous sync",
            }
        pending = self.pending()
        if pending:
            return {
                "phase": "pending",
                "direction": pending["direction"],
                "message": "Repeat qqsync " + pending["direction"] + " to continue",
            }
        mode = self.mode(required=required)
        if mode.location is None or mode.runtime is None:
            return {
                "phase": "unconfigured",
                "deployment": asdict(mode),
                "message": "Set both deployment modes in the real root .env",
            }
        if mode.location == "local" and direction == "pull":
            return {
                "phase": "local_pull",
                "message": "Use qqconf unpack to read local configuration",
            }
        if mode.location == "local":
            candidate = self.root / ".config-staging"
            if not candidate.exists():
                return {"phase": "unchanged", "message": "No configuration staged; use qqconf pack"}
        local, remote = self._peers(mode)
        if mode.location == "local":
            manifest = read_json(candidate / "candidate.json")
            if manifest.get("source_root") != str(self.root):
                raise ConfigError(
                    "candidate_conflict", "Staged configuration belongs to another root"
                )
            origin, base = snapshot.read(candidate), manifest["base"]
            before = local.call("capture", {"source": "published"})
            receiving = {**before["snapshot"], "document": before["draft"]}
        else:
            local_before = local.call("capture", {"source": "draft"})
            remote_before = remote.call(
                "capture", {"source": source if direction == "pull" else "published"}
            )
            remote_mode = remote_before.get("deployment", {})
            if required and (
                remote_mode.get("runtime") != mode.runtime or remote_mode.get("location") != "cloud"
            ):
                raise ConfigError(
                    "deployment_mode_mismatch", "Check deployment modes on the server"
                )
            source_state, before = (
                (local_before, remote_before)
                if direction == "push"
                else (remote_before, local_before)
            )
            origin, receiving = source_state["snapshot"], before["snapshot"]
            base = self._base(mode)
            if base is None:
                base = compatibility.baseline(self.state, remote_before.get("identity"), receiving)
        result = reconciliation.plan(
            base, origin, receiving, prefer=prefer, overwrite=overwrite, show_secrets=show_secrets
        )
        if not result["conflicts"] or prefer:
            result["target"] = snapshot.validate(result["target"])
        result.update(phase="preview", direction=direction, deployment=asdict(mode))
        result["_inputs"] = {
            "route": asdict(mode),
            "before": before,
            "base": base,
            "source": origin,
            "target": result["target"],
            "source_kind": source if direction == "pull" else "published",
            "remote_before": remote_before if mode.location == "cloud" else None,
        }
        return result

    def run(self, direction, *, source="published", prefer=None, overwrite=False):
        legacy = compatibility.pending(self.state)
        if legacy:
            return compatibility.resume(self.root, legacy)
        if self.pending() is None and deployment_mode(self.root).location == "local":
            if direction == "pull" or not (self.root / ".config-staging").exists():
                return self.preview(direction, required=direction == "push")
        self.state.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(self.state.directory / "qqsync-client.lock"), timeout=1):
            record = self.pending()
            if record is not None:
                if record["direction"] != direction:
                    raise ConfigError("operation_pending", "Repeat qqsync " + record["direction"])
                return self._continue(record)
            plan = self.preview(
                direction, source=source, prefer=prefer, overwrite=overwrite, required=True
            )
            if plan["phase"] != "preview":
                return plan
            if plan["conflicts"] and prefer is None:
                raise ConfigError(
                    "configuration_conflict",
                    "Resolve conflicting fields and retry",
                    details={"conflicts": plan["conflicts"]},
                )
            record = {
                **plan["_inputs"],
                "id": uuid.uuid4().hex,
                "phase": "preparing",
                "direction": direction,
                "prefer": prefer,
            }
            if same(record["target"], record["before"]["snapshot"]):
                self._acknowledge(record)
                self._consume(record)
                return {"phase": "unchanged", "direction": direction}
            mode = Deployment(**record["route"])
            local, remote = self._peers(mode)
            receiver = remote if mode.location == "cloud" and direction == "push" else local
            record["publish"] = mode.location == "local" or direction == "push"
            record["original"] = receiver.controller.inspect()
            record["hot"] = (
                record["publish"]
                and record["original"]["bot"]["running"]
                and all(
                    same(record["before"]["snapshot"][key], record["target"][key])
                    for key in ("files", "scopes", "text_modes")
                )
            )
            self.state.write("qqsync/client.json", record)
            return self._continue(record)

    def _save(self, record, phase):
        record["phase"] = phase
        self.state.write("qqsync/client.json", record)

    def _continue(self, record):
        if record.get("deployment"):
            from quickquip.config_sync.deployment import finish

            return finish(self, record)
        mode = Deployment(**record["route"])
        local, remote = self._peers(mode)
        receiver = remote if mode.location == "cloud" and record["direction"] == "push" else local
        operation = {"operation": record["id"]}
        if record["phase"] == "recovering":
            return self._recover(record, receiver)
        try:
            if record["phase"] == "preparing":
                receiver.call(
                    "prepare",
                    {
                        **operation,
                        "expected": record["before"],
                        "target": record["target"],
                        "publish": record["publish"],
                        "prefer": record["prefer"],
                    },
                )
                self._save(record, "prepared")
            if record["phase"] in ("prepared", "installing"):
                if not record["hot"]:
                    receiver.controller.pause(record["original"])
                self._save(record, "installing")
                environment = (
                    receiver.controller.environment(record["target"])
                    if receiver.runtime == "docker"
                    else None
                )
                receiver.call(
                    "install", {**operation, "hot": record["hot"], "environment": environment}
                )
                self._save(record, "installed")
            if record["phase"] == "installed":
                if not record["hot"]:
                    receiver.controller.restore(record["original"])
                    receiver.controller.verify(record["original"])
                receiver.call(
                    "verify", {**operation, "running": record["original"]["bot"]["running"]}
                )
                self._save(record, "verified")
            if record["phase"] == "verified":
                receiver.call("confirm", operation)
                self._acknowledge(record)
                self._consume(record)
                self._save(record, "confirmed")
        except ConfigError as error:
            # Lost transport acknowledgement is uncertain; the next command resumes its receipt.
            if error.code in ("transport_error", "protocol_error"):
                raise
            if record["phase"] == "preparing":
                self._save(record, "recovered")
                raise
            self._save(record, "recovering")
            self._recover(record, receiver)
            raise
        return {"phase": "confirmed", "direction": record["direction"]}

    def _recover(self, record, receiver):
        operation = {"operation": record["id"]}
        if receiver.call("inspect", operation)["phase"] != "prepared":
            receiver.controller.pause(record["original"])
        environment = (
            receiver.controller.environment(record["before"]["snapshot"])
            if receiver.runtime == "docker"
            else None
        )
        receiver.call("restore", {**operation, "environment": environment})
        receiver.controller.restore(record["original"])
        receiver.controller.verify(record["original"])
        receiver.call("recovered", {**operation, "running": record["original"]["bot"]["running"]})
        self._save(record, "recovered")
        return {
            "phase": "recovered",
            "message": "Previous configuration and service states restored",
        }

    def _consume(self, record):
        if record["route"]["location"] != "local":
            return
        candidate = self.root / ".config-staging"
        if candidate.exists() and same(snapshot.read(candidate), record["source"]):
            shutil.rmtree(candidate)


def public_preview(result):
    return {
        key: deepcopy(value) for key, value in result.items() if key not in ("target", "_inputs")
    }
