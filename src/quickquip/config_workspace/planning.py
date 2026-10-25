"""Reconcile local configuration contents and produce secret-safe, field-level previews."""

from copy import deepcopy
import difflib
import re

from quickquip.config_workspace import text
from quickquip.config_workspace.inventory import body, entry
from quickquip.config_workspace.merge import MISSING, differences, reconcile, same

_SECRET = re.compile(r"password|secret|token|api.?key|authorization|cookie", re.I)
_CREDENTIAL_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@", re.I)


def merge(base, workspace, source, prefer=None):
    conflicts = []
    result = {
        key: reconcile(
            base[key], workspace[key], source[key], prefer=prefer, path=key, conflicts=conflicts
        )
        for key in ("document", "scopes", "text_modes")
    }
    files = {}
    for name in sorted(base["files"].keys() | workspace["files"].keys() | source["files"].keys()):
        before, left, right = (
            snapshot["files"].get(name, MISSING) for snapshot in (base, workspace, source)
        )
        if (
            same(left, right)
            or same(left, before)
            or same(right, before)
            or any(item is MISSING for item in (before, left, right))
        ):
            selected = reconcile(before, left, right, prefer=prefer, path=name, conflicts=conflicts)
        else:
            values = [text.parse(name, body(item)) for item in (before, left, right)]
            combined = reconcile(*values, prefer=prefer, path=name, conflicts=conflicts)
            mode = reconcile(
                before["mode"],
                left["mode"],
                right["mode"],
                prefer=prefer,
                path=name + ".permissions",
                conflicts=conflicts,
            )
            selected = entry(text.render(name, combined, body(left)), mode)
        if selected is not MISSING:
            files[name] = selected
    result["files"] = files
    return result, conflicts


def _safe_value(value, field, show_secrets):
    if not show_secrets and _SECRET.search(field):
        return "[hidden]"
    if isinstance(value, dict):
        return {str(key): _safe_value(item, str(key), show_secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, field, show_secrets) for item in value]
    if (
        not show_secrets
        and isinstance(value, str)
        and (_SECRET.search(value) or _CREDENTIAL_URL.search(value))
    ):
        return "[hidden]"
    return value


def _safe_change(change, show_secrets):
    return {
        **change,
        "before": _safe_value(change["before"], change["field"], show_secrets),
        "after": _safe_value(change["after"], change["field"], show_secrets),
    }


def preview(base, workspace, source, target, conflicts, *, show_secrets=False):
    result = {
        "conflicts": deepcopy(conflicts),
        "source_changes": [],
        "workspace_changes": [],
        "write_changes": [],
    }
    for label, before, after in (
        ("source_changes", base, source),
        ("workspace_changes", base, workspace),
        ("write_changes", source, target),
    ):
        for section in ("document", "scopes", "text_modes"):
            for change in differences(before[section], after[section], section):
                result[label].append(_safe_change(change, show_secrets))
        for name in sorted(before["files"].keys() | after["files"].keys()):
            old, new = before["files"].get(name), after["files"].get(name)
            if same(old, new):
                continue
            left = text.parse(name, body(old)) if old else MISSING
            right = text.parse(name, body(new)) if new else MISSING
            changes = differences(left, right, name)
            if not changes:
                result[label].append(
                    {"field": name + ".format", "before": "changed", "after": "changed"}
                )
            for change in changes:
                if not show_secrets and (
                    text.kind(name) == "env" or _SECRET.search(change["field"])
                ):
                    change["before"] = change["after"] = "[hidden]"
                else:
                    change = _safe_change(change, show_secrets)
                result[label].append(change)
            if (show_secrets or text.kind(name) != "env") and not _SECRET.search(name):
                # Text lines help review format/comment changes even when values are identical.
                lines = list(
                    difflib.unified_diff(
                        body(old).decode().splitlines() if old else [],
                        body(new).decode().splitlines() if new else [],
                        fromfile=name,
                        tofile=name,
                        lineterm="",
                    )
                )
                if lines:
                    raw_text = "\n".join(body(item).decode() for item in (old, new) if item)
                    if not show_secrets and (
                        _SECRET.search(raw_text) or _CREDENTIAL_URL.search(raw_text)
                    ):
                        lines = ["[sensitive text diff hidden]"]
                    result[label].append({"file": name, "lines": lines})
    return result
