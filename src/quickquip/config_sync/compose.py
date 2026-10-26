"""Host-side Compose lifecycle and container execution for configuration operations."""

import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time

from quickquip.config_sync.discovery import describe
from quickquip.configuration.errors import ConfigError


class Compose:
    def __init__(self, root, *, release=None, description=None, runner=None):
        self.remote = runner is not None
        self.runner = runner or self._run
        info = description or describe(root, release)
        self.description = info
        path = PurePosixPath if self.remote else Path
        self.root, self.application = path(info["root"]), path(info["application"])
        self.file = path(info["compose"]) if info["compose"] else None
        self.overrides = info["overrides"]
        if self.file is None:
            raise ConfigError("compose_missing", "No real Compose file exists in this project")

    def run(self, arguments, *, payload=None):
        environment = {
            "QUICKQUIP_ROOT": str(self.root),
            "QUICKQUIP_ENV_FILE": str(self.root / ".env"),
        }
        if self.application != self.root:
            environment["QUICKQUIP_RELEASE"] = self.application.name
        command = ["docker", "compose", "--env-file", str(self.root / ".env"), "-f", str(self.file)]
        for override in self.overrides:
            command.extend(["-f", override])
        return self.runner([*command, *arguments], environment, str(self.file.parent), payload)

    @staticmethod
    def _run(command, environment, cwd, payload):
        result = subprocess.run(
            command,
            cwd=cwd,
            env={**os.environ, **environment},
            input=None if payload is None else json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=240,
        )
        if result.returncode:
            # Compose output may contain expanded credentials; keep it out of CLI errors.
            raise ConfigError("compose_failed", "Compose operation failed; inspect service logs")
        return result.stdout

    def inspect(self):
        raw = self.run(["ps", "--all", "--format", "json"]).strip()
        rows = (
            json.loads(raw)
            if raw.startswith("[")
            else [json.loads(line) for line in raw.splitlines() if line]
        )
        services = {
            name: {"running": False, "id": None}
            for name in self.run(["config", "--services"]).splitlines()
        }
        for row in rows:
            if row.get("Service") in services:
                services[row["Service"]] = {
                    "running": row.get("State") == "running",
                    "id": row["ID"],
                }
        return {
            "bot": services.get("quickquip", {"running": False}),
            "web": services.get("web-admin", {"running": False}),
            "services": services,
        }

    def pause(self, original):
        ids = [
            value["id"]
            for value in original["services"].values()
            if value["running"] and value["id"]
        ]
        if ids:
            self.runner(["docker", "stop", "--time", "45", *ids], {}, str(self.root), None)

    def restore(self, original):
        names = [name for name, value in original["services"].items() if value["running"]]
        if names:
            self.run(["up", "-d", "--no-deps", *names])

    def verify(self, original, *, timeout=45):
        deadline = time.monotonic() + timeout
        while True:
            current = self.inspect()["services"]
            if all(
                current.get(name, {}).get("running", False) == value["running"]
                for name, value in original["services"].items()
            ):
                return
            if time.monotonic() >= deadline:
                raise ConfigError("service_start_failed", "Compose consumer states differ")
            time.sleep(0.2)

    def call(self, action, payload):
        # A private one-off helper sees the host's real files, even while Web is stopped.
        if self.application != self.root:
            payload = {**payload, "release": self.application.name}
        ownership = []
        if self.description["uid"] is not None:
            ownership = [
                "-e",
                f"QUICKQUIP_SYNC_UID={self.description['uid']}",
                "-e",
                f"QUICKQUIP_SYNC_GID={self.description['gid']}",
            ]
        raw = self.run(
            [
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "python",
                "-v",
                str(self.root) + ":/qqsync-host",
                *ownership,
                "web-admin",
                "-m",
                "quickquip.config_sync.worker",
                action,
                "--root",
                "/qqsync-host",
            ],
            payload=payload,
        )
        try:
            result = json.loads(raw)
        except ValueError:
            raise ConfigError(
                "protocol_error", "Configuration helper returned invalid data"
            ) from None
        if "error" in result:
            error = result["error"]
            raise ConfigError(error["code"], error["message"], details=error.get("details"))
        return result

    def environment(self, snapshot):
        if not self.remote:
            from quickquip.config_sync.compose_environment import resolve

            return resolve(self.description, snapshot["files"])["environment"]
        script = Path(__file__).with_name("compose_environment.py").read_text(encoding="utf-8")
        raw = self.runner(
            ["python3", "-c", script],
            {},
            str(self.root),
            {"description": self.description, "files": snapshot["files"]},
        )
        return json.loads(raw)["environment"]
