#!/bin/bash
# QuickQuip production deploy script (IPv4 / Linux local driver).
# Linux equivalent of deploy-v4.ps1: builds the frontend locally, packs the
# project, uploads it via scp, and runs the remote deploy over ssh.
#
# Usage (run from project root):
#   bash prod/deploy-v4.sh
#   bash prod/deploy-v4.sh -LocalCheck        # pack + report size, no upload
#   bash prod/deploy-v4.sh -HostAlias <host> -RemoteDir </opt/QuickQuip>
#
# quickquip-prod is a placeholder SSH host alias; change it via -HostAlias.

set -euo pipefail

HostAlias="quickquip-prod"
RemoteDir="/opt/QuickQuip"
LocalCheck=0
while [ $# -gt 0 ]; do
    case "$1" in
        -LocalCheck|--local-check) LocalCheck=1 ;;
        -HostAlias|--host-alias) HostAlias="${2:?missing value for -HostAlias}"; shift ;;
        -RemoteDir|--remote-dir) RemoteDir="${2:?missing value for -RemoteDir}"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -t 1 ]; then
    C=$'\033[0;36m'; G=$'\033[0;32m'; R=$'\033[0;31m'; Y=$'\033[1;33m'; D=$'\033[0;36m'; N=$'\033[0m'
else
    C=''; G=''; R=''; Y=''; D=''; N=''
fi

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ProjectRoot="$(cd "$ScriptDir/.." && pwd)"
cd "$ProjectRoot"

TmpBase="${TMPDIR:-/tmp}"
TempArchive="$TmpBase/quickquip-deploy.tar.gz"
TiebaStateArchive="$TmpBase/quickquip-tieba-state.tar.gz"
TiebaStateFile="data/tieba/storage_state.json"
SendkeyEnvFile="prod/sendkey.env"
FontFile="data/fonts/NotoSansSC-Regular.ttf"
LocalPrivateWorkspace="d""ev"

ssh_args=(-o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)

run_step() {
    local desc="$1"; shift
    if ! "$@"; then
        echo "${R}FAILED: $desc (exit $?)${N}" >&2
        exit 1
    fi
}

for required_path in ".env" "prod/Dockerfile" "prod/docker-compose.yml" "pyproject.toml" "requirements.txt" "src/quickquip" "src/plugins" "config/llm.toml" "llm_about/_example/vocab.yaml" "llm_about/_example/identities.yaml" "docker/searxng/settings.yml"; do
    [ -e "$required_path" ] || { echo "${R}Missing required file: $required_path${N}" >&2; exit 1; }
done

echo "${C}Building frontend...${N}"
run_step "frontend build" bash -c 'cd frontend && pnpm install && pnpm build'

echo "${C}Packing project...${N}"
run_step "tar archive" tar czf "$TempArchive" \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='.vscode' \
    --exclude='./data' \
    --exclude="$LocalPrivateWorkspace" \
    --exclude='prod/sendkey.env' \
    --exclude='prod/sendkey.env.example' \
    --exclude='prod/README.md' \
    --exclude='prod/llbot-qq' \
    --exclude='prod/llbot-data' \
    --exclude='frontend/node_modules' \
    --exclude='./tests' \
    --exclude='test_*.py' \
    --exclude='./scripts' \
    --exclude='requirements-dev.txt' \
    --exclude='.pytest-tmp-*' \
    --exclude='*.tar' \
    --exclude='*.tar.gz' \
    .

if [ -e "$TiebaStateFile" ]; then
    echo "${C}Packing Tieba storage state...${N}"
    run_step "Tieba state archive" tar czf "$TiebaStateArchive" "$TiebaStateFile"
fi

[ -e "$TempArchive" ] || { echo "${R}Archive was not created; aborting.${N}" >&2; exit 1; }

if [ "$LocalCheck" -eq 1 ]; then
    sizeMB=$(awk -v b="$(wc -c < "$TempArchive")" 'BEGIN{printf "%.2f", b/1048576}')
    echo "${G}Local check complete. Archive size: ${sizeMB} MB${N}"
    rm -f "$TempArchive" "$TiebaStateArchive"
    exit 0
fi

echo "${C}Uploading to server...${N}"
run_step "scp archive" scp "${ssh_args[@]}" "$TempArchive" "${HostAlias}:/tmp/quickquip-deploy.tar.gz"
if [ -e "$TiebaStateArchive" ]; then
    run_step "scp Tieba state" scp "${ssh_args[@]}" "$TiebaStateArchive" "${HostAlias}:/tmp/quickquip-tieba-state.tar.gz"
fi
if [ -e "$SendkeyEnvFile" ]; then
    echo "${D}Uploading ops notification env...${N}"
    run_step "scp sendkey env" scp "${ssh_args[@]}" "$SendkeyEnvFile" "${HostAlias}:/tmp/quickquip-sendkey.env"
fi
if [ -e "$FontFile" ]; then
    echo "${D}Uploading wordcloud font...${N}"
    run_step "ssh create font dir" ssh "${ssh_args[@]}" "$HostAlias" "mkdir -p $RemoteDir/data/fonts"
    run_step "scp font" scp "${ssh_args[@]}" "$FontFile" "${HostAlias}:${RemoteDir}/data/fonts/NotoSansSC-Regular.ttf"
fi

echo "${C}Extracting and rebuilding containers...${N}"
remote_script=$(cat <<'REMOTE'
set -eu
REMOTE_DIR="__REMOTE_DIR__"
NULL_DEVICE="/d""ev/null"
mkdir -p "$REMOTE_DIR"
cd "$REMOTE_DIR"

tar xzf /tmp/quickquip-deploy.tar.gz
rm -f "$REMOTE_DIR"/test_*.py "$REMOTE_DIR/requirements-dev.txt"
rm -rf "$REMOTE_DIR/tests" "$REMOTE_DIR/scripts"

if [ -f /tmp/quickquip-sendkey.env ]; then
    mkdir -p "$REMOTE_DIR/prod"
    install -m 600 /tmp/quickquip-sendkey.env "$REMOTE_DIR/prod/sendkey.env"
fi

if [ -f /tmp/quickquip-tieba-state.tar.gz ]; then
    mkdir -p "$REMOTE_DIR/data/tieba"
    tar xzf /tmp/quickquip-tieba-state.tar.gz -C "$REMOTE_DIR"
fi

sed -i 's/\r$//' "$REMOTE_DIR/.env" 2>"$NULL_DEVICE" || true
chmod 600 "$REMOTE_DIR/.env" 2>"$NULL_DEVICE" || true

if [ -f "$REMOTE_DIR/prod/sendkey.env" ]; then
    sed -i 's/\r$//' "$REMOTE_DIR/prod/sendkey.env" 2>"$NULL_DEVICE" || true
    chmod 600 "$REMOTE_DIR/prod/sendkey.env" 2>"$NULL_DEVICE" || true
fi

if [ -d "$REMOTE_DIR/prod/llbot-data" ]; then
    LLBOT_PYTHON=python3
    for candidate in "$REMOTE_DIR/prod/llbot-data/default_config.json" "$REMOTE_DIR"/prod/llbot-data/data/config_*.json; do
        if [ -e "$candidate" ] && [ ! -w "$candidate" ]; then
            LLBOT_PYTHON="sudo -n python3"
            break
        fi
    done
    $LLBOT_PYTHON - "$REMOTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

remote_dir = Path(sys.argv[1])

def read_env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name == key:
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value
    return ""

token = read_env_value(remote_dir / ".env", "ONEBOT_ACCESS_TOKEN")
if not token:
    raise SystemExit(0)

paths = [remote_dir / "prod/llbot-data/default_config.json"]
paths.extend(sorted((remote_dir / "prod/llbot-data/data").glob("config_*.json")))
for path in paths:
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    connect = data.setdefault("ob11", {}).setdefault("connect", [])
    while len(connect) <= 1:
        connect.append({})
    connect[1]["url"] = "ws://quickquip:8080/onebot/v11/ws/"
    connect[1]["token"] = token
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    print(f"Synced LLBot OneBot reverse WebSocket config: {path}")
PY
fi

chmod 750 "$REMOTE_DIR" "$REMOTE_DIR/prod" 2>"$NULL_DEVICE" || true
if [ -f "$REMOTE_DIR/data/tieba/pool.json" ]; then
    sudo chown "$(id -u):$(id -g)" "$REMOTE_DIR/data/tieba/pool.json" 2>"$NULL_DEVICE" || true
fi

rm -f /tmp/quickquip-deploy.tar.gz /tmp/quickquip-tieba-state.tar.gz /tmp/quickquip-sendkey.env

cd "$REMOTE_DIR/prod"
docker compose --env-file ../.env config --quiet
docker compose --env-file ../.env build quickquip web-admin
docker compose --env-file ../.env up -d --remove-orphans llbot quickquip web-admin
docker compose --env-file ../.env up -d --force-recreate quickquip web-admin
docker compose --env-file ../.env ps
docker builder prune --filter 'until=48h' --force
docker image prune -f
REMOTE
)
remote_script=${remote_script//__REMOTE_DIR__/$RemoteDir}
if ! printf '%s\n' "$remote_script" | ssh "${ssh_args[@]}" "$HostAlias" "tr -d '\r' | bash -s"; then
    echo "${R}FAILED: ssh remote deploy${N}" >&2
    exit 1
fi

echo "${G}Deploy complete.${N}"
echo "${Y}QuickQuip logs: ssh $HostAlias 'cd $RemoteDir/prod && docker compose --env-file ../.env logs -f quickquip'${N}"
echo "${Y}Web Admin logs: ssh $HostAlias 'cd $RemoteDir/prod && docker compose --env-file ../.env logs -f web-admin'${N}"

rm -f "$TempArchive" "$TiebaStateArchive"
