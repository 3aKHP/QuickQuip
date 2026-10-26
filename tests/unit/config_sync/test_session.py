"""Exercise qqconf staging and directional qqsync through real configuration endpoints."""

from contextlib import redirect_stdout
import io
import json
import sys

import pytest

from quickquip.config_sync.peers import Local
from quickquip.config_sync.session import Session, public_preview
from quickquip.config_workspace.service import Workspace
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_service import ConfigService


def project(root, location):
    root.mkdir()
    service = ConfigService(root / "config/managed/config.db")
    service.initialize()
    (root / ".env").write_text(
        f"QUICKQUIP_DEPLOY_LOCATION={location}\nQUICKQUIP_DEPLOY_RUNTIME=source\nPORT=5000\n",
        encoding="utf-8",
    )
    return service


def tree(root):
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_local_pack_then_push_consumes_staging_without_touching_workspace(tmp_path):
    root = tmp_path / "local"
    service = project(root, "local")
    workspace = Workspace(root=root)
    workspace.unpack()
    env = workspace.storage.directory / ".env"
    env.write_text(env.read_text().replace("PORT=5000", "PORT=5001"))
    assert workspace.pack()["destination"] == "candidate"
    assert "PORT=5000" in (root / ".env").read_text()
    session = Session(root)
    before = tree(root)
    preview = public_preview(session.preview())
    assert tree(root) == before
    assert preview["write_changes"]
    assert "5001" not in repr(preview)
    work_before = tree(workspace.storage.directory)
    assert session.run("push")["phase"] == "confirmed"
    assert "PORT=5001" in (root / ".env").read_text()
    assert not (root / ".config-staging").exists()
    assert tree(workspace.storage.directory) == work_before
    assert service.read("published")["document"] == service.read()["document"]
    assert session.run("push")["phase"] == "unchanged"
    after = tree(root)
    assert session.run("pull")["phase"] == "local_pull"
    assert tree(root) == after


def test_cloud_push_and_pull_write_only_the_receiver_and_keep_remote_draft(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    local, remote = project(left, "cloud"), project(right, "cloud")
    session = Session(left, remote_factory=lambda *_: Local(right))
    # Establish the baseline without initialization commands.
    assert session.run("push")["phase"] == "unchanged"
    document = local.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 23
    local.replace(document, 1)
    draft = remote.read()["document"]
    draft["settings"]["runtime"]["memory_limit"] = 17
    remote.replace(draft, 1)
    local_before = local.read()
    assert session.run("push")["phase"] == "confirmed"
    assert local.read() == local_before
    assert remote.read("published")["document"]["settings"]["runtime"]["history_limit"] == 23
    assert remote.read("published")["document"]["settings"]["runtime"]["memory_limit"] != 17
    assert remote.read()["document"]["settings"]["runtime"]["memory_limit"] == 17
    remote_before = remote.read()
    assert session.run("pull", source="draft")["phase"] == "confirmed"
    assert remote.read() == remote_before
    assert local.read()["document"]["settings"]["runtime"]["memory_limit"] == 17
    # Pulling a draft has not acknowledged it as remotely published.
    assert session.preview()["write_changes"]
    assert session.run("push")["phase"] == "confirmed"
    assert remote.read("published")["document"]["settings"]["runtime"]["memory_limit"] == 17


def test_retry_uses_original_route_after_environment_changes_during_install(tmp_path, monkeypatch):
    root = tmp_path / "local"
    project(root, "local")
    workspace = Workspace(root=root)
    workspace.unpack()
    env = workspace.storage.directory / ".env"
    env.write_text(env.read_text().replace("=local", "=cloud"))
    workspace.pack()
    session = Session(root)
    original = Local.call
    failed = False

    def disconnect(self, action, body=None):
        nonlocal failed
        result = original(self, action, body)
        if action == "install" and not failed:
            failed = True
            raise ConfigError("transport_error", "lost acknowledgement")
        return result

    monkeypatch.setattr(Local, "call", disconnect)
    with pytest.raises(ConfigError, match="lost acknowledgement"):
        session.run("push")
    assert "LOCATION=cloud" in (root / ".env").read_text()
    assert session.run("push")["phase"] == "confirmed"
    assert not (root / ".config-staging").exists()


def test_missing_modes_allow_reading_but_pack_requires_explicit_real_environment(tmp_path):
    root = tmp_path / "project"
    project(root, "local")
    (root / ".env").write_text("PORT=5000\n")
    workspace = Workspace(root=root)
    workspace.unpack()
    before = tree(root)
    assert workspace.refresh()["destination"] == "unset"
    assert Session(root).preview()["phase"] == "unconfigured"
    assert tree(root) == before
    with pytest.raises(ConfigError) as error:
        workspace.pack()
    assert error.value.code == "deployment_mode_required"
    assert tree(root) == before


@pytest.mark.parametrize("target_history", [10, 30])
def test_local_staging_edits_existing_draft_without_false_conflict(tmp_path, target_history):
    import tomlkit

    root = tmp_path / "local"
    service = project(root, "local")
    original = service.read()["document"]
    original["settings"]["runtime"]["history_limit"] = 20
    service.replace(original, 1)
    workspace = Workspace(root=root)
    workspace.unpack()
    runtime = workspace.storage.directory / "db/llm/settings/runtime.toml"
    contents = tomlkit.parse(runtime.read_text())
    contents["history_limit"] = target_history
    runtime.write_text(tomlkit.dumps(contents))
    workspace.pack()
    assert Session(root).run("push")["phase"] == "confirmed"
    for source in ("draft", "published"):
        assert (
            service.read(source)["document"]["settings"]["runtime"]["history_limit"]
            == target_history
        )
    assert not (root / ".config-staging").exists()


def test_remote_prepare_write_failure_retains_operation_through_worker_envelope(
    tmp_path, monkeypatch
):
    from quickquip.config_sync import worker
    from quickquip.config_sync.installation import Installation
    from quickquip.config_sync.peers import response

    left, right = tmp_path / "left", tmp_path / "right"
    local = project(left, "cloud")
    project(right, "cloud")
    document = local.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 23
    local.replace(document, 1)

    class WorkerPeer(Local):
        def call(self, action, body=None):
            output = io.StringIO()
            with monkeypatch.context() as patch, redirect_stdout(output):
                patch.setattr(
                    sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(body or {}).encode()))
                )
                assert worker.main([action, "--root", str(self.root)]) == 0
            return response(output.getvalue())

    session = Session(left, remote_factory=lambda *_: WorkerPeer(right))
    save = Installation.save

    def interrupted(receiver, record):
        if receiver.root == right and record["phase"] == "prepared":
            raise OSError("receipt write interrupted")
        save(receiver, record)

    monkeypatch.setattr(Installation, "save", interrupted)
    with pytest.raises(ConfigError) as error:
        session.run("push")
    assert error.value.code == "configuration_failed"
    operation = session.pending()["id"]
    receiver = Installation(right)
    assert receiver.state.read("maintenance.json")["token"] == operation
    monkeypatch.setattr(Installation, "save", save)
    assert session.run("push")["phase"] == "confirmed"
    assert receiver.read(operation)["phase"] == "confirmed"
    assert receiver.state.read("maintenance.json") is None
