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

usage() {
    cat <<USAGE
Usage: deploy-v4.sh [options]
Default action: deploy the current working tree as a new release.

Actions:
  --status             Show current/previous releases and container status
  --rollback [<id>]    Roll back to a previous release (default: previous)
  --migrate            One-time migration of a legacy flat deployment

Options:
  --dry-run            Build frontend locally and preview the upload manifest
  --skip-health        Skip the post-deploy health check (deploy/migrate only)
  --host-alias <name>  SSH host alias (default $HostAlias)
  --remote-dir <path>  Remote deployment root (default $RemoteDir)
  --keep-releases <n>  Completed releases to retain, 2..100 (default $KeepReleases)
  -h, --help           Show this help

Legacy single-dash forms (-DryRun, -Status, -Rollback, -Migrate, -SkipHealth,
-HostAlias, -RemoteDir, -KeepReleases, -LocalCheck) remain accepted as aliases.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -DryRun|--dry-run|-LocalCheck|--local-check) DryRun=1 ;;
        -Status|--status) Mode=status; Modes=$((Modes + 1)) ;;
        -Rollback|--rollback)
            Mode=rollback; Modes=$((Modes + 1))
            if [ -n "${2:-}" ] && [[ "$2" != -* ]]; then ReleaseId="$2"; shift; fi ;;
        -Migrate|--migrate) Mode=migrate; Modes=$((Modes + 1)) ;;
        -SkipHealth|--skip-health) SkipHealth=1 ;;
        -HostAlias|--host-alias) HostAlias="${2:?missing host}"; shift ;;
        -RemoteDir|--remote-dir) RemoteDir="${2:?missing root}"; shift ;;
        -KeepReleases|--keep-releases) KeepReleases="${2:?missing retention}"; shift ;;
        *) printf 'Unknown argument: %s (see --help)\n' "$1" >&2; exit 2 ;;
    esac
    shift
done
die() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

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
    [ -f .env ] || die "root .env missing"
    [ -f "$ScriptDir/deploy-manifest.txt" ] || die "manifest missing"
    Version="$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)"
    [[ "$Version" =~ ^[0-9]+(\.[0-9]+){2}([-+][0-9A-Za-z.]+)*$ ]] || die "cannot parse project version from pyproject.toml"
    (cd frontend && pnpm install --frozen-lockfile && pnpm build)
    while IFS= read -r item; do
        [[ "$item" =~ ^[a-zA-Z0-9_./-]+$ && "$item" != /* && "$item" != *..* ]] || die "invalid manifest entry"
        [ -e "$item" ] || die "manifest entry missing: $item"
    done < "$ScriptDir/deploy-manifest.txt"
    if [ "$DryRun" = 1 ]; then
        tar --exclude=__pycache__ --exclude='*.pyc' -cf /dev/null -v -T "$ScriptDir/deploy-manifest.txt"
        printf 'Preview complete; frontend built locally, no remote connection or upload. Shared files: root .env, ops scripts, and present optional assets.\n'
        printf 'Version identity for this release: v%s+build.<server build time>\n' "$Version"
        exit 0
    fi
    command -v rsync >/dev/null || die "local rsync required"
fi

# All uploads are private, unique and outside live directories.
ssh "${ssh_args[@]}" "$HostAlias" \
    "command -v rsync >/dev/null && command -v flock >/dev/null && docker compose version >/dev/null && umask 077 && mkdir -p '$RemoteDir/.deploy/incoming' && chmod 700 '$RemoteDir/.deploy' '$RemoteDir/.deploy/incoming' && mkdir '$Incoming'" \
    || die "remote prerequisites or exclusive staging directory failed"
scp "${ssh_args[@]}" "$ScriptDir/remote-deploy-v4.sh" "$ScriptDir/deploy-state.py" "$HostAlias:$Incoming/"
if [ "$Mode" = deploy ] || [ "$Mode" = migrate ]; then
    ssh "${ssh_args[@]}" "$HostAlias" "umask 077; mkdir '$Incoming/tree' '$Incoming/shared'"
    rsync -ar --chmod=D700,F600 --exclude=__pycache__ --exclude='*.pyc' "${rsync_args[@]}" \
        --files-from="$ScriptDir/deploy-manifest.txt" ./ "$HostAlias:$Incoming/tree/"
    Shared=(.env prod/check_bot.sh prod/cron_check_bot.sh)
    for item in prod/sendkey.env data/fonts/NotoSansSC-Regular.ttf data/tieba/storage_state.json; do
        [ ! -f "$item" ] || Shared+=("$item")
    done
    rsync -aR --chmod=D700,F600 "${rsync_args[@]}" "${Shared[@]}" "$HostAlias:$Incoming/shared/"
fi
ssh "${ssh_args[@]}" "$HostAlias" \
    "DEPLOY_VERSION='$Version' DETACH=1 SKIP_HEALTH=$SkipHealth bash '$Incoming/remote-deploy-v4.sh' '$RemoteDir' '$Id' '$KeepReleases' '$Mode' '$ReleaseId'" \
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
printf '%s complete. Status: bash prod/deploy-v4.sh --status --host-alias %s --remote-dir %s\n' "$Mode" "$HostAlias" "$RemoteDir"
