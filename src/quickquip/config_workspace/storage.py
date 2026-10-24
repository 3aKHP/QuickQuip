"""Private workspace state, byte leases and recoverable multi-file writes."""

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path

from filelock import FileLock

from quickquip.config_sync.bundle import digest, validate_bundle
from quickquip.config_sync.state import identifier
from quickquip.config_workspace.layout import read_file, safe_path, scan
from quickquip.llm.config_durability import durable_write, ensure_directory, sync_directory
from quickquip.llm.config_errors import ConfigError

STATE_FORMAT = 1
MAX_STATE_BYTES = 256 * 1024 * 1024


def private_directory(path):
    ensure_directory(path)
    path.chmod(0o700)


def write_json(path, value):
    private_directory(path.parent)
    durable_write(path, (json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n").encode())
    path.chmod(0o600)


def file_map(files):
    return {name: base64.b64encode(body).decode("ascii") for name, body in files.items()}


def file_bytes(files):
    try:
        return {name: base64.b64decode(body, validate=True) for name, body in files.items()}
    except (TypeError, ValueError):
        raise ConfigError("invalid_workspace", "Invalid workspace recovery data") from None


class Storage:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        for path in (self.directory, *self.directory.parents):
            if path.is_symlink():
                raise ConfigError("invalid_workspace", "Workspace directory is redirected")
        self.directory = self.directory.resolve()
        self.private = self.directory / ".quickquip"
        if self.private.is_symlink():
            raise ConfigError("invalid_workspace", "Workspace state directory is redirected")

    def read(self, name, default=None):
        path = safe_path(self.private, name)
        if not path.exists():
            return default
        try:
            body = read_file(self.private, name, MAX_STATE_BYTES)
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise ConfigError("invalid_workspace", "Workspace state is unreadable", name) from None

    def write(self, name, value):
        path = safe_path(self.private, name)
        write_json(path, value)

    def state(self):
        state = self.read("state.json")
        if not isinstance(state, dict) or state.get("format") != STATE_FORMAT:
            raise ConfigError("invalid_workspace", "Workspace state is missing or unsupported")
        if state.get("base_hash") != digest(state.get("base")):
            raise ConfigError("invalid_workspace", "Workspace baseline digest differs")
        validate_bundle(state["base"])
        if not isinstance(state.get("source"), str) or not isinstance(state.get("version"), dict):
            raise ConfigError("invalid_workspace", "Workspace source metadata is invalid")
        return state

    @contextmanager
    def lock(self):
        if not self.private.is_dir():
            raise ConfigError("invalid_workspace", "Workspace is not initialized")
        path = safe_path(self.private, "write.lock")
        with FileLock(str(path), timeout=10):
            if os.name != "nt":
                path.chmod(0o600)
            yield

    def active(self):
        value = self.read("active.json")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ConfigError("invalid_workspace", "Invalid active workspace operation")
        return identifier(value.get("operation"))

    def require_idle(self):
        active = self.active()
        if active:
            raise ConfigError(
                "recovery_required",
                "Resume or recover the active workspace operation",
                details={"operation": active},
            )

    def operation(self, operation):
        value = self.read(f"operations/{identifier(operation)}.json")
        if value is None:
            raise ConfigError("not_found", "Workspace operation not found")
        if value.get("id") != operation:
            raise ConfigError("invalid_workspace", "Workspace operation identity differs")
        return value

    def save(self, record):
        self.write(f"operations/{identifier(record['id'])}.json", record)

    def begin(self, record):
        self.require_idle()
        self.save(record)
        self.write("active.json", {"operation": record["id"]})

    def finish(self, record, phase):
        record["phase"] = phase
        self.save(record)
        active = self.active()
        if active and active != record["id"]:
            raise ConfigError("operation_conflict", "A different workspace operation is active")
        if active:
            (self.private / "active.json").unlink()
            sync_directory(self.private)

    def check_files(self, record):
        before, target = file_bytes(record["before_files"]), file_bytes(record["target_files"])
        current = scan(self.directory)
        for name in current.keys() | before.keys() | target.keys():
            if current.get(name) not in (before.get(name), target.get(name)):
                raise ConfigError(
                    "revision_conflict",
                    "External workspace edit prevents recovery",
                    name,
                    {"operation": record["id"]},
                )
        state = self.read("state.json")
        if state not in (record["before_state"], record["target_state"]):
            raise ConfigError(
                "revision_conflict", "Workspace baseline changed during the operation"
            )
        return current

    def install(self, record, *, restore=False):
        current = self.check_files(record)
        target = file_bytes(record["before_files"] if restore else record["target_files"])
        # The manifest switches last. The active journal fences normal readers meanwhile.
        for name in sorted(target, key=lambda name: (name == "workspace.toml", name)):
            if current.get(name) == target[name]:
                continue
            path = safe_path(self.directory, name)
            observed = path.read_bytes() if path.exists() else None
            if observed != current.get(name):
                raise ConfigError(
                    "revision_conflict", "Workspace file changed before writing", name
                )
            private_directory(path.parent)
            durable_write(path, target[name])
            path.chmod(0o600)
        for name in sorted(current.keys() - target.keys()):
            path = safe_path(self.directory, name)
            if path.read_bytes() != current[name]:
                raise ConfigError(
                    "revision_conflict", "Workspace file changed before deletion", name
                )
            path.unlink()
            sync_directory(path.parent)
        if self.check_files(record) != target:
            raise ConfigError("revision_conflict", "Workspace changed before confirmation")
        self.write("state.json", record["before_state"] if restore else record["target_state"])


def baseline(source: Path, captured: dict) -> dict:
    return {
        "format": STATE_FORMAT,
        "source": str(source.resolve()),
        "base": captured["bundle"],
        "base_hash": digest(captured["bundle"]),
        "version": captured["version"],
    }
