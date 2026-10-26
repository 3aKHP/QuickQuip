"""Legacy journals are recovered through the new command without losing service state."""

from copy import deepcopy
import uuid

import pytest

from quickquip.config_sync.compatibility import resume, pending
from quickquip.config_sync.endpoint import Endpoint
from quickquip.config_sync.state import State
from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_service import ConfigService


def test_legacy_writing_phase_automatically_recovers_both_endpoints(tmp_path, monkeypatch):
    endpoints = []
    for name in ("local", "remote"):
        root = tmp_path / name
        service = ConfigService(root / "config/managed/config.db")
        service.initialize()
        endpoint = Endpoint(root)
        endpoint.initialize_identity()
        endpoints.append(endpoint)
    local, remote = endpoints
    before, remote_before = local.capture(), remote.capture()
    target = deepcopy(before["bundle"])
    target["document"]["settings"]["triggers"]["default_prefix"] = "/changed"
    operation = uuid.uuid4().hex
    local.prepare(operation, target, before["version"])
    remote.prepare(operation, target, remote_before["version"])
    remote.commit(operation)
    install = local._assets
    monkeypatch.setattr(local, "_assets", lambda *_: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        local.commit(operation)
    monkeypatch.setattr(local, "_assets", install)
    record = {
        "id": operation,
        "phase": "prepared",
        "deployment": False,
        "destination": {"host": "synthetic", "root": "/synthetic"},
        "local": before["identity"]["id"],
        "remote": remote_before["identity"]["id"],
        "bundle": target,
    }
    local.state.write(f"clients/{operation}.json", record)

    class Transport:
        host, root = "synthetic", "/synthetic"

        def call(self, action, body=None):
            if action == "inspect":
                return remote.summary(remote.state.operation(operation))
            if action == "release-terminal":
                return remote.release_terminal(operation)
            raise AssertionError(action)

        def start(self, operation, *, recover=False):
            if recover:
                remote.recover(operation, services_stopped=True)

    monkeypatch.setattr("quickquip.config_sync.transport.SSHRemote", lambda *_: Transport())
    assert resume(local.root, record)["phase"] == "recovered"
    assert pending(local.state) is None
    assert local.capture()["bundle"] == before["bundle"]
    assert remote.capture()["bundle"] == remote_before["bundle"]


def test_legacy_pause_failure_restores_and_persists_original_states(tmp_path, monkeypatch):
    from quickquip.config_sync.native import Native
    from quickquip.configuration import process_control

    states = {role: {"running": True, "managed": True, "record": {}} for role in ("bot", "web")}
    monkeypatch.setattr(process_control, "status", lambda root, role: deepcopy(states[role]))

    def control(root, role, action):
        if role == "web" and action == "pause":
            raise ConfigError("service_control_timeout", "synthetic timeout")
        states[role]["running"] = action == "resume"

    monkeypatch.setattr(process_control, "request", control)
    monkeypatch.setattr(Native, "_web_ready", lambda _: True)
    operation = uuid.uuid4().hex
    record = {
        "id": operation,
        "phase": "prepared",
        "destination": {"host": "synthetic", "root": "/synthetic"},
    }
    with pytest.raises(ConfigError, match="synthetic timeout"):
        resume(tmp_path, record)
    assert all(value["running"] for value in states.values())
    saved = State(tmp_path / "data").read(f"clients/{operation}.json")
    assert all(value["running"] for value in saved["native_services"].values())
