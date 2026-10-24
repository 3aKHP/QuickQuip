"""Manifest-owned workspace layout and exact-byte configuration assets."""

import base64
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from quickquip.config_sync.bundle import MAX_BYTES, allowed, asset_bytes, digest, validate_bundle
from quickquip.config_workspace.codec import load_value, parse, render_table, render_value
from quickquip.llm.config_errors import ConfigError

FORMAT = 1
MAX_TREE_BYTES = MAX_BYTES + 8 * 1024 * 1024
MANIFEST = "workspace.toml"
GROUPS = ("providers", "settings", "styles")


@dataclass
class Tree:
    bundle: dict
    files: dict[str, bytes]
    manifest: dict


def relative_path(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name:
        raise ConfigError("invalid_workspace", "Invalid relative workspace path")
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or path.is_absolute()
        or str(path) != name
        or ".." in path.parts
        or "\\" in name
    ):
        raise ConfigError("invalid_workspace", "Invalid relative workspace path")
    for part in path.parts:
        if (
            PureWindowsPath(part).is_reserved()
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or part.endswith((" ", "."))
        ):
            raise ConfigError("invalid_workspace", "Workspace path is not portable", name)
    return path


def safe_path(directory: Path, name: str) -> Path:
    relative_path(name)
    target = directory / name
    for component in (target, *target.parents):
        if component.is_symlink():
            raise ConfigError("invalid_workspace", "Workspace paths cannot be symbolic links", name)
        if component == directory:
            break
    if target.exists() and not target.is_file():
        raise ConfigError("invalid_workspace", "Expected a regular workspace file", name)
    return target


def read_file(directory: Path, name: str, limit=MAX_TREE_BYTES) -> bytes:
    path = safe_path(directory, name)
    try:
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
    except FileNotFoundError:
        raise ConfigError("invalid_workspace", "Manifest file is missing", name) from None
    if len(content) > limit:
        raise ConfigError("body_too_large", "Workspace file exceeds its size limit", name)
    return content


def scan(directory: Path) -> dict[str, bytes]:
    """Collect managed text paths even when an interrupted manifest is incomplete."""
    names = set()
    if (directory / MANIFEST).exists():
        names.add(MANIFEST)
    for path in directory.glob("*.toml"):
        names.add(path.relative_to(directory).as_posix())
    for group in (*GROUPS, "assets"):
        folder = directory / group
        if folder.is_symlink():
            raise ConfigError("invalid_workspace", "Workspace directory is redirected", group)
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_symlink():
                raise ConfigError("invalid_workspace", "Workspace contains a symbolic link")
            if path.is_file() and (group == "assets" or path.suffix == ".toml"):
                names.add(path.relative_to(directory).as_posix())
    result, total = {}, 0
    for name in sorted(names):
        result[name] = read_file(directory, name, MAX_TREE_BYTES - total)
        total += len(result[name])
    return result


def _manifest(files):
    try:
        raw = files[MANIFEST]
    except KeyError:
        raise ConfigError("invalid_workspace", "workspace.toml is missing") from None
    if len(raw) > 1024 * 1024:
        raise ConfigError("body_too_large", "Workspace manifest exceeds 1 MiB", MANIFEST)
    manifest = parse(raw, MANIFEST)
    keys = {"format_version", "document_format_version", *GROUPS, "routes", "pricing", "assets"}
    if set(manifest) != keys or type(manifest["format_version"]) is not int:
        raise ConfigError("invalid_workspace", "Invalid workspace manifest", MANIFEST)
    if manifest["format_version"] != FORMAT:
        raise ConfigError("unsupported_format", "Unsupported workspace format", MANIFEST)
    registered = [MANIFEST]
    for group in GROUPS:
        entries = manifest[group]
        if not isinstance(entries, list):
            raise ConfigError("invalid_workspace", "Expected a file list", group)
        for entry in entries:
            if group != "providers":
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"id", "file"}
                    or not isinstance(entry["id"], str)
                ):
                    raise ConfigError("invalid_workspace", "Expected an id/file entry", group)
                name = entry["file"]
            else:
                name = entry
            if (
                not isinstance(name, str)
                or not name.startswith(group + "/")
                or len(PurePosixPath(name).parts) != 2
                or not name.endswith(".toml")
            ):
                raise ConfigError(
                    "invalid_workspace", "Invalid configuration file registration", group
                )
            relative_path(name)
            registered.append(name)
    for group in ("routes", "pricing"):
        name = manifest[group]
        if not isinstance(name, str) or name != group + ".toml":
            raise ConfigError("invalid_workspace", "Invalid singleton configuration file", group)
        registered.append(name)
    if not isinstance(manifest["assets"], list):
        raise ConfigError("invalid_workspace", "Expected an asset list", "assets")
    for name in manifest["assets"]:
        if not isinstance(name, str) or not allowed(name):
            raise ConfigError("invalid_asset", "Asset is outside the configuration scope")
        registered.append("assets/" + name)
    if len({name.casefold() for name in registered}) != len(registered):
        raise ConfigError("invalid_workspace", "Workspace file registrations collide", MANIFEST)
    if set(registered) != set(files):
        raise ConfigError(
            "invalid_workspace",
            "Manifest and workspace files differ",
            MANIFEST,
            {
                "missing": sorted(set(registered) - files.keys()),
                "unregistered": sorted(files.keys() - set(registered)),
            },
        )
    return manifest


def parse_tree(files: dict[str, bytes]) -> Tree:
    if sum(len(body) for body in files.values()) > MAX_TREE_BYTES:
        raise ConfigError("body_too_large", "Workspace exceeds its size limit")
    manifest = _manifest(files)
    document = {
        "format_version": manifest["document_format_version"],
        "providers": [],
        "settings": {},
        "style_profiles": {},
    }
    for name in manifest["providers"]:
        document["providers"].append(load_value(files[name], name))
    for group, key in (("settings", "settings"), ("styles", "style_profiles")):
        for entry in manifest[group]:
            if entry["id"] in document[key]:
                raise ConfigError("invalid_workspace", "Duplicate configuration identity", group)
            document[key][entry["id"]] = load_value(files[entry["file"]], entry["file"])
    for group in ("routes", "pricing"):
        name = manifest[group]
        document[group] = load_value(files[name], name)
    assets = {
        name: {
            "content": base64.b64encode(files["assets/" + name]).decode("ascii"),
            "mode": 0o644 if name.startswith("config/niuniu_text") else 0o600,
        }
        for name in manifest["assets"]
    }
    try:
        bundle = validate_bundle({"format": 1, "document": document, "assets": assets})
    except ConfigError as exc:
        # Keep domain field paths and identify their editable source file.
        field = exc.field_path
        name = MANIFEST
        match = re.match(r"providers\[(\d+)\]", field)
        if match and int(match[1]) < len(manifest["providers"]):
            name = manifest["providers"][int(match[1])]
        elif field.startswith(("config/", "llm_about/")):
            name = "assets/" + field
        else:
            for group in ("routes", "pricing"):
                if field.startswith(group):
                    name = manifest[group]
            if field.startswith("settings."):
                key = field.split(".", 2)[1]
                name = next((e["file"] for e in manifest["settings"] if e["id"] == key), name)
        exc.details = {"file": name, "cause": exc.details}
        raise
    return Tree(bundle, files, manifest)


def read_tree(directory: Path) -> Tree:
    files = scan(directory)
    tree = parse_tree(files)
    if scan(directory) != files:
        raise ConfigError("revision_conflict", "Workspace changed while reading")
    return tree


def _filename(group, ident, used):
    slug = re.sub(r"[^a-z0-9_.-]+", "-", ident.lower()).strip(".-")[:48] or "item"
    suffix = hashlib.sha256(ident.encode("utf-8")).hexdigest()
    for size in range(12, 65, 4):
        name = f"{group}/{slug}--{suffix[:size]}.toml"
        if name.casefold() not in used:
            return name
    raise ConfigError("invalid_workspace", "Configuration identities have colliding filenames")


def render_tree(bundle: dict, previous: Tree | None = None) -> dict[str, bytes]:
    if previous and digest(bundle) == digest(previous.bundle):
        return dict(previous.files)
    document = bundle["document"]
    manifest = {
        "format_version": FORMAT,
        "document_format_version": document["format_version"],
        "providers": [],
        "settings": [],
        "styles": [],
        "routes": "routes.toml",
        "pricing": "pricing.toml",
        "assets": sorted(bundle["assets"]),
    }
    old_files = previous.files if previous else {}
    old_names = {group: {} for group in GROUPS}
    if previous:
        for name in previous.manifest["providers"]:
            old_names["providers"][load_value(old_files[name], name)["id"]] = name
        for group in ("settings", "styles"):
            old_names[group] = {e["id"]: e["file"] for e in previous.manifest[group]}
    used = {name.casefold() for names in old_names.values() for name in names.values()}
    result = {}
    values = {
        "providers": [(p["id"], p) for p in document["providers"]],
        "settings": list(document["settings"].items()),
        "styles": list(document["style_profiles"].items()),
    }
    for group in GROUPS:
        for ident, value in values[group]:
            name = old_names[group].get(ident) or _filename(group, ident, used)
            used.add(name.casefold())
            manifest[group].append(name if group == "providers" else {"id": ident, "file": name})
            result[name] = render_value(value, old_files.get(name))
    for group in ("routes", "pricing"):
        name = manifest[group]
        result[name] = render_value(document[group], old_files.get(name))
    for name, entry in bundle["assets"].items():
        result["assets/" + name] = asset_bytes(entry)
    result[MANIFEST] = render_table(manifest, old_files.get(MANIFEST))
    if digest(parse_tree(result).bundle) != digest(bundle):
        raise ConfigError("invalid_workspace", "Workspace rendering changed the configuration")
    return result
