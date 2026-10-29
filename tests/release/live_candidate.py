"""Start the actual candidate entrypoints without a QQ account or model endpoint."""

import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(Path(sys.argv[2]).resolve()))
    from quickquip.configuration.process_control import request
    from quickquip.llm.config_service import ConfigService
    from quickquip.llm.config_wait import wait_loaded
    from quickquip.common.env import PROJECT_ROOT

    assert PROJECT_ROOT == root, "candidate import escaped the isolated installation"

    service = ConfigService(root / "config/managed/config.db", config_dir=root / "config")
    port = free_port()
    env = {
        **os.environ,
        "WEB_ADMIN_HOST": "127.0.0.1",
        "WEB_ADMIN_PORT": str(port),
        "HOST": "127.0.0.1",
        "PORT": str(free_port()),
        "ONEBOT_WS_URLS": "[]",
        "WEB_ADMIN_PASSWORD": "synthetic-release-only",
        "TIEBA_ENABLED": "false",
        "PYTHONPATH": str(Path(sys.argv[2]).resolve()),
    }
    processes, streams = [], []
    try:
        for role, entry in (("bot", "bot.py"), ("web", "web_api.py")):
            stream = (root / "data" / f"release-{role}.log").open("wb")
            streams.append(stream)
            process = subprocess.Popen(
                [sys.executable, "-u", str(root / entry)],
                cwd=root,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            processes.append((role, process))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        origin = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 60
        while True:
            assert all(proc.poll() is None for _, proc in processes), "entrypoint exited"
            try:
                with opener.open(origin + "/ops/", timeout=1) as response:
                    assert response.status == 200
                    assert b'<div id="app"></div>' in response.read()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        login = urllib.request.Request(
            origin + "/ops/api/auth/login",
            data=json.dumps({"password": "synthetic-release-only"}).encode(),
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        with opener.open(login, timeout=5) as response:
            assert response.status == 200
        with opener.open(origin + "/ops/api/auth/me", timeout=5) as response:
            assert json.load(response)["authenticated"]
        wait_loaded(service, service.read("published")["revision"], timeout=60)
        draft = service.read()
        draft["document"]["settings"]["runtime"]["history_limit"] = 43
        revision = service.replace(draft["document"], draft["revision"])["revision"]
        task = service.apply(revision, "synthetic-release-live-apply")
        wait_loaded(service, revision, operation=task["id"], timeout=60)
        assert service.tasks.get(task["id"])["status"] == "succeeded"
        print(json.dumps({"stage": "live", "web_login": True, "loaded_revision": revision}))
    finally:
        for role, process in reversed(processes):
            if process.poll() is None:
                if os.getenv("QUICKQUIP_MANAGED_CONTAINER") == "1":
                    process.terminate()
                else:
                    try:
                        request(root, role, "stop", timeout=20)
                    except Exception:
                        process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()
