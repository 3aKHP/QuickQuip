#!/bin/bash
# Server-side release transaction. Drivers upload a private incoming directory.
set -Eeuo pipefail
umask 077

Root="${1:?deployment root required}"
Id="${2:?operation id required}"
Keep="${3:?retention count required}"
Action="${4:?action required}"
Target="${5:-}"
ConfigSync=${CONFIG_SYNC:-off}
SyncOperation=${SYNC_OPERATION:-}
[[ "$ConfigSync" =~ ^(auto|push|pull|off)$ ]] || exit 2
[[ -z "$SyncOperation" || "$SyncOperation" =~ ^[a-f0-9]{32}$ ]] || exit 2
[[ "$Action" = status || "$Action" = rollback || "$ConfigSync" = off || -n "$SyncOperation" ]] || exit 2
[[ "$Root" =~ ^/[a-zA-Z0-9_./-]+$ && "$Root" != / && "$Root" != *'/../'* ]] || exit 2
[[ "$Id" =~ ^[0-9]{8}-[0-9]{6}-[a-f0-9]{12}$ ]] || exit 2
[[ "$Keep" =~ ^[0-9]+$ && "$Keep" -ge 2 && "$Keep" -le 100 ]] || exit 2
[[ "$Action" =~ ^(deploy|migrate|rollback|status|recover)$ ]] || exit 2
[[ -z "$Target" || "$Target" =~ ^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$ ]] || exit 2

Root="$(realpath -m "$Root")"
[ "$Root" != / ] || exit 2
Incoming="$Root/.deploy/incoming/$Id"
StateTool="$Incoming/deploy-state.py"
Log="$Root/.deploy/$Id.log"
ExitFile="$Root/.deploy/$Id.exit"
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
if [ "${DETACH:-0}" = 1 ]; then
    exec 8>"$Incoming/start.lock"
    flock -n 8 || exit 1
    [ ! -e "$Incoming/started" ] || exit 0
    touch "$Incoming/started"
    "$Python" "$StateTool" durable "$Incoming" || fail "upload persistence failed"
    : > "$Log"
    ReceiptCode='import os,sys,tempfile
path=sys.argv[1]; parent=os.path.dirname(path)
fd, temporary=tempfile.mkstemp(dir=parent)
with os.fdopen(fd,"w") as stream:
    stream.write(sys.argv[2]+"\n"); stream.flush(); os.fsync(stream.fileno())
os.replace(temporary,path)
fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
try: os.fsync(fd)
finally: os.close(fd)'
    DETACH=0 EXIT_FILE="$ExitFile" DEPLOY_PYTHON="$Python" DEPLOY_RECEIPT_CODE="$ReceiptCode" setsid nohup bash -c \
        'bash "$0" "$@"; code=$?; "$DEPLOY_PYTHON" -c "$DEPLOY_RECEIPT_CODE" "$EXIT_FILE" "$code"' \
        "$0" "$@" >>"$Log" 2>&1 </dev/null 8>&- &
    exit 0
fi

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
ServicesStopped=0
RecoveryReady=0

record_transaction() {
    [ -z "$SyncOperation" ] || "$Python" "$StateTool" transaction "$Root" "$Id" \
        "$Prev" "$PrevPrevious" "$OriginalCurrent" "$Changed" "$Activated" \
        "$ServicesStopped" "$SyncOperation" "$SharedSudo"
}

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
        record_transaction
        shared_state snapshot "$Root" "$Incoming" "$Backup"
    else
        return "$code"
    fi
}

release_id() { readlink "$Root/$1" 2>/dev/null | sed 's|^releases/||' || true; }
set_link() {
    local name="$1" value="$2" temp="$Root/.${1}-$Id-$RANDOM-$RANDOM"
    if [ -z "$value" ]; then
        rm -f "$Root/$name" || return 1
    else
        ln -s "releases/$value" "$temp" && mv -Tf "$temp" "$Root/$name" || return 1
    fi
    "$Python" -c 'import os,sys; fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd)' "$Root"
}
# Seed (only when $Root/skills is missing) and merge (on every call) the
# shared skill catalog at the deployment root, beside data/. $1 = release id
# whose skills/ directory provides the merge content. Seeding prefers the
# previous current release (the catalog most recently active on this host)
# or starts empty. The merge is non-destructive: repository-added
# skills land in the catalog while existing files (including Web Admin
# installs and edits) are kept and deletions never propagate. Must run before
# any compose up, which would auto-create an empty root-owned directory.
sync_shared_skills() {
    local release="$1"
    if [ ! -d "$Root/skills" ]; then
        if [ -n "$OriginalCurrent" ] && [ -d "$Root/releases/$OriginalCurrent/skills" ]; then
            cp -a "$Root/releases/$OriginalCurrent/skills" "$Root/skills"
            step "seeded shared skills/ from previous release $OriginalCurrent"
        else
            mkdir -p "$Root/skills"
            step "created empty shared skills/ directory"
        fi
    fi
    if [ -d "$Root/releases/$release/skills" ]; then
        # The web-admin container runs as root; skills it installed can be
        # root-owned and reject the deploy user's cp. Retry with noninteractive
        # sudo and pull the whole catalog back to the deploy user.
        if cp -an "$Root/releases/$release/skills/." "$Root/skills/" 2>/dev/null; then
            step "merged release $release skills/ into shared catalog (existing files kept)"
        elif sudo -n true 2>/dev/null; then
            sudo -n cp -an "$Root/releases/$release/skills/." "$Root/skills/" \
                || fail "shared skills/ merge failed even with sudo"
            sudo -n chown -R "$(id -u):$(id -g)" "$Root/skills" \
                || fail "shared skills/ ownership restore failed"
            step "merged release $release skills/ with sudo; catalog ownership restored"
        else
            fail "shared skills/ merge failed: permission denied; fix with: sudo chown -R $(id -u):$(id -g) $Root/skills"
        fi
    fi
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
# Copy configuration assets into fresh inodes; existing candidate assets have priority.
copy_configuration_assets() {
    local mode="$1" source="$2" destination="$3" code=0 program uid gid
    uid="$(id -u)"; gid="$(id -g)"
    program="$(cat <<'PY'
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

mode, source, destination, uid, gid = sys.argv[1:]
uid, gid = int(uid), int(gid)

def directory(path):
    if path.is_symlink():
        raise ValueError("configuration destination is a symlink")
    if not path.exists():
        directory(path.parent)
        path.mkdir(mode=0o755)
        if os.geteuid() == 0:
            os.chown(path, uid, gid)

def copy_file(source, target, replace=False):
    if not replace and os.path.lexists(target):
        return
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("configuration source is not a regular file")
        directory(target.parent)
        temporary_fd, name = tempfile.mkstemp(prefix=".configuration-copy-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(temporary_fd, "wb") as output, os.fdopen(descriptor, "rb") as input:
                descriptor = None
                shutil.copyfileobj(input, output)
                output.flush()
                os.fchmod(output.fileno(), stat.S_IMODE(metadata.st_mode))
                if os.geteuid() == 0:
                    os.fchown(output.fileno(), uid, gid)
                os.fsync(output.fileno())
            os.utime(temporary, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            if replace:
                os.replace(temporary, target)
            else:
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    pass
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        if descriptor is not None:
            os.close(descriptor)

def copy_personas(source, target):
    with os.scandir(source) as entries:
        for entry in entries:
            original, copied = Path(entry.path), target / entry.name
            if mode == "migrated":
                if (entry.name.startswith("migrated-") and entry.name.endswith(".toml")
                        and entry.is_file(follow_symlinks=False)):
                    copy_file(original, copied)
            elif entry.is_dir(follow_symlinks=False):
                directory(copied)
                copy_personas(original, copied)
            else:
                copy_file(original, copied)

try:
    if mode in ("migrated", "personas", "tree"):
        copy_personas(Path(source), Path(destination))
    else:
        copy_file(Path(source), Path(destination), replace=mode == "replace")
except PermissionError:
    sys.exit(3)
except (OSError, ValueError) as error:
    print(f"configuration asset copy failed ({type(error).__name__})", file=sys.stderr)
    sys.exit(1)
PY
)"
    "$Python" -c "$program" "$mode" "$source" "$destination" "$uid" "$gid" || code=$?
    if [ "$code" = 3 ]; then
        step "configuration assets require noninteractive sudo for copying"
        sudo -n "$Python" -c "$program" "$mode" "$source" "$destination" "$uid" "$gid" \
            || fail "configuration asset copy failed with sudo; activation stopped"
    elif [ "$code" != 0 ]; then
        fail "configuration asset copy failed; activation stopped"
    fi
}
# Candidate code owns initialization; existing DB is kept across releases.
initialize_configuration() {
    local release="$1" source=""
    [ -f "$Root/releases/$release/src/quickquip/llm/config_cli.py" ] || return 0
    if [ ! -f "$Root/data/llm_config.db" ]; then
        if [ -n "$Prev" ] && [ -f "$Root/releases/$Prev/config/llm.toml" ]; then
            source="$Root/releases/$Prev/config/llm.toml"
        elif [ -f "$Root/config/llm.toml" ]; then
            source="$Root/config/llm.toml"
        fi
        if [ -n "$source" ]; then
            mkdir -p "$Root/releases/$release/config"
            copy_configuration_assets replace "$source" "$Root/releases/$release/config/llm.toml"
            local source_config candidate_config
            source_config="$(dirname "$source")"
            candidate_config="$Root/releases/$release/config"
            if [ -d "$candidate_config/personas" ]; then
                mv "$candidate_config/personas" "$candidate_config/.llm-upgrade-personas"
            fi
            if [ -d "$source_config/personas" ]; then
                copy_configuration_assets personas "$source_config/personas" "$candidate_config/personas"
            fi
            if [ -f "$candidate_config/generation.toml" ]; then
                mv "$candidate_config/generation.toml" "$candidate_config/.llm-upgrade-generation.toml"
            fi
            if [ -f "$source_config/generation.toml" ]; then
                copy_configuration_assets file "$source_config/generation.toml" "$candidate_config/generation.toml"
            fi
            step "legacy configuration selected from server for first migration"
        fi
    fi
    if [ -n "$Prev" ] && [ -z "$SyncOperation" ]; then
        local previous_config="$Root/releases/$Prev/config" candidate_config="$Root/releases/$release/config"
        if [ -d "$previous_config/personas" ]; then
            copy_configuration_assets migrated "$previous_config/personas" "$candidate_config/personas"
        fi
        if [ -d "$previous_config/client_profiles" ]; then
            copy_configuration_assets tree "$previous_config/client_profiles" "$candidate_config/client_profiles"
        fi
        if [ -f "$previous_config/generation.toml" ] && [ ! -f "$candidate_config/generation.toml" ]; then
            copy_configuration_assets file "$previous_config/generation.toml" "$candidate_config/generation.toml"
        fi
    fi
    compose "$release" run --rm --no-deps web-admin python -m quickquip.llm.config_cli init \
        >/dev/null || fail "configuration initialization failed; inspect migration report in data/"
    step "configuration schema initialized; production database retained"
}
configuration_health() {
    local release="$1"
    [ -f "$Root/releases/$release/src/quickquip/llm/config_cli.py" ] || return 0
    local container started
    container="$(compose "$release" ps -q quickquip)" || return 1
    started="$(docker inspect -f '{{.State.StartedAt}}' "$container")" || return 1
    started="$("$Python" -c 'from datetime import datetime; import sys; print(datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp())' "$started")" || return 1
    # Read the stable status payload so older releases remain valid rollback targets.
    compose "$release" exec -T web-admin python -m quickquip.llm.config_cli status --require-loaded 2>/dev/null \
        | "$Python" -c 'import json,sys; status=json.load(sys.stdin); sys.exit(0 if status["bot"]["heartbeat_at"] >= float(sys.argv[1]) else 1)' \
            "$started" >/dev/null 2>&1
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
            if ! configuration_health "$release"; then
                sleep 5
                continue
            fi
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
    if [ "$Action" = recover ] && [ "$RecoveryReady" = 0 ]; then
        step "recovery journal invalid; preserve transaction files"
        exit 2
    fi
    export QUICKQUIP_ENV_FILE="$Root/.env"
    if [ "$Succeeded" = 0 ] && [ -n "$SyncOperation" ]; then
        if [ "$Activated" = 1 ]; then
            if ! compose "$Id" stop quickquip web-admin \
                || ! compose "$Id" run --rm --no-deps web-admin python -m quickquip.config_sync.rpc \
                    recover --operation "$SyncOperation" --services-stopped; then
                step "CONFIG RECOVERY FAILED; preserve operation $SyncOperation and $Incoming"
                exit 2
            fi
        elif [ -n "$Prev" ]; then
            RecoveryArgs=()
            if [ "$Action" = recover ] || [ "$ServicesStopped" = 1 ]; then
                ServicesStopped=1
                compose "$Prev" stop quickquip web-admin || exit 2
                RecoveryArgs=(--services-stopped)
            fi
            if ! compose "$Prev" run --rm --no-deps web-admin python -m quickquip.config_sync.rpc \
                recover --operation "$SyncOperation" "${RecoveryArgs[@]}"; then
                step "CONFIG RECOVERY FAILED; preserve operation $SyncOperation and $Incoming"
                exit 2
            fi
        fi
    fi
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
    if [ "$Succeeded" = 0 ] && [ "$ServicesStopped" = 1 ] && [ "$Activated" = 0 ] && [ -n "$Prev" ]; then
        up "$Prev" && health "$Prev" || { step "RECOVERY FAILED: previous services unavailable"; exit 2; }
    fi
    if [ "$Succeeded" = 0 ] && [ -n "$SyncOperation" ] && [ -n "$Prev" ]; then
        compose "$Prev" exec -T web-admin python -m quickquip.config_sync.rpc \
            recovery-verified --operation "$SyncOperation" || { step "CONFIG RECOVERY UNVERIFIED"; exit 2; }
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
if [ "$Action" = recover ]; then
    Saved="$("$Python" "$StateTool" read-transaction "$Root" "$Id")" || fail "recovery journal unavailable"
    mapfile -t Fields <<<"$Saved"
    [ "${Fields[6]}" = "$SyncOperation" ] || fail "recovery operation mismatch"
    Prev=${Fields[0]#_}
    PrevPrevious=${Fields[1]#_}
    OriginalCurrent=${Fields[2]#_}
    Current="$(release_id current)"
    [[ "$Current" = "$Id" || "$Current" = "$Prev" ]] || fail "another release replaced the interrupted operation"
    Changed=${Fields[3]}
    SharedSudo=${Fields[7]}
    Activated=0
    [ "$Current" != "$Id" ] || Activated=1
    ServicesStopped=1
    RecoveryReady=1
    step "recovering interrupted deployment $Id"
    exit 1
fi
if [ -n "$SyncOperation" ]; then
    record_transaction
    compose "$Prev" exec -T web-admin python -m quickquip.config_sync.rpc \
        bind-deployment --operation "$SyncOperation" --release "$Id" || fail "configuration deployment binding failed"
fi

if [ "$Action" = rollback ]; then
    Target="${Target:-$PrevPrevious}"
    [[ "$Target" =~ ^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$ ]] || fail "no valid previous release"
    [ "$Target" != "$Prev" ] || fail "target is already current"
    verify_release "$Prev" || fail "current release cannot be used for recovery"
    verify_release "$Target" || fail "rollback target or image missing"
    compose "$Prev" run --rm --no-deps web-admin python -c \
        'from pathlib import Path; import sys; sys.exit(1 if Path("/app/data/config-sync/maintenance.json").exists() else 0)' \
        || fail "finish configuration synchronization before rollback"
    if [ -f "$Root/releases/$Target/src/quickquip/config_sync/rpc.py" ]; then
        printf '{"source":"published"}' | compose "$Target" run --rm --no-deps -T web-admin \
            python -m quickquip.config_sync.rpc read >/dev/null || fail "rollback configuration incompatible"
    fi
    RollbackVersion=""
    if [ -f "$Root/releases/$Target/pyproject.toml" ]; then
        RollbackVersion="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$Root/releases/$Target/pyproject.toml" | head -1)"
    fi
    RollbackVersion="${RollbackVersion:-unknown}"
    # Empty shared snapshot: manual rollback retains the current environment.
    mkdir -p "$Incoming/shared"
    mkdir -m 700 "$Backup"
    printf '[]\n' > "$Backup/index.json"
    Changed=1
    set_link current "$Target"
    Activated=1
    SkillLayout="$(compose "$Target" config --format json | "$Python" "$StateTool" skill-layout "$Root")" \
        || fail "rollback Skill mount layout could not be resolved"
    if [ "$SkillLayout" = shared ]; then
        sync_shared_skills "$Target"
    else
        step "rollback target does not use shared skills; shared catalog retained"
    fi
    up "$Target" || fail "rollback startup failed"
    health "$Target" || fail "rollback health failed"
    set_link previous "$Prev"
    Succeeded=1
    step "rollback complete: $Target ($RollbackVersion) (current credentials and data retained)"
    exit 0
fi

if [ -f "$Incoming/release.tar.gz" ]; then
    "$Python" "$StateTool" extract "$Incoming/release.tar.gz" "$Incoming/tree"
fi
"$Python" "$StateTool" validate "$Incoming/tree"
if [ "${ENV_SOURCE:-local}" = server ]; then
    [ -f "$Root/.env" ] || fail "server environment unavailable; first deployment requires --env local"
    copy_configuration_assets replace "$Root/.env" "$Incoming/shared/.env"
fi
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
    fail "flat deployment detected; use --migrate first"
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
# Version identity: deployed pyproject version + the server-side build
# timestamp captured when the image build finishes (e.g.
# 1.15.3-dev.2+build.20260909.065235). It is echoed into the transaction
# log lines below; if you maintain a private ops-trail tool, this is the
# hook point to record "$VersionId" with it.
BuildStamp="$(date +%Y%m%d.%H%M%S)"
VersionId="${DEPLOY_VERSION:-unknown}+build.$BuildStamp"
step "image built: quickquip-app:$Id ($VersionId)"
if [ -n "$SyncOperation" ]; then
    compose "$Id" run --rm --no-deps web-admin python -m quickquip.config_sync.rpc \
        stage --operation "$SyncOperation" --release "$Id" || fail "configuration stage failed"
elif [ -n "$Prev" ] && [ -f "$Release/src/quickquip/config_sync/rpc.py" ]; then
    compose "$Id" run --rm --no-deps web-admin python -m quickquip.config_sync.rpc idle \
        || fail "finish or recover pending configuration synchronization first"
    ServicesStopped=1
    compose "$Prev" stop quickquip web-admin || fail "could not pause configuration writers"
    compose "$Id" run --rm --no-deps -v "$Root/releases/$Prev:/sync-previous:ro" \
        web-admin python -m quickquip.config_sync.rpc preserve || fail "server configuration preservation failed"
fi
initialize_configuration "$Id"
DurableCode=0
"$Python" "$StateTool" durable "$Release" || DurableCode=$?
if [ "$DurableCode" = 3 ]; then
    sudo -n "$Python" "$StateTool" durable "$Release" || fail "candidate persistence failed"
elif [ "$DurableCode" != 0 ]; then
    fail "candidate persistence failed"
fi
snapshot_shared
Changed=1
record_transaction
shared_state apply "$Root" "$Incoming" "$Backup"
export QUICKQUIP_ENV_FILE="$Root/.env"
if [ -n "$SyncOperation" ]; then
    ServicesStopped=1
    record_transaction
    compose "$Prev" stop quickquip web-admin || fail "configuration consumers could not stop"
    compose "$Id" run --rm --no-deps web-admin python -m quickquip.config_sync.rpc \
        restart-fence --operation "$SyncOperation" || fail "could not fence previous bot heartbeat"
fi
Activated=1
record_transaction
set_link current "$Id"
# Must run before any compose up; see sync_shared_skills.
sync_shared_skills "$Id"
up "$Id" || fail "deployment startup failed"
if [ "${SKIP_HEALTH:-0}" = 1 ]; then
    step "health explicitly skipped; release is UNVERIFIED"
else
    health "$Id" || fail "deployment health failed"
fi
if [ -n "$SyncOperation" ]; then
    [ "${SKIP_HEALTH:-0}" = 0 ] || fail "synchronization requires health verification"
    compose "$Id" exec -T web-admin python -m quickquip.config_sync.rpc \
        candidate-commit --operation "$SyncOperation" || fail "configuration commit failed"
    compose "$Id" exec -T web-admin python -m quickquip.config_sync.rpc \
        wait --operation "$SyncOperation" || fail "configuration application failed"
fi
set_link previous "$Prev"
Succeeded=1
step "release complete: $Id ($VersionId)"
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
