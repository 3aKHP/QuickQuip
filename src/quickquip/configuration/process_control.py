"""Project-local control of native service supervisors through private files."""

from contextlib import contextmanager
import json
from pathlib import Path
import time
import uuid

from filelock import FileLock

from quickquip.configuration.activity import Lease, directory
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.files import write_json


def control_path(root, role, suffix):
    if role not in ("bot", "web"):
        raise ValueError("Unknown application service")
    return directory(root) / f"{role}.{suffix}"


@contextmanager
def _open_control(path):
    with FileLock(str(path) + ".io.lock", timeout=5):
        with Path(path).open(encoding="utf-8") as stream:
            yield stream


def write_control(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".io.lock", timeout=5):
        deadline = time.monotonic() + 1
        while True:
            try:
                write_json(path, value)
                return
            except PermissionError as exc:
                # Windows can briefly deny replacement while a metadata reader closes.
                if getattr(exc, "winerror", None) not in (5, 32) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)


def read_control(path):
    if not Path(path).parent.exists():
        return None
    try:
        with _open_control(path) as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ConfigError("service_control_unavailable", "Service control record is unreadable")
    if not isinstance(value, dict):
        raise ConfigError("service_control_unavailable", "Service control record is invalid")
    return value


def held(path):
    lease = Lease(path)
    try:
        lease.acquire()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    else:
        lease.close()
        return False


def supervisor_running(root, role):
    return held(control_path(root, role, "supervisor.lock"))


def status(root, role):
    managed = supervisor_running(root, role)
    record = read_control(control_path(root, role, "supervisor.json"))
    if record is not None and record.get("root") != str(Path(root).resolve()):
        raise ConfigError("service_control_unavailable", "Service belongs to another project")
    if record is not None and (
        record.get("format") != 1 or record.get("role") != role
        or not isinstance(record.get("id"), str)
        or record.get("state") not in ("starting", "running", "paused", "stopped", "failed")
    ):
        raise ConfigError("service_control_unavailable", "Service control record is invalid")
    running = held(directory(root) / f"{role}.lock") or (
        managed and record is not None and record.get("state") in ("starting", "running")
    )
    return {"running": running, "managed": managed, "record": record}


def request(root, role, action, *, timeout=45):
    if action not in ("pause", "resume", "stop"):
        raise ValueError("Unknown service control action")
    path = control_path(root, role, "request.lock")
    if not path.parent.exists():
        raise ConfigError("service_control_unavailable", "Start the service through its entrypoint")
    with FileLock(str(path), timeout=timeout):
        current = status(root, role)
        if not current["managed"] or current["record"] is None:
            raise ConfigError(
                "service_control_unavailable", "Restart the service through its updated entrypoint"
            )
        identifier = uuid.uuid4().hex
        write_control(control_path(root, role, "request.json"), {
            "id": identifier, "supervisor": current["record"]["id"], "action": action,
        })
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = read_control(control_path(root, role, "response.json"))
            if response is not None and response.get("id") == identifier:
                if response.get("error"):
                    raise ConfigError("service_control_failed", response["error"], role)
                return response
            if not supervisor_running(root, role):
                raise ConfigError("service_control_failed", "Service controller exited", role)
            time.sleep(0.05)
    raise ConfigError("service_control_timeout", "Service did not acknowledge control", role)
