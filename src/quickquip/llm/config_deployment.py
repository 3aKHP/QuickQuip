"""Pinned deployment inputs and publication under exclusive stopped-Bot ownership."""

from copy import deepcopy
import json
import os
import time
import uuid

from dotenv.main import DotEnv

from quickquip.common.config_utils import expansion_environment
from quickquip.configuration.activity import StoppedService
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_document import compile_document, upgrade_document, validate_document
from quickquip.llm.config_preflight import validate_runtime_configuration
from quickquip.llm.config_store import dumps, next_revision, project_document


def _pin(connection, document, revision, now, note):
    raw = dumps(document)
    row = connection.execute(
        "SELECT document FROM config_snapshots WHERE revision=?", (revision,)
    ).fetchone()
    if row is not None and row[0] != raw:
        raise ConfigError("revision_conflict", "Revision has a different pinned input")
    connection.execute(
        "INSERT OR IGNORE INTO config_snapshots VALUES(?,?,?)", (revision, raw, now)
    )
    connection.execute(
        "INSERT OR IGNORE INTO config_revisions VALUES(?,?,?)", (revision, now, note or "")
    )


def prepare(service, document, expected_revision, *, draft=None, note="qqsync"):
    from quickquip.llm.client_fingerprints.catalog import _load_catalog

    _load_catalog.cache_clear()
    document = validate_document(deepcopy(document), config_dir=service.config_dir)
    draft = document if draft is None else validate_document(
        deepcopy(draft), config_dir=service.config_dir
    )
    now = time.time()
    with service.shared_lock, service.store.connect(write=True) as connection:
        meta = service._check_revision(connection, expected_revision)
        revision = (
            meta["draft_revision"] if dumps(document) == meta["document"]
            else next_revision(connection)
        )
        _pin(connection, document, revision, now, note)
        if dumps(draft) == meta["document"]:
            draft_revision = meta["draft_revision"]
        else:
            draft_revision = revision if draft == document else next_revision(connection)
            previous_note = connection.execute(
                "SELECT note FROM config_revisions WHERE revision=?", (meta["draft_revision"],)
            ).fetchone()
            draft_note = note if draft == document else (previous_note[0] if previous_note else "")
            connection.execute(
                "UPDATE config_meta SET draft_revision=?,document=? WHERE singleton=1",
                (draft_revision, dumps(draft)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO config_revisions VALUES(?,?,?)",
                (draft_revision, now, draft_note or ""),
            )
            project_document(connection, draft)
    return {"revision": revision, "draft_revision": draft_revision, "document": document}


def _environment(service):
    # Match load_root_env_file(override=False) in the process being restarted.
    values = {
        key: value for key, value in DotEnv(
            service.data_dir.parent / ".env", override=False, encoding="utf-8"
        ).dict().items()
        if value is not None
    }
    values.update(os.environ)
    return values


def publish_offline(service, revision, request_id, stopped, *, environment=None):
    root = service.data_dir.parent
    if not isinstance(stopped, StoppedService):
        raise ConfigError("services_running", "A stopped Bot lease is required")
    stopped.verify(root, "bot")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise ConfigError("invalid_field", "Expected a deployment request ID", "request_id")
    with service.shared_lock:
        with service.execution.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM config_operations WHERE request_id=?", (request_id,)
            ).fetchone()
        if existing is not None:
            if (
                existing["kind"] != "apply" or existing["target_revision"] != revision
                or json.loads(existing["payload"]) != {"offline": True}
            ):
                raise ConfigError("operation_conflict", "Request belongs to another operation")
            return json.loads(existing["result"])
        from quickquip.llm.client_fingerprints.catalog import _load_catalog

        _load_catalog.cache_clear()
        target = service.read(revision)
        values = _environment(service) if environment is None else dict(environment)
        with expansion_environment(values):
            document = validate_document(target["document"], config_dir=service.config_dir)
            compiled = compile_document(document, revision=revision, config_dir=service.config_dir)
            validate_runtime_configuration(compiled, document, environment=values)
            service.validate_group_overrides(document)
        stopped.verify(root, "bot")
        with service.execution.connect(write=True) as connection:
            if connection.execute(
                "SELECT 1 FROM config_operations WHERE kind='apply' "
                "AND status IN ('queued','running')"
            ).fetchone():
                raise ConfigError("operation_conflict", "Another configuration apply is pending")
            raw = dumps(document)
            pinned = connection.execute(
                "SELECT document FROM execution_snapshots WHERE revision=?", (revision,)
            ).fetchone()
            if pinned is not None and dumps(upgrade_document(json.loads(pinned[0]))[0]) != raw:
                raise ConfigError("revision_conflict", "Execution revision has different content")
            now = time.time()
            connection.execute(
                "INSERT OR IGNORE INTO execution_snapshots VALUES(?,?,?)", (revision, raw, now)
            )
            result = {"published_revision": revision, "loaded": False}
            connection.execute(
                "INSERT INTO config_operations "
                "(id,request_id,kind,target_revision,status,stage,payload,result,"
                "created_at,updated_at) "
                "VALUES(?,?,'apply',?,'succeeded','published',?,?,?,?)",
                (uuid.uuid4().hex, request_id, revision, dumps({"offline": True}),
                 dumps(result), now, now),
            )
            connection.execute(
                "UPDATE publication SET published_revision=? WHERE singleton=1", (revision,)
            )
            # Keep the actual last loaded revision, but fence old runtime ownership/heartbeat.
            connection.execute(
                "UPDATE bot_runtime SET boot_id=?,heartbeat_at=0 WHERE singleton=1",
                (uuid.uuid4().hex,),
            )
    return result
