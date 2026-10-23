"""Execute real shell entrypoints with isolated SSH/Compose process boundaries."""

from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

TEMPLATE = Path(__file__).resolve().parents[3] / "prod.example"


@pytest.mark.parametrize("shell", ["bash", "powershell"])
def test_legacy_status_keeps_empty_operation_argument(tmp_path, shell):
    pwsh = os.environ.get("QUICKQUIP_TEST_PWSH") or shutil.which("pwsh")
    if shell == "powershell" and not pwsh:
        pytest.skip("PowerShell is not installed")
    root = tmp_path / "server"
    (root / "prod").mkdir(parents=True)
    (root / ".env").write_text("SYNTHETIC=true\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    ssh = binaries / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\n"
        + """
import subprocess, sys
# OpenSSH joins command arguments; unquoted empty arguments disappear here.
command = ' '.join(sys.argv[2:])
result = subprocess.run(['bash', '-c', command], input=sys.stdin.read(), text=True)
sys.exit(result.returncode)
"""
    )
    ssh.chmod(0o700)
    docker = binaries / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + """
import json, sys
assert 'status' in sys.argv
print(json.dumps({'status': 'synthetic'}))
"""
    )
    docker.chmod(0o700)
    args = (
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(TEMPLATE / "config-v1.ps1"),
            "-Action",
            "status",
            "-HostAlias",
            "synthetic",
            "-RemoteDir",
            str(root),
        ]
        if shell == "powershell"
        else [
            "bash",
            str(TEMPLATE / "config-v1.sh"),
            "status",
            "--host-alias",
            "synthetic",
            "--remote-dir",
            str(root),
        ]
    )
    result = subprocess.run(
        args,
        env={**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic" in result.stdout
    assert not list((root / "data").glob(".llm-transfer-*"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["init"],
        ["resume", "--plan", "--operation", "a" * 32],
        ["init", "--overwrite"],
    ],
)
def test_invalid_cli_mode_does_not_initialize_database(tmp_path, arguments, capsys):
    from quickquip.config_sync.cli import main

    assert main([*arguments, "--root", str(tmp_path)]) == 1
    assert not (tmp_path / "data").exists()
    assert "error" in capsys.readouterr().err
