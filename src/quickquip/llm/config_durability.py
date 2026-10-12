"""Durable publication of configuration assets and migration recovery evidence."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


def sync_directory(path: Path) -> None:
    # Windows does not expose directory handles to fsync through Python's os API.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path: Path) -> None:
    missing = []
    directory = path
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    path.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        sync_directory(directory.parent)


def durable_write(path: Path, content: bytes) -> None:
    ensure_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=".llm-config-write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
