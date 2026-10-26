"""Lifetime leases shared by service entrypoints and offline configuration writers."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess

from quickquip.configuration.errors import ConfigError
from quickquip.llm.config_durability import durable_write


class Lease:
    def __init__(self, path, *, create=False):
        self.path, self.create, self.stream = Path(path), create, None

    def acquire(self):
        if self.create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | (os.O_CREAT if self.create else 0)
        descriptor = os.open(self.path, flags, 0o600)
        self.stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    if not self.create:
                        raise OSError("service lease is not initialized")
                    self.stream.write(b"0")
                    self.stream.seek(0)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.stream.close()
            self.stream = None
            raise
        return self

    def close(self):
        if self.stream is not None:
            if os.name == "nt":
                import msvcrt

                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()
            self.stream = None


class StoppedService:
    """Evidence that the caller currently excludes this project's service startup."""

    def __init__(self, root, role, lease):
        self.root, self.role, self.lease = Path(root).resolve(), role, lease

    def verify(self, root, role):
        if (
            self.root != Path(root).resolve()
            or self.role != role
            or self.lease.path.resolve() != (directory(root) / f"{role}.lock").resolve()
            or self.lease.stream is None
            or self.lease.stream.closed
        ):
            raise ConfigError("services_running", "A stopped service lease is required")


@contextmanager
def stopped_service(root, role):
    """Acquire a real lifetime lock; configuration values cannot assert stopped state."""
    if role not in ("bot", "web"):
        raise ValueError("Unknown application service")
    lease = Lease(directory(root) / f"{role}.lock", create=True)
    try:
        lease.acquire()
    except OSError as exc:
        raise ConfigError("services_running", "Stop the application service first", role) from exc
    try:
        record = directory(root) / f"{role}.json"
        if record.exists():
            try:
                metadata = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ConfigError("services_unknown", "Service ownership record is unreadable")
            if not isinstance(metadata, dict) or metadata.get("system") != os.name:
                raise ConfigError(
                    "services_unknown", "Acquire the service lease in its own operating system"
                )
        yield StoppedService(root, role, lease)
    finally:
        lease.close()


def directory(root):
    return Path(root) / "data/qqconf/services"


def require_ready(root):
    if (Path(root) / "data/qqconf/active.json").exists():
        raise ConfigError(
            "recovery_required", "Run qqconf pack to recover interrupted configuration"
        )


@contextmanager
def service_guard(root, role):
    path = directory(root)
    lease = Lease(path / f"{role}.lock", create=True)
    try:
        lease.acquire()
    except OSError as exc:
        raise ConfigError(
            "configuration_busy", "Service or configuration writer holds its lease"
        ) from exc
    try:
        require_ready(root)
        durable_write(
            path / f"{role}.json",
            json.dumps(
                {
                    "format": 1,
                    "system": os.name,
                    "container": os.getenv("QUICKQUIP_MANAGED_CONTAINER") == "1",
                }
            ).encode(),
        )
        yield
    finally:
        lease.close()


def _containers(root):
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        for line in result.stdout.splitlines():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Invalid container status")
            labels = dict(
                part.partition("=")[::2]
                for part in item.get("Labels", "").split(",")
                if "=" in part
            )
            working = (
                labels.get("com.docker.compose.project.working_dir", "")
                .replace("\\", "/")
                .casefold()
                .rstrip("/")
            )
            project = str(Path(root).resolve()).replace("\\", "/").casefold().rstrip("/")
            service = labels.get("com.docker.compose.service")
            if (
                working in (project, project + "/prod")
                and service in ("quickquip", "web-admin")
                and item.get("State") not in ("exited", "dead", "created")
            ):
                return "running"
        return "stopped"
    except (OSError, ValueError, subprocess.SubprocessError):
        return "unknown"


@contextmanager
def offline(root):
    """Return status while retaining both leases whenever direct writes are possible."""
    leases, status, records = [], "stopped", []
    try:
        for role in ("bot", "web"):
            path = directory(root)
            try:
                record = json.loads((path / f"{role}.json").read_text())
                if not isinstance(record, dict) or record.get("format") != 1:
                    raise ValueError
                records.append(record)
            except (OSError, ValueError):
                status = "unknown"
                break
            lease = Lease(path / f"{role}.lock")
            try:
                lease.acquire()
            except FileNotFoundError:
                status = "unknown"
                break
            except OSError:
                status = "running"
                break
            leases.append(lease)
        foreign = [r for r in records if r.get("system") != os.name]
        if status == "stopped" and foreign:
            status = (
                _containers(root) if all(r.get("container") is True for r in foreign) else "unknown"
            )
        yield status
    finally:
        for lease in reversed(leases):
            lease.close()
