"""One-way field merging and acknowledgement of only genuinely shared values."""

from copy import deepcopy

from quickquip.configuration import comparison, text
from quickquip.configuration.inventory import body, entry
from quickquip.configuration.merge import MISSING, collection_key, keyed, same


def plan(base, source, target, *, prefer=None, overwrite=False, show_secrets=False):
    # An initial direction declares the source authoritative, including removals.
    baseline = target if base is None else base
    if overwrite or base is None:
        result, conflicts = deepcopy(source), []
    else:
        result, conflicts = comparison.merge(
            baseline,
            source,
            target,
            "workspace" if prefer == "source" else "source" if prefer == "target" else None,
        )
    preview = comparison.preview(
        baseline, source, target, result, conflicts, show_secrets=show_secrets
    )
    return {
        "target": result,
        "conflicts": conflicts,
        "source_changes": preview["workspace_changes"],
        "target_changes": preview["source_changes"],
        "write_changes": preview["write_changes"],
    }


def _ack(base, source, target, path):
    if same(source, target):
        return deepcopy(source) if source is not MISSING else MISSING
    if isinstance(source, dict) and isinstance(target, dict):
        original = base if isinstance(base, dict) else {}
        result = {}
        for key in original.keys() | source.keys() | target.keys():
            value = _ack(
                original.get(key, MISSING),
                source.get(key, MISSING),
                target.get(key, MISSING),
                f"{path}.{key}",
            )
            if value is not MISSING:
                result[key] = value
        return result
    keys = collection_key(path)
    if keys:
        maps = [keyed(value, keys) for value in (base, source, target)]
        if maps[1] is not None and maps[2] is not None:
            original = maps[0] or {}
            values = _ack(original, maps[1], maps[2], path + ".items")
            # Shared order is acknowledged independently of shared item contents.
            order = list(maps[1]) if list(maps[1]) == list(maps[2]) else list(original)
            order += [key for key in maps[1] if key not in order]
            return [values[key] for key in order if key in values]
    return deepcopy(base) if base is not MISSING else MISSING


def acknowledge(base, source, target):
    """Keep receiver-only edits pending for a later operation in the other direction."""
    base = base or {"document": {}, "scopes": {}, "text_modes": {}, "files": {}}
    result = {
        key: _ack(base[key], source[key], target[key], key)
        for key in ("document", "scopes", "text_modes")
    }
    files = {}
    for name in base["files"].keys() | source["files"].keys() | target["files"].keys():
        old, left, right = [value["files"].get(name, MISSING) for value in (base, source, target)]
        if same(left, right):
            selected = deepcopy(left) if left is not MISSING else MISSING
        elif left is not MISSING and right is not MISSING:
            original = text.parse(name, body(old)) if old is not MISSING else MISSING
            merged = _ack(
                original, text.parse(name, body(left)), text.parse(name, body(right)), name
            )
            if merged is MISSING:
                selected = MISSING
            else:
                template = body(old) if old is not MISSING else body(left)
                mode = _ack(
                    old["mode"] if old is not MISSING else MISSING,
                    left["mode"],
                    right["mode"],
                    name + ".permissions",
                )
                selected = entry(
                    text.render(name, merged, template), left["mode"] if mode is MISSING else mode
                )
        else:
            selected = deepcopy(old) if old is not MISSING else MISSING
        if selected is not MISSING:
            files[name] = selected
    result["files"] = files
    return result
