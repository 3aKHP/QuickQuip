"""Configuration transaction and cross-process control contract regressions."""

from __future__ import annotations

import multiprocessing
import sqlite3
import time

import pytest

from quickquip.llm.config_document import ConfigError, empty_document
from quickquip.llm.config_service import ConfigService


def initialize_worker(path, queue):
    try:
        queue.put(ConfigService(path).initialize()["revision"])
    except Exception as exc:
        queue.put(type(exc).__name__)


@pytest.fixture
def service(tmp_path):
    result = ConfigService(tmp_path / "llm_config.db")
    result.initialize()
    return result


def change(service, text):
    draft = service.read()
    draft["document"]["settings"]["triggers"]["default_prefix"] = text
    return service.replace(draft["document"], draft["revision"])


def test_two_processes_initialize_one_database(tmp_path):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = [
        context.Process(target=initialize_worker, args=(str(tmp_path / "config.db"), queue))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    assert sorted(queue.get(timeout=1) for _ in workers) == [1, 1]
    assert len(ConfigService(tmp_path / "config.db").history()["snapshots"]) == 1


def test_schema_rejection_and_no_legacy_fallback(service, tmp_path):
    with sqlite3.connect(service.path) as conn:
        conn.execute("UPDATE config_meta SET schema_version=999")
    with pytest.raises(ConfigError, match="Unsupported") as exc:
        service.initialize(tmp_path / "legacy.toml")
    assert exc.value.code == "unsupported_schema"


def test_existing_empty_database_is_rejected_not_reinitialized(tmp_path):
    path = tmp_path / "broken.db"
    path.touch()
    with pytest.raises(ConfigError) as exc:
        ConfigService(path).initialize()
    assert exc.value.code == "unsupported_schema"


def test_draft_revision_cas_and_published_is_immutable(service):
    original = service.read()
    updated = change(service, "changed")
    assert updated["revision"] == 2
    assert service.read("published") == original
    with pytest.raises(ConfigError) as exc:
        service.replace(original["document"], 1)
    assert exc.value.code == "revision_conflict"
    assert ConfigService(service.path).read("published") == original
    assert service.replace(updated["document"], 2)["revision"] == 2


def test_apply_target_frozen_while_editing_and_actual_status(service):
    change(service, "target")
    submitted = service.apply(2, "apply-one")
    change(service, "later draft")
    assert service.tasks.get(submitted["id"])["target_revision"] == 2
    assert service.read(2)["document"]["settings"]["triggers"]["default_prefix"] == "target"
    assert service.status()["published_revision"] == 1
    boot = service.register_bot_boot("boot1", 1)
    claim = service.tasks.claim(boot, boot_id=boot)
    service.publish(claim["id"], claim["claim_token"])
    assert service.tasks.get(claim["id"])["status"] == "running"
    service.report_bot(boot, 2, {"mcp": "preparing"}, "1.16.2")
    service.tasks.finish(claim["id"], claim["claim_token"])
    status = service.status()
    assert (status["draft_revision"], status["published_revision"]) == (3, 2)
    assert status["bot"]["loaded_revision"] == 2
    assert not status["bot"]["stale"]


def test_apply_idempotency_conflict_and_cancel(service):
    first = service.apply(1, "same-request")
    assert service.apply(1, "same-request")["id"] == first["id"]
    with pytest.raises(ConfigError) as exc:
        service.apply(1, "other-request")
    assert exc.value.code == "operation_conflict"
    service.tasks.cancel(first["id"])
    assert service.tasks.get(first["id"])["status"] == "cancelled"
    second = service.apply(1, "next-request")
    claim = service.tasks.claim("bot")
    with pytest.raises(ConfigError):
        service.tasks.cancel(second["id"])
    service.tasks.finish(claim["id"], claim["claim_token"], status="failed", error={"code": "test"})


def test_expired_lease_is_reclaimed_and_old_owner_fenced(service):
    service.apply(1, "lease")
    first = service.tasks.claim("old")
    with service.store.connect(write=True) as conn:
        conn.execute("UPDATE config_operations SET lease_until=?", (time.time() - 1,))
    second = service.tasks.claim("new")
    assert second["id"] == first["id"]
    assert second["claim_token"] != first["claim_token"]
    for action in (service.tasks.heartbeat, service.tasks.finish, service.publish):
        with pytest.raises(ConfigError) as exc:
            action(first["id"], first["claim_token"])
        assert exc.value.code == "stale_claim"
    service.tasks.finish(second["id"], second["claim_token"])


def test_publish_callback_failure_preserves_pointer(service):
    change(service, "new")
    service.apply(2, "callback")
    claim = service.tasks.claim("bot")

    def reject():
        raise ConfigError("dependency_conflict", "group refers to old model")

    with pytest.raises(ConfigError):
        service.publish(claim["id"], claim["claim_token"], before_publish=reject)
    assert service.status()["published_revision"] == 1


def test_backup_is_consistent_and_restore_clears_leases(service, tmp_path):
    change(service, "backup-value")
    operation = service.apply(2, "before-backup")
    service.tasks.claim("bot")
    boot = service.register_bot_boot("bot", 1)
    service.report_bot(boot, 1)
    backup = service.backup(tmp_path / "copy.db")
    assert ConfigService(backup).read()["revision"] == 2
    change(service, "after-backup")
    with pytest.raises(ConfigError):
        service.restore_database(backup)
    result = service.restore_database(backup, stopped=True)
    assert result["bot"] is None
    assert service.read()["document"]["settings"]["triggers"]["default_prefix"] == "backup-value"
    assert service.tasks.get(operation["id"])["status"] == "failed"


def test_structured_parameters_and_report_tables(service):
    with service.store.connect() as conn:
        fields = {row["name"] for row in conn.execute("PRAGMA table_info(model_parameters)")}
        assert {"temperature", "extra_body", "reasoning_effort", "stream_enabled"} <= fields
        report = conn.execute("SELECT length_hint FROM weekly_report_settings").fetchone()
        assert report[0] == empty_document()["settings"]["weekly_report"]["length_hint"]


def test_snapshot_sql_update_rejected(service):
    with service.store.connect(write=True) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE config_snapshots SET document='{}' WHERE revision=1")


def test_interrupted_initialization_does_not_publish_partial_database(tmp_path, monkeypatch):
    import quickquip.llm.config_store as store_module

    path = tmp_path / "config.db"

    def interrupt(conn, document):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(store_module, "project_document", interrupt)
    with pytest.raises(RuntimeError):
        ConfigService(path).initialize()
    assert not path.exists()
    assert not list(tmp_path.glob("*.initializing*"))


def configured_provider(service):
    draft = service.read()
    draft["document"]["providers"] = [
        {
            "id": "p",
            "protocol": "openai",
            "base_url": "https://example.com/v1",
            "api_key_env": "MODEL_KEY",
            "default_model": "m",
            "models": [{"model": "m"}, {"model": "next"}],
            "aliases": [{"alias": "short", "model": "m"}],
        }
    ]
    service.replace(draft["document"], draft["revision"])
    return service.read()


def test_interrupted_probe_is_failed_without_replay(service):
    configured_provider(service)
    submitted = service.probe("draft", "p", "m", "once")
    claim = service.tasks.claim("old")
    assert claim["id"] == submitted["id"]
    with service.store.connect(write=True) as conn:
        conn.execute("UPDATE config_operations SET lease_until=?", (time.time() - 1,))
    assert service.tasks.claim("new") is None
    result = service.tasks.get(submitted["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "probe_result_unconfirmed"
    assert service.status()["published_revision"] == 1


def test_relational_projection_failure_rolls_back_all_draft_changes(service, monkeypatch):
    import quickquip.llm.config_service as service_module

    configured_provider(service)
    before = service.read()

    def fail(conn, document):
        conn.execute("DELETE FROM model_aliases")
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(service_module, "project_document", fail)
    with pytest.raises(RuntimeError):
        change(service, "cannot commit")
    assert service.read() == before
    with service.store.connect() as conn:
        assert conn.execute("SELECT alias FROM model_aliases").fetchone()[0] == "short"


def test_group_overrides_validate_published_only_and_block_deletion(service, tmp_path):
    from quickquip.llm.store import LLMStore

    store = LLMStore(tmp_path / "history.db")
    configured_provider(service)
    with pytest.raises(ConfigError) as exc:
        service.update_group_override(store, "10001", provider_id="p", model="m")
    assert exc.value.code == "dependency_conflict"
    submitted = service.apply(2, "publish")
    claim = service.tasks.claim("bot")
    assert claim["id"] == submitted["id"]
    service.publish(claim["id"], claim["claim_token"])
    service.tasks.finish(claim["id"], claim["claim_token"])
    service.update_group_override(store, "10001", provider_id="p", model="short")
    assert store.get_group_settings("10001").model == "short"
    draft = service.read()["document"]
    draft["providers"][0]["models"][0]["enabled"] = False
    with pytest.raises(ConfigError):
        service.validate_group_overrides(draft, store)
    assert store.get_group_settings("10001").provider_id == "p"


def test_same_request_id_cannot_retarget_apply(service):
    service.apply(1, "idempotent")
    change(service, "new draft")
    with pytest.raises(ConfigError) as exc:
        service.apply(2, "idempotent")
    assert exc.value.code == "operation_conflict"


async def test_provider_only_override_protects_inherited_default_on_apply_and_write(
    service, tmp_path
):
    from quickquip.llm.config_runtime import ConfigRuntimeWorker
    from quickquip.llm.service import LLMService

    configured_provider(service)
    runtime = LLMService(
        config_path=service.path, db_path=tmp_path / "history.db", config_service=service
    )
    worker = ConfigRuntimeWorker(service, runtime)
    initial = service.apply(2, "publish-enabled-default")
    await worker.tick()
    assert service.tasks.get(initial["id"])["status"] == "succeeded"
    service.update_group_override(runtime.store, "10001", provider_id="p", model=None)

    draft = service.read()
    draft["document"]["providers"][0]["models"][0]["enabled"] = False
    saved = service.replace(draft["document"], draft["revision"])
    operation = service.apply(saved["revision"], "disable-inherited-default")
    await worker.tick()
    result = service.tasks.get(operation["id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "dependency_conflict"
    assert service.status()["published_revision"] == runtime.config.revision == 2
    assert runtime.config.providers["p"].model_enabled["m"]

    service.update_group_override(runtime.store, "10001", provider_id=None, model=None)
    operation = service.apply(saved["revision"], "disable-without-override")
    await worker.tick()
    assert service.tasks.get(operation["id"])["status"] == "succeeded"
    with pytest.raises(ConfigError) as caught:
        service.update_group_override(runtime.store, "10001", provider_id="p", model=None)
    assert caught.value.code == "dependency_conflict"
    assert caught.value.details["model"] == "m"
    assert runtime.store.get_group_settings("10001").provider_id is None
    await runtime.shutdown()


def test_missing_restore_source_and_same_file_restore_are_rejected(service, tmp_path):
    missing = tmp_path / "missing.db"
    for path in (missing, service.path):
        with pytest.raises(ConfigError):
            service.restore_database(path, stopped=True)
    assert not missing.exists()


@pytest.mark.parametrize(
    "mutation, object_name",
    [
        ("ALTER TABLE runtime_settings DROP COLUMN enabled", "runtime_settings"),
        ("ALTER TABLE config_operations DROP COLUMN claim_token", "config_operations"),
        ("DROP TRIGGER snapshots_immutable_update", "snapshots_immutable_update"),
        (
            "DROP TRIGGER snapshots_immutable_delete; "
            "CREATE TRIGGER snapshots_immutable_delete BEFORE DELETE ON config_snapshots "
            "BEGIN SELECT 1; END",
            "snapshots_immutable_delete",
        ),
        (
            "DROP INDEX one_pending_apply; CREATE INDEX one_pending_apply "
            "ON config_operations(kind) "
            "WHERE kind='apply' AND status IN ('queued','running')",
            "one_pending_apply",
        ),
        (
            "DROP INDEX one_pending_apply; CREATE UNIQUE INDEX one_pending_apply "
            "ON config_operations(kind) WHERE kind='apply' AND status='queued'",
            "one_pending_apply",
        ),
    ],
)
def test_incomplete_schema_rejected_before_initialization_or_restore(
    service,
    tmp_path,
    mutation,
    object_name,
):
    source = service.backup(tmp_path / "tampered.db")
    with sqlite3.connect(source) as conn:
        conn.executescript(mutation)
    before = service.read()
    candidate = ConfigService(source)
    for operation in (
        lambda: candidate.initialize(),
        lambda: candidate.apply(1, "must-not-enqueue"),
        lambda: service.restore_database(source, stopped=True),
    ):
        with pytest.raises(ConfigError) as error:
            operation()
        assert error.value.code == "unsupported_schema"
        assert object_name in {*error.value.details["changed"], *error.value.details["missing"]}
    assert service.read() == before
    assert not list(tmp_path.glob("llm_config.db.*.backup"))


def test_initialized_database_and_backup_directory_entries_are_synced(tmp_path, monkeypatch):
    from quickquip.llm import config_durability

    synced = []

    def observe(directory):
        directory = directory.resolve()
        database = directory / "llm_config.db"
        snapshot = directory / "snapshot.db"
        # Capture publication state, including durability of a newly created backup directory.
        synced.append(
            (directory, database.is_file(), snapshot.is_file(), (directory / "backups").is_dir())
        )
        for file in (database, snapshot):
            if file.is_file():
                ConfigService(file).store.verify()

    monkeypatch.setattr(config_durability, "sync_directory", observe)
    service = ConfigService(tmp_path / "llm_config.db")
    service.initialize()
    destination = service.backup(tmp_path / "backups" / "snapshot.db")
    assert (tmp_path.resolve(), True, False, False) in synced
    assert (tmp_path.resolve(), True, False, True) in synced
    assert ((tmp_path / "backups").resolve(), False, True, False) in synced
    # Reopen after the backup target connection was closed and verify every schema object.
    ConfigService(destination).store.verify()


def test_model_only_group_override_uses_automatic_enabled_default():
    from quickquip.llm.config_document import validate_document

    config = empty_document()
    config["providers"] = [
        {
            "id": "p",
            "protocol": "openai",
            "base_url": "https://example.test",
            "api_key_env": "KEY",
            "default_model": "org/model",
            "models": [{"model": "org/model"}],
            "aliases": [{"alias": "short", "model": "org/model"}],
        }
    ]
    config = validate_document(config)
    assert config["settings"]["runtime"]["default_provider"] is None
    ConfigService.validate_group_reference(config, None, "org/model")
    ConfigService.validate_group_reference(config, None, "short")
    config["providers"][0]["models"][0]["enabled"] = False
    with pytest.raises(ConfigError) as caught:
        ConfigService.validate_group_reference(config, None, "org/model")
    assert caught.value.code == "dependency_conflict"


def publish(service, revision, request_id, note=None):
    operation = service.apply(revision, request_id, note=note)
    claim = service.tasks.claim("bot")
    service.publish(claim["id"], claim["claim_token"])
    service.tasks.finish(claim["id"], claim["claim_token"])
    return operation


def test_revision_notes_follow_unpublished_draft_and_reset_after_publish(service):
    initial = service.status()
    assert initial["draft_version"] == initial["published_version"]
    assert initial["draft_version"]["note"] == ""
    assert isinstance(initial["draft_version"]["saved_at"], float)

    draft = service.read()
    draft["document"]["settings"]["triggers"]["default_prefix"] = "/ask"
    service.replace(draft["document"], 1, note="调整\n唤醒词")
    change(service, "/chat")
    assert service.status()["draft_version"]["note"] == "调整 唤醒词"

    publish(service, 3, "apply-carry")
    status = service.status()
    assert status["published_version"] == status["draft_version"]
    assert status["published_version"]["note"] == "调整 唤醒词"
    change(service, "/next")
    assert service.status()["draft_version"]["note"] == ""

    publish(service, 4, "apply-note", note="上线")
    assert service.status()["published_version"]["note"] == "上线"
    service.set_note(1, "初始导入")
    notes = {s["revision"]: s["note"] for s in service.history()["snapshots"]}
    assert notes == {4: "上线", 3: "调整 唤醒词", 1: "初始导入"}
    with pytest.raises(ConfigError) as caught:
        service.set_note(2, "never snapshotted")
    assert caught.value.code == "not_found"
    with pytest.raises(ConfigError):
        service.set_note("draft", "x" * 121)


def test_unchanged_save_only_relabels_current_draft(service):
    draft = service.read()
    assert service.replace(draft["document"], 1, note="只改备注")["revision"] == 1
    assert service.status()["published_version"]["note"] == "只改备注"


def test_schema_2_upgrade_backfills_versions_and_lifts_draft_pricing(tmp_path):
    from dataclasses import asdict

    from quickquip.llm import config_store
    from quickquip.llm.config import PricingRates
    from quickquip.llm.config_document import validate_document

    path = tmp_path / "llm_config.db"
    doc = empty_document()
    doc["providers"] = [{
        "id": "p", "protocol": "openai", "base_url": "https://example.test/v1",
        "api_key_env": "QQ_TEST_KEY", "default_model": "m", "models": [{"model": "m"}],
    }]
    doc = validate_document(doc)
    rates = asdict(PricingRates(input_per_mtok=1.0))
    doc["format_version"] = 1
    doc["pricing"] = [{"provider_id": None, "model": "p/m", **rates}]
    stored = config_store.dumps(doc)
    with sqlite3.connect(path) as conn:
        conn.executescript(config_store._SCHEMA + config_store.declared_schema())
        conn.execute("INSERT INTO config_meta VALUES(1,2,3,3,?)", (stored,))
        conn.execute("INSERT INTO config_snapshots VALUES(1,?,100)", (stored,))
        conn.execute("INSERT INTO config_snapshots VALUES(3,?,300)", (stored,))
        config_store.project_document(conn, doc)
    service = ConfigService(path)
    with pytest.raises(ConfigError) as caught:
        service.initialize()
    assert caught.value.code == "services_running"

    service.initialize(services_stopped=True)
    status = service.status()
    assert status["schema_version"] == 3
    assert status["published_version"] == {"saved_at": 300.0, "note": ""}
    draft = service.read()
    assert draft["revision"] == 3
    assert draft["document"]["format_version"] == 2
    assert draft["document"]["pricing"] == [{"provider_id": "p", "model": "m", **rates}]
    # Immutable snapshots keep their bytes but read back in the current format.
    assert service.read("published")["document"] == draft["document"]
    assert service.diff()["changes"] == []
    with service.store.connect() as conn:
        snapshot = conn.execute("SELECT document FROM config_snapshots WHERE revision=3")
        assert snapshot.fetchone()[0] == stored
        report = conn.execute("SELECT report FROM config_migrations WHERE source='schema-3'")
        assert '"kind":"converted"' in report.fetchone()[0]
        projected = conn.execute("SELECT document FROM pricing_rules").fetchone()[0]
        assert '"provider_id":"p"' in projected
    assert service.history()["snapshots"][0]["saved_at"] == 300.0


def test_import_preview_reports_format_1_pricing_upgrade(service):
    doc = service.read()["document"]
    doc["format_version"] = 1
    doc["pricing"] = [{"provider_id": None, "model": "gone", "input_per_mtok": 1.0}]
    preview = service.preview_import(doc, 1)
    assert preview["warnings"][0]["code"] == "pricing_upgraded"
    assert preview["warnings"][0]["details"]["kind"] == "unmatched_dropped"
    assert preview["document"]["pricing"] == []
