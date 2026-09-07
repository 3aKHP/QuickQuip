"""Isolated deployment transactions; no SSH or real Docker daemon access."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile

import pytest


TEMPLATE = Path(__file__).resolve().parents[3] / "prod.example"
STATE = runpy.run_path(str(TEMPLATE / "deploy-state.py"))
OLD = "20260907-010000-aaaaaaaaaaaa"
NEW = "20260907-020000-bbbbbbbbbbbb"


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    (root / ".env").write_text("ONEBOT_ACCESS_TOKEN=old\n")
    (root / ".env").chmod(0o600)
    (root / "prod").mkdir()
    inbox = root / ".deploy/incoming" / NEW
    inbox.mkdir(parents=True)
    for name in ("deploy-state.py", "remote-deploy-v4.sh"):
        shutil.copyfile(TEMPLATE / name, inbox / name)
    tree = inbox / "tree"
    (tree / "prod").mkdir(parents=True)
    (tree / "prod/docker-compose.yml").write_text("services: {}\n")
    shared = inbox / "shared"
    shared.mkdir()
    (shared / ".env").write_text("ONEBOT_ACCESS_TOKEN=new\n")
    old = root / "releases" / OLD
    (old / "prod").mkdir(parents=True)
    (old / "prod/docker-compose.yml").write_text("services: {}\n")
    (root / "current").symlink_to(f"releases/{OLD}")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["TEST_ROOT"])
with (root / "calls").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "compose":
    release = pathlib.Path(args[args.index("-f") + 1]).parents[1].name
    if "config" in args:
        if "--images" in args:
            print("quickquip-app:" + release)
        elif "--no-interpolate" in args:
            print(json.dumps({"services": {
                name: {"container_name": name, "environment": {"TOKEN": "${TOKEN:-}"}}
                for name in ("llbot", "quickquip", "web-admin")
            }}))
        elif "--format" in args:
            print(json.dumps({"services": {"quickquip": {"environment": {"ONEBOT_ACCESS_TOKEN": "new"}}}}))
    elif "build" in args and os.environ.get("FAIL_BUILD") == "1":
        sys.exit(1)
    elif "up" in args:
        if os.environ.get("FAIL_UP") == "all" or (os.environ.get("FAIL_UP") == "new" and release == os.environ["TEST_NEW"]):
            sys.exit(1)
    elif "ps" in args:
        print("test-container")
    elif "logs" in args:
        print("Bot 123456 connected")
elif args[0] == "inspect":
    print("true")
''')
    docker.chmod(0o700)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TEST_ROOT=str(root), TEST_NEW=NEW)
    return root, inbox, env


def run_deploy(deployment, action="deploy", target="", **overrides):
    root, inbox, env = deployment
    return subprocess.run(
        ["bash", str(inbox / "remote-deploy-v4.sh"), str(root), NEW, "4", action, target],
        env=env | overrides, text=True, capture_output=True, timeout=20,
    )


def test_success_commits_environment_and_previous(deployment):
    root, inbox, _ = deployment
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "current").readlink() == Path("releases") / NEW
    assert (root / "previous").readlink() == Path("releases") / OLD
    assert (root / ".env").read_text() == "ONEBOT_ACCESS_TOKEN=new\n"
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    assert not inbox.exists()


@pytest.mark.parametrize("failure", ["build", "up"])
def test_failure_restores_original_files_and_links(deployment, failure):
    root, inbox, _ = deployment
    result = run_deploy(deployment, **({"FAIL_BUILD": "1"} if failure == "build" else {"FAIL_UP": "new"}))
    assert result.returncode == 1, result.stdout + result.stderr
    assert (root / ".env").read_text() == "ONEBOT_ACCESS_TOKEN=old\n"
    assert (root / "current").readlink() == Path("releases") / OLD
    assert not (root / "previous").exists()
    assert not inbox.exists()
    if failure == "up":
        assert "RECOVERY SUCCEEDED" in result.stdout


def test_failed_recovery_retains_private_backup_and_reports_failure(deployment):
    root, inbox, _ = deployment
    result = run_deploy(deployment, FAIL_UP="all")
    assert result.returncode == 2
    assert "RECOVERY FAILED" in result.stdout
    assert (inbox / "backup/.env").read_text() == "ONEBOT_ACCESS_TOKEN=old\n"
    assert (inbox / "backup").stat().st_mode & 0o777 == 0o700
    assert (root / "current").readlink() == Path("releases") / OLD


def test_lock_rejects_second_action_before_live_mutation(deployment):
    import fcntl

    root, _, _ = deployment
    with (root / ".deploy/lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_deploy(deployment)
    assert result.returncode == 1
    assert "another deployment is active" in result.stderr
    assert (root / ".env").read_text() == "ONEBOT_ACCESS_TOKEN=old\n"
    assert not (root / "calls").exists()


@pytest.mark.parametrize("args", [["-Rollback", "-DryRun"], ["-Status", "-Migrate"], ["-Status", "-SkipHealth"]])
def test_bash_rejects_invalid_modes_before_side_effects(args):
    result = subprocess.run(["bash", str(TEMPLATE / "deploy-v4.sh"), *args], capture_output=True, text=True)
    assert result.returncode != 0
    assert "FAILED:" in result.stderr


def test_shared_transaction_restores_token_and_missing_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    incoming = tmp_path / "incoming"
    (incoming / "shared/prod").mkdir(parents=True)
    (incoming / "shared/.env").write_text("ONEBOT_ACCESS_TOKEN=new\r\n")
    (incoming / "shared/prod/sendkey.env").write_text("SENDKEY=synthetic\n")
    (incoming / "candidate-compose.json").write_text(json.dumps({"services": {"quickquip": {"environment": {"ONEBOT_ACCESS_TOKEN": "new"}}}}))
    path = root / "prod/llbot-data/default_config.json"
    path.parent.mkdir(parents=True)
    original = b'{"ob11":{"connect":[{}, {"token":"old","url":"old-url"}]}}'
    path.write_bytes(original)
    backup = incoming / "backup"
    STATE["snapshot_shared"](root, incoming, backup)
    STATE["apply_shared"](root, incoming, backup)
    assert json.loads(path.read_text())["ob11"]["connect"][1]["token"] == "new"
    assert (root / ".env").read_bytes() == b"ONEBOT_ACCESS_TOKEN=new\n"
    STATE["restore_shared"](root, backup)
    assert path.read_bytes() == original
    assert not (root / ".env").exists()
    assert not (root / "prod/sendkey.env").exists()


def test_archive_rejects_escape_and_links(tmp_path):
    for index, name in enumerate(("../escape", "link")):
        archive = tmp_path / f"bundle-{index}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            member = tarfile.TarInfo(name)
            if name == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
            bundle.addfile(member, io.BytesIO())
        with pytest.raises(ValueError):
            STATE["extract"](archive, tmp_path / f"tree-{index}")


def test_migration_build_failure_keeps_flat_files_and_no_current(deployment):
    root, _, _ = deployment
    (root / "current").unlink()
    (root / "prod/docker-compose.yml").write_text("services: {}\n")
    (root / "src").mkdir()
    (root / "src/server.txt").write_text("original server code")
    result = run_deploy(deployment, action="migrate", FAIL_BUILD="1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert not (root / "current").is_symlink()
    assert (root / "src/server.txt").read_text() == "original server code"
    baseline = root / "releases" / (NEW + "-baseline")
    assert (baseline / "src/server.txt").read_text() == "original server code"
    config = json.loads((baseline / "prod/docker-compose.yml").read_text())
    assert config["services"]["quickquip"]["env_file"] == [str(root / ".env")]
    assert config["services"]["quickquip"]["environment"]["TOKEN"] == "${TOKEN:-}"
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    assert not any("up" in call for call in calls)
    assert (root / ".env").read_text() == "ONEBOT_ACCESS_TOKEN=old\n"


def test_sudo_atomic_write_assigns_new_owner_and_preserves_existing(tmp_path, monkeypatch):
    owners = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: owners.append((uid, gid)))
    path = tmp_path / "new/ops/sendkey.env"
    STATE["atomic_write"](path, b"synthetic", 0o600, (1234, 5678))
    assert owners == [(1234, 5678)] * 3
    assert path.parent.stat().st_mode & 0o777 == 0o755
    assert path.parent.parent.stat().st_mode & 0o777 == 0o755
    existing = path.stat()
    STATE["atomic_write"](path, b"updated", 0o600, (1234, 5678))
    assert owners[-1] == (existing.st_uid, existing.st_gid)


def test_sudo_new_shared_file_uses_invoking_user(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    incoming = tmp_path / "incoming"
    (incoming / "shared").mkdir(parents=True)
    (incoming / "shared/.env").write_text("TOKEN=synthetic\n")
    (incoming / "candidate-compose.json").write_text('{"services":{"quickquip":{}}}')
    backup = incoming / "backup"
    STATE["snapshot_shared"](root, incoming, backup)
    owners = []
    monkeypatch.setenv("SUDO_UID", "1234")
    monkeypatch.setenv("SUDO_GID", "5678")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: owners.append((uid, gid)))
    STATE["apply_shared"](root, incoming, backup)
    assert owners == [(1234, 5678)]
