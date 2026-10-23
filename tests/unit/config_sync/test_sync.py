from copy import deepcopy
import sqlite3

import pytest

from quickquip.common.config_writes import ConfigurationBusy
from quickquip.config_sync.bundle import digest, read_assets
from quickquip.config_sync.endpoint import Endpoint
from quickquip.config_sync.planning import plan
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_service import ConfigService


@pytest.fixture
def endpoint(tmp_path):
    (tmp_path / "config").mkdir()
    service = ConfigService(tmp_path / "data/llm_config.db")
    service.initialize()
    return Endpoint(tmp_path)


def changed(bundle, prefix):
    result = deepcopy(bundle)
    result["document"]["settings"]["triggers"]["default_prefix"] = prefix
    return result


def test_three_way_document_conflict_and_explicit_overwrite(endpoint):
    base = endpoint.capture()["bundle"]
    local, remote = changed(base, "/local"), changed(base, "/remote")
    assert plan(base, local, remote)["conflicts"] == ["document"]
    assert plan(base, local, remote, mode="push")["conflicts"] == ["document"]
    result = plan(base, local, remote, mode="push", overwrite=True)
    assert result["bundle"] == local
    assert plan(base, base, remote)["bundle"] == remote
    assert plan(base, local, base)["bundle"] == local
    assert plan(base, local, local)["bundle"] == local


def test_file_deletion_conflicts_with_remote_edit(endpoint):
    path = endpoint.root / "config/games.toml"
    path.write_text("a = 1\n")
    base = endpoint.capture()["bundle"]
    path.write_text("a = 2\n")
    remote = endpoint.capture()["bundle"]
    path.unlink()
    local = endpoint.capture()["bundle"]
    assert plan(base, local, remote)["conflicts"] == ["config/games.toml"]
    assert "config/games.toml" not in plan(base, local, base)["bundle"]["assets"]


def test_sql_projection_edit_is_detected(endpoint):
    with sqlite3.connect(endpoint.service.path) as conn:
        conn.execute("UPDATE triggers_settings SET default_prefix=?", ("/bypass",))
    with pytest.raises(ConfigError) as exc:
        endpoint.capture()
    assert exc.value.code == "projection_mismatch"


def test_plan_does_not_create_sync_state(endpoint):
    directory = endpoint.state.directory
    # Initialization of a fresh DB does not create synchronization identity or state.
    assert not directory.exists()
    endpoint.capture()
    assert not directory.exists()


def test_prepared_transaction_blocks_web_style_service_writes(endpoint):
    captured = endpoint.capture()
    target = changed(captured["bundle"], "/new")
    operation = "a" * 32
    endpoint.prepare(operation, target, captured["version"])
    with pytest.raises(ConfigError) as exc:
        endpoint.service.replace(target["document"], 1)
    assert exc.value.code == "configuration_busy"
    with pytest.raises(ConfigurationBusy):
        endpoint.capture()
    endpoint.commit(operation)
    assert endpoint.service.read()["document"]["settings"]["triggers"]["default_prefix"] == "/new"
    endpoint.confirm(operation, "b" * 32)
    assert endpoint.state.baseline("b" * 32) == target
    assert endpoint.capture()["bundle"] == target


def test_content_lease_rejects_sql_change_without_revision_increment(endpoint):
    before = endpoint.capture()
    target = changed(before["bundle"], "/new")
    # Simulate a writer that preserves projections but forgets the revision.
    from quickquip.llm.config_store import project_document, dumps

    document = changed(before["bundle"], "/concurrent")["document"]
    with endpoint.service.store.connect(write=True) as conn:
        conn.execute("UPDATE config_meta SET document=?", (dumps(document),))
        project_document(conn, document)
    with pytest.raises(ConfigError) as exc:
        endpoint.prepare("a" * 32, target, before["version"])
    assert exc.value.code == "revision_conflict"


def test_rollback_restores_configuration_and_not_business_data(endpoint):
    path = endpoint.root / "config/games.toml"
    path.write_text("a=1\n")
    before = endpoint.capture()
    path.write_text("a=2\n")
    target = changed(endpoint.capture()["bundle"], "/new")
    path.write_text("a=1\n")
    business = endpoint.data / "business.db"
    business.write_bytes(b"untouched")
    endpoint.prepare("a" * 32, target, before["version"])
    endpoint.commit("a" * 32)
    endpoint.recover("a" * 32, services_stopped=True)
    assert endpoint.capture()["bundle"] == before["bundle"]
    assert business.read_bytes() == b"untouched"
    assert endpoint.state.operation("a" * 32)["phase"] == "recovered"


def test_old_healthy_bot_does_not_acknowledge_new_revision(endpoint):
    before = endpoint.capture()
    endpoint.prepare("a" * 32, changed(before["bundle"], "/new"), before["version"], publish=True)
    endpoint.commit("a" * 32)
    boot = endpoint.service.register_bot_boot("boot", 1)
    endpoint.service.report_bot(boot, 1, {"core": {"state": "ready"}})
    with pytest.raises(ConfigError) as exc:
        endpoint.wait("a" * 32, timeout=0)
    assert exc.value.code == "application_timeout"
    record = endpoint.state.operation("a" * 32)
    claim = endpoint.service.tasks.claim(boot, boot_id=boot)
    endpoint.service.publish(claim["id"], claim["claim_token"])
    endpoint.service.report_bot(boot, record["revision"], {"core": {"state": "ready"}})
    endpoint.service.tasks.finish(claim["id"], claim["claim_token"])
    assert endpoint.wait("a" * 32, timeout=0)["phase"] == "committed"


def test_symlink_asset_rejected(endpoint, tmp_path):
    other = tmp_path / "private"
    other.write_text("a=1")
    (endpoint.root / "config/games.toml").symlink_to(other)
    with pytest.raises(ConfigError):
        read_assets(endpoint.root)


def test_digest_preserves_value_types_and_sequence():
    assert digest({"a": None}) != digest({})
    assert digest({"a": False}) != digest({"a": 0})
    assert digest([1, 2]) != digest([2, 1])
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


class LocalRemote:
    host = "synthetic"
    root = "/synthetic"

    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.drop_prepare = False

    def call(self, action, body=None):
        from quickquip.config_sync.rpc import execute

        result = execute(self.endpoint, action, body or {})
        if action == "prepare" and self.drop_prepare:
            self.drop_prepare = False
            raise ConfigError("transport_error", "lost response")
        return result

    def start(self, operation, recover=False):
        if recover:
            return self.endpoint.recover(operation, services_stopped=True)
        state = self.endpoint.state.operation(operation)
        if state["phase"] in ("committed", "confirmed"):
            return
        self.endpoint.commit(operation)
        state = self.endpoint.state.operation(operation)
        boot = self.endpoint.service.register_bot_boot("synthetic", 1)
        if state["task"]:
            claim = self.endpoint.service.tasks.claim(boot, boot_id=boot)
            self.endpoint.service.publish(claim["id"], claim["claim_token"])
            self.endpoint.service.tasks.finish(claim["id"], claim["claim_token"])
        self.endpoint.service.report_bot(boot, state["revision"], {"core": {"state": "ready"}})
        self.endpoint.wait(operation, timeout=0)


@pytest.fixture
def pair(endpoint, tmp_path):
    root = tmp_path / "remote"
    (root / "config").mkdir(parents=True)
    ConfigService(root / "data/llm_config.db").initialize()
    from quickquip.config_sync.client import Synchronizer

    remote = LocalRemote(Endpoint(root))
    return Synchronizer(endpoint, remote)


def test_initialize_push_then_remote_hotfix_flows_back(pair):
    pair.run(initial="local")
    remote = pair.remote.endpoint
    draft = remote.service.read()
    draft["document"]["settings"]["triggers"]["default_prefix"] = "/hotfix"
    saved = remote.service.replace(draft["document"], draft["revision"])
    task = remote.service.apply(saved["revision"], "hotfix")
    boot = remote.service.register_bot_boot("hotfix", 1)
    claim = remote.service.tasks.claim(boot, boot_id=boot)
    remote.service.publish(claim["id"], claim["claim_token"])
    remote.service.tasks.finish(claim["id"], claim["claim_token"])
    remote.service.report_bot(boot, saved["revision"], {"core": {"state": "ready"}})
    assert task["id"] == claim["id"]
    result = pair.run()
    assert result["phase"] == "confirmed"
    assert (
        pair.local.service.read()["document"]["settings"]["triggers"]["default_prefix"] == "/hotfix"
    )


def test_lost_prepare_reply_resumes_same_operation(pair):
    pair.remote.drop_prepare = True
    with pytest.raises(ConfigError) as exc:
        pair.run(initial="local")
    operation = exc.value.details["operation"]
    assert pair.local.state.operation(operation)["phase"] == "prepared"
    result = pair.resume(operation, timeout=0)
    assert result["phase"] == "confirmed"
    assert len(list((pair.remote.endpoint.state.directory / "operations").glob("*.json"))) == 1


def test_unpublished_remote_draft_survives_pull(pair):
    pair.run(initial="local")
    service = pair.remote.endpoint.service
    draft = service.read()
    draft["document"]["settings"]["triggers"]["default_prefix"] = "/unpublished"
    service.replace(draft["document"], draft["revision"])
    pair.run(mode="pull")
    assert service.read()["document"]["settings"]["triggers"]["default_prefix"] == "/unpublished"
    assert (
        pair.local.service.read()["document"]["settings"]["triggers"]["default_prefix"]
        != "/unpublished"
    )


def test_local_edit_after_commit_remains_after_acknowledgement(pair):
    operation = pair.prepare(initial="local")
    pair.remote.start(operation)
    pair.local.commit(operation)
    from quickquip.common.config_writes import maintenance_owner

    record = pair.local.state.operation(operation)
    with maintenance_owner(record["token"]):
        draft = pair.local.service.read()
        draft["document"]["settings"]["triggers"]["default_prefix"] = "/next-edit"
        pair.local.service.replace(draft["document"], draft["revision"])
    pair.finish(operation, timeout=0)
    assert (
        pair.local.service.read()["document"]["settings"]["triggers"]["default_prefix"]
        == "/next-edit"
    )
    result, _, _ = pair.preview()
    assert result["changes"][0]["remote"]


def test_recovery_keeps_gate_until_bot_health_is_verified(endpoint):
    before = endpoint.capture()
    endpoint.prepare(
        "a" * 32, changed(before["bundle"], "/target"), before["version"], publish=True
    )
    endpoint.commit("a" * 32)
    result = endpoint.recover("a" * 32, services_stopped=True, defer_release=True)
    assert result["phase"] == "restored"
    with pytest.raises(ConfigError):
        endpoint.verify_recovery("a" * 32)
    assert endpoint.state.read("maintenance.json") is not None
    boot = endpoint.service.register_bot_boot("recovery", 1)
    endpoint.service.report_bot(boot, 1, {"core": {"state": "ready"}})
    assert endpoint.verify_recovery("a" * 32)["phase"] == "recovered"
    assert endpoint.state.read("maintenance.json") is None


def test_file_commit_uses_new_inode_and_can_restore_partial_write(endpoint, monkeypatch):
    import os

    path = endpoint.root / "config/games.toml"
    path.write_text("a=1\n")
    historical = endpoint.root / "historical.toml"
    os.link(path, historical)
    before = endpoint.capture()
    target = deepcopy(before["bundle"])
    import base64

    target["assets"]["config/games.toml"]["content"] = base64.b64encode(b"a=2\n").decode()
    endpoint.prepare("a" * 32, target, before["version"])
    install = endpoint._assets

    def interrupted(assets):
        install(assets)
        raise OSError("injected interruption after atomic file replacement")

    monkeypatch.setattr(endpoint, "_assets", interrupted)
    with pytest.raises(OSError):
        endpoint.commit("a" * 32)
    assert historical.read_text() == "a=1\n"
    assert path.read_text() == "a=2\n"
    assert path.stat().st_ino != historical.stat().st_ino
    monkeypatch.setattr(endpoint, "_assets", install)
    endpoint.recover("a" * 32, services_stopped=True)
    assert path.read_text() == historical.read_text() == "a=1\n"


def test_external_file_edit_blocks_automatic_restore(endpoint):
    path = endpoint.root / "config/games.toml"
    path.write_text("a=1\n")
    before = endpoint.capture()
    endpoint.prepare("a" * 32, changed(before["bundle"], "/target"), before["version"])
    endpoint.commit("a" * 32)
    path.write_text("a=99\n")
    with pytest.raises(ConfigError) as exc:
        endpoint.recover("a" * 32, services_stopped=True)
    assert exc.value.code == "revision_conflict"
    assert path.read_text() == "a=99\n"
    assert endpoint.state.read("maintenance.json") is not None


def test_maintenance_rejects_another_process(endpoint):
    import os
    from pathlib import Path
    import subprocess
    import sys

    before = endpoint.capture()
    endpoint.prepare("a" * 32, before["bundle"], before["version"])
    code = """
import sys
from quickquip.llm.config_service import ConfigService
from quickquip.llm.config_errors import ConfigError
s = ConfigService(sys.argv[1]); d = s.read()
try:
    s.replace(d['document'], d['revision'])
except ConfigError as error:
    assert error.code == 'configuration_busy'
    sys.exit(0)
sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(endpoint.service.path)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3] / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_group_directory_symlink_is_not_silently_omitted(endpoint):
    base = endpoint.root / "llm_about"
    base.mkdir()
    (base / "123456").symlink_to(endpoint.root / "config", target_is_directory=True)
    with pytest.raises(ConfigError):
        endpoint.capture()


def test_old_confirmation_cannot_move_newer_baseline(endpoint):
    peer = "b" * 32
    for operation, prefix in [("a" * 32, "/a"), ("c" * 32, "/b")]:
        before = endpoint.capture()
        endpoint.prepare(operation, changed(before["bundle"], prefix), before["version"])
        endpoint.commit(operation)
        endpoint.confirm(operation, peer)
    latest = endpoint.state.baseline(peer)
    endpoint.confirm("a" * 32, peer)
    assert endpoint.state.baseline(peer) == latest
    with pytest.raises(ConfigError):
        endpoint.confirm("a" * 32, "d" * 32)


def test_missing_local_prepare_is_completed_before_remote_publication(pair, monkeypatch):
    original = pair.local.prepare

    def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted before local prepare")

    monkeypatch.setattr(pair.local, "prepare", interrupted)
    with pytest.raises(RuntimeError):
        pair.run(initial="local")
    operation = next((pair.local.state.directory / "clients").glob("*.json")).stem
    assert not (pair.local.state.directory / "operations" / f"{operation}.json").exists()
    monkeypatch.setattr(pair.local, "prepare", original)
    assert pair.resume(operation, timeout=0)["phase"] == "confirmed"


def test_remote_confirmed_receipt_finishes_instead_of_local_rollback(pair):
    operation = pair.prepare(initial="local")
    pair.remote.start(operation)
    pair.local.commit(operation)
    client = pair.local.state.read(f"clients/{operation}.json")
    pair.remote.call("confirm", {"operation": operation, "peer": client["local"]})
    assert pair.recover(operation, timeout=0)["phase"] == "confirmed"
    assert pair.local.state.baseline(client["remote"]) == pair.remote.endpoint.state.baseline(
        client["local"]
    )


def test_cancel_before_remote_prepare_leaves_a_tombstone(pair, monkeypatch):
    original = pair.remote.call

    def disconnected(action, body=None):
        if action == "prepare":
            raise ConfigError("transport_error", "request never sent")
        return original(action, body)

    monkeypatch.setattr(pair.remote, "call", disconnected)
    with pytest.raises(ConfigError) as error:
        pair.run(initial="local")
    operation = error.value.details["operation"]
    monkeypatch.setattr(pair.remote, "call", original)
    assert pair.recover(operation, timeout=0)["phase"] == "recovered"
    client = pair.local.state.read(f"clients/{operation}.json")
    with pytest.raises(ConfigError):
        original(
            "prepare",
            {
                "operation": operation,
                "bundle": client["bundle"],
                "expected": client["remote_expected"],
            },
        )


def test_late_commit_cannot_resurrect_recovery(endpoint, monkeypatch):
    import threading
    from contextlib import contextmanager

    captured = endpoint.capture()
    endpoint.prepare("a" * 32, changed(captured["bundle"], "/late"), captured["version"])
    ready, release = threading.Event(), threading.Event()
    original = endpoint.owned_operation
    failures = []

    @contextmanager
    def delayed(operation):
        if threading.current_thread().name == "late":
            ready.set()
            assert release.wait(5)
        with original(operation) as record:
            yield record

    monkeypatch.setattr(endpoint, "owned_operation", delayed)

    def commit():
        try:
            endpoint.commit("a" * 32)
        except ConfigError as error:
            failures.append(error.code)

    thread = threading.Thread(target=commit, name="late")
    thread.start()
    assert ready.wait(5)
    endpoint.recover("a" * 32)
    release.set()
    thread.join(5)
    assert failures == ["recovery_required"]
    assert endpoint.state.operation("a" * 32)["phase"] == "recovered"
    assert endpoint.capture()["bundle"] == captured["bundle"]


def test_same_endpoint_identity_is_rejected(pair):
    ident = pair.local.initialize_identity()
    pair.remote.endpoint.state.write("identity.json", ident)
    with pytest.raises(ConfigError) as error:
        pair.prepare(initial="local")
    assert error.value.code == "endpoint_conflict"


@pytest.mark.parametrize(
    "filename", ["NUL.toml", "bad\\name.toml", "foo:bar.toml", "COM¹.toml", "CON .toml"]
)
def test_nonportable_managed_names_fail_instead_of_being_omitted(endpoint, filename):
    personas = endpoint.root / "config/personas"
    personas.mkdir()
    (personas / filename).write_text('id="synthetic"\n')
    with pytest.raises(ConfigError) as error:
        endpoint.capture()
    assert error.value.code == "invalid_asset"


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("games.toml", '[economy]\nsign_base_gold="broken"\n'),
        ("awakening.toml", '[awakening.defaults]\nextend_duration="broken"\n'),
        ("generation.toml", '[[image.providers]]\nid="bad"\nprotocol="invalid-protocol"\n'),
    ],
)
def test_domain_invalid_assets_are_rejected(endpoint, filename, body):
    import base64
    from quickquip.config_sync.bundle import validate_bundle

    bundle = endpoint.capture()["bundle"]
    bundle["assets"]["config/" + filename] = {
        "mode": 0o600,
        "content": base64.b64encode(body.encode()).decode(),
    }
    with pytest.raises(ConfigError):
        validate_bundle(bundle)


def test_staged_candidate_recovers_real_assets_after_activation_failure(endpoint):
    from quickquip.config_sync.rpc import execute
    import base64

    path = endpoint.root / "config/games.toml"
    path.write_text("a=1\n")
    before = endpoint.capture()
    target = deepcopy(before["bundle"])
    target["assets"]["config/games.toml"]["content"] = base64.b64encode(b"a=2\n").decode()
    endpoint.prepare("a" * 32, target, before["version"], publish=True, deployment=True)
    candidate = endpoint.root / "candidate"
    (candidate / "config").mkdir(parents=True)
    (candidate / "data").symlink_to(endpoint.data, target_is_directory=True)
    new = Endpoint(candidate)
    execute(new, "stage", {"operation": "a" * 32, "release": "20261024-010000-" + "b" * 12})
    assert (candidate / "config/games.toml").read_text() == "a=2\n"
    new.recover("a" * 32, services_stopped=True, defer_release=True)
    assert (candidate / "config/games.toml").read_text() == path.read_text() == "a=1\n"
    assert endpoint.state.operation("a" * 32)["phase"] == "restored"


def test_file_only_update_requires_a_new_bot_boot(endpoint):
    import base64

    old_boot = endpoint.service.register_bot_boot("old", 1)
    endpoint.service.report_bot(old_boot, 1, {"core": {"state": "ready"}})
    before = endpoint.capture()
    target = deepcopy(before["bundle"])
    target["assets"]["config/games.toml"] = {
        "mode": 0o600,
        "content": base64.b64encode(b"[economy]\nsign_base_gold=11\n").decode(),
    }
    endpoint.prepare("a" * 32, target, before["version"], publish=True)
    endpoint.commit("a" * 32)
    assert endpoint.state.operation("a" * 32)["task"] is None
    with pytest.raises(ConfigError, match="unconfirmed"):
        endpoint.wait("a" * 32, timeout=0)
    with pytest.raises(ConfigError):
        endpoint.service.report_bot(old_boot, 1, {"core": {"state": "ready"}})
    new_boot = endpoint.service.register_bot_boot("new", 1)
    endpoint.service.report_bot(new_boot, 1, {"core": {"state": "ready"}})
    assert endpoint.wait("a" * 32, timeout=0)["phase"] == "committed"


def test_terminal_retry_cleans_marker_without_rewriting_baseline(endpoint):
    before = endpoint.capture()
    endpoint.prepare("a" * 32, before["bundle"], before["version"])
    endpoint.commit("a" * 32)
    endpoint.confirm("a" * 32, "b" * 32)
    record = endpoint.state.operation("a" * 32)
    endpoint.state.write("maintenance.json", {"operation": record["id"], "token": record["token"]})
    expected = endpoint.state.baseline("b" * 32)
    endpoint.release_terminal("a" * 32)
    assert endpoint.state.read("maintenance.json") is None
    assert endpoint.state.baseline("b" * 32) == expected


def test_application_failure_details_survive_database_recovery(endpoint):
    before = endpoint.capture()
    endpoint.prepare(
        "a" * 32, changed(before["bundle"], "/failure"), before["version"], publish=True
    )
    endpoint.commit("a" * 32)
    boot = endpoint.service.register_bot_boot("boot", 1)
    claim = endpoint.service.tasks.claim(boot, boot_id=boot)
    endpoint.service.tasks.finish(
        claim["id"],
        claim["claim_token"],
        status="failed",
        error={"code": "dependency_conflict", "message": "synthetic binding"},
    )
    with pytest.raises(ConfigError):
        endpoint.wait("a" * 32, timeout=0)
    endpoint.recover("a" * 32, services_stopped=True)
    summary = endpoint.summary(endpoint.state.operation("a" * 32))
    assert summary["failure"]["details"]["error"]["code"] == "dependency_conflict"


@pytest.mark.parametrize(
    ("before", "after"), [({"value": False}, {"value": 0}), ({}, {"value": None})]
)
def test_review_diff_preserves_types_and_missing_values(before, after):
    from quickquip.config_sync.planning import document_changes

    changes = document_changes(before, after)
    assert len(changes) == 1
    assert changes[0]["field_path"] == "value"
    assert changes[0]["before_present"] == ("value" in before)
    assert changes[0]["after_present"] is True
