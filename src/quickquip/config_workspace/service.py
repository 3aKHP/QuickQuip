"""Workspace operations: inspect, plan and orchestrate recoverable local changes."""

import os
from pathlib import Path
import tempfile
import uuid

from quickquip.config_sync.bundle import digest
from quickquip.config_sync.endpoint import Endpoint
from quickquip.config_workspace.layout import read_tree, render_tree, safe_path
from quickquip.config_workspace.planning import preview, public_plan
from quickquip.config_workspace.storage import (
    Storage,
    baseline,
    file_map,
    private_directory,
    write_json,
)
from quickquip.config_workspace.transactions import (
    advance,
    rollback,
    summary,
)
from quickquip.llm.config_durability import durable_write, sync_directory
from quickquip.llm.config_errors import ConfigError


def validate_location(directory, root):
    if root.is_relative_to(directory):
        raise ConfigError("invalid_workspace", "Workspace must not contain the active project root")
    if any(
        directory.is_relative_to((root / name).resolve())
        for name in ("config", "data", "llm_about")
    ):
        raise ConfigError(
            "invalid_workspace", "Workspace must be outside active configuration and data"
        )


class Workspace:
    def __init__(self, directory, root):
        self.storage = Storage(directory)
        self.endpoint = Endpoint(root)
        validate_location(self.storage.directory, self.endpoint.root)

    def initialize(self):
        directory = self.storage.directory
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            raise ConfigError("workspace_exists", "Initialization requires an empty destination")
        captured = self.endpoint.capture()
        files = render_tree(captured["bundle"])
        directory.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".quickquip-workspace-", dir=directory.parent
        ) as tmp:
            staged = Path(tmp) / "tree"
            private_directory(staged)
            for name, body in files.items():
                path = safe_path(staged, name)
                private_directory(path.parent)
                durable_write(path, body)
                path.chmod(0o600)
            write_json(staged / ".quickquip/state.json", baseline(self.endpoint.root, captured))
            if self.endpoint.version() != captured["version"]:
                raise ConfigError(
                    "revision_conflict", "Source changed during workspace initialization"
                )
            if directory.exists():
                # rmdir only removes a still-empty directory and rejects racing user content.
                directory.rmdir()
            os.rename(staged, directory)
            sync_directory(directory.parent)
        return {
            "directory": str(directory),
            "baseline_hash": digest(captured["bundle"]),
            "draft_revision": captured["version"]["draft_revision"],
            "files": len(files),
        }

    def validate(self):
        with self.storage.lock():
            self.storage.require_idle()
            self.storage.state()
            tree = read_tree(self.storage.directory)
            return {"valid": True, "bundle_hash": digest(tree.bundle), "files": len(tree.files)}

    def plan(self, *, action="refresh", overwrite=False):
        with self.storage.lock():
            result, *_ = preview(self.storage, self.endpoint, action=action, overwrite=overwrite)
            return public_plan(result)

    def execute(self, action, expected_plan, *, overwrite=False):
        with self.storage.lock():
            result, state, tree, captured, target_files = preview(
                self.storage,
                self.endpoint,
                action=action,
                overwrite=overwrite,
            )
            if not expected_plan or expected_plan != result["plan_hash"]:
                raise ConfigError("revision_conflict", "Workspace plan changed; preview it again")
            if result["conflicts"]:
                raise ConfigError(
                    "configuration_conflict",
                    "Workspace and database changed the same unit",
                    details={"conflicts": result["conflicts"]},
                )
            # Guard workspace edits made while the source and candidate were validated.
            if read_tree(self.storage.directory).files != tree.files:
                raise ConfigError("revision_conflict", "Workspace changed after planning")
            target_state = baseline(self.endpoint.root, captured)
            if tree.files == target_files and state == target_state:
                return {
                    "action": action,
                    "phase": "unchanged",
                    "baseline_hash": state["base_hash"],
                    "draft_revision": captured["version"]["draft_revision"],
                }
            record = {
                "id": uuid.uuid4().hex,
                "phase": "prepared",
                "action": action,
                "source": str(self.endpoint.root),
                "workspace": str(self.storage.directory),
                "source_version": captured["version"],
                "before_state": state,
                "target_state": target_state,
                "before_files": file_map(tree.files),
                "target_files": file_map(target_files),
            }
            self.storage.begin(record)
            return advance(self.storage, self.endpoint, record)

    def status(self, operation=None):
        with self.storage.lock():
            state = self.storage.state()
            active = self.storage.active()
            result = {
                "baseline_hash": state["base_hash"],
                "source_revision": state["version"]["draft_revision"],
                "active_operation": active,
            }
            if operation or active:
                result["operation"] = summary(self.storage.operation(operation or active))
            if not active:
                tree = read_tree(self.storage.directory)
                result.update(
                    workspace_hash=digest(tree.bundle),
                    dirty=digest(tree.bundle) != state["base_hash"],
                )
            return result

    def resume(self, operation):
        with self.storage.lock():
            active = self.storage.active()
            if active and active != operation:
                raise ConfigError("operation_conflict", "Another workspace operation is active")
            record = self.storage.operation(operation)
            return advance(self.storage, self.endpoint, record)

    def recover(self, operation):
        with self.storage.lock():
            active = self.storage.active()
            if active and active != operation:
                raise ConfigError("operation_conflict", "Another workspace operation is active")
            record = self.storage.operation(operation)
            return rollback(self.storage, self.endpoint, record)


def validate_offline(directory):
    storage = Storage(directory)
    with storage.lock():
        storage.require_idle()
        storage.state()
        tree = read_tree(storage.directory)
        return {"valid": True, "bundle_hash": digest(tree.bundle), "files": len(tree.files)}
