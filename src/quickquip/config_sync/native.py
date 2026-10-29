"""Pause and restore native Bot/Web services using their retained supervisors."""

import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values

from quickquip.configuration import process_control as control
from quickquip.configuration.errors import ConfigError


class Native:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def inspect(self):
        return {role: control.status(self.root, role) for role in ("bot", "web")}

    def pause(self, original):
        states = self.inspect()
        for role, saved in original.items():
            current = states[role]
            if not current["running"]:
                continue
            if not saved["running"]:
                raise ConfigError("service_state_changed", "A stopped service was started", role)
            if not current["managed"]:
                raise ConfigError(
                    "service_unmanaged", "Restart through the updated entrypoint", role
                )
        for role, current in states.items():
            if not current["running"]:
                continue
            control.request(self.root, role, "pause")

    def restore(self, original):
        for role, saved in original.items():
            current = control.status(self.root, role)
            if not saved["running"] or current["running"]:
                continue
            if current["managed"]:
                control.request(self.root, role, "resume")
            else:
                self._relaunch(role, saved)

    def _relaunch(self, role, saved):
        record = saved.get("record")
        if record is None or not saved["managed"]:
            raise ConfigError(
                "service_unmanaged", "Original service has no managed entrypoint", role
            )
        command = record.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(value, str) for value in command)
        ):
            raise ConfigError("service_control_unavailable", "Original entrypoint is missing", role)
        log_path = self.root / "data" / ("web-admin.log" if role == "web" else "bot.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        with log_path.open("ab") as log:
            subprocess.Popen(
                command,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **options,
            )

    def verify(self, original, *, timeout=45):
        deadline = time.monotonic() + timeout
        while True:
            states = self.inspect()
            ready = all(
                states[role]["running"] == saved["running"] for role, saved in original.items()
            )
            if ready and (not original["web"]["running"] or self._web_ready()):
                return
            if time.monotonic() >= deadline:
                raise ConfigError(
                    "service_start_failed", "Original service states were not restored"
                )
            time.sleep(0.1)

    def _web_ready(self):
        values = dotenv_values(self.root / ".env")
        host = values.get("WEB_ADMIN_HOST") or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        if ":" in host:
            host = f"[{host}]"
        port = values.get("WEB_ADMIN_PORT") or "5104"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://{host}:{port}/ops/api/auth/me", timeout=1) as response:
                return response.status == 200
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return code == 401
        except (OSError, ValueError):
            return False
