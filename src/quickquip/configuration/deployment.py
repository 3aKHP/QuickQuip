"""Deployment routing read exclusively from the project's real environment file."""

from dataclasses import dataclass
from pathlib import Path
import re

from dotenv import dotenv_values

from quickquip.configuration.errors import ConfigError


@dataclass(frozen=True)
class Deployment:
    location: str | None
    runtime: str | None
    host: str = "quickquip-prod"
    remote_dir: str = "/opt/QuickQuip"

    def require(self):
        if self.location is None or self.runtime is None:
            raise ConfigError(
                "deployment_mode_required",
                "Set QUICKQUIP_DEPLOY_LOCATION=local|cloud and "
                "QUICKQUIP_DEPLOY_RUNTIME=source|docker in the real root .env",
            )
        return self


def read(root, *, required=False):
    values = dotenv_values(Path(root) / ".env")
    modes = []
    for suffix, choices in (("LOCATION", ("local", "cloud")), ("RUNTIME", ("source", "docker"))):
        key = "QUICKQUIP_DEPLOY_" + suffix
        value = values.get(key) or None
        if value is not None and value not in choices:
            raise ConfigError("invalid_deployment_mode", "Expected " + "|".join(choices), key)
        modes.append(value)
    host = values.get("QUICKQUIP_DEPLOY_SSH_HOST") or "quickquip-prod"
    remote = values.get("QUICKQUIP_DEPLOY_REMOTE_DIR") or "/opt/QuickQuip"
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
        raise ConfigError("invalid_deployment_mode", "Invalid SSH host alias")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", remote) or ".." in remote or remote == "/":
        raise ConfigError("invalid_deployment_mode", "Invalid remote project root")
    result = Deployment(*modes, host, remote.rstrip("/"))
    return result.require() if required else result
