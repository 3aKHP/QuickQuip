#!/usr/bin/env bash
# SSH driver for shared LLM configuration; never upload local databases during deployment.
set -euo pipefail
umask 077
HostAlias=quickquip-prod
RemoteDir=/opt/QuickQuip
Action=${1:-help}
[ "$#" = 0 ] || shift
File=""
Revision=""
Source=published
RequestId=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --host-alias) HostAlias=${2:?}; shift 2;;
        --remote-dir) RemoteDir=${2:?}; shift 2;;
        --file) File=${2:?}; shift 2;;
        --revision) Revision=${2:?}; shift 2;;
        --source) Source=${2:?}; shift 2;;
        --request-id) RequestId=${2:?}; shift 2;;
        *) echo "Unknown argument: $1" >&2; exit 2;;
    esac
done
if [ "$Action" = help ] || [ "$Action" = --help ]; then
    echo 'Usage: config-v1.sh status|export|preview|import|apply|backup|restore'
    echo '  --file PATH --revision N --source draft|published|N --request-id ID'
    echo '  --host-alias HOST --remote-dir /opt/QuickQuip'
    exit 0
fi
[[ "$Action" =~ ^(status|export|preview|import|apply|backup|restore)$ ]] || exit 2
[[ "$HostAlias" =~ ^[A-Za-z0-9_.@-]+$ && "$HostAlias" != -* ]] || exit 2
[[ "$RemoteDir" =~ ^/[A-Za-z0-9_./-]+$ && "$RemoteDir" != / && "$RemoteDir" != *..* ]] || exit 2
[[ "$Source" =~ ^(draft|published|[0-9]+)$ ]] || exit 2
if [[ "$Action" =~ ^(preview|import|apply)$ ]]; then
    [[ "$Revision" =~ ^[1-9][0-9]*$ ]] || { echo 'Expected --revision required' >&2; exit 2; }
fi
if [[ "$Action" =~ ^(export|preview|import|backup|restore)$ ]]; then
    [ -n "$File" ] || { echo '--file required' >&2; exit 2; }
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
fi
ssh "$HostAlias" bash -s -- "$RemoteDir" "$Action" "$TransferId" "$Revision" "$Source" "$RequestId" <<'REMOTE'
set -euo pipefail
Root=$1 Action=$2 TransferId=$3 Revision=$4 Source=$5 RequestId=$6
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
    status) "${Compose[@]}" exec -T web-admin "${CLI[@]}" status;;
    export) "${Compose[@]}" exec -T web-admin "${CLI[@]}" export --source "$Source" --output "$Path/output";;
    preview) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision" --preview;;
    import) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision";;
    apply) "${Compose[@]}" exec -T web-admin "${CLI[@]}" apply --expected-revision "$Revision" --request-id "$RequestId";;
    backup) "${Compose[@]}" exec -T web-admin "${CLI[@]}" backup "$Path/output";;
    restore)
        "${Compose[@]}" stop quickquip web-admin
        "${Compose[@]}" run --rm --no-deps web-admin "${CLI[@]}" restore --file "$Path/input" --services-stopped
        "${Compose[@]}" up -d --no-build quickquip web-admin
        ;;
esac
# Container may run as root; enable private transfer read-back for deployment user.
if [ -f "$Root/data/.llm-transfer-$TransferId/output" ]; then
    "${Compose[@]}" exec -T web-admin python -c \
        'import os,sys; os.chmod(sys.argv[1], 0o600); os.chown(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))' \
        "$Path/output" "$(id -u)" "$(id -g)"
fi
REMOTE
if [[ "$Action" =~ ^(export|backup)$ ]]; then
    Destination="$(cd "$(dirname "$File")" && pwd)/$(basename "$File")"
    Temporary="$(mktemp "${Destination}.XXXXXX")"
    scp "$HostAlias:$Transfer/output" "$Temporary"
    mv "$Temporary" "$Destination"
    echo "Saved $Destination"
fi
