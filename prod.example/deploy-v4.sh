#!/bin/bash
# Local release driver. DryRun builds locally and previews the upload manifest.
set -euo pipefail
umask 077
HostAlias="quickquip-prod"
RemoteDir="/opt/QuickQuip"
Mode=deploy
Modes=0
DryRun=0
SkipHealth=0
KeepReleases=4
ReleaseId=""
Version=""
ConfigSync=auto
EnvSource=server
ConfigPlan=0
SyncOperation=""
SyncPython=""

usage() {
    cat <<USAGE
Usage: deploy-v4.sh [options]
Default action: deploy the current working tree as a new release.

Actions:
  --status             Show current/previous releases and container status
  --rollback [<id>]    Roll back to a previous release (default: previous)
  --migrate            One-time migration of a legacy flat deployment

Options:
  --config-sync <mode> auto (default), push, pull, or off (retain server config)
  --env <source>       server (default) or local
  --plan               Read-only remote configuration plan
  --dry-run            Build frontend locally and preview the upload manifest
  --skip-health        Skip the post-deploy health check (deploy/migrate only)
  --host-alias <name>  SSH host alias (default $HostAlias)
  --remote-dir <path>  Remote deployment root (default $RemoteDir)
  --keep-releases <n>  Completed releases to retain, 2..100 (default $KeepReleases)
  -h, --help           Show this help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run|--local-check) DryRun=1 ;;
        --status) Mode=status; Modes=$((Modes + 1)) ;;
        --rollback)
            Mode=rollback; Modes=$((Modes + 1))
            if [ -n "${2:-}" ] && [[ "$2" != -* ]]; then ReleaseId="$2"; shift; fi ;;
        --migrate) Mode=migrate; Modes=$((Modes + 1)) ;;
        --skip-health) SkipHealth=1 ;;
        --config-sync) ConfigSync="${2:?missing sync mode}"; shift ;;
        --env) EnvSource="${2:?missing environment source}"; shift ;;
        --plan) ConfigPlan=1 ;;
        --host-alias) HostAlias="${2:?missing host}"; shift ;;
        --remote-dir) RemoteDir="${2:?missing root}"; shift ;;
        --keep-releases) KeepReleases="${2:?missing retention}"; shift ;;
        *) printf 'Unknown argument: %s (see --help)\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
die() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }
TmpManifest=""
cleanup() { if [ -n "$TmpManifest" ]; then rm -f "$TmpManifest"; fi; }
trap cleanup EXIT

[[ "$ConfigSync" =~ ^(auto|push|pull|off)$ ]] || die "invalid configuration sync mode"
[[ "$EnvSource" =~ ^(server|local)$ ]] || die "invalid environment source"
[[ "$ConfigPlan" = 0 || ( "$Mode" = deploy && "$DryRun" = 0 && "$SkipHealth" = 0 ) ]] || die "plan supports deployment only"
[[ "$SkipHealth" = 0 || "$ConfigSync" = off ]] || die "skip-health requires --config-sync off"
[[ "$Modes" -le 1 ]] || die "choose only one action"
[[ "$DryRun" = 0 || ( "$Mode" = deploy && "$SkipHealth" = 0 ) ]] || die "DryRun supports deployment preview only"
[[ "$SkipHealth" = 0 || "$Mode" = deploy || "$Mode" = migrate ]] || die "SkipHealth supports deploy/migrate only"
[[ "$RemoteDir" =~ ^/[a-zA-Z0-9_./-]+$ && "$RemoteDir" != / && "$RemoteDir" != *'/../'* ]] || die "use an absolute root with letters, digits, dot, slash, underscore or hyphen"
[[ "$HostAlias" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ ]] || die "invalid SSH alias"
[[ "$KeepReleases" =~ ^[0-9]+$ && "$KeepReleases" -ge 2 && "$KeepReleases" -le 100 ]] || die "KeepReleases must be 2..100"
[[ -z "$ReleaseId" || "$ReleaseId" =~ ^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$ ]] || die "invalid release id"

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ScriptDir/.."
[ ! -d prod/prod.example ] || die "nested prod/prod.example; move it aside and initialize prod again"
for file in remote-deploy-v4.sh deploy-state.py; do
    [ -f "$ScriptDir/$file" ] || die "missing $file"
done
Id="$(date -u +%Y%m%d-%H%M%S)-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
Incoming="$RemoteDir/.deploy/incoming/$Id"
ssh_args=(-o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
rsync_args=(--rsh "ssh ${ssh_args[*]}")

if [ "$Mode" = deploy ] || [ "$Mode" = migrate ]; then
    if [ "$EnvSource" = local ]; then [ -f .env ] || die "root .env missing"; fi
    if [ "$DryRun" = 0 ] && [ "$ConfigSync" != off ]; then
        for candidate in .venv/bin/python .venv/Scripts/python.exe python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then SyncPython="$candidate"; break; fi
        done
        [ -n "$SyncPython" ] || die "local Python environment required for configuration sync"
        if [ "$ConfigPlan" = 1 ]; then
            exec "$SyncPython" -m quickquip.config_sync.cli --plan --mode "$ConfigSync" --host-alias "$HostAlias" --remote-dir "$RemoteDir"
        fi
    elif [ "$ConfigPlan" = 1 ]; then
        die "--plan requires a synchronization mode"
    fi
    [ -f "$ScriptDir/deploy-manifest.txt" ] || die "manifest missing"
    Version="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"
    [[ "$Version" =~ ^[0-9]+(\.[0-9]+){2}([-+][0-9A-Za-z.]+)*$ ]] || die "cannot parse project version from pyproject.toml"
    (cd frontend && pnpm install --frozen-lockfile && pnpm build)
    while IFS= read -r item; do
        [[ "$item" =~ ^[a-zA-Z0-9_./-]+$ && "$item" != /* && "$item" != *..* ]] || die "invalid manifest entry"
        [ -e "$item" ] || die "manifest entry missing: $item"
    done < "$ScriptDir/deploy-manifest.txt"
    UploadManifest="$ScriptDir/deploy-manifest.txt"
    if [ -d skills ]; then
        TmpManifest="$(mktemp "${TMPDIR:-/tmp}/quickquip-manifest.XXXXXX")"
        cat "$UploadManifest" > "$TmpManifest"
        printf 'skills\n' >> "$TmpManifest"
        UploadManifest="$TmpManifest"
    fi
    if [ -d skills.example ]; then
        # Preset skill drift report (best-effort): prints missing/diverged
        # preset skills and the sync command; never blocks the deployment.
        SyncPy=""
        for candidate in .venv/bin/python python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then SyncPy="$candidate"; break; fi
        done
        if [ -n "$SyncPy" ]; then
            "$SyncPy" scripts/sync_preset_skills.py --check || true
        fi
    fi
    if [ "$DryRun" = 1 ]; then
        tar --exclude=__pycache__ --exclude='*.pyc' --exclude='config/llm.toml' --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' -cf /dev/null -v -T "$UploadManifest"
        printf 'Preview complete; frontend built locally, no remote connection or upload. Shared files: root .env, ops scripts, and present optional assets.\n'
        printf 'Version identity for this release: v%s+build.<server build time>\n' "$Version"
        exit 0
    fi
    command -v rsync >/dev/null || die "local rsync required"
    if [ "$ConfigSync" != off ]; then
        SyncOperation="$("$SyncPython" -m quickquip.config_sync.cli deploy-prepare --mode "$ConfigSync" --host-alias "$HostAlias" --remote-dir "$RemoteDir")" || die "configuration preparation failed; inspect sync status"
        [[ "$SyncOperation" =~ ^[a-f0-9]{32}$ ]] || die "invalid synchronization operation"
        printf 'Configuration operation: %s
' "$SyncOperation"
    fi
fi

# All uploads are private, unique and outside live directories.
ssh "${ssh_args[@]}" "$HostAlias" \
    "command -v rsync >/dev/null && command -v flock >/dev/null && docker compose version >/dev/null && umask 077 && mkdir -p '$RemoteDir/.deploy/incoming' && chmod 700 '$RemoteDir/.deploy' '$RemoteDir/.deploy/incoming' && mkdir '$Incoming'" \
    || die "remote prerequisites or exclusive staging directory failed"
scp "${ssh_args[@]}" "$ScriptDir/remote-deploy-v4.sh" "$ScriptDir/deploy-state.py" "$HostAlias:$Incoming/"
if [ "$Mode" = deploy ] || [ "$Mode" = migrate ]; then
    ssh "${ssh_args[@]}" "$HostAlias" "umask 077; mkdir '$Incoming/tree' '$Incoming/shared'"
    rsync -ar --chmod=D700,F600 --exclude=__pycache__ --exclude='*.pyc' --exclude='config/llm.toml' --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' "${rsync_args[@]}" \
        --files-from="$UploadManifest" ./ "$HostAlias:$Incoming/tree/"
    Shared=(prod/check_bot.sh prod/cron_check_bot.sh)
    if [ "$EnvSource" = local ]; then
        Shared+=(.env)
    fi
    for item in prod/sendkey.env data/fonts/NotoSansSC-Regular.ttf data/tieba/storage_state.json prod/host_metrics_collector.py; do
        [ ! -f "$item" ] || Shared+=("$item")
    done
    rsync -aR --chmod=D700,F600 "${rsync_args[@]}" "${Shared[@]}" "$HostAlias:$Incoming/shared/"
fi
ssh "${ssh_args[@]}" "$HostAlias" \
    "DEPLOY_VERSION='$Version' DETACH=1 SKIP_HEALTH=$SkipHealth ENV_SOURCE='$EnvSource' CONFIG_SYNC='$ConfigSync' SYNC_OPERATION='$SyncOperation' bash '$Incoming/remote-deploy-v4.sh' '$RemoteDir' '$Id' '$KeepReleases' '$Mode' '$ReleaseId'" \
    || die "launch uncertain; inspect $RemoteDir/.deploy/$Id.log and .exit before retrying"
Log="$RemoteDir/.deploy/$Id.log"
ExitFile="$RemoteDir/.deploy/$Id.exit"
attempts=0
until ssh "${ssh_args[@]}" "$HostAlias" \
    "while [ ! -f '$ExitFile' ]; do sleep 1; done & watcher=\$!; tail -n +1 -f --pid=\$watcher '$Log'; wait \$watcher"; do
    attempts=$((attempts + 1))
    [ "$attempts" -le 20 ] || die "connection lost; remote action may continue: $Log"
    sleep 5
done
code="$(ssh "${ssh_args[@]}" "$HostAlias" "cat '$ExitFile'")" || die "cannot read completion status: $ExitFile"
[ "$code" = 0 ] || die "remote action failed (exit $code): $Log"
if [ -n "$SyncOperation" ]; then
    "$SyncPython" -m quickquip.config_sync.cli deploy-finish --operation "$SyncOperation" --host-alias "$HostAlias" --remote-dir "$RemoteDir" || die "deployment finished; configuration acknowledgement needs resume"
fi
printf '%s complete. Status: bash prod/deploy-v4.sh --status --host-alias %s --remote-dir %s\n' "$Mode" "$HostAlias" "$RemoteDir"
