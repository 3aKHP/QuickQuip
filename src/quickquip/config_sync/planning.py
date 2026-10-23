"""Pure three-way reconciliation at document and file granularity."""

from quickquip.config_sync.bundle import FORMAT, digest, validate_bundle
from quickquip.llm.config_errors import ConfigError


def units(bundle):
    return {"document": bundle["document"], **bundle["assets"]}


def same(left, right):
    return digest(left) == digest(right)


def document_changes(before, after, path=""):
    """Keep JSON types and missing/null distinctions visible in the review output."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            location = f"{path}.{key}" if path else key
            if key not in before or key not in after:
                changes.append(
                    {
                        "field_path": location,
                        "before": before.get(key),
                        "after": after.get(key),
                        "before_present": key in before,
                        "after_present": key in after,
                    }
                )
            else:
                changes.extend(document_changes(before[key], after[key], location))
        return changes
    if same(before, after):
        return []
    return [
        {
            "field_path": path,
            "before": before,
            "after": after,
            "before_present": True,
            "after_present": True,
        }
    ]


def plan(base, local, remote, *, mode="auto", overwrite=False):
    if mode not in ("auto", "push", "pull") or (overwrite and mode == "auto"):
        raise ConfigError("invalid_field", "Overwrite requires an explicit push or pull direction")
    before, left, right = units(base), units(local), units(remote)
    merged, conflicts, changes = {}, [], []
    for key in sorted(before.keys() | left.keys() | right.keys()):
        baseline, local_value, remote_value = before.get(key), left.get(key), right.get(key)
        if mode == "auto":
            if same(local_value, remote_value):
                selected = local_value
            elif same(local_value, baseline):
                selected = remote_value
            elif same(remote_value, baseline):
                selected = local_value
            else:
                conflicts.append(key)
                continue
        else:
            source, target = (
                (local_value, remote_value) if mode == "push" else (remote_value, local_value)
            )
            if not same(source, target) and not same(target, baseline) and not overwrite:
                conflicts.append(key)
                continue
            selected = source
        if selected is not None:
            merged[key] = selected
        if not same(local_value, selected) or not same(remote_value, selected):
            changes.append(
                {
                    "unit": key,
                    "local": not same(local_value, selected),
                    "remote": not same(remote_value, selected),
                    "deleted": selected is None,
                }
            )
    result = {
        "conflicts": conflicts,
        "changes": changes,
        "local_hash": digest(local),
        "remote_hash": digest(remote),
        "document_diff": document_changes(remote["document"], local["document"]),
    }
    if not conflicts:
        result["bundle"] = validate_bundle(
            {
                "format": FORMAT,
                "document": merged.pop("document"),
                "assets": merged,
            }
        )
        result["target_hash"] = digest(result["bundle"])
    return result
