"""The real Web entrypoint reloads root credentials after a managed native restart."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from quickquip.configuration.process_control import request, status


def test_native_web_restart_reads_updated_root_environment(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    (tmp_path / "web_api.py").write_bytes((repository / "web_api.py").read_bytes())
    # Bind project globals before the real entrypoint imports any application modules.
    (tmp_path / "sitecustomize.py").write_text(
        "from pathlib import Path\nfrom quickquip.common import env\n"
        f"env.PROJECT_ROOT = Path({str(tmp_path)!r})\n", encoding="utf-8"
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"

    def configure(password):
        (tmp_path / ".env").write_text(
            f"WEB_ADMIN_HOST=127.0.0.1\nWEB_ADMIN_PORT={port}\n"
            f"WEB_ADMIN_PASSWORD={password}\nTIEBA_ENABLED=false\n",
            encoding="utf-8",
        )

    configure("first-synthetic-password")
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("WEB_ADMIN_", "_QUICKQUIP_SERVICE_"))}
    env.pop("QUICKQUIP_MANAGED_CONTAINER", None)
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(repository / "src")))
    executable = (
        str(Path(sys.executable).with_name("pythonw.exe")) if os.name == "nt" else sys.executable
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(password=None):
        endpoint = "/ops/api/auth/me" if password is None else "/ops/api/auth/login"
        message = urllib.request.Request(
            origin + endpoint,
            data=None if password is None else json.dumps({"password": password}).encode(),
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        try:
            with opener.open(message, timeout=1) as response:
                return response.status
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return code
        except (OSError, urllib.error.URLError):
            return None

    log_path = tmp_path / "web.log"

    def diagnostics():
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (log_path, tmp_path / "data/web-admin.log") if path.exists()
        )

    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [executable, str(tmp_path / "web_api.py")], cwd=tmp_path, env=env,
            stdout=log, stderr=subprocess.STDOUT,
        )

        def ready():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if call() == 401:
                    return
                assert process.poll() is None, diagnostics()
                time.sleep(0.05)
            raise AssertionError(diagnostics())

        try:
            ready()
            assert call("first-synthetic-password") == 200
            first = status(tmp_path, "web")["record"]["child_pid"]
            request(tmp_path, "web", "pause")
            assert not status(tmp_path, "web")["running"]
            configure("second-synthetic-password")
            request(tmp_path, "web", "resume")
            ready()
            assert status(tmp_path, "web")["record"]["child_pid"] != first
            assert call("first-synthetic-password") == 401
            assert call("second-synthetic-password") == 200
        finally:
            if process.poll() is None:
                try:
                    request(tmp_path, "web", "stop", timeout=10)
                    process.wait(timeout=10)
                except Exception:
                    process.kill()
                    process.wait(timeout=5)
