"""Recoverable receiver-side installation of logical configuration snapshots."""

from contextlib import contextmanager, ExitStack

from quickquip.common.config_writes import configuration_write, maintenance_owner
from quickquip.config_sync import capture
from quickquip.config_sync.layout import Layout
from quickquip.config_sync.state import State, identifier
from quickquip.configuration.activity import stopped_service
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.images import write_settings
from quickquip.configuration.merge import reconcile, same
from quickquip.configuration.snapshot import validate
from quickquip.llm.config_service import ConfigService


class Installation:
    def __init__(self, root, *, release=None):
        self.layout = Layout(root, release=release)
        self.root = self.layout.root
        self.state = State(self.root / "data")

    def _name(self, operation):
        return f"qqsync/operations/{identifier(operation)}.json"

    def read(self, operation):
        record = self.state.read(self._name(operation))
        if record is None:
            raise ConfigError("operation_missing", "No prepared configuration operation")
        return record

    def save(self, record):
        self.state.write(self._name(record["id"]), record)

    def _marker(self, record, *, allow_start):
        self.state.write(
            "maintenance.json",
            {
                "protocol": 2,
                "token": record["id"],
                "operation": record["id"],
                "allow_start": allow_start,
            },
        )

    def service(self):
        return ConfigService(
            self.layout.database, config_dir=self.layout.config_dir, data_dir=self.root / "data"
        )

    @contextmanager
    def owned(self, operation):
        with maintenance_owner(identifier(operation)), configuration_write(self.root / "data"):
            record = self.read(operation)
            if not record.get("deployment") and record["application"] != str(
                self.layout.application
            ):
                raise ConfigError(
                    "deployment_changed", "The application release changed; retry recovery"
                )
            yield record

    def prepare(self, operation, expected, target, *, publish, prefer=None):
        identifier(operation)
        with maintenance_owner(operation), configuration_write(self.root / "data"):
            existing = self.state.read(self._name(operation))
            if existing is not None:
                if existing["target"] != target or existing["before"] != expected:
                    raise ConfigError(
                        "operation_conflict", "Prepared operation has different input"
                    )
                return self.summary(existing)
            current = capture.read(self.layout, "published" if publish else "draft")
            if current != expected:
                raise ConfigError("revision_conflict", "Configuration changed after preview; retry")
            if current["pending"]:
                raise ConfigError("operation_conflict", "Finish the pending configuration apply")
            target = validate(target)
            draft = target["document"]
            if publish:
                conflicts = []
                draft = reconcile(
                    current["published"],
                    target["document"],
                    current["draft"],
                    path="document",
                    prefer="workspace" if prefer == "source" else "source",
                    conflicts=conflicts,
                )
                if conflicts and prefer is None:
                    raise ConfigError(
                        "draft_conflict",
                        "Deployment conflicts with unpublished edits",
                        details={"conflicts": conflicts},
                    )
                validate({**target, "document": draft})
            record = {
                "id": operation,
                "phase": "prepared",
                "before": current,
                "target": target,
                "draft": draft,
                "publish": publish,
                "application": str(self.layout.application),
            }
            self.save(record)
            self._marker(record, allow_start=True)
            return self.summary(record)

    @staticmethod
    def summary(record):
        return {key: record[key] for key in ("id", "phase", "publish", "revision") if key in record}

    def install(self, operation, *, hot=False, environment=None):
        with self.owned(operation) as record:
            if record["phase"] in ("installed", "confirmed"):
                return self.summary(record)
            if record["phase"] not in ("prepared", "staged", "writing"):
                raise ConfigError("operation_conflict", "Operation is being recovered")
            before, target = record["before"], record["target"]
            if hot and any(
                not same(before["snapshot"][key], target[key])
                for key in ("files", "scopes", "text_modes")
            ):
                raise ConfigError("operation_conflict", "This configuration requires a restart")
            with ExitStack() as leases:
                stopped = None
                if not hot:
                    stopped = leases.enter_context(stopped_service(self.root, "bot"))
                    leases.enter_context(stopped_service(self.root, "web"))
                record["phase"] = "writing"
                self.save(record)
                self._marker(record, allow_start=hot)
                self.layout.install(before["snapshot"]["files"], target["files"])
                service = self.service()
                current = service.read()
                if current["document"] not in (before["draft"], record["draft"]):
                    raise ConfigError(
                        "revision_conflict", "An independent draft edit prevents retry"
                    )
                if "revision" not in record:
                    prepared = service.prepare_deployment(
                        target["document"], current["revision"], draft=record["draft"]
                    )
                    record["revision"] = prepared["revision"]
                    self.save(record)
                with service.store.connect(write=True) as connection:
                    write_settings(connection, target)
                if record["publish"]:
                    if hot:
                        task = service.apply_deployment(record["revision"], "qqsync-" + operation)
                        record["task"] = task["id"]
                    else:
                        service.publish_offline(
                            record["revision"],
                            "qqsync-" + operation,
                            stopped,
                            environment=environment,
                        )
                record["phase"] = "installed"
                self.save(record)
                self._marker(record, allow_start=True)
            return self.summary(record)

    def verify(self, operation, *, running=False, timeout=150):
        with self.owned(operation) as record:
            if record["phase"] not in ("installed", "confirmed"):
                raise ConfigError("operation_conflict", "Configuration has not been installed")
            if record["publish"] and running:
                from quickquip.llm.config_wait import wait_loaded

                wait_loaded(
                    self.service(),
                    record["revision"],
                    operation=record.get("task"),
                    timeout=timeout,
                )
            actual = capture.read(self.layout, "published" if record["publish"] else "draft")
            if not same(actual["snapshot"], record["target"]) or actual["draft"] != record["draft"]:
                raise ConfigError("revision_conflict", "Installed configuration changed")
            return self.summary(record)

    def confirm(self, operation):
        with self.owned(operation) as record:
            if record["phase"] not in ("installed", "confirmed"):
                raise ConfigError("operation_conflict", "Configuration has not been verified")
            record["phase"] = "confirmed"
            self.save(record)
            self.state.clear_maintenance(operation)
            return self.summary(record)

    def restore(self, operation, *, environment=None):
        with self.owned(operation) as record:
            if record["phase"] in ("restored", "recovered"):
                return self.summary(record)
            if record["phase"] == "confirmed":
                raise ConfigError(
                    "operation_conflict", "Confirmed configuration cannot be rolled back"
                )
            if record["phase"] in ("prepared", "staged"):
                record["phase"] = "restored"
                self.save(record)
                return self.summary(record)
            with stopped_service(self.root, "bot") as stopped, stopped_service(self.root, "web"):
                record["phase"] = "recovering"
                self.save(record)
                self._marker(record, allow_start=False)
                before = record["before"]
                self.layout.install(record["target"]["files"], before["snapshot"]["files"])
                service = self.service()
                current = service.read()
                if current["document"] not in (before["draft"], record["draft"]):
                    raise ConfigError("revision_conflict", "Independent draft prevents recovery")
                with service.execution.connect(write=True) as connection:
                    # Fence only this deployment's interrupted hot application.
                    connection.execute(
                        "UPDATE config_operations SET status='cancelled',stage='cancelled' "
                        "WHERE request_id=? AND status IN ('queued','running')",
                        ("qqsync-" + operation,),
                    )
                restored = service.prepare_deployment(
                    before["published"],
                    current["revision"],
                    draft=before["draft"],
                    note="qqsync recovery",
                )
                with service.store.connect(write=True) as connection:
                    write_settings(connection, before["snapshot"])
                if record["publish"]:
                    service.publish_offline(
                        restored["revision"],
                        "qqsync-recovery-" + operation,
                        stopped,
                        environment=environment,
                    )
                record["phase"] = "restored"
                record["recovery_revision"] = restored["revision"]
                self.save(record)
                self._marker(record, allow_start=True)
            return self.summary(record)

    def recovered(self, operation, *, running=False):
        with self.owned(operation) as record:
            if record["phase"] not in ("restored", "recovered"):
                raise ConfigError("operation_conflict", "Configuration has not been restored")
            if running and record["publish"] and "recovery_revision" in record:
                from quickquip.llm.config_wait import wait_loaded

                wait_loaded(self.service(), record["recovery_revision"])
            actual = capture.read(self.layout, "published" if record["publish"] else "draft")
            if actual["snapshot"] != record["before"]["snapshot"]:
                raise ConfigError(
                    "revision_conflict", "Configuration recovery differs from original"
                )
            record["phase"] = "recovered"
            self.save(record)
            self.state.clear_maintenance(operation)
            return self.summary(record)
