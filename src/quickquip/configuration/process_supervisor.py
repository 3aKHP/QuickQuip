"""Native entrypoint supervision retaining the user's console across configuration restarts."""

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from quickquip.configuration.activity import Lease, directory
from quickquip.configuration.errors import ConfigError
from quickquip.configuration.files import write_json
from quickquip.configuration.process_control import (
    control_path, held, read_control, supervisor_running,
)

CHILD_ROLE = "_QUICKQUIP_SERVICE_CHILD"
CHILD_ID = "_QUICKQUIP_SERVICE_CHILD_ID"
SUPERVISOR_ID = "_QUICKQUIP_SERVICE_SUPERVISOR_ID"


@contextmanager
def _child_control(root, role):
    finished = threading.Event()
    identity = os.environ[CHILD_ID]
    supervisor = os.environ[SUPERVISOR_ID]

    def monitor():
        while not finished.wait(0.1):
            try:
                request = read_control(control_path(root, role, "shutdown.json"))
                owner = read_control(control_path(root, role, "supervisor.json"))
            except ConfigError:
                signal.raise_signal(signal.SIGINT)
                return
            if (
                request is not None and request.get("child") == identity
                or not supervisor_running(root, role)
                or owner is None or owner.get("id") != supervisor
            ):
                # Raising SIGINT inside pythonw also works without a Windows console.
                signal.raise_signal(signal.SIGINT)
                return

    thread = threading.Thread(target=monitor, name=f"{role}-control", daemon=True)
    thread.start()
    try:
        yield
    finally:
        finished.set()
        thread.join(timeout=1)


class Supervisor:
    def __init__(self, root, role, command):
        self.root, self.role = Path(root).resolve(), role
        self.command = list(command)
        self.identity = uuid.uuid4().hex
        self.child = None
        self.child_id = None
        self.state = "stopped"
        self.last_request = None

    def _record(self):
        write_json(control_path(self.root, self.role, "supervisor.json"), {
            "format": 1, "id": self.identity, "root": str(self.root), "role": self.role,
            "pid": os.getpid(), "child_pid": self.child.pid if self.child else None,
            "command": self.command, "state": self.state,
        })

    def _start(self):
        if self.child is not None and self.child.poll() is None:
            return
        self.child_id = uuid.uuid4().hex
        self.state = "starting"
        self._record()
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt" else {"start_new_session": True}
        )
        self.child = subprocess.Popen(
            self.command, cwd=self.root,
            env={
                **os.environ, CHILD_ROLE: self.role, CHILD_ID: self.child_id,
                SUPERVISOR_ID: self.identity,
            },
            **options,
        )
        self._record()

    def _pause(self):
        if self.child is not None and self.child.poll() is None:
            write_json(control_path(self.root, self.role, "shutdown.json"), {
                "child": self.child_id,
            })
            try:
                self.child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:
                    self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=5)
        self.child = None
        self.state = "paused"
        self._record()

    def _control(self):
        message = read_control(control_path(self.root, self.role, "request.json"))
        if (
            message is None or message.get("supervisor") != self.identity
            or message.get("id") == self.last_request
        ):
            return False
        self.last_request = message.get("id")
        action = message.get("action")
        response = {"id": self.last_request, "action": action}
        try:
            if action in ("pause", "stop"):
                self._pause()
            elif action == "resume":
                self._start()
            else:
                raise ValueError("Invalid service action")
        except (OSError, ValueError, subprocess.SubprocessError):
            response["error"] = "Managed service control failed"
        response["state"] = self.state
        write_json(control_path(self.root, self.role, "response.json"), response)
        return action == "stop" and "error" not in response

    def run(self):
        lease = Lease(control_path(self.root, self.role, "supervisor.lock"), create=True)
        try:
            lease.acquire()
        except OSError as exc:
            raise ConfigError(
                "service_running", "Service supervisor already exists", self.role
            ) from exc
        try:
            if held(directory(self.root) / f"{self.role}.lock"):
                raise ConfigError("service_running", "Service is already running", self.role)
            self._start()
            while True:
                if self._control():
                    return 0
                if self.child is not None:
                    code = self.child.poll()
                    if code is not None:
                        self.state = "failed" if code else "stopped"
                        self._record()
                        return code
                    if self.state == "starting" and held(
                        directory(self.root) / f"{self.role}.lock"
                    ):
                        self.state = "running"
                        self._record()
                time.sleep(0.05)
        except KeyboardInterrupt:
            return 130
        finally:
            try:
                self._pause()
                self.state = "stopped"
                self._record()
            finally:
                lease.close()


def managed_entrypoint(root, role, run):
    """Compose owns container processes; native entrypoints retain a small supervisor."""
    if os.getenv("QUICKQUIP_MANAGED_CONTAINER") == "1":
        return run()
    if os.getenv(CHILD_ROLE) == role and os.getenv(CHILD_ID) and os.getenv(SUPERVISOR_ID):
        with _child_control(root, role):
            return run()
    command = [sys.executable, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    return Supervisor(root, role, command).run()
