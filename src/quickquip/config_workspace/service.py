"""Local workspace orchestration, independent of server synchronization endpoints."""

import os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile

from quickquip.common.config_writes import configuration_write, maintenance_owner
from quickquip.configuration import activity
from quickquip.configuration.errors import ConfigError
from quickquip.config_workspace import content, database, planning, transactions
from quickquip.config_workspace.inventory import entry, safe_path
from quickquip.config_workspace.layout import read_tree, workspace_files
from quickquip.config_workspace.merge import same
from quickquip.config_workspace.storage import FORMAT, Storage, read_json


def validate_location(directory, root):
    if root.is_relative_to(directory):
        raise ConfigError("invalid_workspace", "Workspace must not contain the source project")
    if any(
        directory.is_relative_to(root / name)
        for name in (
            "config",
            "data",
            "llm_about",
            "prod",
            "docker",
            "skills",
            ".config-staging",
            ".config-staging.new",
            ".config-staging.previous",
        )
    ):
        raise ConfigError(
            "invalid_workspace", "Workspace must be separate from active configuration"
        )


class Workspace:
    def __init__(self, directory=None, root=None):
        from quickquip.common.env import PROJECT_ROOT

        self.root = Path(root or PROJECT_ROOT).resolve()
        safe_path(self.root, "data/qqconf/active.json")
        for name in (
            "data/qqconf",
            ".config-staging",
            ".config-staging.new",
            ".config-staging.previous",
        ):
            if (self.root / name).is_symlink():
                raise ConfigError(
                    "invalid_workspace", "Configuration state path is redirected", name
                )
        self.storage = Storage(directory or self.root / ".config-workspace")
        validate_location(self.storage.directory, self.root)

    def _state(self):
        state = self.storage.state()
        if state["source"] != str(self.root):
            raise ConfigError("endpoint_changed", "Workspace belongs to a different project root")
        return state

    def _pending(self):
        return self.storage.pending() or any(
            (self.root / "data/qqconf" / name).exists() for name in ("active.json", "staging.json")
        )

    @contextmanager
    def _write(self):
        with self.storage.lock():
            with activity.offline(self.root) as status:
                marker = self.root / "data/qqconf/active.json"
                if marker.exists():
                    if status != "stopped":
                        raise ConfigError(
                            "recovery_required", "Stop services before recovering configuration"
                        )
                    with (
                        maintenance_owner("qqconf:" + str(self.storage.directory)),
                        configuration_write(self.root / "data"),
                    ):
                        transactions.recover_source(self.root, self.storage)
                transactions.recover_candidate(self.root, self.storage)
                self.storage.recover()
                yield status

    def _inputs(self, prefer):
        state = self._state()
        tree = read_tree(self.storage.directory)
        workspace = tree.snapshot
        source = content.read(self.root)
        target, conflicts = planning.merge(state["base"], workspace, source, prefer)
        # Always validate the complete merged result; conflict inspection is still readable.
        if not conflicts or prefer:
            target = content.validate(target)
        return state, tree, workspace, source, target, conflicts

    def refresh(self, *, prefer=None, show_secrets=False):
        if self._pending():
            return {
                "action": "refresh",
                "recovery_required": True,
                "message": "Run qqconf pack to recover the unfinished write",
            }
        state, tree, workspace, source, target, conflicts = self._inputs(prefer)
        with activity.offline(self.root) as status:
            destination = "source" if status == "stopped" else "candidate"
        result = planning.preview(
            state["base"], workspace, source, target, conflicts, show_secrets=show_secrets
        )
        candidate = self.root / ".config-staging/candidate.json"
        result.update(
            action="refresh",
            services=status,
            destination=destination,
            candidate_present=candidate.exists(),
        )
        if candidate.exists():
            previous = read_json(candidate)
            staged = content.read(self.root / ".config-staging")
            result.update(
                candidate_pending=not same(staged, source),
                candidate_stale=not same(previous["base"], source),
                candidate_matches_workspace=same(staged, target),
            )
        return result

    def unpack(self, *, prefer=None):
        def require_source_ready():
            if any(
                (self.root / "data/qqconf" / name).exists()
                for name in ("active.json", "staging.json")
            ):
                raise ConfigError("recovery_required", "Run qqconf pack before unpacking")

        require_source_ready()
        directory = self.storage.directory
        if not (self.storage.private / "state.json").exists():
            if (
                directory.exists()
                and any(directory.iterdir())
                and not self.storage.private.is_dir()
            ):
                raise ConfigError(
                    "workspace_exists", "Unpack requires an empty or qqconf workspace"
                )
            with self.storage.lock():
                self.storage.recover()
                if any(
                    path.is_file() and not path.is_relative_to(self.storage.private)
                    for path in directory.rglob("*")
                ):
                    raise ConfigError(
                        "workspace_exists", "Unpack requires an empty or qqconf workspace"
                    )
                snapshot = content.read(self.root)
                require_source_ready()
                state = {"format": FORMAT, "source": str(self.root), "base": snapshot}
                if not same(content.read(self.root), snapshot):
                    raise ConfigError("revision_conflict", "Source changed; run unpack again")
                require_source_ready()
                self.storage.save({}, workspace_files(snapshot), state)
            return {"action": "unpack", "phase": "created", "workspace": str(directory)}
        if any(
            (self.root / "data/qqconf" / name).exists() for name in ("active.json", "staging.json")
        ):
            raise ConfigError("recovery_required", "Run qqconf pack before unpacking")
        with self.storage.lock():
            self.storage.recover()
            state, tree, workspace, source, target, conflicts = self._inputs(prefer)
            self._require_resolved(conflicts, prefer)
            before = self._work_files(tree, workspace)
            after = self._render(target, tree, before)
            state = {**state, "base": source}
            if content.read(self.root) != source:
                raise ConfigError("revision_conflict", "Source changed; run unpack again")
            require_source_ready()
            self.storage.save(before, after, state)
        return {"action": "unpack", "phase": "updated", "workspace": str(directory)}

    def _work_files(self, tree, workspace):
        return {
            **{
                name: entry(
                    raw,
                    (self.storage.directory / name).stat().st_mode & 0o777
                    if os.name != "nt"
                    else 0o600,
                )
                for name, raw in tree.files.items()
            },
            **workspace["files"],
        }

    @staticmethod
    def _render(target, tree, before):
        after = workspace_files(target, tree.files)
        for name in after.keys() & before.keys():
            if name.startswith("db/"):
                after[name]["mode"] = before[name]["mode"]
        return after

    @staticmethod
    def _require_resolved(conflicts, prefer):
        if conflicts and not prefer:
            raise ConfigError(
                "configuration_conflict",
                "Edit the conflicting fields and retry",
                details={"conflicts": conflicts},
            )

    def pack(self, *, prefer=None):
        with self._write() as status:
            state, tree, workspace, source, target, conflicts = self._inputs(prefer)
            self._require_resolved(conflicts, prefer)
            before = self._work_files(tree, workspace)
            after = self._render(target, tree, before)
            destination = "source" if status == "stopped" else "candidate"
            state = {**state, "base": target if destination == "source" else source}
            candidate = self.root / ".config-staging"
            if destination == "candidate" and (candidate.exists() or not same(target, source)):
                state["packed"] = deepcopy(target)
            else:
                state.pop("packed", None)
            unchanged = (
                same(target, source)
                if destination == "source"
                else (same(target, source) and not candidate.exists())
            )
            if destination == "candidate" and candidate.exists():
                manifest = read_json(candidate / "candidate.json")
                unchanged = (
                    manifest.get("source_root") == str(self.root)
                    and same(content.read(candidate), target)
                    and same(manifest.get("base"), source)
                )
            if unchanged:
                self.storage.save(before, after, state)
                return {
                    "action": "pack",
                    "phase": "unchanged",
                    "destination": destination,
                    "services": status,
                }
            with configuration_write(self.root / "data"):
                if not same(content.read(self.root), source):
                    raise ConfigError("revision_conflict", "Source changed; run pack again")
                # Re-read working bytes to reject an editor racing the snapshot above.
                current = read_tree(self.storage.directory)
                if current.files != tree.files or current.snapshot["files"] != workspace["files"]:
                    raise ConfigError("revision_conflict", "Workspace changed; run pack again")
                with tempfile.TemporaryDirectory(prefix="qqconf-database-") as directory:
                    prepared = Path(directory) / "config.db"
                    database.prepare(self.root / database.DB_NAME, prepared, target)
                    commit = (
                        transactions.commit_source
                        if destination == "source"
                        else transactions.commit_candidate
                    )
                    commit(self.root, self.storage, source, target, prepared, before, after, state)
        return {
            "action": "pack",
            "phase": "written",
            "destination": destination,
            "services": status,
            "activation": "pending_deployment",
        }
