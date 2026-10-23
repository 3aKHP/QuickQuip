#!/usr/bin/env bash
# Detached configuration activation/recovery. The database journal owns its result.
set -Eeuo pipefail
umask 077
Root=${1:?deployment root required}
Operation=${2:?operation required}
Action=${3:-activate}
[[ "$Root" =~ ^/[A-Za-z0-9_./-]+$ && "$Root" != / && "$Root" != *..* ]] || exit 2
[[ "$Operation" =~ ^[a-f0-9]{32}$ ]] || exit 2
[[ "$Action" = activate || "$Action" = recover ]] || exit 2
export QUICKQUIP_ROOT="$Root" QUICKQUIP_ENV_FILE="$Root/.env"
export QUICKQUIP_RELEASE="$(basename "$(readlink "$Root/current")")"
cd "$Root/current/prod"
Compose=(docker compose --env-file "$Root/.env")
CLI=(python -m quickquip.config_sync.rpc)
exec 9>"$Root/.deploy/lock"
flock -n 9 || { echo 'Another deployment/configuration operation is running'; exit 1; }
rpc() { "${Compose[@]}" exec -T web-admin "${CLI[@]}" "$1" --operation "$Operation" "${@:2}"; }
offline_rpc() { "${Compose[@]}" run --rm --no-deps web-admin "${CLI[@]}" "$1" --operation "$Operation" "${@:2}"; }
start_services() { "${Compose[@]}" up -d --no-build --pull never --force-recreate quickquip web-admin; }
health() {
    local deadline=$((SECONDS + 150)) container started
    while [ "$SECONDS" -lt "$deadline" ]; do
        container="$("${Compose[@]}" ps -q quickquip)" || return 1
        started="$(docker inspect -f '{{.State.StartedAt}}' "$container")" || return 1
        started="$(python3 -c 'from datetime import datetime; import sys; print(datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp())' "$started")" || return 1
        if "${Compose[@]}" exec -T web-admin python -c \
            'import urllib.request; urllib.request.urlopen("http://127.0.0.1:5104/ops/", timeout=5).close()' \
            >/dev/null 2>&1 \
            && "${Compose[@]}" exec -T web-admin python -m quickquip.llm.config_cli status --require-loaded --not-before "$started" \
            >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    return 1
}
recover() {
    trap - ERR
    local current_phase
    current_phase="$(offline_rpc inspect | python3 -c 'import json,sys; print(json.load(sys.stdin)["phase"])')" || return 1
    case "$current_phase" in
        confirmed|recovered)
            offline_rpc release-terminal || return 1
            echo "Operation is already terminal: $current_phase"; return 0;;
        *)
            "${Compose[@]}" stop quickquip web-admin || return 1
            offline_rpc recover --services-stopped || return 1;;
    esac
    start_services || return 1
    health || return 1
    rpc recovery-verified || return 1
    echo "Configuration recovery verified: $Operation"
}
State="$(offline_rpc inspect)"
Decision="$(python3 -c 'import json,sys; s=json.load(sys.stdin); print(s["phase"] if s["phase"] in ("confirmed","recovered") else "deployment" if (s.get("deployment") or s.get("deployment_pending")) else s["phase"])' <<<"$State")"
if [ "$Decision" = deployment ]; then
    Deployment="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("deployment") or "")' <<<"$State")"
    if [ -n "$Deployment" ]; then
        [[ "$Deployment" =~ ^[0-9]{8}-[0-9]{6}-[a-f0-9]{12}$ ]] || exit 2
        ExitFile="$Root/.deploy/$Deployment.exit"
        if [ -f "$ExitFile" ] && [ "$(cat "$ExitFile")" = 0 ]; then
            [ "$QUICKQUIP_RELEASE" = "$Deployment" ] || { echo 'Committed release is no longer current'; exit 1; }
            health
            rpc verify-committed
            exit 0
        fi
        Runner="$Root/.deploy/incoming/$Deployment/remote-deploy-v4.sh"
        if [ ! -f "$Runner" ]; then
            # Successful cleanup can precede the final exit receipt after a host interruption.
            [ "$QUICKQUIP_RELEASE" = "$Deployment" ] || exit 1
            health
            rpc verify-committed
            python3 - "$ExitFile" <<'RECEIPT'
import os, sys, tempfile
path = sys.argv[1]
parent = os.path.dirname(path)
fd, temporary = tempfile.mkstemp(dir=parent)
with os.fdopen(fd, "w") as stream:
    stream.write("0\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
RECEIPT
            exit 0
        fi
        # Acquiring the lock above proves the original transaction is no longer running.
        flock -u 9
        exec env SYNC_OPERATION="$Operation" CONFIG_SYNC=auto bash "$Runner" \
            "$Root" "$Deployment" 4 recover ""
    elif [ "$Action" != recover ]; then
        echo 'Deployment has not started; recover this preparation before planning again'
        exit 1
    fi
fi
if [ "$Action" = recover ]; then recover; exit $?; fi
case "$Decision" in
    confirmed|recovered) offline_rpc release-terminal; exit 0;;
    committed) exit 0;;
    deployment) exit 1;;
    writing|restored) recover; exit 1;;
esac
trap 'code=$?; recover || echo "RECOVERY FAILED: inspect synchronization journal"; exit "$code"' ERR
Restart="$(python3 -c 'import json,sys; print(int(json.load(sys.stdin)["restart"]))' <<<"$State")"
if [ "$Decision" = prepared ]; then
    if [ "$Restart" = 1 ]; then
        "${Compose[@]}" stop quickquip web-admin
        offline_rpc commit
        start_services
    else
        rpc commit
    fi
fi
health
rpc wait
echo "Configuration activation verified: $Operation"
