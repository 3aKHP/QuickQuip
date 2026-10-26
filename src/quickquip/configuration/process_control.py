"""Project-local control of native service supervisors through private files."""

import json
import os
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


def _open_control(path):
    if os.name != "nt":
        return Path(path).open(encoding="utf-8")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    # Share read/write/delete so polling never blocks the writer's atomic replacement.
    handle = create(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_NOINHERIT)
    except BaseException:
        close = kernel.CloseHandle
        close.argtypes, close.restype = (wintypes.HANDLE,), wintypes.BOOL
        close(handle)
        raise
    return os.fdopen(descriptor, encoding="utf-8")


def read_control(path):
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
