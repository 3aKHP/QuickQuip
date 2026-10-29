"""Service lifetime and foreign-system status evidence used for pack routing."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from quickquip.configuration.activity import directory, offline


@pytest.mark.parametrize("container", [True, False])
@pytest.mark.parametrize("state,expected", [("running", "running"), ("exited", "stopped")])
def test_foreign_native_services_remain_unknown_and_compose_uses_exact_project(
    project, monkeypatch, container, state, expected
):
    root, _ = project
    for role in ("bot", "web"):
        path = directory(root) / f"{role}.json"
        value = json.loads(path.read_text())
        value.update(system="foreign-" + os.name, container=container)
        path.write_text(json.dumps(value))
    labels = (
        f"com.docker.compose.project.working_dir={root}/prod,com.docker.compose.service=quickquip"
    )
    rows = [
        dict(Labels=labels, State=state),
        dict(Labels=labels.replace("/prod,", "-other/prod,"), State="running"),
    ]
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="\n".join(map(json.dumps, rows)))
    )
    with offline(root) as status:
        assert status == (expected if container else "unknown")


def test_unavailable_docker_keeps_foreign_container_status_unknown(project, monkeypatch):
    root, _ = project
    for role in ("bot", "web"):
        path = directory(root) / f"{role}.json"
        value = json.loads(path.read_text())
        value.update(system="foreign-" + os.name, container=True)
        path.write_text(json.dumps(value))

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", unavailable)
    with offline(root) as status:
        assert status == "unknown"


def test_invalid_service_record_is_unknown(project):
    root, _ = project
    (directory(root) / "web.json").write_text("null")
    with offline(root) as status:
        assert status == "unknown"
