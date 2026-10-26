"""Local and SSH access to the same configuration installation protocol."""

import json
from pathlib import Path
import re
import shlex
import subprocess

from quickquip.config_sync.compose import Compose
from quickquip.config_sync.native import Native
from quickquip.configuration.errors import ConfigError


def response(raw):
    try:
        result = json.loads(raw)
    except ValueError:
        raise ConfigError("protocol_error", "Configuration response is invalid") from None
    if "error" in result:
        error = result["error"]
        raise ConfigError(error["code"], error["message"], details=error.get("details"))
    return result


class Local:
    def __init__(self, root, runtime="source"):
        self.root = Path(root).resolve()
        self.runtime = runtime
        self.controller = Compose(root) if runtime == "docker" else Native(root)

    def call(self, action, body=None):
        if self.runtime == "docker":
            return self.controller.call(action, body or {})
        from quickquip.config_sync.worker import execute

        return execute(self.root, action, body or {})


class RemoteNative:
    def __init__(self, peer):
        self.peer = peer

    def inspect(self):
        return self.peer.call("native-state")

    def pause(self, original):
        self.peer.call("native-pause", {"original": original})

    def restore(self, original):
        self.peer.call("native-restore", {"original": original})

    def verify(self, original):
        self.peer.call("native-verify", {"original": original})


class Remote:
    def __init__(self, host, root, runtime):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
            raise ConfigError("invalid_field", "Invalid SSH host alias")
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", root) or ".." in root or root == "/":
            raise ConfigError("invalid_field", "Invalid remote project root")
        self.host, self.root, self.runtime = host, root, runtime
        discovery = Path(__file__).with_name("discovery.py").read_text(encoding="utf-8")
        self.description = response(
            self._ssh(
                shlex.join(["python3", "-c", discovery, root]),
                None,
            )
        )
        self.controller = (
            Compose(root, description=self.description, runner=self._run)
            if runtime == "docker"
            else RemoteNative(self)
        )

    def _ssh(self, command, body):
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
            input=None if body is None else json.dumps(body),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        if result.returncode == 76:
            raise ConfigError(
                "upgrade_required", "Upgrade remote code with --config-sync off first"
            )
        if result.returncode:
            raise ConfigError(
                "transport_error", "SSH operation failed; repeat the same qqsync command"
            )
        return result.stdout

    def _run(self, command, environment, cwd, payload):
        exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in environment.items())
        return self._ssh(f"cd {shlex.quote(cwd)} && env {exports} {shlex.join(command)}", payload)

    def call(self, action, body=None):
        if self.runtime == "docker":
            return self.controller.call(action, body or {})
        return response(
            self._run(
                [
                    self.description["python"],
                    "-m",
                    "quickquip.config_sync.worker",
                    action,
                    "--root",
                    self.root,
                ],
                {"PYTHONPATH": self.description["application"] + "/src"},
                self.description["application"],
                body or {},
            )
        )

    def deployment_status(self, release):
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release):
            raise ConfigError("invalid_field", "Invalid deployment release")
        root = shlex.quote(self.root)
        path = shlex.quote(f"{self.root}/.deploy/{release}.exit")
        return self._ssh(
            f"if test -f {path}; then "
            f'if test "$(cat {path})" = 0 && test "$(basename "$(readlink {root}/current)")" '
            f'!= "{release}"; then printf superseded; else cat {path}; fi; '
            "else printf pending; fi",
            None,
        ).strip()

    def recover_deployment(self, operation, release):
        from quickquip.config_sync.state import identifier

        identifier(operation)
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{12}", release):
            raise ConfigError("invalid_field", "Invalid deployment release")
        root = shlex.quote(self.root)
        runner = shlex.quote(f"{self.root}/.deploy/incoming/{release}/remote-deploy-v4.sh")
        log = shlex.quote(f"{self.root}/.deploy/{release}.recovery.log")
        self._ssh(
            f"CONFIG_SYNC_PROTOCOL=2 CONFIG_SYNC=push SYNC_OPERATION={operation} bash {runner} "
            f"{root} {release} 4 recover >{log} 2>&1; result=$?; test $result -le 1",
            None,
        )
