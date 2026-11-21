"""Unit tests for scripts/ops/check_bot.sh status probing and token precedence."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import pytest


PROJECT = Path(__file__).resolve().parents[3]
CHECK_BOT = PROJECT / "scripts/ops/check_bot.sh"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="scripts/ops/check_bot.sh requires Linux /proc/net/tcp and bash",
)


class _OneBotServer:
    def __init__(self, *, expected_token: str, online: bool = True, good: bool = True,
                 user_id: int = 123456):
        self.expected_token = expected_token
        self.online = online
        self.good = good
        self.user_id = user_id
        self.seen_tokens: list[str] = []
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                auth = self.headers.get("Authorization", "")
                server_ref.seen_tokens.append(auth)
                if server_ref.expected_token and auth != f"Bearer {server_ref.expected_token}":
                    self.send_response(401)
                    self.end_headers()
                    return
                if self.path == "/get_status":
                    payload = {"status": "ok", "data": {
                        "online": server_ref.online,
                        "good": server_ref.good,
                    }}
                elif self.path == "/get_login_info":
                    payload = {"status": "ok", "data": {"user_id": server_ref.user_id}}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._httpd.shutdown()
        self._httpd.server_close()


def _install_docker_stub(tmp_path: Path, container_env: dict[str, str],
                         *, running: bool = True, container_id: str = "cid-qq") -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env_file = tmp_path / "container_env.json"
    env_file.write_text(json.dumps(container_env), encoding="utf-8")
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        + f"""
import json, os, subprocess, sys
args = sys.argv[1:]
if args[0] == "compose":
    print({container_id!r})
elif args[0] == "inspect":
    print({"true" if running else "false"!r})
elif args[0] == "exec":
    idx = args.index("-c")
    probe = args[idx + 1]
    url = args[idx + 2]
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("ONEBOT_") or key == "QQ_ACCOUNT":
            del env[key]
    env.update(json.loads(open({str(env_file)!r}, encoding="utf-8").read()))
    proc = subprocess.run([sys.executable, "-c", probe, url], env=env)
    sys.exit(proc.returncode)
else:
    sys.exit(1)
""",
        encoding="utf-8",
    )
    docker.chmod(0o700)
    return bin_dir


def _run_check(tmp_path: Path, bin_dir: Path, sendkey_lines: list[str]) -> str:
    remote_dir = tmp_path / "remote"
    (remote_dir / "prod").mkdir(parents=True, exist_ok=True)
    (remote_dir / ".env").write_text("", encoding="utf-8")
    (remote_dir / "prod/docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    sendkey = remote_dir / "prod/sendkey.env"
    if sendkey_lines:
        sendkey.write_text("\n".join(sendkey_lines) + "\n", encoding="utf-8")
    elif sendkey.exists():
        sendkey.unlink()
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", REMOTE_DIR=str(remote_dir))
    for key in ("ONEBOT_STATUS_API_URL", "ONEBOT_STATUS_API_TOKEN", "QUICKQUIP_OPS_RELEASE"):
        env.pop(key, None)
    result = subprocess.run(
        ["bash", str(CHECK_BOT), "status"],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _established_loopback_peer():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=2)
    accepted, _ = listener.accept()
    return listener, client, accepted, port


def test_unconfigured_without_status_api_url(tmp_path):
    bin_dir = _install_docker_stub(tmp_path, {})
    assert _run_check(tmp_path, bin_dir, []) == "UNCONFIGURED"


def test_online_and_token_precedence(tmp_path):
    listener, client, accepted, ws_port = _established_loopback_peer()
    try:
        with _OneBotServer(expected_token="v11-secret", user_id=123456) as api:
            bin_dir = _install_docker_stub(tmp_path, {
                "ONEBOT_V11_WS_URLS": json.dumps([f"ws://127.0.0.1:{ws_port}/"]),
                "ONEBOT_V11_ACCESS_TOKEN": "v11-secret",
                "ONEBOT_ACCESS_TOKEN": "",
                "QQ_ACCOUNT": "123456",
            })
            status = _run_check(tmp_path, bin_dir, [
                f"ONEBOT_STATUS_API_URL=http://127.0.0.1:{api.port}",
            ])
            assert status == "ONLINE"
            assert api.seen_tokens == ["Bearer v11-secret", "Bearer v11-secret"]

        with _OneBotServer(expected_token="override-secret", user_id=123456) as api:
            bin_dir = _install_docker_stub(tmp_path, {
                "ONEBOT_WS_URLS": json.dumps([f"ws://127.0.0.1:{ws_port}/"]),
                "ONEBOT_V11_ACCESS_TOKEN": "v11-secret",
                "ONEBOT_ACCESS_TOKEN": "base-secret",
            })
            status = _run_check(tmp_path, bin_dir, [
                f"ONEBOT_STATUS_API_URL=http://127.0.0.1:{api.port}",
                "ONEBOT_STATUS_API_TOKEN=override-secret",
            ])
            assert status == "ONLINE"
            assert api.seen_tokens == ["Bearer override-secret", "Bearer override-secret"]
    finally:
        for sock in (client, accepted, listener):
            sock.close()


@pytest.mark.parametrize(
    ("server_kwargs", "qq_account", "connect_ws", "expected"),
    [
        ({"online": True, "good": True, "user_id": 123456}, "123456", False, "OFFLINE"),
        ({"online": False, "good": True, "user_id": 123456}, "123456", True, "OFFLINE"),
        ({"online": True, "good": False, "user_id": 123456}, "123456", True, "OFFLINE"),
        ({"online": True, "good": True, "user_id": 654321}, "123456", True, "OFFLINE"),
    ],
)
def test_offline_conditions(tmp_path, server_kwargs, qq_account, connect_ws, expected):
    listener, client, accepted, ws_port = _established_loopback_peer()
    try:
        if not connect_ws:
            client.close()
            accepted.close()
        with _OneBotServer(expected_token="tok", **server_kwargs) as api:
            bin_dir = _install_docker_stub(tmp_path, {
                "ONEBOT_WS_URLS": json.dumps([f"ws://127.0.0.1:{ws_port}/"]),
                "ONEBOT_ACCESS_TOKEN": "tok",
                "QQ_ACCOUNT": qq_account,
            })
            status = _run_check(tmp_path, bin_dir, [
                f"ONEBOT_STATUS_API_URL=http://127.0.0.1:{api.port}",
            ])
            assert status == expected
    finally:
        for sock in (client, accepted, listener):
            sock.close()


def test_unknown_on_reverse_ws_or_auth_failure(tmp_path):
    listener, client, accepted, ws_port = _established_loopback_peer()
    try:
        with _OneBotServer(expected_token="right-token", user_id=123456) as api:
            bin_dir = _install_docker_stub(tmp_path, {
                "ONEBOT_WS_URLS": "[]",
                "ONEBOT_ACCESS_TOKEN": "right-token",
            })
            assert _run_check(tmp_path, bin_dir, [
                f"ONEBOT_STATUS_API_URL=http://127.0.0.1:{api.port}",
            ]) == "UNKNOWN"

            bin_dir = _install_docker_stub(tmp_path, {
                "ONEBOT_WS_URLS": json.dumps([f"ws://127.0.0.1:{ws_port}/"]),
                "ONEBOT_ACCESS_TOKEN": "wrong-token",
            })
            assert _run_check(tmp_path, bin_dir, [
                f"ONEBOT_STATUS_API_URL=http://127.0.0.1:{api.port}",
            ]) == "UNKNOWN"
    finally:
        for sock in (client, accepted, listener):
            sock.close()
