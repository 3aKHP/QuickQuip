"""Host-side Compose lifecycle and container execution for configuration operations."""

import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time

from quickquip.config_sync.discovery import describe, candidate
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
        self.refresh()
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

    def refresh(self):
        release = self.application.name if self.application != self.root else None
        if self.remote:
            script = Path(__file__).with_name("discovery.py").read_text(encoding="utf-8")
            command = ["python3", "-c", script, str(self.root)] + ([release] if release else [])
            description = json.loads(self.runner(command, {}, str(self.root), None))
            path = PurePosixPath
        else:
            description, path = describe(self.root, release), Path
        if description.get("compose") is None:
            raise ConfigError("compose_missing", "No installed Compose file exists")
        self.description = description
        self.file, self.overrides = path(description["compose"]), description["overrides"]

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
        definition = json.loads(self.run(["config", "--format", "json"]))
        raw = self.run(["ps", "--all", "--format", "json"]).strip()
        rows = (
            json.loads(raw)
            if raw.startswith("[")
            else [json.loads(line) for line in raw.splitlines() if line]
        )
        services = {name: {"running": False, "id": None} for name in definition["services"]}
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
            "project": definition["name"],
        }

    def pause(self, original):
        current = self.inspect()
        ids = []
        for project in {original["project"], current["project"]}:
            raw = self.runner(
                [
                    "docker",
                    "ps",
                    "--all",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                    "--filter",
                    "label=com.docker.compose.oneoff=False",
                    "--format",
                    "{{json .}}",
                ],
                {},
                str(self.root),
                None,
            )
            for line in raw.splitlines():
                row = json.loads(line)
                labels = dict(
                    item.split("=", 1) for item in row["Labels"].split(",") if "=" in item
                )
                service = labels.get("com.docker.compose.service")
                if service in original["services"] and row["State"] == "running":
                    if not original["services"][service]["running"]:
                        raise ConfigError("service_state_changed", "A stopped service was started")
                    ids.append(row["ID"])
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
            ) and (not original["web"]["running"] or self.web_ready()):
                return
            if time.monotonic() >= deadline:
                raise ConfigError("service_start_failed", "Compose consumer states differ")
            time.sleep(0.2)

    def web_ready(self):
        program = """import os, urllib.request, urllib.error
host = '[::1]' if ':' in os.getenv('WEB_ADMIN_HOST', '') else '127.0.0.1'
url = 'http://' + host + ':' + os.getenv('WEB_ADMIN_PORT', '5104') + '/ops/api/auth/me'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(url, timeout=1) as response:
        print('ready' if response.status == 200 else 'waiting')
except urllib.error.HTTPError as error:
    print('ready' if error.code == 401 else 'waiting')
except Exception:
    print('waiting')
"""
        try:
            return self.run(["exec", "-T", "web-admin", "python", "-c", program]).strip() == "ready"
        except ConfigError as error:
            if error.code in ("compose_failed", "remote_command_failed"):
                return False
            raise

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
        try:
            description = candidate(
                self.description, snapshot["files"], PurePosixPath if self.remote else Path
            )
            if not self.remote:
                from quickquip.config_sync.compose_environment import resolve

                result = resolve(description, snapshot["files"])
            else:
                script = (
                    Path(__file__).with_name("compose_environment.py").read_text(encoding="utf-8")
                )
                raw = self.runner(
                    ["python3", "-c", script],
                    {},
                    str(self.root),
                    {"description": description, "files": snapshot["files"]},
                )
                result = json.loads(raw)
            if "error" in result:
                raise ValueError("Candidate validation failed")
            return result["environment"]
        except (ValueError, KeyError, OSError, subprocess.SubprocessError):
            raise ConfigError("invalid_compose", "Candidate Compose validation failed") from None
