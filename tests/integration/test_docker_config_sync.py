"""Real Compose smoke for stopped Bot and running Web configuration deployment."""

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest
import tomlkit

from quickquip.config_sync.compose import Compose
from quickquip.config_sync.peers import Remote
from quickquip.config_sync.session import Session
from quickquip.config_workspace.service import Workspace
from quickquip.llm.config_service import ConfigService

pytestmark = pytest.mark.skipif(
    os.getenv("QUICKQUIP_DOCKER_SMOKE") != "1", reason="Dedicated Compose smoke job"
)


@pytest.mark.parametrize("location", ["local", "cloud"])
@pytest.mark.parametrize("bot_running", [False, True])
def test_compose_sync_reloads_credentials_and_preserves_service_states(
    tmp_path, monkeypatch, location, bot_running
):
    remote = tmp_path / "server"
    remote.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    name = "qqsync-smoke-" + uuid.uuid4().hex[:12]
    (remote / ".env").write_text(
        f"QUICKQUIP_DEPLOY_LOCATION={location}\nQUICKQUIP_DEPLOY_RUNTIME=docker\n"
        f"SMOKE_PORT={port}\nWEB_ADMIN_PASSWORD=first-synthetic\n"
        "WEB_ADMIN_HOST=0.0.0.0\nWEB_ADMIN_PORT=5104\nTIEBA_ENABLED=false\n",
        encoding="utf-8",
    )
    (remote / "docker-compose.yml").write_text(
        f"name: {name}\nservices:\n"
        "  quickquip:\n    image: quickquip-qqsync-smoke\n"
        "    env_file: .env\n    environment:\n      QUICKQUIP_MANAGED_CONTAINER: '1'\n"
        "    volumes:\n      - ./data:/app/data\n      - ./config:/app/config\n"
        "  web-admin:\n    image: quickquip-qqsync-smoke\n"
        "    command: [python, web_api.py]\n"
        "    env_file: .env\n    environment:\n      QUICKQUIP_MANAGED_CONTAINER: '1'\n"
        "    ports:\n      - '127.0.0.1:${SMOKE_PORT}:5104'\n"
        "    volumes:\n      - ./data:/app/data\n      - ./config:/app/config\n",
        encoding="utf-8",
    )
    service = ConfigService(remote / "config/managed/config.db")
    service.initialize()
    controller = Compose(remote)
    origin = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def login(password):
        request = urllib.request.Request(
            origin + "/ops/api/auth/login",
            data=json.dumps({"password": password}).encode(),
            headers={"Origin": origin, "Content-Type": "application/json"},
        )
        try:
            with opener.open(request, timeout=1) as result:
                return result.status
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            return code
        except OSError:
            return None

    try:
        controller.run(["up", "-d", "--no-deps", "web-admin"])
        if bot_running:
            controller.run(["up", "-d", "--no-deps", "quickquip"])
        deadline = time.monotonic() + 30
        while login("first-synthetic") != 200:
            assert time.monotonic() < deadline, controller.run(["logs", "web-admin"])
            time.sleep(0.1)
        if bot_running:
            from quickquip.llm.config_wait import wait_loaded

            wait_loaded(service, 1, timeout=45)
        original = controller.inspect()
        if location == "cloud":
            local = tmp_path / "local"
            local.mkdir()
            ConfigService(local / "config/managed/config.db").initialize()
            for filename in (".env", "docker-compose.yml"):
                (local / filename).write_bytes((remote / filename).read_bytes())

            def shell_transport(self, command, body):
                result = subprocess.run(
                    ["bash", "-c", command],
                    input=None if body is None else json.dumps(body),
                    text=True,
                    capture_output=True,
                    timeout=120,
                )
                assert result.returncode == 0, result.stderr
                return result.stdout

            monkeypatch.setattr(Remote, "_ssh", shell_transport)
            session = Session(local, host="synthetic", remote_dir=str(remote))
        else:
            local = remote
            session = Session(local)
        workspace = Workspace(root=local)
        workspace.unpack()
        environment = workspace.storage.directory / ".env"
        environment.write_text(
            environment.read_text().replace("first-synthetic", "second-synthetic")
        )
        workspace.pack()
        assert session.run("push")["phase"] == "confirmed"
        assert login("first-synthetic") == 401
        assert login("second-synthetic") == 200
        current = controller.inspect()
        assert current["bot"]["running"] == bot_running
        assert current["web"]["running"]
        assert current["web"]["id"] != original["web"]["id"]
        if bot_running:
            if location == "cloud":
                draft = service.read()
                draft["document"]["settings"]["runtime"]["memory_limit"] = 17
                service.replace(draft["document"], draft["revision"])
            runtime = workspace.storage.directory / "db/llm/settings/runtime.toml"
            content = tomlkit.parse(runtime.read_text())
            content["history_limit"] = 21
            runtime.write_text(tomlkit.dumps(content))
            workspace.pack()
            assert session.run("push")["phase"] == "confirmed"
            after_hot = controller.inspect()
            assert after_hot["bot"]["id"] == current["bot"]["id"]
            assert after_hot["web"]["id"] == current["web"]["id"]
            assert (
                service.read("published")["document"]["settings"]["runtime"]["history_limit"] == 21
            )
            if location == "cloud":
                assert service.read()["document"]["settings"]["runtime"]["memory_limit"] == 17
                assert (
                    service.read("published")["document"]["settings"]["runtime"]["memory_limit"]
                    != 17
                )
    finally:
        controller.run(["down", "--remove-orphans"])
