
import pytest

from quickquip.config_workspace.layout import read_tree
from quickquip.config_workspace.service import Workspace
from quickquip.config_workspace.storage import Storage
from tests.unit.config_workspace.conftest import change_source, provider_file


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
