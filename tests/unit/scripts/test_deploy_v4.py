"""Isolated deployment transactions; no SSH or real Docker daemon access."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
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
    docker.write_text(
        f"#!{sys.executable}\n"
        + """
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
            if os.environ.get("FAIL_CONFIG_JSON") == "1":
                print("invalid-json")
                sys.exit(0)
            source = os.environ.get("TEST_SKILL_BIND")
            volumes = []
            if source:
                path = (root / "skills" if source.startswith("shared")
                        else root / "releases" / release / "skills")
                if source == "shared-child":
                    path /= "demo"
                volumes = [{"type": "bind", "source": str(path), "target": "/app/skills"}]
            print(json.dumps(
                {"services": {"quickquip": {
                    "environment": {"ONEBOT_ACCESS_TOKEN": "new"}, "volumes": volumes,
                }}}
            ))
    elif "run" in args and "migrate-storage" in args:
        from quickquip.configuration.migration import migrate, rollback
        if "--rollback" in args:
            print(json.dumps(rollback(root, args[args.index("--rollback") + 1],
                                      services_stopped=True)))
        else:
            print(json.dumps(migrate(root, services_stopped=True)))
    elif "build" in args and os.environ.get("FAIL_BUILD") == "1":
        sys.exit(1)
    elif "run" in args and os.environ.get("FAIL_CONFIG_INIT") == "1":
        sys.exit(1)
    elif "up" in args:
        if os.environ.get("FAIL_UP") == "all" or (
            os.environ.get("FAIL_UP") == "new" and release == os.environ["TEST_NEW"]
        ):
            sys.exit(1)
    elif "ps" in args:
        print("test-container")
    elif "logs" in args:
        print("Bot 123456 connected")
    elif "exec" in args and "quickquip.llm.config_cli" in args and "status" in args:
        import argparse
        # The previous release supports require-loaded but no timestamp argument.
        parser = argparse.ArgumentParser()
        parser.add_argument("--require-loaded", action="store_true")
        parser.parse_args(args[args.index("status") + 1:])
        print(json.dumps({"bot": {"heartbeat_at": float(os.environ.get("BOT_HEARTBEAT", "2"))}}))
elif args[0] == "inspect":
    print("1970-01-01T00:00:01Z" if "{{.State.StartedAt}}" in args else "true")
"""
    )
    docker.chmod(0o700)
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        TEST_ROOT=str(root),
        TEST_NEW=NEW,
    )
    return root, inbox, env


def run_deploy(deployment, action="deploy", target="", **overrides):
    root, inbox, env = deployment
    return subprocess.run(
        ["bash", str(inbox / "remote-deploy-v4.sh"), str(root), NEW, "4", action, target],
        env=env | overrides,
        text=True,
        capture_output=True,
        timeout=20,
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
    result = run_deploy(
        deployment, **({"FAIL_BUILD": "1"} if failure == "build" else {"FAIL_UP": "new"})
    )
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


def test_upgrade_failure_recovers_legacy_configuration_health(deployment):
    root, _, _ = deployment
    cli = root / "releases" / OLD / "src/quickquip/llm/config_cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("# Previous release with status --require-loaded.\n")
    result = run_deploy(deployment, FAIL_UP="new", DEPLOY_HEALTH_TIMEOUT="1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RECOVERY SUCCEEDED" in result.stdout
    assert (root / "current").readlink() == Path("releases") / OLD


def test_rollback_checks_legacy_configuration_health(deployment):
    root, _, _ = deployment
    target = root / "releases" / NEW
    (target / "prod").mkdir(parents=True)
    (target / "prod/docker-compose.yml").write_text("services: {}\n")
    cli = target / "src/quickquip/llm/config_cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("# Previous release with status --require-loaded.\n")
    (root / "previous").symlink_to(f"releases/{NEW}")
    result = run_deploy(deployment, action="rollback", DEPLOY_HEALTH_TIMEOUT="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "current").readlink() == Path("releases") / NEW


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


@pytest.mark.parametrize(
    "args",
    [["--rollback", "--dry-run"], ["--status", "--migrate"], ["--status", "--skip-health"]],
)
def test_bash_rejects_invalid_modes_before_side_effects(args):
    result = subprocess.run(
        ["bash", str(TEMPLATE / "deploy-v4.sh"), *args], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "FAILED:" in result.stderr


@pytest.mark.parametrize(
    "legacy",
    [
        "-DryRun",
        "-Status",
        "-Rollback",
        "-Migrate",
        "-SkipHealth",
        "-HostAlias",
        "-RemoteDir",
        "-KeepReleases",
        "-LocalCheck",
    ],
)
def test_bash_rejects_legacy_single_dash_aliases(legacy):
    result = subprocess.run(
        ["bash", str(TEMPLATE / "deploy-v4.sh"), legacy], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "Unknown argument" in result.stderr


def test_shared_transaction_restores_token_and_missing_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    incoming = tmp_path / "incoming"
    (incoming / "shared/prod").mkdir(parents=True)
    (incoming / "shared/.env").write_text("ONEBOT_ACCESS_TOKEN=new\r\n")
    (incoming / "shared/prod/sendkey.env").write_text("SENDKEY=synthetic\n")
    (incoming / "candidate-compose.json").write_text(
        json.dumps({"services": {"quickquip": {"environment": {"ONEBOT_ACCESS_TOKEN": "new"}}}})
    )
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


def _write_fake_docker_for_baseline(
    bin_dir: Path, source: str = "${QUICKQUIP_ROOT:-..}/skills"
) -> None:
    services = {
        "services": {
            "llbot": {"container_name": "llbot"},
            "quickquip": {
                "container_name": "quickquip",
                "volumes": [{"type": "bind", "source": source, "target": "/app/skills"}],
            },
            "web-admin": {"container_name": "web-admin"},
        }
    }
    payload = json.dumps(services)
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        'if args[0] == "compose" and "config" in args and "--no-interpolate" in args:\n'
        f"    print({payload!r})\n"
        'elif args[0] == "inspect":\n'
        '    print("sha256:fake")\n'
    )
    docker.chmod(0o700)


def _minimal_server_root(tmp_path) -> Path:
    root = tmp_path / "server"
    (root / "prod").mkdir(parents=True)
    (root / ".env").write_text("TOKEN=synthetic\n")
    (root / "prod/docker-compose.yml").write_text("services: {}\n")
    return root


def _write_skill(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_fake_sudo(bin_dir: Path, available: bool) -> None:
    sudo = bin_dir / "sudo"
    if available:
        sudo.write_text(
            "#!/bin/bash\n"
            '[ "$1" = "-n" ] && shift\n'
            'echo "$@" >> "$TEST_ROOT/sudo-calls"\n'
            'case "$1" in\n'
            "    true) exit 0 ;;\n"
            '    cp) chmod -R u+w "$TEST_ROOT/skills" ;;\n'
            "    chown) exit 0 ;;\n"
            "esac\n"
            'exec "$@"\n'
        )
    else:
        sudo.write_text("#!/bin/bash\nexit 1\n")
    sudo.chmod(0o700)


@pytest.mark.parametrize("shared", ["skills", "config/managed", "config/managed/child"])
def test_capture_baseline_keeps_shared_volumes_on_root(tmp_path, monkeypatch, shared):
    root = _minimal_server_root(tmp_path)
    _write_skill(root / "skills/demo/SKILL.md", "---\nname: demo\ndescription: 演示\n---\n正文\n")
    _write_skill(root / shared / "state", "shared content")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_docker_for_baseline(bin_dir, source="${QUICKQUIP_ROOT:-..}/" + shared)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    baseline = tmp_path / "baseline"
    STATE["capture_baseline"](root, baseline)
    assert not (baseline / shared).exists()
    config = json.loads((baseline / "prod/docker-compose.yml").read_text())
    (volume,) = config["services"]["quickquip"]["volumes"]
    assert volume["source"] == str(root / shared)
    assert config["services"]["quickquip"]["image"] == f"quickquip-quickquip:{baseline.name}"


def test_resolve_defaulted_variables():
    resolve = STATE["resolve_defaulted_variables"]
    assert resolve("${QUICKQUIP_ROOT:-..}/skills") == "../skills"
    assert resolve("${QUICKQUIP_ROOT:-/opt/QuickQuip}/skills") == "/opt/QuickQuip/skills"
    assert resolve("/opt/QuickQuip/skills") == "/opt/QuickQuip/skills"
    assert resolve("${QUICKQUIP_ROOT}/skills") == "${QUICKQUIP_ROOT}/skills"


def test_capture_baseline_rejects_variable_without_default(tmp_path, monkeypatch):
    root = _minimal_server_root(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_docker_for_baseline(bin_dir, source="${QUICKQUIP_ROOT}/skills")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    with pytest.raises(ValueError, match="unsupported bind mount"):
        STATE["capture_baseline"](root, tmp_path / "baseline")


def test_seed_skips_existing_shared_skills(deployment):
    root, inbox, _ = deployment
    marker = root / "skills/marker.txt"
    marker.parent.mkdir()
    marker.write_text("web-installed")
    (root / "releases" / OLD / "skills/old-skill").mkdir(parents=True)
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == "web-installed"
    assert not (root / "skills/old-skill").exists()


def test_seed_prefers_previous_current_release(deployment):
    root, inbox, _ = deployment
    _write_skill(root / "releases" / OLD / "skills/old-skill/SKILL.md", "old")
    _write_skill(inbox / "tree/skills/new-skill/SKILL.md", "new")
    _write_skill(inbox / "tree/skills/old-skill/SKILL.md", "new-version")
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "skills/old-skill/SKILL.md").read_text() == "old"
    assert (root / "skills/new-skill/SKILL.md").read_text() == "new"
    assert f"seeded shared skills/ from previous release {OLD}" in result.stdout
    assert f"merged release {NEW} skills/ into shared catalog" in result.stdout


def test_seed_empty_then_merges_uploaded_release(deployment):
    root, inbox, _ = deployment
    _write_skill(inbox / "tree/skills/new-skill/SKILL.md", "new")
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "skills/new-skill/SKILL.md").read_text() == "new"
    assert "created empty shared skills/ directory" in result.stdout
    assert f"merged release {NEW} skills/ into shared catalog" in result.stdout


def test_merge_adds_repo_skills_without_overwriting(deployment):
    root, inbox, _ = deployment
    _write_skill(root / "skills/web-skill/SKILL.md", "web-edited")
    _write_skill(inbox / "tree/skills/repo-skill/SKILL.md", "repo")
    _write_skill(inbox / "tree/skills/web-skill/SKILL.md", "repo-version")
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "skills/repo-skill/SKILL.md").read_text() == "repo"
    assert (root / "skills/web-skill/SKILL.md").read_text() == "web-edited"


def test_merge_falls_back_to_sudo_for_root_owned_skills(deployment):
    root, inbox, env = deployment
    _write_skill(root / "skills/web-skill/SKILL.md", "web-edited")
    _write_skill(inbox / "tree/skills/repo-skill/SKILL.md", "repo")
    (root / "skills").chmod(0o555)
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    _write_fake_sudo(bin_dir, available=True)
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "skills/repo-skill/SKILL.md").read_text() == "repo"
    assert "with sudo; catalog ownership restored" in result.stdout
    calls = (root / "sudo-calls").read_text()
    assert "cp -an" in calls
    owner = f"{os.getuid()}:{os.getgid()}"
    assert f"chown -R {owner} {os.path.realpath(root)}/skills" in calls


def test_merge_without_sudo_prints_chown_guidance(deployment):
    root, inbox, env = deployment
    _write_skill(root / "skills/web-skill/SKILL.md", "web-edited")
    _write_skill(inbox / "tree/skills/repo-skill/SKILL.md", "repo")
    (root / "skills").chmod(0o555)
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    _write_fake_sudo(bin_dir, available=False)
    result = run_deploy(deployment)
    (root / "skills").chmod(0o755)
    assert result.returncode == 1, result.stdout + result.stderr
    owner = f"{os.getuid()}:{os.getgid()}"
    guidance = f"sudo chown -R {owner} {os.path.realpath(root)}/skills"
    assert guidance in result.stderr


def test_seed_creates_empty_directory_without_sources(deployment):
    root, _, _ = deployment
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "skills").is_dir()
    assert list((root / "skills").iterdir()) == []
    assert "created empty shared skills/ directory" in result.stdout


@pytest.mark.parametrize("bind", ["shared", "shared-child"])
def test_rollback_keeps_shared_skills_and_merges_target(deployment, bind):
    root, _, _ = deployment
    marker = root / "skills/marker.txt"
    marker.parent.mkdir()
    marker.write_text("web-installed")
    target = root / "releases" / NEW
    (target / "prod").mkdir(parents=True)
    (target / "prod/docker-compose.yml").write_text("services: {}\n")
    _write_skill(target / "skills/rollback-skill/SKILL.md", "rollback")
    (root / "previous").symlink_to(f"releases/{NEW}")
    result = run_deploy(deployment, action="rollback", TEST_SKILL_BIND=bind)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "current").readlink() == Path("releases") / NEW
    assert marker.read_text() == "web-installed"
    assert (root / "skills/rollback-skill/SKILL.md").read_text() == "rollback"


@pytest.mark.parametrize("bind", ["local", "shared"])
def test_rollback_requires_catalog_merge_only_for_shared_mount(deployment, bind):
    root, _, env = deployment
    _write_skill(root / "skills/marker.txt", "web-installed")
    target = root / "releases" / NEW
    (target / "prod").mkdir(parents=True)
    (target / "prod/docker-compose.yml").write_text("services: {}\n")
    _write_skill(target / "skills/rollback-skill/SKILL.md", "rollback")
    (root / "previous").symlink_to(f"releases/{NEW}")
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    _write_fake_sudo(bin_dir, available=False)
    cp = bin_dir / "cp"
    cp.write_text('#!/bin/bash\ntouch "$TEST_ROOT/merge-attempt"\nexit 1\n')
    cp.chmod(0o700)

    result = run_deploy(deployment, action="rollback", TEST_SKILL_BIND=bind)
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    target_started = any(
        "up" in call and str(target / "prod/docker-compose.yml") in call for call in calls
    )
    assert (root / "skills/marker.txt").read_text() == "web-installed"
    assert (target / "skills/rollback-skill/SKILL.md").read_text() == "rollback"
    if bind == "local":
        assert result.returncode == 0, result.stdout + result.stderr
        assert target_started
        assert not (root / "merge-attempt").exists()
        assert (root / "current").readlink() == Path("releases") / NEW
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert not target_started
        assert (root / "merge-attempt").exists()
        assert (root / "current").readlink() == Path("releases") / OLD
        assert "RECOVERY SUCCEEDED" in result.stdout


def test_rollback_rejects_unknown_mount_layout(deployment):
    root, _, _ = deployment
    target = root / "releases" / NEW
    (target / "prod").mkdir(parents=True)
    (target / "prod/docker-compose.yml").write_text("services: {}\n")
    (root / "previous").symlink_to(f"releases/{NEW}")
    result = run_deploy(deployment, action="rollback", FAIL_CONFIG_JSON="1")
    assert result.returncode == 1
    assert "layout could not be resolved" in result.stderr
    assert (root / "current").readlink() == Path("releases") / OLD
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    assert not any(
        "up" in call and str(target / "prod/docker-compose.yml") in call for call in calls
    )


def _add_config_initializer(deployment):
    root, inbox, _ = deployment
    marker = inbox / "tree/src/quickquip/llm/config_cli.py"
    marker.parent.mkdir(parents=True)
    marker.write_text("# isolated configuration initializer marker\n")
    old = root / "releases" / OLD / "config"
    old.mkdir()
    (old / "llm.toml").write_text("[runtime]\nenabled = false\n")
    candidate = inbox / "tree/config"
    candidate.mkdir()
    return old, candidate


def test_previous_bot_heartbeat_cannot_acknowledge_new_container(deployment):
    root, _, _ = deployment
    _add_config_initializer(deployment)
    result = run_deploy(deployment, BOT_HEARTBEAT="0", DEPLOY_HEALTH_TIMEOUT="1")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RECOVERY SUCCEEDED" in result.stdout
    assert (root / "current").readlink() == Path("releases") / OLD


def test_config_migration_selects_server_assets_before_initializer(deployment):
    root, _, _ = deployment
    old, candidate = _add_config_initializer(deployment)
    (candidate / "generation.toml").write_text("[image]\nenabled = false\n")
    (candidate / "personas").mkdir()
    (candidate / "personas/local.toml").write_text('id="local"\n')
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    config = root / "releases" / NEW / "config"
    assert (config / "llm.toml").read_bytes() == (old / "llm.toml").read_bytes()
    assert not (config / "generation.toml").exists()
    assert (config / ".llm-upgrade-generation.toml").exists()
    assert not (config / "personas/local.toml").exists()
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    build = next(i for i, call in enumerate(calls) if "build" in call)
    initialize = next(
        i for i, call in enumerate(calls) if "config_cli" in " ".join(call) and "init" in call
    )
    activate = next(i for i, call in enumerate(calls) if "up" in call)
    assert build < initialize < activate


def test_config_initialization_failure_preserves_current_release(deployment):
    root, _, _ = deployment
    _add_config_initializer(deployment)
    result = run_deploy(deployment, FAIL_CONFIG_INIT="1")
    assert result.returncode != 0
    assert (root / "current").readlink() == Path("releases") / OLD
    assert not (root / "data/llm_config.db").exists()
    assert not any("up" in json.loads(line) for line in (root / "calls").read_text().splitlines())


def test_profile_assets_survive_upgrade_with_candidate_priority(deployment):
    root, _, _ = deployment
    old, candidate = _add_config_initializer(deployment)
    (old / "client_profiles").mkdir()
    (candidate / "client_profiles").mkdir()
    (old / "client_profiles/quickquip.toml").write_text('id="quickquip"\n')
    (old / "client_profiles/custom.toml").write_text('id="custom"\nlabel="server"\n')
    selected = candidate / "client_profiles/custom.toml"
    selected.write_text('id="custom"\nlabel="candidate"\n')
    candidate_bytes = selected.read_bytes()
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    copied = root / "releases" / NEW / "config/client_profiles"
    assert (copied / "quickquip.toml").read_bytes() == (
        old / "client_profiles/quickquip.toml"
    ).read_bytes()
    assert (copied / "custom.toml").read_bytes() == candidate_bytes
    assert 'label="server"' in (old / "client_profiles/custom.toml").read_text()


def test_first_migration_breaks_candidate_generation_hardlink(deployment):
    root, _, _ = deployment
    old, candidate = _add_config_initializer(deployment)
    body = "[image]\nenabled = true\n"
    (old / "generation.toml").write_text(body)
    (candidate / "generation.toml").write_text(body)
    (candidate / "generation.toml").chmod(0o644)
    (old / "generation.toml").chmod(0o644)
    # Force matching timestamps so the release driver chooses rsync's hardlink path.
    source_stat = (old / "generation.toml").stat()
    os.utime(candidate / "generation.toml", ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    current = root / "releases" / NEW / "config/generation.toml"
    assert current.read_text() == body
    assert (old / "generation.toml").read_text() == body
    assert current.stat().st_ino != (old / "generation.toml").stat().st_ino


@pytest.mark.parametrize("asset", ["persona", "generation"])
def test_unreadable_configuration_asset_stops_before_activation(deployment, asset):
    root, _, env = deployment
    old, _ = _add_config_initializer(deployment)
    (root / "data").mkdir()
    (root / "data/llm_config.db").write_text("existing-db-marker")
    path = old / "generation.toml"
    if asset == "persona":
        path = old / "personas/migrated-protected.toml"
        path.parent.mkdir()
    path.write_text('id="synthetic"\n')
    path.chmod(0)
    _write_fake_sudo(Path(env["PATH"].split(os.pathsep)[0]), available=False)
    try:
        result = run_deploy(deployment)
        assert result.returncode != 0, result.stdout + result.stderr
        assert (root / "current").readlink() == Path("releases") / OLD
        calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
        assert not any("run" in call or "up" in call for call in calls)
        assert "configuration asset copy failed with sudo" in result.stderr
        assert path.stat().st_mode & 0o777 == 0
    finally:
        path.chmod(0o600)


def _inject_configuration_copy_permission(deployment, *, failure="permission", discovery=False):
    """Inject errors at real filesystem I/O; execute the production copy program unchanged."""
    root, _, env = deployment
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    protected = str(root / "releases" / OLD / "config")
    interpreter = bin_dir / "python3.13"
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        'if len(sys.argv) > 2 and sys.argv[1] == "-c" and "def copy_personas" in sys.argv[2]:\n'
        "    program = sys.argv[2]\n"
        "    sys.argv = [sys.argv[0], *sys.argv[3:]]\n"
        f"    protected = {protected!r}\n"
        f"    failure = {failure!r}\n"
        f"    discovery = {discovery!r}\n"
        '    privileged = os.environ.get("TEST_COPY_SUDO") == "1"\n'
        "    real_open, real_scandir = os.open, os.scandir\n"
        "    def denied(path):\n"
        "        if str(path).startswith(protected) and not privileged:\n"
        '            if failure == "permission":\n'
        '                raise PermissionError("synthetic protected source")\n'
        '            raise OSError("synthetic I/O failure")\n'
        "    def guarded_open(path, *args, **kwargs):\n"
        "        if not discovery:\n"
        "            denied(path)\n"
        "        return real_open(path, *args, **kwargs)\n"
        "    def guarded_scandir(path):\n"
        "        if discovery:\n"
        "            denied(path)\n"
        "        return real_scandir(path)\n"
        "    os.open, os.scandir = guarded_open, guarded_scandir\n"
        "    if privileged:\n"
        "        os.geteuid = lambda: 0\n"
        "        real_fchown, real_chown = os.fchown, os.chown\n"
        "        def record(path, uid, gid):\n"
        '            with open(os.environ["TEST_ROOT"] + "/asset-owners", "a") as log:\n'
        '                log.write(str(path) + " " + str(uid) + ":" + str(gid) + "\\n")\n'
        "        def fchown(fd, uid, gid):\n"
        '            record(os.readlink("/proc/self/fd/" + str(fd)), uid, gid)\n'
        "            return real_fchown(fd, uid, gid)\n"
        "        def chown(path, uid, gid):\n"
        "            record(path, uid, gid)\n"
        "            return real_chown(path, uid, gid)\n"
        "        os.fchown, os.chown = fchown, chown\n"
        '    exec(compile(program, "configuration-copy", "exec"), {})\n'
        "else:\n"
        "    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n"
    )
    interpreter.chmod(0o700)
    sudo = bin_dir / "sudo"
    sudo.write_text(
        '#!/bin/bash\n[ "$1" = "-n" ] || exit 1\nshift\n'
        'echo "noninteractive configuration copy" >> "$TEST_ROOT/asset-sudo"\n'
        'TEST_COPY_SUDO=1 exec "$@"\n'
    )
    sudo.chmod(0o700)


def test_configuration_asset_sudo_copy_keeps_candidate_and_old_release(deployment):
    root, _, _ = deployment
    old, candidate = _add_config_initializer(deployment)
    (root / "data").mkdir()
    (root / "data/llm_config.db").write_text("existing-db-marker")
    (old / "personas").mkdir()
    (candidate / "personas").mkdir()
    original = old / "personas/migrated-protected.toml"
    original.write_text('id="default"\nsystem_prompt="server"\n')
    original.chmod(0o600)
    generation = old / "generation.toml"
    generation.write_text("[image]\nenabled=false\n")
    generation.chmod(0o600)
    kept = old / "personas/migrated-kept.toml"
    kept.write_text('id="kept"\nsystem_prompt="candidate-priority"\n')
    kept.chmod(0o644)
    os.link(kept, candidate / "personas" / kept.name)
    before = [(path.read_bytes(), path.stat()) for path in (original, generation, kept)]
    _inject_configuration_copy_permission(deployment)
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    copied = root / "releases" / NEW / "config"
    for path, (content, metadata) in zip((original, generation, kept), before):
        assert path.read_bytes() == content
        after = path.stat()
        assert (after.st_uid, after.st_gid, after.st_mode, after.st_mtime_ns) == (
            metadata.st_uid, metadata.st_gid, metadata.st_mode, metadata.st_mtime_ns
        )
    for path in (copied / "personas" / original.name, copied / generation.name):
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_gid == os.getgid()
        assert path.stat().st_mode & 0o777 == 0o600
    assert (copied / "personas" / original.name).read_bytes() == original.read_bytes()
    assert (copied / generation.name).read_bytes() == generation.read_bytes()
    assert (copied / "personas" / kept.name).stat().st_ino == kept.stat().st_ino
    assert len((root / "asset-sudo").read_text().splitlines()) == 2
    owners = (root / "asset-owners").read_text().splitlines()
    assert len(owners) == 2
    assert all(str(copied) in entry for entry in owners)
    assert all(entry.endswith(f" {os.getuid()}:{os.getgid()}") for entry in owners)


@pytest.mark.parametrize("discovery", [False, True])
def test_configuration_copy_io_failure_stops_before_activation(deployment, discovery):
    root, _, _ = deployment
    old, _ = _add_config_initializer(deployment)
    (root / "data").mkdir()
    (root / "data/llm_config.db").write_text("existing-db-marker")
    (old / "personas").mkdir()
    (old / "personas/migrated-protected.toml").write_text('id="synthetic"\n')
    _inject_configuration_copy_permission(deployment, failure="io", discovery=discovery)
    result = run_deploy(deployment)
    assert result.returncode != 0, result.stdout + result.stderr
    assert (root / "current").readlink() == Path("releases") / OLD
    assert not (root / "asset-sudo").exists()
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    assert not any("run" in call or "up" in call for call in calls)


def test_first_migration_copies_protected_assets_as_deployment_user(deployment):
    root, _, _ = deployment
    old, _ = _add_config_initializer(deployment)
    (old / "personas").mkdir()
    (old / "personas/default.toml").write_text('id="default"\n')
    (old / "generation.toml").write_text("[image]\nenabled=false\n")
    _inject_configuration_copy_permission(deployment)
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stdout + result.stderr
    config = root / "releases" / NEW / "config"
    for relative in ("llm.toml", "personas/default.toml", "generation.toml"):
        source, copied = old / relative, config / relative
        assert copied.read_bytes() == source.read_bytes()
        assert copied.stat().st_ino != source.stat().st_ino
        assert (copied.stat().st_uid, copied.stat().st_gid) == (os.getuid(), os.getgid())
    assert (config / "personas").stat().st_uid == os.getuid()
    assert len((root / "asset-sudo").read_text().splitlines()) == 3
    owners = (root / "asset-owners").read_text().splitlines()
    assert len(owners) == 4
    assert all(str(config) in entry for entry in owners)


def _sync_candidate(deployment):
    root, inbox, _ = deployment
    marker = inbox / 'tree/src/quickquip/config_sync/rpc.py'
    marker.parent.mkdir(parents=True)
    marker.write_text('# isolated configuration protocol marker\n')
    return root, inbox


def test_sync_deployment_preserves_selected_environment(deployment):
    root, _ = _sync_candidate(deployment)
    result = run_deploy(deployment, CONFIG_SYNC='auto', SYNC_OPERATION='a' * 32,
                        ENV_SOURCE='server')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / '.env').read_text() == 'ONEBOT_ACCESS_TOKEN=old\n'
    calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
    stage = next(i for i, call in enumerate(calls) if 'stage' in call)
    commit = next(i for i, call in enumerate(calls) if 'candidate-commit' in call)
    application_up = next(i for i, call in enumerate(calls) if '--force-recreate' in call)
    assert stage < application_up < commit
    assert any('wait' in call for call in calls[commit:])


def test_sync_failure_restores_database_before_previous_containers(deployment):
    root, _ = _sync_candidate(deployment)
    result = run_deploy(deployment, CONFIG_SYNC='auto', SYNC_OPERATION='a' * 32,
                        FAIL_UP='new')
    assert result.returncode == 1, result.stdout + result.stderr
    calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
    restore = next(i for i, call in enumerate(calls) if 'recover' in call)
    old_up = next(i for i, call in enumerate(calls)
                  if 'up' in call and any(OLD in value for value in call))
    verified = next(i for i, call in enumerate(calls) if 'recovery-verified' in call)
    assert restore < old_up < verified


def test_sync_exact_assets_do_not_reinherit_deleted_files(deployment):
    root, inbox = _sync_candidate(deployment)
    initializer = inbox / 'tree/src/quickquip/llm/config_cli.py'
    initializer.parent.mkdir(parents=True)
    initializer.write_text('# initializer marker\n')
    old = root / 'releases' / OLD / 'config'
    (old / 'personas').mkdir(parents=True)
    (old / 'client_profiles').mkdir()
    (old / 'personas/migrated-removed.toml').write_text('id="removed"\n')
    (old / 'client_profiles/removed.toml').write_text('id="removed"\n')
    (old / 'generation.toml').write_text('[image]\nenabled=false\n')
    (root / 'data').mkdir()
    (root / 'data/llm_config.db').write_text('existing marker')
    result = run_deploy(deployment, CONFIG_SYNC='auto', SYNC_OPERATION='a' * 32)
    assert result.returncode == 0, result.stdout + result.stderr
    candidate = root / 'releases' / NEW / 'config'
    assert not (candidate / 'personas/migrated-removed.toml').exists()
    assert not (candidate / 'client_profiles/removed.toml').exists()
    assert not (candidate / 'generation.toml').exists()


def test_interrupted_deployment_recovers_using_durable_journal(deployment):
    root, inbox = _sync_candidate(deployment)
    docker = Path(deployment[2]['PATH'].split(os.pathsep)[0]) / 'docker'
    body = docker.read_text().replace(
        '    elif "up" in args:',
        '''    elif "candidate-commit" in args and os.environ.get("KILL_COMMIT") == "1":
        os.kill(os.getppid(), 9)
    elif "up" in args:''',
    )
    docker.write_text(body)
    result = run_deploy(deployment, CONFIG_SYNC='auto', SYNC_OPERATION='a' * 32, KILL_COMMIT='1')
    assert result.returncode == -9
    assert (root / 'current').readlink() == Path('releases') / NEW
    assert (root / '.deploy' / f'{NEW}.transaction.json').exists()
    result = run_deploy(deployment, action='recover', CONFIG_SYNC='auto', SYNC_OPERATION='a' * 32)
    assert result.returncode == 1, result.stdout + result.stderr
    assert (root / 'current').readlink() == Path('releases') / OLD
    assert (root / '.env').read_text() == 'ONEBOT_ACCESS_TOKEN=old\n'
    assert not inbox.exists()


@pytest.mark.parametrize("failure", ["", "new", "migration"])
def test_storage_migration_precedes_start_and_reverses_before_old_release(deployment, failure):
    root, _, _ = deployment
    _add_config_initializer(deployment)
    (root / "data").mkdir()
    with sqlite3.connect(root / "data/niuniu.db") as connection:
        connection.executescript(
            "CREATE TABLE players(uid TEXT PRIMARY KEY,score INTEGER);"
            "INSERT INTO players VALUES('player',99);"
            "CREATE TABLE niuniu_group_text(group_id TEXT PRIMARY KEY,text_mode TEXT);"
            "INSERT INTO niuniu_group_text VALUES('12345','safe');"
        )
    if failure == "migration":
        (root / "data/scheduled_messages.json").write_text("invalid JSON")
    result = run_deploy(deployment, MIGRATE_STORAGE="1", FAIL_UP=failure)
    calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
    migration = next(i for i, call in enumerate(calls) if "migrate-storage" in call)
    old_compose = str(root / "releases" / OLD / "prod/docker-compose.yml")
    old_stop = next(i for i, call in enumerate(calls)
                    if "stop" in call and old_compose in call)
    assert old_stop < migration
    if not failure:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (root / "config/managed/config.db").exists()
        start = next(i for i, call in enumerate(calls) if "up" in call)
        assert migration < start
        assert (root / "current").readlink() == Path("releases") / NEW
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert not (root / "config/managed/config.db").exists()
        assert (root / "current").readlink() == Path("releases") / OLD
        if failure == "new":
            reverse = next(i for i, call in enumerate(calls) if "--rollback" in call)
            restart = next(i for i, call in enumerate(calls)
                           if "up" in call and old_compose in call)
            assert migration < reverse < restart
    with sqlite3.connect(root / "data/niuniu.db") as connection:
        assert connection.execute("SELECT score FROM players").fetchone()[0] == 99
        if failure:
            assert connection.execute("SELECT text_mode FROM niuniu_group_text").fetchone() == (
                "safe",
            )
