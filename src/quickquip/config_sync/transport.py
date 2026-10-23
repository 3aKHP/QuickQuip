"""SSH transport for the container protocol and detached activation worker."""

import json
import re
import shlex
import subprocess

from quickquip.config_sync.state import identifier
from quickquip.llm.config_errors import ConfigError


class SSHRemote:
    def __init__(self, host, root):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
            raise ConfigError("invalid_field", "Invalid SSH host alias")
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", root) or ".." in root or root == "/":
            raise ConfigError("invalid_field", "Invalid deployment root")
        self.host, self.root = host, root

    def _ssh(self, command, body=None):
        result = subprocess.run(
            [
                "ssh",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                self.host,
                command,
            ],
            input=json.dumps(body or {}),
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if result.returncode:
            if result.returncode == 75:
                raise ConfigError("deployment_busy", "Another deployment operation is active")
            if "No module named quickquip.config_sync" in result.stderr:
                raise ConfigError(
                    "protocol_unavailable", "Upgrade the server with --config-sync off first"
                )
            try:
                error = json.loads(result.stderr)["error"]
            except (ValueError, KeyError):
                raise ConfigError(
                    "transport_error", "SSH operation failed; inspect or resume its ID"
                ) from None
            raise ConfigError(error["code"], error["message"], details=error.get("details"))
        return result.stdout

    def call(self, action, body=None):
        if not re.fullmatch(r"[a-z-]+", action):
            raise ConfigError("invalid_command", "Invalid RPC action")
        root = shlex.quote(self.root)
        runner = "run --rm --no-deps -T" if action in ("inspect", "release-terminal") else "exec -T"
        gate = (
            f"flock -n -E 75 {root}/.deploy/lock "
            if action in ("prepare", "cancel-preparation")
            else ""
        )
        command = (
            f"set -eu; export QUICKQUIP_ROOT={root} QUICKQUIP_ENV_FILE={root}/.env; "
            f"test -L {root}/current; "
            f'export QUICKQUIP_RELEASE="$(basename "$(readlink {root}/current)")"; '
            f"cd {root}/current/prod; "
            f'{gate}docker compose --env-file "$QUICKQUIP_ENV_FILE" {runner} web-admin '
            f"python -m quickquip.config_sync.rpc {action}"
        )
        try:
            return json.loads(self._ssh(command, body))
        except ValueError as exc:
            raise ConfigError(
                "transport_error", "Remote returned an invalid synchronization response"
            ) from exc

    def start(self, operation, *, recover=False):
        identifier(operation)
        root = shlex.quote(self.root)
        mode = "recover" if recover else "activate"
        self._ssh(
            f"set -eu; umask 077; mkdir -p {root}/.deploy; "
            f"nohup bash {root}/current/prod/remote-config-sync.sh {root} {operation} {mode} "
            f">>{root}/.deploy/sync-{operation}.log 2>&1 </dev/null &"
        )

    def deployment_status(self, release):
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release):
            raise ConfigError("invalid_field", "Invalid deployment identifier")
        path = shlex.quote(f"{self.root}/.deploy/{release}.exit")
        root = shlex.quote(self.root)
        return self._ssh(
            f'if [ "$(basename "$(readlink {root}/current)")" != "{release}" ]; '
            f"then printf superseded; elif test -f {path}; then cat {path}; "
            "else printf pending; fi"
        ).strip()
