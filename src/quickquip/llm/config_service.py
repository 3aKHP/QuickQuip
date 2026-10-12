"""Application service shared by configuration CLI, Web Admin and bot control."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path

from filelock import FileLock

from quickquip.common.paths import CONFIG_LLM_TOML, DATA_DIR
from quickquip.llm.config_document import ConfigError, empty_document, validate_document
from quickquip.llm.config_store import ConfigStore, SCHEMA_VERSION, dumps, project_document
from quickquip.llm.config_durability import ensure_directory
from quickquip.llm.config_tasks import ConfigTaskQueue, operation

from quickquip.llm.config_validation import document_diff as document_diff, validation_report

DEFAULT_CONFIG_DB = DATA_DIR / "llm_config.db"


class ConfigService:
    def __init__(self, path=DEFAULT_CONFIG_DB):
        self.path = Path(path)
        self._references_lock = FileLock(str(self.path) + ".references.lock", timeout=10)
        self.store = ConfigStore(self.path)
        self.tasks = ConfigTaskQueue(self.store)

    @property
    def shared_lock(self):
        return self._references_lock

    def initialize(self, legacy_path=None):
        ensure_directory(self.path.parent)
        with FileLock(str(self.path) + ".init.lock", timeout=60):
            if self.path.exists():
                # An existing database is authoritative, including failure/new-schema cases.
                self.store.verify()
                return self.read()
            report = None
            legacy = Path(legacy_path) if legacy_path else None
            if legacy and legacy.exists():
                from quickquip.llm.config_migration import migrate_legacy

                document, report = migrate_legacy(legacy)
            else:
                document = empty_document()
            document = validate_document(document)
            self.store.create(document, report, str(legacy or ""))
        return self.read()

    def read(self, source="draft"):
        with self.store.connect() as conn:
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            if source == "draft":
                return {
                    "revision": meta["draft_revision"],
                    "document": json.loads(meta["document"]),
                }
            try:
                revision = meta["published_revision"] if source == "published" else int(source)
            except (TypeError, ValueError):
                raise ConfigError(
                    "invalid_field", "Invalid configuration source", field_path="source"
                ) from None
            row = conn.execute(
                "SELECT document FROM config_snapshots WHERE revision=?", (revision,)
            ).fetchone()
            if row is None:
                raise ConfigError("not_found", "Snapshot not found", details={"revision": revision})
            return {"revision": revision, "document": json.loads(row[0])}

    @staticmethod
    def _check_revision(conn, expected_revision):
        meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
        if expected_revision != meta["draft_revision"]:
            raise ConfigError(
                "revision_conflict",
                "Draft changed since it was read",
                details={"expected": expected_revision, "actual": meta["draft_revision"]},
            )
        return meta

    def migrate_legacy(self, path, expected_revision):
        from quickquip.llm.config_migration import migrate_legacy

        with self.shared_lock:
            if self.read()["revision"] != expected_revision:
                raise ConfigError(
                    "revision_conflict", "Draft changed before legacy asset preparation"
                )
            document, report = migrate_legacy(path)
            return {**self.replace(document, expected_revision), "migration": report}

    def replace(self, document, expected_revision):
        document = validate_document(copy.deepcopy(document))
        with self.shared_lock, self.store.connect(write=True) as conn:
            meta = self._check_revision(conn, expected_revision)
            if dumps(document) == meta["document"]:
                return {"revision": expected_revision, "document": document}
            revision = expected_revision + 1
            conn.execute(
                "UPDATE config_meta SET draft_revision=?,document=? WHERE singleton=1",
                (revision, dumps(document)),
            )
            project_document(conn, document)
        return {"revision": revision, "document": document}

    def update(self, expected_revision, transform):
        draft = self.read()
        if draft["revision"] != expected_revision:
            raise ConfigError(
                "revision_conflict",
                "Draft changed since it was read",
                details={"actual": draft["revision"]},
            )
        document = copy.deepcopy(draft["document"])
        transform(document)
        return self.replace(document, expected_revision)

    def patch_provider(self, provider_id, fields, expected_revision):
        if "id" in fields:
            raise ConfigError("invalid_field", "Provider identity is immutable", "fields.id")

        def transform(document):
            provider = next((p for p in document["providers"] if p["id"] == provider_id), None)
            if provider is None:
                raise ConfigError("not_found", "Provider not found")
            for key, value in fields.items():
                if key == "parameters":
                    if not isinstance(value, dict):
                        raise ConfigError(
                            "invalid_field", "Parameters must be an object", "fields.parameters"
                        )
                    # Parameter omissions keep their value; complex parameter objects replace whole.
                    provider["parameters"].update(value)
                else:
                    provider[key] = value

        return self.update(expected_revision, transform)

    def _enqueue(self, kind, source, request_id, payload=None, expected_revision=None):
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise ConfigError(
                "invalid_field",
                "request_id must contain 1 to 128 characters",
                field_path="request_id",
            )
        with self.shared_lock, self.store.connect(write=True) as conn:
            existing = conn.execute(
                "SELECT * FROM config_operations WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing:
                if (
                    existing["kind"] != kind
                    or (
                        expected_revision is not None
                        and existing["target_revision"] != expected_revision
                    )
                    or existing["payload"] != dumps(payload or {})
                ):
                    raise ConfigError(
                        "operation_conflict", "Request ID belongs to another operation"
                    )
                return self.tasks.get(existing["id"])
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            if expected_revision is not None:
                self._check_revision(conn, expected_revision)
            if (
                kind == "apply"
                and conn.execute("""SELECT 1 FROM config_operations
                    WHERE kind='apply' AND status IN ('queued','running')""").fetchone()
            ):
                raise ConfigError("operation_conflict", "A configuration apply is already pending")
            if source == "draft":
                revision, document = meta["draft_revision"], json.loads(meta["document"])
            else:
                revision = meta["published_revision"] if source == "published" else int(source)
                row = conn.execute(
                    "SELECT document FROM config_snapshots WHERE revision=?", (revision,)
                ).fetchone()
                if row is None:
                    raise ConfigError("not_found", "Snapshot not found")
                document = json.loads(row[0])
            validate_document(document)
            if kind == "probe":
                provider = next(
                    (p for p in document["providers"] if p["id"] == payload["provider_id"]), None
                )
                if not provider or not any(
                    m["model"] == payload["model"] for m in provider["models"]
                ):
                    raise ConfigError(
                        "invalid_reference", "Unknown probe target", field_path="model"
                    )
            conn.execute(
                "INSERT OR IGNORE INTO config_snapshots VALUES(?,?,?)",
                (revision, dumps(document), time.time()),
            )
            identifier = uuid.uuid4().hex
            now = time.time()
            conn.execute(
                """INSERT INTO config_operations
                (id,request_id,kind,target_revision,status,stage,payload,created_at,updated_at)
                VALUES(?,?,?,?, 'queued','queued',?,?,?)""",
                (identifier, request_id, kind, revision, dumps(payload or {}), now, now),
            )
            row = conn.execute(
                "SELECT * FROM config_operations WHERE id=?", (identifier,)
            ).fetchone()
            result = operation(row)
            result.pop("claim_token", None)
            return result

    def apply(self, expected_revision, request_id):
        return self._enqueue("apply", "draft", request_id, expected_revision=expected_revision)

    def probe(self, source, provider_id, model, request_id, payload=None):
        if source not in ("draft", "published"):
            try:
                source = int(source)
            except (TypeError, ValueError):
                raise ConfigError(
                    "invalid_field", "Invalid configuration source", field_path="source"
                ) from None
        return self._enqueue(
            "probe",
            source,
            request_id,
            {**(payload or {}), "provider_id": provider_id, "model": model, "source": source},
        )

    def publish(self, operation_id, token, before_publish=None, boot_id=None):
        with self.shared_lock:
            if before_publish is not None:
                before_publish()
            return self._publish_locked(operation_id, token, boot_id=boot_id)

    def _publish_locked(self, operation_id, token, boot_id=None):
        with self.store.connect(write=True) as conn:
            if boot_id is not None:
                self._assert_bot_boot(conn, boot_id)
            row = self.tasks.assert_claim(conn, operation_id, token)
            if row["kind"] != "apply":
                raise ConfigError("operation_conflict", "Only apply operations can publish")
            conn.execute(
                "UPDATE config_meta SET published_revision=? WHERE singleton=1",
                (row["target_revision"],),
            )
            conn.execute(
                "UPDATE config_operations SET stage='published',updated_at=? WHERE id=?",
                (time.time(), operation_id),
            )
        return row["target_revision"]

    @staticmethod
    def validate_group_reference(document, provider_id, model, field_path="group_settings"):
        if not provider_id and not model:
            return
        pid = provider_id or document["settings"]["runtime"]["default_provider"]
        if pid is None:
            pid = next((p["id"] for p in document["providers"] if p["enabled"]), None)
        provider = next((p for p in document["providers"] if p["id"] == pid and p["enabled"]), None)
        if provider is None:
            raise ConfigError(
                "dependency_conflict",
                "Group override references unavailable provider",
                field_path=field_path,
                details={"provider_id": pid},
            )
        selected = model or provider["default_model"]
        if not any(m["model"] == selected and m["enabled"] for m in provider["models"]):
            # Aliases resolve through the same enabled model list.
            alias = next((a["model"] for a in provider["aliases"] if a["alias"] == selected), None)
            if not alias or not any(
                m["model"] == alias and m["enabled"] for m in provider["models"]
            ):
                raise ConfigError(
                    "dependency_conflict",
                    "Group override references unavailable model",
                    field_path=field_path,
                    details={"provider_id": pid, "model": selected},
                )

    def validate_group_overrides(self, document, store):
        if not store.path.exists():
            return
        with store._connect() as conn:
            rows = conn.execute("SELECT group_id,provider_id,model FROM group_settings").fetchall()
        for row in rows:
            self.validate_group_reference(
                document, row["provider_id"], row["model"], f"group_settings.{row['group_id']}"
            )

    def update_group_override(self, store, group_id, **payload):
        if "provider_id" not in payload and "model" not in payload:
            return store.update_group_settings(group_id, **payload)
        with self.shared_lock:
            existing = store.get_group_settings(group_id)
            self.validate_group_reference(
                self.read("published")["document"],
                payload.get("provider_id", existing.provider_id),
                payload.get("model", existing.model),
            )
            return store.update_group_settings(group_id, **payload)

    @staticmethod
    def _assert_bot_boot(conn, boot_id):
        row = conn.execute("SELECT boot_id FROM bot_runtime WHERE singleton=1").fetchone()
        if row is None or row[0] != boot_id:
            raise ConfigError("runtime_superseded", "A newer bot boot owns configuration control")

    def assert_bot_boot(self, boot_id):
        with self.store.connect() as conn:
            self._assert_bot_boot(conn, boot_id)

    def register_bot_boot(self, boot_id, loaded_revision, application_version=""):
        """Atomically advance the boot epoch; registration is separate from heartbeats."""
        with self.store.connect(write=True) as conn:
            row = conn.execute("SELECT boot_id FROM bot_runtime WHERE singleton=1").fetchone()
            try:
                previous_epoch = int(row[0].split(":", 1)[0]) if row else 0
            except ValueError:
                previous_epoch = 0
            token = f"{previous_epoch + 1}:{boot_id}"
            conn.execute(
                """INSERT INTO bot_runtime VALUES(1,?,?,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET boot_id=excluded.boot_id,
                loaded_revision=excluded.loaded_revision,application_version=excluded.application_version,
                heartbeat_at=excluded.heartbeat_at,components=excluded.components""",
                (
                    token,
                    loaded_revision,
                    application_version,
                    time.time(),
                    dumps({}),
                ),
            )
            now = time.time()
            conn.execute(
                """UPDATE config_operations SET lease_until=0,updated_at=?
                WHERE status='running' AND kind='apply'""",
                (now,),
            )
            conn.execute(
                """UPDATE config_operations SET status='failed',stage='unconfirmed',
                error=?,updated_at=?,lease_until=NULL WHERE status='running' AND kind='probe'""",
                (
                    dumps(
                        {
                            "code": "probe_result_unconfirmed",
                            "message": "Probe interrupted by a newer bot boot",
                        }
                    ),
                    now,
                ),
            )
        return token

    def report_bot(self, boot_id, loaded_revision, components=None, application_version=""):
        with self.store.connect(write=True) as conn:
            self._assert_bot_boot(conn, boot_id)
            conn.execute(
                """UPDATE bot_runtime SET loaded_revision=?,application_version=?,
                heartbeat_at=?,components=? WHERE singleton=1 AND boot_id=?""",
                (
                    loaded_revision,
                    application_version,
                    time.time(),
                    dumps(components or {}),
                    boot_id,
                ),
            )

    def status(self):
        observed = time.time()
        with self.store.connect() as conn:
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            row = conn.execute("SELECT * FROM bot_runtime WHERE singleton=1").fetchone()
        bot = dict(row) if row else None
        if bot:
            bot.pop("singleton")
            bot["components"] = json.loads(bot["components"])
            bot["observed_at"] = observed
            bot["stale"] = observed - bot["heartbeat_at"] > 20
        return {
            "schema_version": SCHEMA_VERSION,
            "draft_revision": meta["draft_revision"],
            "published_revision": meta["published_revision"],
            "bot": bot,
        }

    def history(self):
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT revision,created_at FROM config_snapshots ORDER BY revision DESC"
            )
            return {"snapshots": [dict(row) for row in rows]}

    def restore_snapshot(self, revision, expected_revision):
        return self.replace(self.read(revision)["document"], expected_revision)

    def validate(self, document=None):
        return validation_report(self.read()["document"] if document is None else document)

    def preview_import(self, document, expected_revision):
        draft = self.read()
        if draft["revision"] != expected_revision:
            raise ConfigError(
                "revision_conflict",
                "Draft changed since it was read",
                details={"actual": draft["revision"]},
            )
        normalized = validate_document(document)
        return {
            **validation_report(normalized, draft["document"]),
            "document": normalized,
            "expected_draft_revision": draft["revision"],
        }

    def diff(self, source="draft", target="published"):
        return validation_report(self.read(source)["document"], self.read(target)["document"])

    def backup(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ConfigError("invalid_field", "Backup must use a separate file")
        ensure_directory(destination.parent)
        with self.store.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        with destination.open("rb") as stream:
            os.fsync(stream.fileno())
        from quickquip.llm.config_durability import sync_directory

        sync_directory(destination.parent)
        return destination

    def restore_database(self, source, *, stopped=False):
        if not stopped:
            raise ConfigError("services_running", "Stop bot and Web before database restore")
        source = Path(source)
        if not source.is_file():
            raise ConfigError("not_found", "Backup database does not exist")
        if source.resolve() == self.path.resolve():
            raise ConfigError("invalid_field", "Restore must use a separate backup file")
        candidate = ConfigStore(source)
        candidate.verify()
        recovered = ConfigService(source)
        validate_document(recovered.read()["document"])
        validate_document(recovered.read("published")["document"])
        backup = self.path.with_name(f"{self.path.name}.{time.time_ns()}.backup")
        self.backup(backup)
        with self.shared_lock, candidate.connect() as origin, sqlite3.connect(self.path) as target:
            origin.backup(target)
            with target:
                target.execute("DELETE FROM bot_runtime")
                target.execute(
                    """UPDATE config_operations SET status='failed',stage='restored',
                    claim_token=NULL,lease_until=NULL,error=?
                    WHERE status IN ('queued','running')""",
                    (
                        dumps(
                            {
                                "code": "database_restored",
                                "message": "Operation cleared by database restore",
                            }
                        ),
                    ),
                )
        return {"backup": str(backup), **self.status()}


@lru_cache(maxsize=1)
def get_config_service():
    service = ConfigService()
    service.initialize(CONFIG_LLM_TOML)
    return service
