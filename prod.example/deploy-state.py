"""Filesystem transactions and flat-layout snapshots for the deployment runner."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile


SHARED_FILES = {
    ".env": 0o600,
    "prod/sendkey.env": 0o600,
    "prod/check_bot.sh": 0o700,
    "prod/cron_check_bot.sh": 0o700,
    "prod/host_metrics_collector.py": 0o700,
    "data/fonts/NotoSansSC-Regular.ttf": 0o644,
    "data/tieba/storage_state.json": 0o600,
}
SERVICES = ("llbot", "quickquip", "web-admin")
# Deployment-root subdirectories whose bind-mounted content is shared state;
# migration keeps their live source path. Prefix match: a mount of a data/ or
# skills/ subdirectory is still shared state, not release-private content.
ROOT_SHARED_SUBDIRS = ("data", "skills")
DEFAULTED_VARIABLE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:-([^}]*)\}")


def resolve_defaulted_variables(source: str) -> str:
    """Substitute ${VAR:-default} placeholders in a compose path with defaults."""
    return DEFAULTED_VARIABLE.sub(lambda match: match.group(1), source)


def atomic_write(
    path: Path, data: bytes, mode: int, new_owner: tuple[int, int] | None = None
) -> None:
    missing_parents = []
    parent = path.parent
    while not parent.exists():
        missing_parents.append(parent)
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in reversed(missing_parents):
        if new_owner is not None:
            os.chmod(parent, 0o755)
        if new_owner is not None and os.geteuid() == 0:
            os.chown(parent, *new_owner)
        _sync_directory(parent.parent)
    owner = path.stat() if path.exists() else None
    fd, name = tempfile.mkstemp(prefix=".deploy-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, mode)
        if owner is not None and os.geteuid() == 0:
            os.chown(name, owner.st_uid, owner.st_gid)
        elif new_owner is not None and os.geteuid() == 0:
            os.chown(name, *new_owner)
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_tree(root: Path) -> None:
    """Persist uploaded runners and candidate bind mounts before recording activation."""
    validate_tree(root)
    directories = [root]
    for path in root.rglob("*"):
        if path.is_dir():
            directories.append(path)
        else:
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        _sync_directory(path)
    _sync_directory(root.parent)


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"path outside deployment root: {relative}")
    if path.is_symlink():
        raise ValueError(f"symlink not permitted: {relative}")
    return path


def extract(archive: Path, destination: Path) -> None:
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            checked_path(destination, member.name)
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsupported archive entry: {member.name}")
        bundle.extractall(destination, members=members, filter="data")


def validate_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"unsupported release entry: {path.relative_to(root)}")


def snapshot_shared(root: Path, incoming: Path, backup: Path) -> None:
    backup.mkdir(mode=0o700)
    _sync_directory(backup.parent)
    names = [name for name in SHARED_FILES if (incoming / "shared" / name).is_file()]
    llbot = root / "prod/llbot-data"
    names += [str(path.relative_to(root)) for path in (
        [llbot / "default_config.json"] + sorted((llbot / "data").glob("config_*.json"))
    ) if path.is_file()]
    records = []
    for name in names:
        path = checked_path(root, name)
        parent = path.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            raise PermissionError(f"deployment user cannot replace {name}")
        present = path.exists()
        mode = stat.S_IMODE(path.stat().st_mode) if present else SHARED_FILES.get(name, 0o600)
        if present:
            atomic_write(backup / name, path.read_bytes(), 0o600)
        records.append({"name": name, "present": present, "mode": mode})
    atomic_write(backup / "index.json", json.dumps(records).encode(), 0o600)


def apply_shared(root: Path, incoming: Path, backup: Path) -> None:
    records = json.loads((backup / "index.json").read_text())
    compose = json.loads((incoming / "candidate-compose.json").read_text())
    token = compose["services"]["quickquip"].get("environment", {}).get("ONEBOT_ACCESS_TOKEN", "")
    for record in records:
        name = record["name"]
        path = checked_path(root, name)
        source = incoming / "shared" / name
        if name in SHARED_FILES:
            data = source.read_bytes()
            if name.endswith((".env", ".sh")) or name == ".env":
                data = data.replace(b"\r\n", b"\n")
            deploy_owner = (int(os.environ.get("SUDO_UID", os.getuid())),
                            int(os.environ.get("SUDO_GID", os.getgid())))
            atomic_write(path, data, SHARED_FILES[name], deploy_owner)
        else:
            data = json.loads((backup / name).read_text(encoding="utf-8"))
            connections = data.setdefault("ob11", {}).setdefault("connect", [])
            while len(connections) <= 1:
                connections.append({})
            connections[1]["url"] = "ws://quickquip:8080/onebot/v11/ws/"
            connections[1]["token"] = token or ""
            payload = (json.dumps(data, ensure_ascii=False, indent=4) + "\n").encode()
            atomic_write(path, payload, record["mode"])


def restore_shared(root: Path, backup: Path) -> None:
    for record in json.loads((backup / "index.json").read_text()):
        path = checked_path(root, record["name"])
        if record["present"]:
            atomic_write(path, (backup / record["name"]).read_bytes(), record["mode"])
        else:
            path.unlink(missing_ok=True)


def capture_baseline(root: Path, baseline: Path) -> None:
    """Capture server files and running image IDs without moving live bind sources."""
    command = [
        "docker", "compose", "--env-file", str(root / ".env"),
        "-f", str(root / "prod/docker-compose.yml"),
    ]
    # No interpolation also preserves env_file references on Compose 2.27+.
    raw = subprocess.check_output(command + ["config", "--no-interpolate", "--format", "json"])
    config = json.loads(raw)
    if set(config["services"]) != set(SERVICES):
        raise ValueError(
            "migration requires exactly llbot, quickquip and web-admin; "
            "review custom services first"
        )
    # Keep private runtime files out of the snapshot; copy only mounted app assets.
    # skills/ is shared root state beside data/; the volume rewrite below keeps
    # its deployment-root source instead of a baseline copy.
    baseline.mkdir(mode=0o700)
    for name in (
        "src", "config", "llm_about", "frontend/dist", "bot.py", "web_api.py",
        "pyproject.toml", "requirements.txt", ".dockerignore",
    ):
        source = checked_path(root, name)
        if source.is_dir():
            validate_tree(source)
            shutil.copytree(source, baseline / name, dirs_exist_ok=True)
        elif source.is_file():
            atomic_write(baseline / name, source.read_bytes(), 0o644)
    for service, spec in config["services"].items():
        container = spec.get("container_name")
        if not container:
            raise ValueError(f"migration needs container_name for {service}")
        image = subprocess.check_output(
            ["docker", "inspect", "--format", "{{.Image}}", container], text=True
        ).strip()
        tag = f"quickquip-{service}:{baseline.name}"
        subprocess.run(["docker", "tag", image, tag], check=True)
        spec["image"] = tag
        spec.pop("build", None)
        spec.pop("pull_policy", None)
        # Normalize the root env reference without expanding its credentials.
        if service != "llbot":
            spec["env_file"] = [str(root / ".env")]
        for volume in spec.get("volumes", []):
            if volume.get("type") != "bind":
                continue
            source = Path(resolve_defaulted_variables(volume["source"]))
            if not source.is_absolute():
                source = (root / "prod" / source).resolve()
            if not source.is_relative_to(root):
                raise ValueError(f"external bind mount requires manual migration: {source}")
            relative = source.relative_to(root)
            if relative.parts[0] in ROOT_SHARED_SUBDIRS or str(relative) in (
                "prod/llbot-qq", "prod/llbot-data", ".env",
            ):
                volume["source"] = str(source)
            elif (baseline / relative).exists():
                volume["source"] = str(baseline / relative)
            else:
                raise ValueError(f"unsupported bind mount: {relative}")
    atomic_write(baseline / "prod/docker-compose.yml", json.dumps(config).encode(), 0o600)
    subprocess.run(
        [
            "docker", "compose", "--env-file", str(root / ".env"),
            "-f", str(baseline / "prod/docker-compose.yml"), "config", "--quiet",
        ],
        check=True,
    )


def skill_catalog_layout(root: Path) -> None:
    """Classify resolved Compose bind sources without emitting configuration."""
    config = json.load(sys.stdin)
    shared = (root / "skills").resolve()
    for spec in config["services"].values():
        for volume in spec.get("volumes", []):
            if volume.get("type") != "bind":
                continue
            source = Path(volume["source"])
            if not source.is_absolute():
                raise ValueError("resolved Compose bind source must be absolute")
            if source.resolve().is_relative_to(shared):
                print("shared")
                return
    print("local")


def main() -> None:
    action, *args = sys.argv[1:]
    if action == "transaction":
        root, release, *values = args
        names = ("previous", "previous_previous", "original", "changed", "activated",
                 "stopped", "sync_operation", "shared_sudo")
        if len(values) != len(names):
            raise ValueError("invalid deployment journal")
        payload = dict(zip(names, values))
        for name in names[:3]:
            if payload[name] and not re.fullmatch(
                r"[0-9]{8}-[0-9]{6}(?:-[a-f0-9]{12})?(?:-baseline)?", payload[name]
            ):
                raise ValueError("invalid journal release")
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release):
            raise ValueError("invalid journal id")
        if any(payload[name] not in ("0", "1") for name in (*names[3:6], "shared_sudo")):
            raise ValueError("invalid transaction state")
        if not re.fullmatch(r"[a-f0-9]{32}", payload["sync_operation"]):
            raise ValueError("invalid synchronization id")
        atomic_write(Path(root) / ".deploy" / f"{release}.transaction.json",
                     json.dumps(payload).encode(), 0o600)
        return
    if action == "read-transaction":
        root, release = args
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release):
            raise ValueError("invalid journal id")
        payload = json.loads((Path(root) / ".deploy" / f"{release}.transaction.json").read_text())
        for name in ("previous", "previous_previous", "original", "changed", "activated",
                     "stopped", "sync_operation", "shared_sudo"):
            print(payload[name] or "_")
        return
    paths = [Path(arg).absolute() for arg in args]
    actions = {
        "extract": extract,
        "validate": validate_tree,
        "snapshot": snapshot_shared,
        "apply": apply_shared,
        "restore": restore_shared,
        "baseline": capture_baseline,
        "skill-layout": skill_catalog_layout,
        "durable": durable_tree,
    }
    actions[action](*paths)


if __name__ == "__main__":
    try:
        main()
    except PermissionError as exc:
        print(
            f"deployment filesystem permission denied: {exc.filename or 'shared files'}",
            file=sys.stderr,
        )
        raise SystemExit(3) from None
