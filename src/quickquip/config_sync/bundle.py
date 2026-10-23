"""Versioned, content-addressed configuration packages independent of SQLite storage."""

import base64
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import tomllib

import yaml

from quickquip.llm.config_document import validate_document
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_store import dumps

FORMAT = 1
MAX_BYTES = 32 * 1024 * 1024
ROOT_FILES = frozenset(
    f"config/{name}.toml"
    for name in (
        "generation",
        "chat_rules",
        "games",
        "awakening",
        "sensitive_words",
        "admins",
        "niuniu_text",
        "niuniu_text_safe",
    )
)


def digest(value) -> str:
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def in_scope(name: str) -> bool:
    path = PurePosixPath(name)
    if str(path) != name or path.is_absolute() or ".." in path.parts:
        return False
    if name in ROOT_FILES:
        return True
    if len(path.parts) == 3 and path.parts[:2] in (
        ("config", "personas"),
        ("config", "client_profiles"),
    ):
        return path.suffix == ".toml"
    return (
        len(path.parts) in (2, 3)
        and path.parts[0] == "llm_about"
        and path.name in ("vocab.yaml", "identities.yaml")
        and (len(path.parts) == 2 or path.parts[1].isdigit())
    )


def allowed(name: str) -> bool:
    if not in_scope(name) or "\\" in name:
        return False
    path = PurePosixPath(name)
    for part in path.parts:
        if (
            PureWindowsPath(part).is_reserved()
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or part.endswith((" ", "."))
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
        ):
            return False
    return True


def safe_path(root: Path, name: str) -> Path:
    if not allowed(name):
        raise ConfigError("invalid_asset", "Asset is outside the synchronization scope", name)
    target = root / name
    if target.resolve() != target.absolute():
        raise ConfigError("invalid_asset", "Configuration path is redirected", name)
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ConfigError("invalid_asset", "Symbolic links are not configuration assets", name)
    if target.exists() and not target.is_file():
        raise ConfigError("invalid_asset", "Configuration asset must be a regular file", name)
    return target


def read_assets(root: Path) -> dict:
    names = set(ROOT_FILES)
    for directory in ("config/personas", "config/client_profiles", "llm_about"):
        base = root / directory
        if base.is_symlink():
            raise ConfigError("invalid_asset", "Configuration directory is a symbolic link")
        if base.exists():
            for path in base.rglob("*"):
                if (
                    directory == "llm_about"
                    and path.parent == base
                    and path.name.isdigit()
                    and path.is_symlink()
                ):
                    raise ConfigError(
                        "invalid_asset", "Group configuration directory is a symbolic link"
                    )
                names.add(path.relative_to(root).as_posix())
    result = {}
    total = 0
    for name in sorted(filter(in_scope, names)):
        path = safe_path(root, name)
        if not path.exists():
            continue
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        total += len(content)
        if total > MAX_BYTES:
            raise ConfigError("body_too_large", "Configuration assets exceed 32 MiB")
        result[name] = {
            "content": base64.b64encode(content).decode("ascii"),
            # Portable access policy; Windows does not round-trip POSIX permission bits.
            "mode": 0o644 if name.startswith("config/niuniu_text") else 0o600,
        }
    return result


def asset_bytes(entry: dict) -> bytes:
    try:
        if set(entry) != {"content", "mode"} or type(entry["mode"]) is not int:
            raise ValueError
        if not 0 <= entry["mode"] <= 0o777:
            raise ValueError
        return base64.b64decode(entry["content"], validate=True)
    except (TypeError, ValueError, KeyError) as exc:
        raise ConfigError("invalid_asset", "Invalid asset encoding or permissions") from exc


def install_assets(root: Path, target: dict) -> None:
    """Replace managed files using new inodes, retaining unrelated release content."""
    import os
    from quickquip.llm.config_durability import durable_write, sync_directory

    current = read_assets(root)
    # Delete first: a case-only rename aliases the old path on Windows.
    for name in sorted(current.keys() - target.keys()):
        path = safe_path(root, name)
        path.unlink()
        sync_directory(path.parent)
    for name in sorted(target):
        if current.get(name) == target[name]:
            continue
        path = safe_path(root, name)
        durable_write(path, asset_bytes(target[name]))
        os.chmod(path, target[name]["mode"])


def validate_bundle(bundle: dict, *, environment=False) -> dict:
    if not isinstance(bundle, dict) or set(bundle) != {"format", "document", "assets"}:
        raise ConfigError("invalid_bundle", "Invalid configuration package")
    if (
        type(bundle["format"]) is not int
        or bundle["format"] != FORMAT
        or not isinstance(bundle["assets"], dict)
    ):
        raise ConfigError("unsupported_format", "Unsupported configuration package format")
    if len(dumps(bundle["document"]).encode("utf-8")) > 1024 * 1024:
        raise ConfigError("body_too_large", "LLM configuration exceeds 1 MiB")
    total = 0
    with tempfile.TemporaryDirectory(prefix="quickquip-config-validate-") as directory:
        root = Path(directory)
        names = set()
        for name, entry in bundle["assets"].items():
            if name.casefold() in names:
                raise ConfigError("invalid_asset", "Asset names collide on Windows", name)
            names.add(name.casefold())
            path = safe_path(root, name)
            content = asset_bytes(entry)
            total += len(content)
            if total > MAX_BYTES:
                raise ConfigError("body_too_large", "Configuration assets exceed 32 MiB")
            try:
                text = content.decode("utf-8")
                if path.suffix == ".toml":
                    tomllib.loads(text)
                else:
                    value = yaml.safe_load(text)
                    if value is not None and not isinstance(value, dict):
                        raise ValueError("YAML root must be a mapping")
            except (ValueError, UnicodeError, yaml.YAMLError) as exc:
                raise ConfigError("invalid_asset", "Invalid configuration file", name) from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        from quickquip.config_sync.validation import validate_asset_tree

        validate_asset_tree(root)
        normalized = validate_document(bundle["document"], config_dir=root / "config")
        from quickquip.llm.config_document import compile_document

        compiled = compile_document(normalized, revision=0, config_dir=root / "config")
        if environment:
            from quickquip.llm.config_preflight import validate_runtime_configuration

            validate_runtime_configuration(compiled, normalized)
        reports = ("daily_summary", "daily_briefing", "weekly_report", "monthly_report")
        if compiled.runtime.enabled or any(getattr(compiled, key).enabled for key in reports):
            if compiled.runtime.default_persona not in compiled.personas:
                raise ConfigError("missing_persona", "Default persona asset is missing")
    return {"format": FORMAT, "document": normalized, "assets": bundle["assets"]}


def projection_consistent(connection) -> None:
    """Compare stored projections against an independently projected draft in memory."""
    import sqlite3
    from quickquip.llm.config_store import (
        _SCHEMA,
        _REVISIONS_SCHEMA,
        declared_schema,
        project_document,
    )

    document = json.loads(connection.execute("SELECT document FROM config_meta").fetchone()[0])
    with sqlite3.connect(":memory:") as expected:
        expected.executescript(_SCHEMA + _REVISIONS_SCHEMA + declared_schema())
        project_document(expected, document)
        tables = [
            row[0]
            for row in expected.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("config_") and row[0] != "bot_runtime"
        ]
        tables.append("config_settings")
        for table in tables:
            actual_rows = sorted(
                tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')
            )
            expected_rows = sorted(expected.execute(f'SELECT * FROM "{table}"').fetchall())
            if actual_rows != expected_rows:
                raise ConfigError(
                    "projection_mismatch",
                    "Draft and relational projections differ; use ConfigService",
                    table,
                )
