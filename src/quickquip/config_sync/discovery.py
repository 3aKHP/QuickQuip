"""Standard-library-only discovery, also executable on a Docker deployment host."""

import json
import os
from pathlib import Path
import sys


COMPOSE_NAMES = (
    "prod/compose.yaml",
    "prod/compose.yml",
    "prod/docker-compose.yml",
    "prod/docker-compose.yaml",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yml",
    "docker-compose.yaml",
)


def describe(root, release=None):
    root = Path(root).resolve()
    current = root / "current"
    application = root
    if release is not None:
        application = (root / "releases" / release).resolve(strict=True)
    elif current.is_symlink():
        application = current.resolve(strict=True)
    if application != root and application.parent != root / "releases":
        raise ValueError("Release is outside releases/")
    compose = next(
        (application / name for name in COMPOSE_NAMES if (application / name).is_file()), None
    )
    overrides = []
    if compose is not None:
        overrides = [
            str(path)
            for suffix in (".override.yml", ".override.yaml")
            if (path := compose.with_name(compose.stem + suffix)).is_file()
        ]
    executable = next(
        (
            path
            for path in (
                root / ".venv/bin/python",
                application / ".venv/bin/python",
                root / "python/python.exe",
                root / ".venv/Scripts/python.exe",
            )
            if path.is_file()
        ),
        None,
    )
    return {
        "root": str(root),
        "application": str(application),
        "compose": str(compose) if compose else None,
        "overrides": overrides,
        "python": str(executable) if executable else sys.executable,
        "uid": os.getuid() if os.name == "posix" else None,
        "gid": os.getgid() if os.name == "posix" else None,
    }


def candidate(description, files, path_type=Path):
    application = path_type(description["application"])
    name = next((name for name in COMPOSE_NAMES if name in files), None)
    if name is None:
        raise ValueError("Candidate has no Compose file")
    compose = application / name
    overrides = [
        str(path)
        for suffix in (".override.yml", ".override.yaml")
        if str((path := compose.with_name(compose.stem + suffix)).relative_to(application)) in files
    ]
    return {**description, "compose": str(compose), "overrides": overrides}


if __name__ == "__main__":
    try:
        print(json.dumps(describe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
    except (ValueError, OSError):
        print('{"error":"Deployment layout is unavailable"}')
        raise SystemExit(1)
