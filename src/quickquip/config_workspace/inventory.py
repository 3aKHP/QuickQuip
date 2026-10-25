"""Project-local configuration membership and portable file access."""

import os
import base64
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from quickquip.configuration.errors import ConfigError

APP_FILES = {
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
}
GROUP_FILES = {
    f"data/{name}.json"
    for name in (
        "rule_switch",
        "daily_summary_groups",
        "daily_briefing_groups",
        "weekly_report_groups",
        "monthly_report_groups",
        "awakening_boredom_groups",
    )
}
COMPOSE_FILES = {
    f"{prefix}{name}{suffix}"
    for prefix in ("", "prod/")
    for name in ("compose", "compose.override", "docker-compose", "docker-compose.override")
    for suffix in (".yml", ".yaml")
}
FIXED_FILES = (
    APP_FILES
    | GROUP_FILES
    | COMPOSE_FILES
    | {
        ".env",
        "prod/sendkey.env",
        "docker/searxng/settings.yml",
        "config/managed/scheduled_messages.json",
    }
)
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def relative_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or str(path) != name or ".." in path.parts or "\\" in name:
        raise ConfigError("invalid_workspace", "Expected a relative configuration path", name)
    for part in path.parts:
        if (
            PureWindowsPath(part).is_reserved()
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or part.endswith((" ", "."))
        ):
            raise ConfigError("invalid_workspace", "Configuration path is not portable", name)
    return path


def safe_path(root, name):
    relative_path(name)
    root = Path(root)
    target = root / name
    for component in (target, *target.parents):
        if component.is_symlink():
            raise ConfigError("invalid_workspace", "Configuration path is a symbolic link", name)
        if component == root:
            break
    if target.exists() and not target.is_file():
        raise ConfigError("invalid_workspace", "Expected a regular configuration file", name)
    return target


def in_scope(name):
    path = PurePosixPath(name)
    if name in FIXED_FILES:
        return True
    if len(path.parts) == 3 and path.parts[:2] in (
        ("config", "personas"),
        ("config", "client_profiles"),
    ):
        return path.suffix == ".toml" and not path.name.startswith(".")
    return (
        len(path.parts) in (2, 3)
        and path.parts[0] == "llm_about"
        and path.name in ("vocab.yaml", "identities.yaml")
        and (len(path.parts) == 2 or path.parts[1].isdigit())
    )


def entry(body, mode=0o600):
    return {"content": base64.b64encode(body).decode("ascii"), "mode": mode}


def body(value):
    return base64.b64decode(value["content"], validate=True)


def read_files(root):
    root = Path(root)
    names = set(FIXED_FILES)
    for directory in ("config/personas", "config/client_profiles", "llm_about"):
        folder = root / directory
        if folder.is_symlink():
            raise ConfigError(
                "invalid_workspace", "Configuration directory is redirected", directory
            )
        if folder.exists():
            for path in folder.rglob("*"):
                name = path.relative_to(root).as_posix()
                if in_scope(name):
                    names.add(name)
    result, total = {}, 0
    for name in sorted(names):
        path = safe_path(root, name)
        if not path.exists():
            continue
        with path.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ConfigError("body_too_large", "Configuration exceeds its size limit", name)
        mode = stat.S_IMODE(path.stat().st_mode) if os.name != "nt" else 0o600
        result[name] = entry(content, mode)
    return result
