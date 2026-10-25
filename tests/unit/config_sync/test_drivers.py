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


@pytest.mark.parametrize("shell", ["bash", "powershell"])
def test_remote_backup_restore_transfers_the_configuration_and_runtime_pair(tmp_path, shell):
    from quickquip.llm.config_service import ConfigService

    pwsh = os.environ.get("QUICKQUIP_TEST_PWSH") or shutil.which("pwsh")
    if shell == "powershell" and not pwsh:
        pytest.skip("PowerShell is not installed")
    root = tmp_path / "server"
    (root / "prod").mkdir(parents=True)
    (root / ".env").write_text("SYNTHETIC=true\n")
    service = ConfigService(root / "config/managed/config.db")
    service.initialize()
    document = service.read()["document"]
    document["settings"]["runtime"]["history_limit"] = 37
    service.replace(document, 1)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    programs = {
        "ssh": """
import subprocess, sys
result = subprocess.run(['bash', '-c', ' '.join(sys.argv[2:])],
                        input=sys.stdin.read(), text=True)
sys.exit(result.returncode)
""",
        "scp": """
import shutil, sys
source, target = [path.removeprefix('synthetic:') for path in sys.argv[1:]]
shutil.copyfile(source, target)
""",
        "docker": """
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ['TEST_ROOT'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
args = [arg.replace('/app/data/', str(root / 'data') + '/') for arg in args]
if 'quickquip.llm.config_cli' in args:
    from quickquip.llm.config_cli import execute, parser
    command = ['--db', str(root / 'config/managed/config.db')]
    command += args[args.index('quickquip.llm.config_cli') + 1:]
    print(json.dumps(execute(parser().parse_args(command))))
elif '-c' in args:
    sys.exit(subprocess.run([sys.executable, *args[args.index('-c'):]]).returncode)
""",
    }
    for name, program in programs.items():
        path = binaries / name
        path.write_text(f"#!{sys.executable}\n" + program)
        path.chmod(0o700)
    destination = tmp_path / "backup.db"

    def run(action):
        args = (
            [pwsh, "-NoProfile", "-File", str(TEMPLATE / "config-v1.ps1"),
             "-Action", action, "-HostAlias", "synthetic", "-RemoteDir", str(root),
             "-File", str(destination)]
            if shell == "powershell" else
            ["bash", str(TEMPLATE / "config-v1.sh"), action, "--host-alias", "synthetic",
             "--remote-dir", str(root), "--file", str(destination)]
        )
        return subprocess.run(args, env={**os.environ, "TEST_ROOT": str(root),
                              "PYTHONPATH": os.pathsep.join((str(TEMPLATE.parent / "src"),
                                                            os.environ.get("PYTHONPATH", ""))),
                              "PATH": str(binaries) + os.pathsep + os.environ["PATH"]},
                              capture_output=True, text=True, timeout=20)

    result = run("backup")
    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.exists()
    sidecar = destination.with_name(destination.name + ".runtime.db")
    assert sidecar.exists()
    document["settings"]["runtime"]["history_limit"] = 91
    service.replace(document, 2)
    result = run("restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert service.read()["document"]["settings"]["runtime"]["history_limit"] == 37
    assert service.read("published")["revision"] == 1
    calls = (root / "calls.jsonl").read_text()
    sidecar.unlink()
    result = run("restore")
    assert result.returncode != 0
    assert (root / "calls.jsonl").read_text() == calls
    assert not list((root / "data").glob(".llm-transfer-*"))
