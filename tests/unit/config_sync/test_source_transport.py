"""Run the SSH command payload through real source-side Python and SQLite."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

from quickquip.config_sync.peers import Remote
from quickquip.llm.config_service import ConfigService


@pytest.mark.skipif(os.name == "nt", reason="Linux remote recovery worker")
@pytest.mark.parametrize("location", ["prod", "scripts/deploy/legacy"])
def test_legacy_recovery_launches_on_old_and_reorganized_releases(tmp_path, monkeypatch, location):
    from quickquip.config_sync.transport import SSHRemote

    script = tmp_path / "current" / location / "remote-config-sync.sh"
    script.parent.mkdir(parents=True)
    script.write_text('#!/bin/sh\nprintf "%s" "$3" > "$1/finished"\n')

    def local_shell(self, command, body=None):
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr
        return result.stdout

    monkeypatch.setattr(SSHRemote, "_ssh", local_shell)
    SSHRemote("synthetic", str(tmp_path)).start("a" * 32, recover=True)
    deadline = time.monotonic() + 3
    while not (tmp_path / "finished").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (tmp_path / "finished").read_text() == "recover"


@pytest.mark.skipif(os.name == "nt", reason="Linux SSH source deployment")
def test_source_transport_runs_without_a_web_service_and_leaves_local_source_untouched(
    tmp_path, monkeypatch
):
    root = tmp_path / "server"
    root.mkdir()
    (root / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    # Installed/source code can be elsewhere; the protocol receives its real target root explicitly.
    repository = Path(__file__).resolve().parents[3]
    (root / "src").symlink_to(repository / "src", target_is_directory=True)
    (root / ".env").write_text("QUICKQUIP_DEPLOY_LOCATION=cloud\nQUICKQUIP_DEPLOY_RUNTIME=source\n")
    service = ConfigService(root / "config/managed/config.db")
    service.initialize()

    def local_ssh(self, command, body):
        completed = subprocess.run(
            ["bash", "-c", command],
            input=None if body is None else json.dumps(body),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout

    monkeypatch.setattr(Remote, "_ssh", local_ssh)
    peer = Remote("synthetic", str(root), "source")
    before = peer.call("capture", {"source": "published"})
    assert not peer.controller.inspect()["web"]["running"]
    target = json.loads(json.dumps(before["snapshot"]))
    target["document"]["settings"]["runtime"]["history_limit"] = 32
    operation = uuid.uuid4().hex
    peer.call(
        "prepare", {"operation": operation, "expected": before, "target": target, "publish": True}
    )
    peer.call("install", {"operation": operation})
    peer.call("verify", {"operation": operation})
    peer.call("confirm", {"operation": operation})
    assert peer.call("capture", {"source": "published"})["snapshot"] == target
    assert service.read("published")["document"] == target["document"]
    assert not peer.controller.inspect()["bot"]["running"]
