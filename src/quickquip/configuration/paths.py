"""Explicit locations for configuration, execution state and migration records."""

from dataclasses import dataclass
from pathlib import Path

from quickquip.common.env import PROJECT_ROOT


@dataclass(frozen=True)
class StoragePaths:
    root: Path = PROJECT_ROOT

    @property
    def managed(self):
        return self.root / "config" / "managed"

    @property
    def configuration(self):
        return self.managed / "config.db"

    @property
    def runtime(self):
        return self.root / "data" / "config_runtime.db"

    @property
    def recurring(self):
        return self.managed / "scheduled_messages.json"

    @property
    def pending(self):
        return self.root / "data" / "pending_scheduled_messages.json"

    @property
    def migration(self):
        return self.root / "data" / "storage-migration.json"


PATHS = StoragePaths()


def data_directory(configuration: Path) -> Path:
    """Locate runtime coordination for the standard layout or an explicit standalone DB."""
    configuration = Path(configuration)
    if configuration.parent.name == "managed":
        return configuration.parents[2] / "data"
    return configuration.parent
