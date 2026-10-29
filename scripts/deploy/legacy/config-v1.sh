#!/usr/bin/env bash
# SSH driver for shared LLM configuration; never upload local databases during deployment.
set -euo pipefail
umask 077
HostAlias=quickquip-prod
RemoteDir=/opt/QuickQuip
Action=${1:-help}
[ "$#" = 0 ] || shift
if [ "$Action" = sync ]; then
    ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$ScriptDir/../../.."
    Python=""
    for candidate in .venv/bin/python .venv/Scripts/python.exe python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then Python="$candidate"; break; fi
    done
    [ -n "$Python" ] || { echo 'Install the local Python environment first' >&2; exit 2; }
    exec "$Python" -m quickquip.config_sync.cli "$@"
fi
File=""
Revision=""
Source=published
RequestId=""
Wait=0
Timeout=150
Operation=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --host-alias) HostAlias=${2:?}; shift 2;;
        --remote-dir) RemoteDir=${2:?}; shift 2;;
        --file) File=${2:?}; shift 2;;
        --revision) Revision=${2:?}; shift 2;;
        --source) Source=${2:?}; shift 2;;
        --request-id) RequestId=${2:?}; shift 2;;
        --wait) Wait=1; shift;;
        --timeout) Timeout=${2:?}; shift 2;;
        --operation) Operation=${2:?}; shift 2;;
        *) echo "Unknown argument: $1" >&2; exit 2;;
    esac
done
if [ "$Action" = help ] || [ "$Action" = --help ]; then
    echo 'Usage: config-v1.sh status|export|preview|import|apply|backup|restore|sync'
    echo '  --file PATH --revision N --source draft|published|N --request-id ID'
    echo '  --host-alias HOST --remote-dir /opt/QuickQuip'
    echo '  apply --wait --timeout SECONDS; status --operation ID'
    echo '  sync [init|status|resume|recover] --plan --mode auto|push|pull --from local|remote'
    exit 0
fi
[[ "$Action" =~ ^(status|export|preview|import|apply|backup|restore)$ ]] || exit 2
[[ "$HostAlias" =~ ^[A-Za-z0-9_.@-]+$ && "$HostAlias" != -* ]] || exit 2
[[ "$RemoteDir" =~ ^/[A-Za-z0-9_./-]+$ && "$RemoteDir" != / && "$RemoteDir" != *..* ]] || exit 2
[[ "$Source" =~ ^(draft|published|[0-9]+)$ ]] || exit 2
[[ "$Timeout" =~ ^[1-9][0-9]*$ ]] || exit 2
[[ -z "$Operation" || "$Operation" =~ ^[a-f0-9]{32}$ ]] || exit 2
if [[ "$Action" =~ ^(preview|import|apply)$ ]]; then
    [[ "$Revision" =~ ^[1-9][0-9]*$ ]] || { echo 'Expected --revision required' >&2; exit 2; }
fi
if [[ "$Action" =~ ^(export|preview|import|backup|restore)$ ]]; then
    [ -n "$File" ] || { echo '--file required' >&2; exit 2; }
fi
if [ "$Action" = restore ]; then
    [ -f "$File" ] && [ -f "$File.runtime.db" ] || {
        echo 'Restore requires the backup and its .runtime.db file' >&2; exit 2;
    }
fi
Revision=${Revision:-0}
TransferId="$(date -u +%Y%m%d%H%M%S)-${RANDOM}-${RANDOM}"
RequestId=${RequestId:-$TransferId}
[[ "$RequestId" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || exit 2
Transfer="$RemoteDir/data/.llm-transfer-$TransferId"
ssh "$HostAlias" "umask 077; mkdir -p '$RemoteDir/data'; mkdir '$Transfer'"
# Transfer is unique and constrained above; its cleanup cannot address unrelated server assets.
cleanup() { ssh "$HostAlias" "rm -rf '$Transfer'" >/dev/null 2>&1 || true; }
trap cleanup EXIT
if [[ "$Action" =~ ^(preview|import|restore)$ ]]; then
    [ -f "$File" ] || { echo 'Input file missing' >&2; exit 2; }
    File="$(cd "$(dirname "$File")" && pwd)/$(basename "$File")"
    scp "$File" "$HostAlias:$Transfer/input"
    ssh "$HostAlias" "chmod 600 '$Transfer/input'"
    if [ "$Action" = restore ]; then
        scp "$File.runtime.db" "$HostAlias:$Transfer/input.runtime.db"
        ssh "$HostAlias" "chmod 600 '$Transfer/input.runtime.db'"
    fi
fi
ssh "$HostAlias" bash -s -- "$RemoteDir" "$Action" "$TransferId" "$Revision" "$Source" "$RequestId" "$Wait" "$Timeout" "$Operation" <<'REMOTE'
set -euo pipefail
Root=$1 Action=$2 TransferId=$3 Revision=$4 Source=$5 RequestId=$6
Wait=$7 Timeout=$8 Operation=${9:-}
export QUICKQUIP_ROOT="$Root" QUICKQUIP_ENV_FILE="$Root/.env"
if [ -L "$Root/current" ]; then
    QUICKQUIP_RELEASE="$(basename "$(readlink "$Root/current")")"
    export QUICKQUIP_RELEASE
    cd "$Root/current/prod"
else
    cd "$Root/prod"
fi
Compose=(docker compose --env-file "$Root/.env")
CLI=(python -m quickquip.llm.config_cli)
Path="/app/data/.llm-transfer-$TransferId"
case "$Action" in
    status)
        Extra=(); [ -z "$Operation" ] || Extra=(--operation "$Operation")
        "${Compose[@]}" exec -T web-admin "${CLI[@]}" status "${Extra[@]}";;
    export) "${Compose[@]}" exec -T web-admin "${CLI[@]}" export --source "$Source" --output "$Path/output";;
    preview) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision" --preview;;
    import) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision";;
    apply)
        Extra=(); [ "$Wait" = 0 ] || Extra=(--wait --timeout "$Timeout")
        "${Compose[@]}" exec -T web-admin "${CLI[@]}" apply --expected-revision "$Revision" --request-id "$RequestId" "${Extra[@]}";;
    backup) "${Compose[@]}" exec -T web-admin "${CLI[@]}" backup "$Path/output";;
    restore)
        umask 077
        mkdir -p "$Root/.deploy"
        exec 9>"$Root/.deploy/lock"
        flock -n 9 || { echo 'Another deployment operation is active' >&2; exit 1; }
        "${Compose[@]}" run --rm --no-deps web-admin python -c \
            'from pathlib import Path; import sys; sys.exit(1 if Path("/app/data/config-sync/maintenance.json").exists() else 0)' \
            || { echo 'Finish configuration synchronization before restoring a database' >&2; exit 1; }
        "${Compose[@]}" stop quickquip web-admin
        "${Compose[@]}" run --rm --no-deps web-admin "${CLI[@]}" restore --file "$Path/input" --services-stopped
        "${Compose[@]}" up -d --no-build quickquip web-admin
        ;;
esac
# Container may run as root; enable private transfer read-back for deployment user.
for name in output output.runtime.db; do
    if [ -f "$Root/data/.llm-transfer-$TransferId/$name" ]; then
        "${Compose[@]}" exec -T web-admin python -c \
            'import os,sys; os.chmod(sys.argv[1], 0o600); os.chown(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))' \
            "$Path/$name" "$(id -u)" "$(id -g)"
    fi
done
REMOTE
if [[ "$Action" =~ ^(export|backup)$ ]]; then
    Destination="$(cd "$(dirname "$File")" && pwd)/$(basename "$File")"
    Temporary="$(mktemp "${Destination}.XXXXXX")"
    scp "$HostAlias:$Transfer/output" "$Temporary"
    if [ "$Action" = backup ]; then
        RuntimeTemporary="$(mktemp "${Destination}.runtime.db.XXXXXX")"
        scp "$HostAlias:$Transfer/output.runtime.db" "$RuntimeTemporary"
        mv "$RuntimeTemporary" "$Destination.runtime.db"
    fi
    mv "$Temporary" "$Destination"
    echo "Saved $Destination"
fi
