"""Tracked deployment clients preserve private connection settings and upload their worker."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("shell", ["bash", "powershell"])
@pytest.mark.parametrize("override", [False, True])
def test_status_uses_project_connection_and_tracked_worker(tmp_path, shell, override):
    executable = shutil.which("pwsh" if shell == "powershell" else "bash")
    if not executable or (shell == "bash" and os.name == "nt"):
        pytest.skip("Client shell is unavailable on this platform")
    project = tmp_path / "private project"
    directory = project / "scripts/deploy"
    (directory / "server").mkdir(parents=True)
    for name in (
        "deploy-v4.sh",
        "deploy-v4.ps1",
        "server/remote-deploy-v4.sh",
        "server/deploy-state.py",
    ):
        shutil.copyfile(ROOT / "scripts/deploy" / name, directory / name)
    (project / ".env").write_text(
        "QUICKQUIP_DEPLOY_SSH_HOST=configured-host\nQUICKQUIP_DEPLOY_REMOTE_DIR=/srv/configured\n"
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    trace = tmp_path / "transport.jsonl"
    for name in ("ssh", "scp"):
        helper = binary / (name + ".py" if os.name == "nt" else name)
        helper.write_text(
            f"#!{sys.executable}\n"
            "import json,os,sys\n"
            "with open(os.environ['TRANSPORT_TRACE'],'a') as f:\n"
            f"    f.write(json.dumps([{name!r},sys.argv[1:]])+'\\n')\n"
            "if sys.argv[-1].startswith('cat '): print('0')\n"
        )
        helper.chmod(0o700)
        if os.name == "nt":
            (binary / (name + ".cmd")).write_text(
                f'@echo off\n"{sys.executable}" "{helper}" %*\nexit /b %errorlevel%\n'
            )
    if os.name == "nt":
        (binary / "python3.cmd").write_text(
            f'@echo off\n"{sys.executable}" %*\nexit /b %errorlevel%\n'
        )
    else:
        python = binary / "python3"
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        python.chmod(0o700)
    if shell == "bash":
        command = [
            executable,
            str(directory / "deploy-v4.sh"),
            "--status",
            "--message",
            "Owner's 更新",
        ]
        if override:
            command += ["--host-alias", "explicit-host", "--remote-dir", "/srv/explicit"]
    else:
        command = [
            executable,
            "-NoProfile",
            "-File",
            str(directory / "deploy-v4.ps1"),
            "-Status",
            "-Message",
            "Owner's 更新",
        ]
        if override:
            command += ["-HostAlias", "explicit-host", "-RemoteDir", "/srv/explicit"]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "PYTHONPATH": str(ROOT / "src"),
            "TRANSPORT_TRACE": str(trace),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in trace.read_text().splitlines()]
    host = "explicit-host" if override else "configured-host"
    remote = "/srv/explicit" if override else "/srv/configured"
    assert all(host in args for name, args in calls if name == "ssh")
    upload = next(args for name, args in calls if name == "scp")
    assert str(directory / "server/remote-deploy-v4.sh") in upload
    assert any(value.startswith(host + ":" + remote + "/.deploy/incoming/") for value in upload)
    encoded = base64.b64encode("Owner's 更新".encode()).decode()
    assert any(
        "DEPLOY_NOTE_B64='" + encoded + "'" in args[-1] for name, args in calls if name == "ssh"
    )
