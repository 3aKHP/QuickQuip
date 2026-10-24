from copy import deepcopy
import shutil

import pytest

from quickquip.config_sync.bundle import digest
from quickquip.config_workspace.layout import read_tree
from quickquip.config_workspace.service import Workspace
from quickquip.config_workspace.storage import Storage
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_service import ConfigService
from tests.unit.config_workspace.conftest import change_source, edit_value, provider_file


def test_pack_resume_after_database_commit_does_not_create_another_revision(workspace, monkeypatch):
    initial = workspace.endpoint.version()
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=42.0)
    )
    plan = workspace.plan()
    original = Storage.write

    def interrupt_state(self, name, value):
        if name == "state.json":
            raise OSError("simulated interrupted state write")
        return original(self, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "write", interrupt_state)
        with pytest.raises(OSError):
            workspace.execute("pack", plan["plan_hash"])
    operation = workspace.storage.active()
    assert operation and workspace.endpoint.state.operation(operation)["phase"] == "committed"
    resumed = Workspace(workspace.storage.directory, workspace.endpoint.root)
    assert resumed.resume(operation)["phase"] == "confirmed"
    assert resumed.resume(operation)["phase"] == "confirmed"
    assert resumed.endpoint.version()["draft_revision"] == initial["draft_revision"] + 1
    assert resumed.endpoint.state.read("maintenance.json") is None


def test_receipt_resume_preserves_later_source_and_workspace_edits(workspace, source, monkeypatch):
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=42.0)
    )
    original = Storage.finish

    def interrupt_receipt(self, record, phase):
        if phase == "confirmed":
            raise OSError("receipt interrupted after local confirmation")
        return original(self, record, phase)

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "finish", interrupt_receipt)
        with pytest.raises(OSError):
            workspace.execute("pack", workspace.plan()["plan_hash"])
    operation = workspace.storage.active()
    assert source.state.operation(operation)["phase"] == "confirmed"
    change_source(source, 50.0)
    path = workspace.storage.directory / provider_file(workspace)
    contents = b"# later user note\n" + path.read_bytes()
    path.write_bytes(contents)
    assert workspace.resume(operation)["phase"] == "confirmed"
    assert workspace.storage.active() is None
    assert path.read_bytes() == contents
    assert (
        source.service.read()["document"]["providers"][0]["parameters"]["timeout_seconds"] == 50.0
    )


def test_refresh_partial_file_install_can_resume_from_a_new_process_owner(
    workspace, source, monkeypatch
):
    from quickquip.config_workspace import storage as storage_module

    name = provider_file(workspace)
    before = read_tree(workspace.storage.directory).files
    change_source(source, 42.0)
    plan = workspace.plan(action="refresh")
    original = storage_module.durable_write

    def interrupt_file(path, body):
        original(path, body)
        if path == workspace.storage.directory / name:
            raise OSError("simulated crash after file replacement")

    with monkeypatch.context() as patch:
        patch.setattr(storage_module, "durable_write", interrupt_file)
        with pytest.raises(OSError):
            workspace.execute("refresh", plan["plan_hash"])
    operation = workspace.storage.active()
    assert operation
    assert (workspace.storage.directory / name).read_bytes() != before[name]
    resumed = Workspace(workspace.storage.directory, source.root)
    assert resumed.resume(operation)["phase"] == "confirmed"
    assert read_tree(resumed.storage.directory).bundle == source.capture()["bundle"]


def test_refresh_recovery_restores_exact_workspace_text_and_baseline(
    workspace, source, monkeypatch
):
    change_source(source, 42.0)
    before_state = workspace.storage.state()
    before_files = read_tree(workspace.storage.directory).files
    plan = workspace.plan(action="refresh")
    original = Storage.write

    def interrupt(self, name, value):
        if name == "state.json":
            raise OSError("state failure")
        return original(self, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "write", interrupt)
        with pytest.raises(OSError):
            workspace.execute("refresh", plan["plan_hash"])
    operation = workspace.storage.active()
    assert workspace.recover(operation)["phase"] == "recovered"
    assert read_tree(workspace.storage.directory).files == before_files
    assert workspace.storage.state() == before_state
    assert (
        source.service.read()["document"]["providers"][0]["parameters"]["timeout_seconds"] == 42.0
    )


@pytest.mark.parametrize("after_commit", [False, True])
def test_asset_and_document_failure_recovers_source_but_preserves_user_work(
    workspace, monkeypatch, after_commit
):
    original = ConfigService.replace
    before = workspace.endpoint.capture()
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=42.0)
    )
    asset = workspace.storage.directory / "assets/config/admins.toml"
    asset.write_bytes(b"# user asset edit\n")
    edited_files = read_tree(workspace.storage.directory).files
    plan = workspace.plan()

    def interrupt(self, document, expected_revision, **kwargs):
        if after_commit:
            original(self, document, expected_revision, **kwargs)
        raise OSError("simulated source transaction interruption")

    with monkeypatch.context() as patch:
        patch.setattr(ConfigService, "replace", interrupt)
        with pytest.raises(OSError):
            workspace.execute("pack", plan["plan_hash"], services_stopped=True)
    operation = workspace.storage.active()
    assert workspace.endpoint.state.operation(operation)["phase"] == "writing"
    assert (workspace.endpoint.root / "config/admins.toml").read_bytes() == asset.read_bytes()
    with pytest.raises(ConfigError):
        workspace.resume(operation, services_stopped=True)
    result = workspace.recover(operation, services_stopped=True)
    assert result["phase"] == "recovered"
    assert workspace.endpoint.capture()["bundle"] == before["bundle"]
    assert read_tree(workspace.storage.directory).files == edited_files
    assert workspace.storage.active() is None
    assert workspace.endpoint.state.read("maintenance.json") is None


def test_external_workspace_edit_blocks_recovery_before_source_is_restored(workspace, monkeypatch):
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=42.0)
    )
    original = Storage.install
    with monkeypatch.context() as patch:
        patch.setattr(Storage, "install", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            workspace.execute("pack", workspace.plan()["plan_hash"])
    operation = workspace.storage.active()
    path = workspace.storage.directory / provider_file(workspace)
    edited = b"# external new work\n" + path.read_bytes()
    path.write_bytes(edited)
    with pytest.raises(ConfigError) as error:
        workspace.recover(operation, services_stopped=True)
    assert error.value.code == "revision_conflict"
    assert path.read_bytes() == edited
    assert workspace.endpoint.state.operation(operation)["phase"] == "committed"
    assert Storage.install is original


def test_copied_pending_workspace_cannot_take_over_the_original_transaction(
    workspace, tmp_path, monkeypatch
):
    edit_value(
        workspace, provider_file(workspace), lambda p: p["parameters"].update(timeout_seconds=42.0)
    )
    with monkeypatch.context() as patch:
        patch.setattr(Storage, "install", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            workspace.execute("pack", workspace.plan()["plan_hash"])
    operation = workspace.storage.active()
    copied = tmp_path / "copied-workspace"
    shutil.copytree(workspace.storage.directory, copied)
    clone = Workspace(copied, workspace.endpoint.root)
    for command in (clone.resume, clone.recover):
        with pytest.raises(ConfigError) as error:
            command(operation, services_stopped=True)
        assert error.value.code == "endpoint_changed"
    assert workspace.endpoint.state.operation(operation)["phase"] == "committed"
    assert workspace.resume(operation)["phase"] == "confirmed"


def test_pending_task_and_other_maintenance_are_not_bypassed(workspace):
    endpoint = workspace.endpoint
    endpoint.service.probe("draft", "alpha", "first", "pending-probe")
    plan = workspace.plan()
    with pytest.raises(ConfigError) as error:
        workspace.execute("pack", plan["plan_hash"])
    assert error.value.code == "operation_conflict"


def test_peer_confirmation_rejects_local_operation(workspace):
    endpoint = workspace.endpoint
    captured = endpoint.capture()
    target = deepcopy(captured["bundle"])
    target["document"]["providers"][0]["parameters"]["timeout_seconds"] = 42.0
    operation = "a" * 32
    endpoint.prepare(operation, target, captured["version"], local_only=True)
    endpoint.commit(operation)
    with pytest.raises(ConfigError):
        endpoint.confirm(operation, "b" * 32)
    endpoint.complete_local(operation)
    assert not (endpoint.state.directory / "peers").exists()
    assert digest(endpoint.capture()["bundle"]) == digest(target)


def test_resume_continues_an_interrupted_recovery_in_its_original_direction(
    workspace,
    source,
    monkeypatch,
):
    change_source(source, 42.0)
    before_files = read_tree(workspace.storage.directory).files
    original_write = Storage.write

    def interrupt_state(self, name, value):
        if name == "state.json":
            raise OSError("forward state interrupted")
        return original_write(self, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "write", interrupt_state)
        with pytest.raises(OSError):
            workspace.execute("refresh", workspace.plan(action="refresh")["plan_hash"])
    operation = workspace.storage.active()
    original_install = Storage.install

    def interrupt_recovery(self, record, **kwargs):
        original_install(self, record, **kwargs)
        if kwargs.get("restore"):
            raise OSError("recovery receipt interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(Storage, "install", interrupt_recovery)
        with pytest.raises(OSError):
            workspace.recover(operation)
    assert workspace.storage.operation(operation)["phase"] == "recovering"
    assert workspace.resume(operation)["phase"] == "recovered"
    assert read_tree(workspace.storage.directory).files == before_files
