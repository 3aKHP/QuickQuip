#!/bin/bash
# Server-side release transaction. Drivers upload a private incoming directory.
set -Eeuo pipefail
umask 077

Root="${1:?deployment root required}"
Id="${2:?operation id required}"
Keep="${3:?retention count required}"
Action="${4:?action required}"
Target="${5:-}"
[[ "$Root" =~ ^/[a-zA-Z0-9_./-]+$ && "$Root" != / && "$Root" != *'/../'* ]] || exit 2
[[ "$Id" =~ ^[0-9]{8}-[0-9]{6}-[a-f0-9]{12}$ ]] || exit 2
[[ "$Keep" =~ ^[0-9]+$ && "$Keep" -ge 2 && "$Keep" -le 100 ]] || exit 2
[[ "$Action" =~ ^(deploy|migrate|rollback|status)$ ]] || exit 2
[[ -z "$Target" || "$Target" =~ ^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$ ]] || exit 2

Root="$(realpath -m "$Root")"
[ "$Root" != / ] || exit 2
Incoming="$Root/.deploy/incoming/$Id"
StateTool="$Incoming/deploy-state.py"
Log="$Root/.deploy/$Id.log"
ExitFile="$Root/.deploy/$Id.exit"
if [ "${DETACH:-0}" = 1 ]; then
    exec 8>"$Incoming/start.lock"
    flock -n 8 || exit 1
    [ ! -e "$Incoming/started" ] || exit 0
    touch "$Incoming/started"
    : > "$Log"
    DETACH=0 EXIT_FILE="$ExitFile" setsid nohup bash -c \
        'bash "$0" "$@"; code=$?; printf "%s\n" "$code" > "$EXIT_FILE"' \
        "$0" "$@" >>"$Log" 2>&1 </dev/null 8>&- &
    exit 0
fi

step() { printf '[deploy] %s\n' "$*"; }
fail() { step "FAILED: $*" >&2; exit 1; }
Python=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; assert sys.version_info >= (3, 11, 8)' 2>/dev/null; then
        Python="$candidate"
        break
    fi
done
[ -n "$Python" ] || fail "Python >= 3.11.8 required on server"
export QUICKQUIP_ROOT="$Root"
export QUICKQUIP_ENV_FILE="$Root/.env"
Release="$Root/releases/$Id"
Backup="$Incoming/backup"
Prev=""
OriginalCurrent=""
PrevPrevious=""
Changed=0
Activated=0
Succeeded=0
SharedSudo=0

shared_state() {
    if [ "$SharedSudo" = 1 ]; then
        sudo -n "$Python" "$StateTool" "$@"
    else
        "$Python" "$StateTool" "$@"
    fi
}
snapshot_shared() {
    local code=0
    shared_state snapshot "$Root" "$Incoming" "$Backup" || code=$?
    if [ "$code" = 3 ]; then
        rm -rf "$Backup"
        step "shared files require sudo; retrying snapshot with noninteractive sudo"
        SharedSudo=1
        shared_state snapshot "$Root" "$Incoming" "$Backup"
    else
        return "$code"
    fi
}

release_id() { readlink "$Root/$1" 2>/dev/null | sed 's|^releases/||' || true; }
set_link() {
    local name="$1" value="$2" temp="$Root/.${1}-$Id"
    if [ -z "$value" ]; then rm -f "$Root/$name"; return 0; fi
    ln -s "releases/$value" "$temp" && mv -Tf "$temp" "$Root/$name"
}
compose() {
    local release="$1"; shift
    QUICKQUIP_RELEASE="$release" docker compose --env-file "$QUICKQUIP_ENV_FILE" \
        -f "$Root/releases/$release/prod/docker-compose.yml" "$@"
}
verify_release() {
    local release="$1" image images
    [ -f "$Root/releases/$release/prod/docker-compose.yml" ] || return 1
    compose "$release" config --quiet || return 1
    images="$(compose "$release" config --images)" || return 1
    [ -n "$images" ] || return 1
    while IFS= read -r image; do
        docker image inspect "$image" >/dev/null || return 1
    done <<< "$images"
}
up() {
    compose "$1" up -d --no-build --pull never --remove-orphans llbot || return 1
    compose "$1" up -d --no-build --pull never --force-recreate --remove-orphans quickquip web-admin
}
health() {
    local release="$1" deadline=$((SECONDS + ${DEPLOY_HEALTH_TIMEOUT:-150})) bad container service
    while [ "$SECONDS" -lt "$deadline" ]; do
        bad=0
        for service in llbot quickquip web-admin; do
            container="$(compose "$release" ps -q "$service")" || return 1
            [ -n "$container" ] && [ "$(docker inspect -f '{{.State.Running}}' "$container")" = true ] || bad=1
        done
        if [ "$bad" = 0 ] \
            && compose "$release" logs --tail 500 quickquip 2>&1 | grep -E 'Bot [0-9]+ connected' >/dev/null \
            && compose "$release" exec -T web-admin python -c \
                'import urllib.request; urllib.request.urlopen("http://127.0.0.1:5104/ops/", timeout=5).close()' >/dev/null 2>&1; then
            step "health PASS: $release"
            return 0
        fi
        sleep 5
    done
    step "health FAILED: $release"
    compose "$release" logs --tail 30 quickquip web-admin || true
    return 1
}
finish() {
    local code=$? restored=1
    trap - EXIT INT TERM
    export QUICKQUIP_ENV_FILE="$Root/.env"
    if [ "$Succeeded" = 0 ] && [ "$Changed" = 1 ]; then
        step "restoring shared files and previous release: ${Prev:-none}"
        shared_state restore "$Root" "$Backup" || restored=0
        if [ "$Activated" = 1 ]; then
            set_link current "$Prev" || restored=0
        else
            set_link current "$OriginalCurrent" || restored=0
        fi
        set_link previous "$PrevPrevious" || restored=0
        if [ "$Activated" = 1 ]; then
            if [ -n "$Prev" ]; then
                if ! verify_release "$Prev" || ! up "$Prev" || ! health "$Prev"; then restored=0; fi
            else
                step "no previous release exists; manual recovery required"
                restored=0
            fi
        fi
        if [ "$restored" = 1 ]; then
            step "RECOVERY SUCCEEDED; requested action failed"
        else
            step "RECOVERY FAILED; containers may be unavailable; preserve $Incoming"
            exit 2
        fi
    fi
    # Secrets are transient; retain only logs and numeric exit status.
    if [ "$SharedSudo" = 1 ]; then sudo -n rm -rf "$Backup" || exit 2; fi
    rm -rf "$Incoming"
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$Action" = status ]; then
    step "current: $(release_id current); previous: $(release_id previous)"
    Current="$(release_id current)"
    if [ -n "$Current" ]; then
        compose "$Current" ps -a
    elif [ -f "$Root/prod/docker-compose.yml" ]; then
        docker compose --env-file "$Root/.env" -f "$Root/prod/docker-compose.yml" ps -a
    fi
    exit 0
fi
exec 9>"$Root/.deploy/lock"
flock -n 9 || fail "another deployment is active; retry after it finishes"
mkdir -p "$Root/releases"
Prev="$(release_id current)"
OriginalCurrent="$Prev"
PrevPrevious="$(release_id previous)"

if [ "$Action" = rollback ]; then
    Target="${Target:-$PrevPrevious}"
    [[ "$Target" =~ ^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$ ]] || fail "no valid previous release"
    [ "$Target" != "$Prev" ] || fail "target is already current"
    verify_release "$Prev" || fail "current release cannot be used for recovery"
    verify_release "$Target" || fail "rollback target or image missing"
    # Empty shared snapshot: manual rollback retains the current environment.
    mkdir -p "$Incoming/shared"
    mkdir -m 700 "$Backup"
    printf '[]\n' > "$Backup/index.json"
    Changed=1
    set_link current "$Target"
    Activated=1
    up "$Target" || fail "rollback startup failed"
    health "$Target" || fail "rollback health failed"
    set_link previous "$Prev"
    Succeeded=1
    step "rollback complete: $Target (current credentials and data retained)"
    exit 0
fi

if [ -f "$Incoming/release.tar.gz" ]; then
    "$Python" "$StateTool" extract "$Incoming/release.tar.gz" "$Incoming/tree"
fi
"$Python" "$StateTool" validate "$Incoming/tree"
[ -f "$Incoming/shared/.env" ] || fail "staged environment missing"
if [ "$Action" = migrate ]; then
    [ -z "$Prev" ] || fail "already migrated"
    [ -f "$Root/.env" ] || fail "flat layout .env missing"
    Baseline="$Id-baseline"
    "$Python" "$StateTool" baseline "$Root" "$Root/releases/$Baseline"
    verify_release "$Baseline" || fail "baseline verification failed"
    # Existing containers retain their original bind mounts until first activation.
    Prev="$Baseline"
elif [ -z "$Prev" ] && [ -f "$Root/prod/docker-compose.yml" ]; then
    fail "flat deployment detected; use -Migrate first"
fi
[ -z "$Prev" ] || verify_release "$Prev" || fail "previous release lacks a usable image; repair it before deploying"
[ ! -e "$Release" ] || fail "release id already exists"
mkdir -m 700 "$Release"
LinkDest=()
[ -z "$Prev" ] || LinkDest=(--link-dest="$Root/releases/$Prev/")
rsync -ar --chmod=D755,F644 --exclude=__pycache__ --exclude='*.pyc' \
    "${LinkDest[@]}" "$Incoming/tree/" "$Release/"
chmod 700 "$Release"
export QUICKQUIP_ENV_FILE="$Incoming/shared/.env"
compose "$Id" config --quiet
# Resolved values stay within the private transaction and never enter the release.
compose "$Id" config --format json > "$Incoming/candidate-compose.json"
llbot_image="$(compose "$Id" config --images llbot)"
if ! docker image inspect "$llbot_image" >/dev/null 2>&1; then
    pulled=0
    for attempt in 1 2 3; do
        if compose "$Id" pull llbot; then pulled=1; break; fi
        sleep 10
    done
    [ "$pulled" = 1 ] || fail "LLBot pull failed before activation"
fi
compose "$Id" build quickquip
snapshot_shared
Changed=1
shared_state apply "$Root" "$Incoming" "$Backup"
export QUICKQUIP_ENV_FILE="$Root/.env"
set_link current "$Id"
Activated=1
up "$Id" || fail "deployment startup failed"
if [ "${SKIP_HEALTH:-0}" = 1 ]; then
    step "health explicitly skipped; release is UNVERIFIED"
else
    health "$Id" || fail "deployment health failed"
fi
set_link previous "$Prev"
Succeeded=1
step "release complete: $Id"
# Only collect completed deployments; never remove current, previous or baselines.
touch "$Release/.complete"
count=0
while IFS= read -r stale; do
    count=$((count + 1))
    [ "$count" -gt "$Keep" ] || continue
    [ "$stale" != "$Id" ] && [ "$stale" != "$Prev" ] || continue
    rm -rf "$Root/releases/$stale"
    docker rmi "quickquip-app:$stale" >/dev/null 2>&1 || true
done < <(find "$Root/releases" -mindepth 2 -maxdepth 2 -name .complete -printf '%h\n' | sort -r | sed 's|.*/||')
