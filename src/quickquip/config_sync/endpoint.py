"""One endpoint's durable configuration transaction; transport owns service restarts."""

import json
from contextlib import contextmanager
from pathlib import Path
import uuid

from quickquip.common.config_writes import (
    write_lock,
    configuration_write,
    maintenance_owner,
    check_writable,
)
from quickquip.config_sync.bundle import (
    FORMAT,
    digest,
    projection_consistent,
    read_assets,
    validate_bundle,
)
from quickquip.config_sync.state import State, identifier
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_service import ConfigService


class Endpoint:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data = self.root / "data"
        self.state = State(self.data)
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = ConfigService(
                self.data / "llm_config.db", config_dir=self.root / "config"
            )
        return self._service

    @service.setter
    def service(self, value):
        self._service = value

    def _raw_snapshot(self):
        from quickquip.llm.config_store import ConfigStore

        check_writable(self.data)
        store = ConfigStore(self.data / "llm_config.db")
        store.verify()
        assets = read_assets(self.root)
        with store.connect() as conn:
            conn.execute("BEGIN")
            projection_consistent(conn)
            meta = dict(conn.execute("SELECT * FROM config_meta").fetchone())
            published = json.loads(
                conn.execute(
                    "SELECT document FROM config_snapshots WHERE revision=?",
                    (meta["published_revision"],),
                ).fetchone()[0]
            )
            draft = json.loads(meta["document"])
            pending = conn.execute(
                "SELECT COUNT(*) FROM config_operations WHERE status IN ('queued','running')"
            ).fetchone()[0]
        if assets != read_assets(self.root):
            raise ConfigError("revision_conflict", "Configuration assets changed while reading")
        return meta, draft, published, pending, assets

    def version(self):
        meta, draft, published, _, assets = self._raw_snapshot()
        return {
            "draft_revision": meta["draft_revision"],
            "published_revision": meta["published_revision"],
            "draft_hash": digest(draft),
            "published_hash": digest(published),
            "assets_hash": digest(assets),
        }

    def capture(self, source="draft"):
        meta, draft, published, pending, assets = self._raw_snapshot()
        raw_draft_hash, raw_published_hash = digest(draft), digest(published)
        from quickquip.llm.config_document import validate_document

        draft = validate_document(draft, config_dir=self.root / "config")
        published = validate_document(published, config_dir=self.root / "config")
        document = draft if source == "draft" else published
        bundle = validate_bundle({"format": FORMAT, "document": document, "assets": assets})
        return {
            "identity": self.state.identity(),
            "bundle": bundle,
            "pending": pending,
            "dirty_draft": digest(draft) != digest(published),
            "draft": draft,
            "published": published,
            "version": {
                "draft_revision": meta["draft_revision"],
                "published_revision": meta["published_revision"],
                "draft_hash": raw_draft_hash,
                "published_hash": raw_published_hash,
                "assets_hash": digest(assets),
            },
        }

    def initialize_identity(self):
        with configuration_write(self.data):
            return self.state.identity(create=True)

    @contextmanager
    def owned_operation(self, operation):
        with write_lock(self.state.directory.resolve()):
            record = self.state.operation(operation)
            with maintenance_owner(record["token"]), configuration_write(self.data):
                yield record

    def prepare(
        self, operation, bundle, expected, *, publish=False, overwrite=False, deployment=False
    ):
        identifier(operation)
        bundle = validate_bundle(bundle, environment=publish and not deployment)
        self.state.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with write_lock(self.state.directory.resolve()):
            existing = self.state.read(f"operations/{operation}.json")
            token = existing["token"] if existing else uuid.uuid4().hex
            with maintenance_owner(token), configuration_write(self.data):
                if existing:
                    if existing.get("cancelled"):
                        raise ConfigError("operation_conflict", "Preparation was cancelled")
                    if (
                        digest(existing["target"]) != digest(bundle)
                        or existing["publish"] != publish
                        or existing.get("deployment_pending", False) != deployment
                        or existing["before"]["version"] != expected
                    ):
                        raise ConfigError("operation_conflict", "Operation has a different target")
                    return self.summary(existing)
                current = self.capture("published" if publish else "draft")
                if current["version"] != expected:
                    raise ConfigError(
                        "revision_conflict", "Endpoint changed after the plan was read"
                    )
                if current["pending"]:
                    raise ConfigError(
                        "operation_conflict", "Finish pending configuration tasks first"
                    )
                write_document = digest(bundle["document"]) != digest(
                    current["published"] if publish else current["draft"]
                )
                if publish and write_document and current["dirty_draft"] and not overwrite:
                    raise ConfigError(
                        "draft_conflict", "A separate unpublished draft would be replaced"
                    )
                files_changed = current["bundle"]["assets"] != bundle["assets"]
                if publish and files_changed and not write_document and current["dirty_draft"]:
                    from quickquip.config_sync.validation import protect_draft_assets

                    protect_draft_assets(current["draft"], current["bundle"], bundle)
                if publish:
                    # A restarted bot boots the old publication before consuming our apply task.
                    validate_bundle({**bundle, "document": current["published"]})
                record = {
                    "id": operation,
                    "token": token,
                    "phase": "prepared",
                    "target": bundle,
                    "before": current,
                    "publish": publish,
                    "restart": files_changed and publish,
                    "expected": expected,
                    "write_document": write_document,
                    "deployment_pending": deployment,
                }
                directory = self.state.directory / "backups" / operation
                from quickquip.llm.config_durability import ensure_directory

                ensure_directory(directory)
                directory.chmod(0o700)
                backup = directory / "configuration.db"
                self.service.backup(backup)
                backup.chmod(0o600)
                self.state.save_operation(record)
                self.state.write(
                    "maintenance.json", {"operation": operation, "token": record["token"]}
                )
                return self.summary(record)

    def cancel_preparation(self, operation, expected_endpoint):
        from quickquip.common.config_writes import write_lock

        identifier(operation)
        if (self.state.identity() or {}).get("id") != expected_endpoint:
            raise ConfigError("endpoint_changed", "Cancellation targets a different endpoint")
        # Serialize with a possibly still-running original prepare before declaring it absent.
        with write_lock(self.state.directory.resolve()):
            record = self.state.read(f"operations/{operation}.json")
            token = record["token"] if record else uuid.uuid4().hex
            with maintenance_owner(token), configuration_write(self.data):
                if record:
                    return self.summary(record)
                record = {
                    "id": operation,
                    "token": token,
                    "phase": "recovered",
                    "restart": False,
                    "publish": True,
                    "cancelled": True,
                }
                self.state.save_operation(record)
                return self.summary(record)

    @staticmethod
    def summary(record):
        result = {key: record[key] for key in ("id", "phase", "restart", "publish")}
        if record.get("failure"):
            result["failure"] = record["failure"]
        return result

    def _assets(self, target):
        from quickquip.config_sync.bundle import install_assets

        install_assets(self.root, target)

    def _fence_stopped_bot(self, record):
        """Called only after the deployment worker has stopped Bot and Web."""
        from quickquip.llm.config_store import ConfigStore

        with ConfigStore(self.data / "llm_config.db").connect(write=True) as conn:
            bot = conn.execute("SELECT boot_id FROM bot_runtime").fetchone()
            record["boot_before_restart"] = bot[0] if bot else None
            self.state.save_operation(record)
            conn.execute("DELETE FROM bot_runtime")

    def fence_stopped_bot(self, operation):
        with self.owned_operation(operation) as record:
            if record["phase"] not in ("prepared", "staged") or not record["publish"]:
                raise ConfigError(
                    "operation_conflict", "Operation cannot restart configuration consumers"
                )
            self._fence_stopped_bot(record)
            return self.summary(record)

    def commit(self, operation):
        with self.owned_operation(operation) as record:
            if record["phase"] in ("committed", "confirmed", "queued"):
                return self.summary(record)
            if record["phase"] != "prepared":
                raise ConfigError("recovery_required", "Interrupted writes require recovery")
            if self.version() != record["expected"]:
                raise ConfigError("revision_conflict", "Endpoint changed after preparation")
            self.state.write("maintenance.json", {"operation": operation, "token": record["token"]})
            validate_bundle(record["target"], environment=record["publish"])
            record["phase"] = "writing"
            self.state.save_operation(record)
            if record["restart"] and "boot_before_restart" not in record:
                self._fence_stopped_bot(record)
            self._assets(record["target"]["assets"])
            # Reconstruct the service in this new CLI process after asset installation.
            from quickquip.llm.client_fingerprints.catalog import _load_catalog

            _load_catalog.cache_clear()
            self.service = ConfigService(self.service.path, config_dir=self.root / "config")
            if record["write_document"]:
                saved = self.service.replace(
                    record["target"]["document"], record["expected"]["draft_revision"]
                )
                record["revision"] = saved["revision"]
            else:
                record["revision"] = record["expected"][
                    "published_revision" if record["publish"] else "draft_revision"
                ]
            if record["publish"]:
                task = (
                    self.service.apply(record["revision"], "sync-" + operation)
                    if record["write_document"]
                    else None
                )
                record["task"] = task["id"] if task else None
                record["phase"] = "queued"
            else:
                record["phase"] = "committed"
            self.state.save_operation(record)
            return self.summary(record)

    def wait(self, operation, timeout=150):
        record = self.state.operation(operation)
        if record["phase"] in ("committed", "confirmed"):
            return self.summary(record)
        if record["phase"] != "queued":
            raise ConfigError("recovery_required", "Operation has not queued an application")
        from quickquip.llm.config_wait import wait_loaded

        try:
            wait_loaded(
                self.service,
                record["revision"],
                operation=record["task"],
                timeout=timeout,
                previous_boot=record.get("boot_before_restart"),
            )
        except ConfigError as error:
            with self.owned_operation(operation) as latest:
                if latest["phase"] == "queued":
                    latest["failure"] = error.as_dict()
                    self.state.save_operation(latest)
            raise
        with self.owned_operation(operation) as latest:
            if latest["phase"] in ("committed", "confirmed"):
                return self.summary(latest)
            if latest["phase"] != "queued" or latest.get("task") != record.get("task"):
                raise ConfigError("operation_conflict", "Application was superseded by recovery")
            latest["phase"] = "committed"
            latest.pop("failure", None)
            self.state.save_operation(latest)
            return self.summary(latest)

    def recover(self, operation, *, services_stopped=False, defer_release=False):
        with self.owned_operation(operation) as record:
            if record["phase"] in ("recovered", "restored"):
                if record["phase"] == "recovered":
                    self.state.clear_maintenance(record["token"])
                return self.summary(record)
            if record["phase"] == "confirmed":
                raise ConfigError("operation_conflict", "Confirmed operation cannot be recovered")
            unchanged = False
            if record["phase"] in ("prepared", "staging", "staged"):
                unchanged = self.version() == record["before"]["version"]
            if record["phase"] == "prepared":
                if self.version() != record["expected"]:
                    raise ConfigError(
                        "revision_conflict", "External edits detected during maintenance"
                    )
            elif not unchanged:
                if not services_stopped:
                    raise ConfigError(
                        "services_running", "Stop application services before recovery"
                    )
                # Each observed unit must be either its original value or our planned replacement.
                old = record["before"]["bundle"]["assets"]
                target = record["target"]["assets"]
                actual = read_assets(self.root)
                for name in old.keys() | target.keys() | actual.keys():
                    if actual.get(name) not in (old.get(name), target.get(name)):
                        raise ConfigError(
                            "revision_conflict", "External asset edit prevents recovery", name
                        )
                from quickquip.llm.config_store import ConfigStore

                with ConfigStore(self.data / "llm_config.db").connect() as conn:
                    conn.execute("BEGIN")
                    projection_consistent(conn)
                    meta = conn.execute("SELECT * FROM config_meta").fetchone()
                    draft = json.loads(meta["document"])
                    published = json.loads(
                        conn.execute(
                            "SELECT document FROM config_snapshots WHERE revision=?",
                            (meta["published_revision"],),
                        ).fetchone()[0]
                    )
                if digest(published) not in (
                    record["before"]["version"]["published_hash"],
                    digest(record["target"]["document"]),
                ):
                    raise ConfigError("revision_conflict", "External publication prevents recovery")
                if digest(draft) not in (
                    record["before"]["version"]["draft_hash"],
                    digest(record["target"]["document"]),
                ):
                    raise ConfigError("revision_conflict", "External draft edit prevents recovery")
                self._assets(old)
                from quickquip.llm.client_fingerprints.catalog import _load_catalog

                _load_catalog.cache_clear()
                self._service = None
                backup = self.state.directory / "backups" / operation / "configuration.db"
                self.service.restore_database(backup, stopped=True)
            if services_stopped and defer_release:
                self._fence_stopped_bot(record)
            record["phase"] = "restored" if defer_release else "recovered"
            self.state.save_operation(record)
            if not defer_release:
                self.state.clear_maintenance(record["token"])
            return self.summary(record)

    def verify_recovery(self, operation):
        from quickquip.llm.config_wait import wait_loaded

        with self.owned_operation(operation) as record:
            if record["phase"] == "recovered":
                self.state.clear_maintenance(record["token"])
                return self.summary(record)
            if record["phase"] != "restored":
                raise ConfigError("operation_conflict", "Recovery has not restored configuration")
            current = self.capture("published")
            if digest(current["bundle"]) != digest(record["before"]["bundle"]):
                raise ConfigError("revision_conflict", "Configuration changed during recovery")
            wait_loaded(self.service, current["version"]["published_revision"], timeout=0)
            record["phase"] = "recovered"
            self.state.save_operation(record)
            self.state.clear_maintenance(record["token"])
            return self.summary(record)

    def release_terminal(self, operation):
        with self.owned_operation(operation) as record:
            if record["phase"] not in ("confirmed", "recovered"):
                raise ConfigError(
                    "operation_conflict", "Operation has not reached a terminal state"
                )
            self.state.clear_maintenance(record["token"])
            return self.summary(record)

    def confirm(self, operation, peer):
        with self.owned_operation(operation) as record:
            identifier(peer)
            if record["phase"] == "confirmed":
                if record.get("peer") != peer:
                    raise ConfigError("operation_conflict", "Confirmation belongs to another peer")
                self.state.clear_maintenance(record["token"])
                return self.summary(record)
            if record["phase"] != "committed":
                raise ConfigError(
                    "operation_conflict", "Only committed configurations can be confirmed"
                )
            source = "published" if record["publish"] else "draft"
            if record["phase"] != "confirmed" and record["publish"]:
                actual = self.capture(source)
                if digest(actual["bundle"]) != digest(record["target"]):
                    raise ConfigError("revision_conflict", "Endpoint changed before confirmation")
            self.state.acknowledge(peer, record["target"], operation)
            record["peer"] = peer
            record["phase"] = "confirmed"
            self.state.save_operation(record)
            self.state.clear_maintenance(record["token"])
            return self.summary(record)
