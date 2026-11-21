#!/bin/bash
# Read the QuickQuip container and its configured forward OneBot connection.
set -o pipefail

if [ "${1:-status}" != status ] || [ "$#" -gt 1 ]; then
    echo "Usage: $0 [status]" >&2
    exit 2
fi

REMOTE_DIR="${REMOTE_DIR:-/opt/QuickQuip}"
if [ -f "$REMOTE_DIR/prod/sendkey.env" ]; then
    source "$REMOTE_DIR/prod/sendkey.env"
fi
if [ -z "${ONEBOT_STATUS_API_URL:-}" ]; then
    echo UNCONFIGURED
    exit 0
fi

export QUICKQUIP_ROOT="$REMOTE_DIR"
export QUICKQUIP_ENV_FILE="$REMOTE_DIR/.env"
if [ -n "${QUICKQUIP_OPS_RELEASE:-}" ]; then
    export QUICKQUIP_RELEASE="$QUICKQUIP_OPS_RELEASE"
    compose_file="$REMOTE_DIR/releases/$QUICKQUIP_RELEASE/prod/docker-compose.yml"
elif [ -L "$REMOTE_DIR/current" ]; then
    QUICKQUIP_RELEASE="$(basename "$(readlink "$REMOTE_DIR/current")")"
    export QUICKQUIP_RELEASE
    compose_file="$REMOTE_DIR/current/prod/docker-compose.yml"
else
    compose_file="$REMOTE_DIR/prod/docker-compose.yml"
fi

container=$(docker compose --env-file "$QUICKQUIP_ENV_FILE" -f "$compose_file" ps --all -q quickquip 2>/dev/null) ||
    { echo UNKNOWN; exit 0; }
if [ -z "$container" ]; then
    echo OFFLINE
    exit 0
fi
running=$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null) ||
    { echo UNKNOWN; exit 0; }
if [ "$running" != true ]; then
    echo OFFLINE
    exit 0
fi

probe=$(cat <<'PY'
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def address(value):
    ip = ipaddress.ip_address(value)
    return getattr(ip, "ipv4_mapped", None) or ip


def established_peers():
    peers = set()
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not table.exists():
            continue
        for line in table.read_text().splitlines()[1:]:
            _, _, remote, state, *_ = line.split()
            if state == "01":  # Established
                raw_ip, port = remote.split(":")
                packed = b"".join(bytes.fromhex(raw_ip[i:i + 8])[::-1] for i in range(0, len(raw_ip), 8))
                peers.add((address(packed), int(port, 16)))
    return peers


def status(base, token):
    api = urlsplit(base)
    configured = os.getenv("ONEBOT_V11_WS_URLS") or os.getenv("ONEBOT_WS_URLS") or "[]"
    targets = [urlsplit(url) for url in json.loads(configured)]
    ports = {target.port or (443 if target.scheme == "wss" else 80)
             for target in targets if target.hostname == api.hostname}
    if not ports:
        return "UNKNOWN"
    peers = established_peers()
    ips = {address(info[4][0]) for info in socket.getaddrinfo(api.hostname, None, type=socket.SOCK_STREAM)}
    if not any((ip, port) in peers for ip in ips for port in ports):
        return "OFFLINE"

    opener = build_opener(ProxyHandler({}))

    def call(action):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(base.rstrip("/") + "/" + action, data=b"{}", headers=headers)
        with opener.open(req, timeout=4) as response:
            result = json.load(response)
        if result.get("status") != "ok":
            raise ValueError("OneBot action failed")
        return result["data"]

    state = call("get_status")
    if state.get("online") is not True or state.get("good") is False:
        return "OFFLINE"
    expected_accounts = {item for item in re.split(r"[,\s]+", os.getenv("QQ_ACCOUNT", "")) if item.isdigit()}
    account = str(call("get_login_info").get("user_id", ""))
    return "ONLINE" if account.isdigit() and (not expected_accounts or account in expected_accounts) else "OFFLINE"


try:
    token = sys.stdin.read() or os.getenv("ONEBOT_ACCESS_TOKEN", "")
    print(status(sys.argv[1], token))
except (OSError, ValueError, KeyError, TypeError):
    print("UNKNOWN")
PY
)

printf '%s' "${ONEBOT_STATUS_API_TOKEN:-}" |
    docker exec -i "$container" python -c "$probe" "$ONEBOT_STATUS_API_URL" 2>/dev/null ||
    echo UNKNOWN
