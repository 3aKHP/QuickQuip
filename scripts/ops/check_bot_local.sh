#!/bin/bash
# Read QuickQuip Bot status over SSH.
set -u

Server=""
RemoteDir=""
while [ $# -gt 0 ]; do
    case "$1" in
        -Server|--server) Server="${2:?missing value for -Server}"; shift ;;
        -RemoteDir|--remote-dir) RemoteDir="${2:?missing value for -RemoteDir}"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ProjectRoot="$(cd "$ScriptDir/../.." && pwd)"
ConnectionPython=""
for candidate in "$ProjectRoot/.venv/bin/python" "$ProjectRoot/.venv/Scripts/python.exe" python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then ConnectionPython="$candidate"; break; fi
done
[ -n "$ConnectionPython" ] || { echo "Local Python environment required" >&2; exit 1; }
Connection="$("$ConnectionPython" -m quickquip.config_sync.deployment connection --root "$ProjectRoot")" || exit 1
read -r DefaultHost DefaultRoot <<< "$Connection"
Server=${Server:-$DefaultHost}
RemoteDir=${RemoteDir:-$DefaultRoot}
[[ "$Server" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$ ]] || exit 2
[[ "$RemoteDir" =~ ^/[a-zA-Z0-9_./-]+$ && "$RemoteDir" != / && "$RemoteDir" != *..* ]] || exit 2

status="$(ssh -o StrictHostKeyChecking=accept-new "$Server" \
    "REMOTE_DIR='$RemoteDir' bash '$RemoteDir/scripts/ops/check_bot.sh' status")" || exit 1
printf 'QuickQuip Bot status: %s\n' "$status"
[ "$status" = ONLINE ]
