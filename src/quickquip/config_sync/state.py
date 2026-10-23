"""Private durable identities, snapshots, receipts and operation journals."""

import json
from pathlib import Path
import re
import uuid

from quickquip.llm.config_durability import durable_write, sync_directory
from quickquip.llm.config_errors import ConfigError
from quickquip.config_sync.bundle import digest


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ConfigError("invalid_field", "Expected a synchronization UUID")
    return value


class State:
    def __init__(self, data: Path):
        self.directory = data / "config-sync"

    def read(self, name, default=None):
        path = self.directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write(self, name, value):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        durable_write(
            self.directory / name, (json.dumps(value, ensure_ascii=False) + "\n").encode()
        )

    def identity(self, *, create=False):
        value = self.read("identity.json")
        if value is None and create:
            value = {"id": uuid.uuid4().hex, "protocol": 1}
            self.write("identity.json", value)
        return value

    def operation(self, operation):
        value = self.read(f"operations/{identifier(operation)}.json")
        if value is None:
            raise ConfigError("not_found", "Synchronization operation not found")
        return value

    def save_operation(self, value):
        self.write(f"operations/{identifier(value['id'])}.json", value)

    def baseline(self, peer):
        reference = self.read(f"peers/{identifier(peer)}.json")
        if reference is None:
            return None
        return self.read(f"snapshots/{reference['hash']}.json")

    def acknowledge(self, peer, bundle, operation):
        content_hash = digest(bundle)
        self.write(f"snapshots/{content_hash}.json", bundle)
        self.write(
            f"peers/{identifier(peer)}.json",
            {
                "hash": content_hash,
                "operation": identifier(operation),
                "scope": 1,
            },
        )

    def clear_maintenance(self, token):
        marker = self.read("maintenance.json")
        if marker and marker["token"] == token:
            (self.directory / "maintenance.json").unlink()
            sync_directory(self.directory)
