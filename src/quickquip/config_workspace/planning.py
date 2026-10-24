"""Workspace byte leases over the existing whole-document three-way policy."""

import hashlib
from pathlib import Path

from quickquip.config_sync.bundle import digest
from quickquip.config_sync.planning import document_changes, plan, units
from quickquip.config_workspace.layout import read_tree, render_tree
from quickquip.llm.config_errors import ConfigError


def preview(storage, endpoint, *, action="pack", overwrite=False):
    if action not in ("pack", "refresh"):
        raise ConfigError("invalid_field", "Expected pack or refresh")
    storage.require_idle()
    state = storage.state()
    if Path(state["source"]).resolve() != endpoint.root:
        raise ConfigError("endpoint_changed", "Workspace belongs to a different configuration root")
    tree = read_tree(storage.directory)
    captured = endpoint.capture()
    mode = ("push" if action == "pack" else "pull") if overwrite else "auto"
    result = plan(state["base"], tree.bundle, captured["bundle"], mode=mode, overwrite=overwrite)
    token = digest(
        {
            "state": state,
            "workspace": {
                name: hashlib.sha256(body).hexdigest() for name, body in tree.files.items()
            },
            "source": str(endpoint.root),
            "version": captured["version"],
            "action": action,
            "overwrite": overwrite,
        }
    )
    result.update(
        action=action,
        overwrite=overwrite,
        plan_hash=token,
        source_revision=captured["version"]["draft_revision"],
        pending=captured["pending"],
    )
    source = tree.bundle if action == "pack" else captured["bundle"]
    target = captured["bundle"] if action == "pack" else tree.bundle
    base_units, source_units, target_units = units(state["base"]), units(source), units(target)
    result["discarded_units"] = [
        name
        for name in sorted(base_units.keys() | source_units.keys() | target_units.keys())
        if overwrite
        and digest(target_units.get(name)) != digest(base_units.get(name))
        and digest(target_units.get(name)) != digest(source_units.get(name))
    ]
    if "bundle" in result:
        target_files = render_tree(result["bundle"], tree)
        result["document_diff"] = document_changes(captured["draft"], result["bundle"]["document"])
        result["workspace_files"] = [
            {"file": name, "deleted": name not in target_files}
            for name in sorted(tree.files.keys() | target_files.keys())
            if tree.files.get(name) != target_files.get(name)
        ]
        result["assets_changed"] = captured["bundle"]["assets"] != result["bundle"]["assets"]
    else:
        target_files = None
    return result, state, tree, captured, target_files


def public_plan(result):
    return {key: value for key, value in result.items() if key != "bundle"}
