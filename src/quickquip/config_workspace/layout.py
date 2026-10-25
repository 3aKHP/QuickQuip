"""Automatically discovered business TOML alongside mirrored configuration files."""

from copy import deepcopy
from dataclasses import dataclass
import re
from pathlib import Path
from dataclasses import asdict
from quickquip.llm.config import PricingRates

from quickquip.configuration.errors import ConfigError
from quickquip.config_workspace.codec import decode, encode, parse, render_table
from quickquip.config_workspace.inventory import read_files, safe_path, entry
from quickquip.llm.config_document import empty_document


@dataclass
class Tree:
    snapshot: dict
    files: dict


def _read(path):
    value = decode(parse(path.read_bytes(), path.name))
    if not isinstance(value, dict):
        raise ConfigError("invalid_workspace", "Expected a TOML table", path.name)
    return value


def _omit_nulls(value):
    # Optional fields default back to None; arbitrary request bodies retain null sentinels.
    if isinstance(value, dict):
        return {
            key: (_omit_nulls(item) if key not in ("extra_body", "parameters") else item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_omit_nulls(item) for item in value]
    return value


def _names(values, original):
    result, used = {}, set()
    for name, value in original.items():
        ident = value.get("id")
        if ident in values and ident not in result:
            result[ident] = name
            used.add(name.casefold())
    for ident in values:
        if ident in result:
            continue
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", ident).strip(". -") or "item"
        slug = slug[:64].rstrip(". ") or "item"
        if slug.split(".")[0].lower() in {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)),
        }:
            slug = "item-" + slug
        name, number = slug + ".toml", 2
        while name.casefold() in used:
            name = f"{slug}-{number}.toml"
            number += 1
        result[ident] = name
        used.add(name.casefold())
    return result


def read_tree(directory):
    directory = Path(directory)
    for folder in (
        "db",
        "db/llm",
        "db/llm/settings",
        "db/scopes",
        "db/scopes/groups",
        "db/scopes/private",
        "db/games",
    ):
        if (directory / folder).is_symlink():
            raise ConfigError("invalid_workspace", "Database directory is redirected", folder)
    if (directory / "workspace.toml").exists() or (directory / ".quickquip").exists():
        raise ConfigError(
            "legacy_workspace", "Keep the old workspace and unpack into a new directory"
        )
    document = empty_document()
    paths, providers, styles, scopes = {}, {}, {}, {}
    for group in ("providers", "styles"):
        folder = directory / f"db/llm/{group}"
        if folder.is_symlink():
            raise ConfigError("invalid_workspace", "Database directory is redirected")
        for path in sorted(folder.glob("*.toml")):
            name = path.relative_to(directory).as_posix()
            value = _read(safe_path(directory, name))
            ident = value.get("id")
            target = providers if group == "providers" else styles
            if not isinstance(ident, str) or not ident or ident in target:
                raise ConfigError("invalid_workspace", "Object ID is missing or duplicated", name)
            target[ident] = value if group == "providers" else value.get("content")
            paths[name] = path.read_bytes()
    order_path = directory / "db/llm/order.toml"
    order = []
    if order_path.exists():
        order = _read(safe_path(directory, "db/llm/order.toml")).get("providers", [])
        if not isinstance(order, list) or any(not isinstance(i, str) for i in order):
            raise ConfigError(
                "invalid_workspace", "Expected provider ID order", "db/llm/order.toml"
            )
        if len(set(order)) != len(order):
            raise ConfigError("invalid_workspace", "Provider order contains duplicate IDs")
        paths["db/llm/order.toml"] = order_path.read_bytes()
    document["providers"] = [providers[key] for key in order if key in providers] + [
        item for key, item in providers.items() if key not in order
    ]
    for provider in document["providers"]:
        defaults = {
            "enabled": True,
            "client_fingerprint": "default",
            "headers": {},
            "fallback_urls": [],
            "proxy": "",
            "auth_method": "api_key",
            "aliases": [],
            "parameters": {},
        }
        for key, value in defaults.items():
            provider.setdefault(key, value)
        for model in provider.get("models", []):
            for key, value in {
                "enabled": True,
                "vision": True,
                "context_window": None,
                "parameters": {},
            }.items():
                model.setdefault(key, value)
    document["style_profiles"] = styles
    for path in sorted((directory / "db/llm/settings").glob("*.toml")):
        name = path.relative_to(directory).as_posix()
        if path.stem not in document["settings"]:
            raise ConfigError("invalid_workspace", "Unknown settings section", name)
        document["settings"][path.stem].update(_read(safe_path(directory, name)))
        paths[name] = path.read_bytes()
    for section in ("routes", "pricing"):
        name = f"db/llm/{section}.toml"
        path = safe_path(directory, name)
        if path.exists():
            value = _read(path)
            document[section] = value if section == "routes" else value["rules"]
            paths[name] = path.read_bytes()
    document["pricing"] = [{**asdict(PricingRates()), **rule} for rule in document["pricing"]]
    for category in ("groups", "private"):
        for path in sorted((directory / f"db/scopes/{category}").glob("*.toml")):
            name = path.relative_to(directory).as_posix()
            value = _read(safe_path(directory, name))
            ident = value.pop("id", None)
            if not isinstance(ident, str) or not ident.isdigit():
                raise ConfigError("invalid_workspace", "Expected numeric scope ID", name)
            key = f"private:{ident}" if category == "private" else ident
            if key in scopes:
                raise ConfigError("invalid_workspace", "Duplicate scope ID", name)
            scopes[key] = value
            paths[name] = path.read_bytes()
    game_name = "db/games/niuniu.toml"
    game_path = safe_path(directory, game_name)
    modes = _read(game_path).get("groups", {}) if game_path.exists() else {}
    if game_path.exists():
        paths[game_name] = game_path.read_bytes()
    # Reject unknown database TOML rather than silently dropping user configuration.
    for path in (directory / "db").rglob("*.toml"):
        if path.relative_to(directory).as_posix() not in paths:
            raise ConfigError(
                "invalid_workspace",
                "Unknown database configuration file",
                path.relative_to(directory).as_posix(),
            )
    snapshot = {
        "document": document,
        "scopes": scopes,
        "text_modes": modes,
        "files": read_files(directory),
    }
    return Tree(snapshot, paths)


def render_tree(snapshot, original=None):
    original = original or {}
    files = {}

    def add(name, value):
        files[name] = render_table(encode(value), original.get(name))

    doc = snapshot["document"]
    for group, values in (
        ("providers", {item["id"]: _omit_nulls(item) for item in doc["providers"]}),
        (
            "styles",
            {key: {"id": key, "content": value} for key, value in doc["style_profiles"].items()},
        ),
    ):
        prefix = f"db/llm/{group}/"
        old = {}
        for name, content in original.items():
            if name.startswith(prefix):
                old[name[len(prefix) :]] = decode(parse(content, name))
        names = _names(values, old)
        for ident, value in values.items():
            add(prefix + names[ident], value)
    order = {"providers": [p["id"] for p in doc["providers"]]}
    # An absent optional order file remains absent if lexical order already suffices.
    provider_order = [
        decode(parse(files[name], name))["id"]
        for name in sorted(files)
        if name.startswith("db/llm/providers/")
    ]
    if "db/llm/order.toml" in original or order["providers"] != provider_order:
        add("db/llm/order.toml", order)
    for name, value in doc["settings"].items():
        add(f"db/llm/settings/{name}.toml", _omit_nulls(value))
    add("db/llm/routes.toml", doc["routes"])
    add("db/llm/pricing.toml", {"rules": _omit_nulls(doc["pricing"])})
    for scope, value in snapshot["scopes"].items():
        category = "private" if scope.startswith("private:") else "groups"
        ident = scope.removeprefix("private:")
        name = f"db/scopes/{category}/{ident}.toml"
        for old_name, content in original.items():
            if old_name.startswith(f"db/scopes/{category}/"):
                if decode(parse(content, old_name)).get("id") == ident:
                    name = old_name
                    break
        add(name, {"id": ident, **_omit_nulls(value)})
    add("db/games/niuniu.toml", {"groups": snapshot["text_modes"]})
    return files


def workspace_files(snapshot, original=None):
    return {
        **{name: entry(content) for name, content in render_tree(snapshot, original).items()},
        **deepcopy(snapshot["files"]),
    }
