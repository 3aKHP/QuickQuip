"""Compose lifecycle resolves current files and container identities at process boundaries."""

import json
import subprocess

import pytest

from quickquip.config_sync.compose import Compose
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.inventory import entry


def project(tmp_path):
    (tmp_path / ".env").write_text("PORT=5000\n")
    (tmp_path / "docker-compose.yml").write_text("services: {web-admin: {image: synthetic}}\n")
    return Compose(tmp_path)


def test_added_and_removed_override_participates_in_candidate_and_restart(tmp_path, monkeypatch):
    controller = project(tmp_path)
    override = tmp_path / "docker-compose.override.yml"
    files = {
        ".env": entry(b"PORT=5000\n"),
        "docker-compose.yml": entry((tmp_path / "docker-compose.yml").read_bytes()),
        override.name: entry(b"services: {web-admin: {environment: {CUSTOM: enabled}}}\n"),
    }
    checked = []

    def compose_config(command, **kwargs):
        checked.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"services": {"quickquip": {"environment": {}}, "web-admin": {}}}),
            "",
        )

    monkeypatch.setattr(subprocess, "run", compose_config)
    controller.environment({"files": files})
    assert any(str(value).endswith(override.name) for value in checked)
    calls = []
    controller.runner = lambda command, *args: calls.append(command) or ""
    override.write_bytes(b"services: {}\n")
    original = {"services": {"web-admin": {"running": True}}}
    controller.restore(original)
    assert str(override) in calls[-1]
    override.unlink()
    controller.restore(original)
    assert str(override) not in calls[-1]


def test_pause_finds_recreated_containers_and_excludes_other_services(tmp_path):
    controller = project(tmp_path)
    stopped = []

    def docker(command, *args):
        if command[:2] == ["docker", "compose"]:
            if "config" in command:
                return json.dumps({"name": "project", "services": {"web-admin": {}}})
            return json.dumps([{"Service": "web-admin", "State": "running", "ID": "replacement"}])
        if command[1] == "ps":
            return "\n".join(
                json.dumps(
                    {
                        "ID": identity,
                        "State": "running",
                        "Labels": "com.docker.compose.service=" + service,
                    }
                )
                for identity, service in (("replacement", "web-admin"), ("unrelated", "external"))
            )
        stopped.extend(command[command.index("45") + 1 :])
        return ""

    controller.runner = docker
    controller.pause(
        {
            "project": "project",
            "services": {"web-admin": {"running": True, "id": "removed-original"}},
        }
    )
    assert stopped == ["replacement"]


def test_invalid_compose_is_a_domain_error_before_service_mutation(tmp_path, monkeypatch):
    controller = project(tmp_path)
    from quickquip.config_sync import compose_environment

    def invalid(*args):
        raise ValueError("invalid compose")

    monkeypatch.setattr(compose_environment, "resolve", invalid)
    files = {
        ".env": entry(b"PORT=5000\n"),
        "docker-compose.yml": entry((tmp_path / "docker-compose.yml").read_bytes()),
    }
    with pytest.raises(ConfigError) as error:
        controller.environment({"files": files})
    assert error.value.code == "invalid_compose"
