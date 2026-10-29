"""Field-level reconciliation with explicit collection identities and missing values."""

from copy import deepcopy
import math
import re

MISSING = object()


def same(left, right):
    if left is MISSING or right is MISSING:
        return left is right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and left == right == 0:
        return math.copysign(1, left) == math.copysign(1, right)
    return left == right


def collection_key(path):
    if path == "config/managed/scheduled_messages.json.jobs":
        return ("id",)
    if path == "document.providers":
        return ("id",)
    if re.fullmatch(
        r"document\.providers(?:\.items\.\('[A-Za-z0-9_.-]+',\)|\[[A-Za-z0-9_.-]+\])\.models", path
    ):
        return ("model",)
    if re.fullmatch(
        r"document\.providers(?:\.items\.\('[A-Za-z0-9_.-]+',\)|\[[A-Za-z0-9_.-]+\])\.aliases", path
    ):
        return ("alias",)
    if path == "document.pricing":
        return ("provider_id", "model")
    return None


def keyed(items, keys):
    if not isinstance(items, list) or not all(
        isinstance(item, dict) and all(key in item for key in keys) for item in items
    ):
        return None
    values = [tuple(item[key] for key in keys) for item in items]
    try:
        unique = len(set(values)) == len(values)
    except TypeError:
        return None
    if not unique:
        return None
    return dict(zip(values, items))


def reconcile(base, workspace, source, *, prefer=None, path="", conflicts=None):
    if conflicts is None:
        conflicts = []
    if same(workspace, source):
        return deepcopy(workspace) if workspace is not MISSING else MISSING
    if same(workspace, base):
        return deepcopy(source) if source is not MISSING else MISSING
    if same(source, base):
        return deepcopy(workspace) if workspace is not MISSING else MISSING
    if all(isinstance(item, dict) for item in (base, workspace, source)):
        result = {}
        for key in sorted(base.keys() | workspace.keys() | source.keys(), key=str):
            value = reconcile(
                base.get(key, MISSING),
                workspace.get(key, MISSING),
                source.get(key, MISSING),
                prefer=prefer,
                path=f"{path}.{key}" if path else str(key),
                conflicts=conflicts,
            )
            if value is not MISSING:
                result[key] = value
        return result
    keys = collection_key(path)
    if keys:
        maps = [keyed(value, keys) for value in (base, workspace, source)]
        if all(value is not None for value in maps):
            merged = reconcile(*maps, prefer=prefer, path=path + ".items", conflicts=conflicts)
            common = set(maps[0]) & set(maps[1]) & set(maps[2])
            orders = [[key for key in mapping if key in common] for mapping in maps]
            selected = reconcile(*orders, prefer=prefer, path=path + ".order", conflicts=conflicts)
            order = list(selected)
            for mapping in (maps[1], maps[2], maps[0]):
                items = list(mapping)
                for index, key in enumerate(items):
                    if key in merged and key not in order:
                        following = next((k for k in items[index + 1 :] if k in order), None)
                        position = order.index(following) if following is not None else len(order)
                        order.insert(position, key)
            return [merged[key] for key in order if key in merged]

    conflicts.append(
        {
            "field": path,
            "base_present": base is not MISSING,
            "workspace_present": workspace is not MISSING,
            "source_present": source is not MISSING,
        }
    )
    selected = source if prefer == "source" else workspace
    return deepcopy(selected) if selected is not MISSING else MISSING


def differences(before, after, path=""):
    if same(before, after):
        return []
    keys = collection_key(path)
    if keys:
        left, right = keyed(before, keys), keyed(after, keys)
        if left is not None and right is not None:
            changes = differences(left, right, path)
            if list(left) != list(right):
                changes.append(
                    {
                        "field": path + ".order",
                        "before": list(left),
                        "after": list(right),
                        "before_present": True,
                        "after_present": True,
                    }
                )
            return changes
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys(), key=str):
            location = (
                f"{path}[{','.join(str(k) for k in key)}]"
                if isinstance(key, tuple)
                else f"{path}.{key}"
                if path
                else str(key)
            )
            changes.extend(differences(before.get(key, MISSING), after.get(key, MISSING), location))
        return changes
    return [
        {
            "field": path,
            "before": None if before is MISSING else before,
            "after": None if after is MISSING else after,
            "before_present": before is not MISSING,
            "after_present": after is not MISSING,
        }
    ]
