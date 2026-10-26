"""Map logical configuration names to flat or release-layout real files."""

from pathlib import Path

from quickquip.config_sync.discovery import describe
from quickquip.config_sync.host_files import return_ownership
from quickquip.configuration import inventory
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.files import install


class Layout:
    def __init__(self, root, *, release=None):
        self.root = Path(root).resolve()
        try:
            self.application = Path(describe(root, release)["application"])
        except (OSError, ValueError):
            raise ConfigError(
                "invalid_deployment_layout", "Current release is unavailable"
            ) from None

    def owner(self, name):
        if name in (".env", "prod/sendkey.env") or name.startswith(("data/", "config/managed/")):
            return self.root
        return self.application

    def read_files(self):
        roots = {self.root, self.application}
        result = {}
        for root in roots:
            for name, value in inventory.read_files(root).items():
                if self.owner(name) == root:
                    result[name] = value
        return result

    def install(self, before, after):
        for root in {self.root, self.application}:
            install(
                root,
                {name: value for name, value in before.items() if self.owner(name) == root},
                {name: value for name, value in after.items() if self.owner(name) == root},
            )
        for name in after:
            return_ownership(inventory.safe_path(self.owner(name), name))

    @property
    def config_dir(self):
        return self.application / "config"

    @property
    def database(self):
        return self.root / "config/managed/config.db"
