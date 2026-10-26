"""Real Compose smoke for stopped Bot and running Web configuration deployment."""

import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest
import tomlkit

from quickquip.config_sync.compose import Compose
from quickquip.config_sync.peers import Local, Remote
from quickquip.config_sync.session import Session
from quickquip.config_workspace.service import Workspace
from quickquip.configuration.errors import ConfigError
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
        "WEB_ADMIN_HOST=0.0.0.0\nWEB_ADMIN_PORT=5104\nTIEBA_ENABLED=false\nOLD_REQUIRED=synthetic\n",
        encoding="utf-8",
    )
    (remote / "docker-compose.yml").write_text(
        f"name: {name}\nservices:\n"
        "  quickquip:\n    image: quickquip-qqsync-smoke\n"
        "    env_file: .env\n    environment:\n      QUICKQUIP_MANAGED_CONTAINER: '1'\n"
        "      CHECK_OLD: '${OLD_REQUIRED:?}'\n"
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
            environment.read_text()
            .replace("first-synthetic", "second-synthetic")
            .replace("OLD_REQUIRED=synthetic\n", "")
        )
        compose_file = workspace.storage.directory / "docker-compose.yml"
        compose_file.write_text(
            compose_file.read_text().replace("      CHECK_OLD: '${OLD_REQUIRED:?}'\n", "")
        )
        workspace.pack()
        if location == "local" and not bot_running:
            call = Local.call

            def interrupt_install(peer, action, body=None):
                if action != "install":
                    return call(peer, action, body)
                monkeypatch.setattr(Local, "call", call)
                program = """import json, os, sys
from quickquip.config_sync.installation import Installation
from quickquip.configuration.files import install
body = json.load(sys.stdin)
receiver = Installation('/qqsync-host')
def partial_write(before, after):
    install(receiver.root, {'.env': before['.env']}, {'.env': after['.env']})
    os._exit(71)
receiver.layout.install = partial_write
receiver.install(body['operation'], environment=body['environment'])
"""
                image = session.state.read("qqsync/client.json")["original"]["helper_image"]
                result = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-i",
                        "--entrypoint",
                        "python",
                        "-v",
                        str(remote) + ":/qqsync-host",
                        image,
                        "-c",
                        program,
                    ],
                    input=json.dumps(body),
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                assert result.returncode == 71, result.stderr
                raise ConfigError("transport_error", "Interrupted after environment write")

            monkeypatch.setattr(Local, "call", interrupt_install)
            with pytest.raises(ConfigError, match="Interrupted after environment write"):
                session.run("push")
            with pytest.raises(ConfigError, match="Compose operation failed"):
                controller.run(["config", "--quiet"])
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


def test_hybrid_helper_uses_mounted_code_when_image_lacks_sync_module(tmp_path):
    image = "qqsync-hybrid-" + uuid.uuid4().hex[:12]
    dockerfile = (
        "FROM quickquip-qqsync-smoke\n"
        'RUN python -c "import pathlib, quickquip, shutil; '
        "shutil.rmtree(pathlib.Path(quickquip.__file__).parent / 'config_sync')\"\n"
    )
    subprocess.run(
        ["docker", "build", "-t", image, "-"],
        input=dockerfile,
        text=True,
        capture_output=True,
        check=True,
        timeout=90,
    )
    try:
        missing = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                image,
                "python",
                "-m",
                "quickquip.config_sync.worker",
                "--help",
            ],
            capture_output=True,
            timeout=30,
        )
        assert missing.returncode != 0
        source = Path(__file__).resolve().parents[2] / "src"
        (tmp_path / ".env").write_text(
            "QUICKQUIP_DEPLOY_LOCATION=local\nQUICKQUIP_DEPLOY_RUNTIME=docker\n"
        )
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            "services:\n"
            f"  quickquip:\n    image: {image}\n"
            f"  web-admin:\n    image: {image}\n"
            "    environment:\n      PYTHONPATH: /app/src\n"
            f"    volumes:\n      - {source}:/app/src:ro\n"
        )
        ConfigService(tmp_path / "config/managed/config.db").initialize()
        controller = Compose(tmp_path)
        before = controller.call("capture", {})
        original = controller.inspect()
        controller.environment(before["snapshot"])
        assert controller.target_project == original["project"]
        compose_file.unlink()
        resumed = Compose(tmp_path)
        resumed.bind(original)
        assert resumed.call("capture", {})["snapshot"]["document"] == before["snapshot"]["document"]
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True, timeout=30)
