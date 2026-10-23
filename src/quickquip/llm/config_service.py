"""Application service shared by configuration CLI, Web Admin and bot control."""

from __future__ import annotations

import copy
from functools import wraps
import json
import os
import sqlite3
import time
import uuid
from functools import lru_cache
from pathlib import Path

from filelock import FileLock

from quickquip.common.paths import CONFIG_LLM_TOML, DATA_DIR
from quickquip.llm.config_document import (
    ConfigError,
    empty_document,
    upgrade_document,
    validate_document,
)
from quickquip.llm.config_store import ConfigStore, SCHEMA_VERSION, dumps, project_document
from quickquip.llm.config_durability import ensure_directory
from quickquip.llm.config_tasks import ConfigTaskQueue, operation

from quickquip.llm.config_validation import document_diff as document_diff, validation_report

DEFAULT_CONFIG_DB = DATA_DIR / "llm_config.db"
MAX_NOTE_LENGTH = 120


def _clean_note(note):
    """Version notes are single-line labels shown as ``YYYY-MM-DD HH:mm (note)``."""
    if note is None:
        return None
    if not isinstance(note, str) or "\x00" in note:
        raise ConfigError("invalid_field", "Note must be a string", field_path="note")
    cleaned = " ".join(note.split())
    if len(cleaned) > MAX_NOTE_LENGTH:
        raise ConfigError(
            "invalid_field",
            f"Note must be at most {MAX_NOTE_LENGTH} characters",
            field_path="note",
        )
    return cleaned


def _set_note(conn, revision, note):
    conn.execute(
        "INSERT INTO config_revisions(revision,note) VALUES(?,?) "
        "ON CONFLICT(revision) DO UPDATE SET note=excluded.note",
        (revision, note),
    )


def _version(conn, revision):
    row = conn.execute(
        "SELECT saved_at,note FROM config_revisions WHERE revision=?", (revision,)
    ).fetchone()
    return {"saved_at": row["saved_at"], "note": row["note"]} if row else {
        "saved_at": None,
        "note": "",
    }


def configuration_mutation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        from quickquip.common.config_writes import ConfigurationBusy, configuration_write

        try:
            with configuration_write(self.path.parent):
                return method(self, *args, **kwargs)
        except ConfigurationBusy as exc:
            raise ConfigError("configuration_busy", str(exc)) from exc
    return guarded


class ConfigService:
    def __init__(self, path=DEFAULT_CONFIG_DB, *, config_dir=None):
        self.path = Path(path)
        self.config_dir = Path(config_dir) if config_dir else self.path.parent.parent / "config"
        from quickquip.llm.client_fingerprints.catalog import get_catalog

        get_catalog(self.config_dir)
        self._references_lock = FileLock(str(self.path) + ".references.lock", timeout=10)
        self.store = ConfigStore(self.path)
        self.tasks = ConfigTaskQueue(self.store)

    @property
    def shared_lock(self):
        return self._references_lock

    def initialize(self, legacy_path=None, *, services_stopped=False):
        ensure_directory(self.path.parent)
        with FileLock(str(self.path) + ".init.lock", timeout=60):
            if self.path.exists():
                # An existing database is authoritative, including failure/new-schema cases.
                with self.shared_lock:
                    self.store.upgrade(services_stopped=services_stopped)
                self.store.verify()
                return self.read()
            report = None
            legacy = Path(legacy_path) if legacy_path else None
            if legacy and legacy.exists():
                from quickquip.llm.config_migration import migrate_legacy

                document, report = migrate_legacy(legacy)
            else:
                document = empty_document()
            document = validate_document(document, config_dir=self.config_dir)
            self.store.create(document, report, str(legacy or ""))
        return self.read()

    def read(self, source="draft"):
        with self.store.connect() as conn:
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            if source == "draft":
                return {
                    "revision": meta["draft_revision"],
                    "document": upgrade_document(json.loads(meta["document"]))[0],
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
            # Immutable format-1 snapshots are presented in the current format.
            return {"revision": revision, "document": upgrade_document(json.loads(row[0]))[0]}

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

    @configuration_mutation
    def migrate_legacy(self, path, expected_revision):
        from quickquip.llm.config_migration import migrate_legacy

        with self.shared_lock:
            if self.read()["revision"] != expected_revision:
                raise ConfigError(
                    "revision_conflict", "Draft changed before legacy asset preparation"
                )
            document, report = migrate_legacy(path)
            return {**self.replace(document, expected_revision), "migration": report}

    @configuration_mutation
    def replace(self, document, expected_revision, *, note=None):
        """Save a draft revision. Without an explicit note an unpublished draft keeps its
        note across saves; the first save after publishing starts unlabeled."""
        note = _clean_note(note)
        document = validate_document(copy.deepcopy(document), config_dir=self.config_dir)
        with self.shared_lock, self.store.connect(write=True) as conn:
            meta = self._check_revision(conn, expected_revision)
            if dumps(document) == meta["document"]:
                if note is not None:
                    _set_note(conn, expected_revision, note)
                return {"revision": expected_revision, "document": document}
            revision = expected_revision + 1
            if note is None:
                note = (
                    ""
                    if expected_revision == meta["published_revision"]
                    else _version(conn, expected_revision)["note"]
                )
            conn.execute(
                "UPDATE config_meta SET draft_revision=?,document=? WHERE singleton=1",
                (revision, dumps(document)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO config_revisions(revision,saved_at,note) VALUES(?,?,?)",
                (revision, time.time(), note),
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

    @configuration_mutation
    def _enqueue(self, kind, source, request_id, payload=None, expected_revision=None, note=None):
        note = _clean_note(note)
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
            validate_document(document, config_dir=self.config_dir)
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
            if note is not None:
                _set_note(conn, revision, note)
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

    def apply(self, expected_revision, request_id, *, note=None):
        return self._enqueue(
            "apply", "draft", request_id, expected_revision=expected_revision, note=note
        )

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

    @configuration_mutation
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
            draft_version = _version(conn, meta["draft_revision"])
            published_version = _version(conn, meta["published_revision"])
            loaded_version = _version(conn, row["loaded_revision"]) if row else None
        bot = dict(row) if row else None
        if bot:
            bot.pop("singleton")
            bot["components"] = json.loads(bot["components"])
            bot["observed_at"] = observed
            bot["stale"] = observed - bot["heartbeat_at"] > 20
            bot["loaded_version"] = loaded_version
        return {
            "schema_version": SCHEMA_VERSION,
            "draft_revision": meta["draft_revision"],
            "draft_version": draft_version,
            "published_revision": meta["published_revision"],
            "published_version": published_version,
            "bot": bot,
        }

    def history(self):
        with self.store.connect() as conn:
            rows = conn.execute(
                """SELECT s.revision,s.created_at,r.saved_at,COALESCE(r.note,'') AS note
                FROM config_snapshots s LEFT JOIN config_revisions r USING(revision)
                ORDER BY s.revision DESC"""
            )
            return {"snapshots": [dict(row) for row in rows]}

    def version(self, source="draft"):
        """Label of a draft/published/snapshot revision: saved time and operator note."""
        with self.store.connect() as conn:
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            return _version(conn, self._revision(conn, meta, source))

    @configuration_mutation
    def set_note(self, source, note):
        note = _clean_note(note)
        if note is None:
            raise ConfigError("invalid_field", "Note must be a string", field_path="note")
        with self.shared_lock, self.store.connect(write=True) as conn:
            meta = conn.execute("SELECT * FROM config_meta WHERE singleton=1").fetchone()
            _set_note(conn, self._revision(conn, meta, source), note)
        return self.status()

    @staticmethod
    def _revision(conn, meta, source):
        if source == "draft":
            return meta["draft_revision"]
        try:
            revision = meta["published_revision"] if source == "published" else int(source)
        except (TypeError, ValueError):
            raise ConfigError(
                "invalid_field", "Invalid configuration source", field_path="source"
            ) from None
        if not conn.execute(
            "SELECT 1 FROM config_snapshots WHERE revision=?", (revision,)
        ).fetchone():
            raise ConfigError("not_found", "Snapshot not found", details={"revision": revision})
        return revision

    def restore_snapshot(self, revision, expected_revision):
        return self.replace(self.read(revision)["document"], expected_revision)

    def validate(self, document=None):
        return validation_report(self.read()["document"] if document is None else document,
                                 config_dir=self.config_dir)

    def preview_import(self, document, expected_revision):
        draft = self.read()
        if draft["revision"] != expected_revision:
            raise ConfigError(
                "revision_conflict",
                "Draft changed since it was read",
                details={"actual": draft["revision"]},
            )
        normalized = validate_document(document, config_dir=self.config_dir)
        report = validation_report(normalized, draft["document"], config_dir=self.config_dir)
        report["warnings"] = [
            {
                "code": "pricing_upgraded",
                "field_path": change["field_path"],
                "message": "Format 1 catch-all price was reassigned or dropped",
                "details": change,
            }
            for change in upgrade_document(document)[1]
        ] + report["warnings"]
        return {
            **report,
            "document": normalized,
            "expected_draft_revision": draft["revision"],
        }

    def diff(self, source="draft", target="published"):
        return validation_report(self.read(source)["document"], self.read(target)["document"],
                                 config_dir=self.config_dir)

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
        with destination.open("r+b") as stream:
            os.fsync(stream.fileno())
        from quickquip.llm.config_durability import sync_directory

        sync_directory(destination.parent)
        return destination

    @configuration_mutation
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
        recovered = ConfigService(source, config_dir=self.config_dir)
        validate_document(recovered.read()["document"], config_dir=self.config_dir)
        validate_document(recovered.read("published")["document"], config_dir=self.config_dir)
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
