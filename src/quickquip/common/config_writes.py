"""Cross-process exclusion for configuration edits during a recoverable operation."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from functools import lru_cache
from pathlib import Path

from filelock import FileLock

from quickquip.common.paths import DATA_DIR

_OWNER = ContextVar("configuration_maintenance_owner", default=None)


@lru_cache(maxsize=64)
def write_lock(directory: Path):
    return FileLock(str(directory / "write.lock"), timeout=10)


class ConfigurationBusy(ValueError):
    """A durable maintenance operation owns configuration writes."""


@contextmanager
def maintenance_owner(token: str):
    marker = _OWNER.set(token)
    try:
        yield
    finally:
        _OWNER.reset(marker)


def check_writable(data_dir: Path = DATA_DIR) -> None:
    marker = Path(data_dir) / "config-sync" / "maintenance.json"
    if marker.exists():
        state = json.loads(marker.read_text(encoding="utf-8"))
        if state["token"] != _OWNER.get():
            raise ConfigurationBusy(
                "Configuration maintenance is active; inspect config sync status"
            )


@contextmanager
def configuration_write(data_dir: Path = DATA_DIR):
    directory = Path(data_dir) / "config-sync"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        descriptor = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    with write_lock(directory.resolve()):
        check_writable(Path(data_dir))
        yield
