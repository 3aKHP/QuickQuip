"""Project-local control of native service supervisors through private files."""

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


def read_control(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
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
        write_json(control_path(root, role, "request.json"), {
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
