#!/bin/bash
# QuickQuip Bot status checker and QR login helper (Linux local driver).
# Linux equivalent of check_bot.ps1. SSHes into the server, calls the
# server-side prod/check_bot.sh worker, and renders the QR code locally.
#
# NOTE: this file is named check_bot_local.sh (not check_bot.sh) on purpose:
# check_bot.sh is the SERVER-side worker that this script invokes remotely.
#
# Usage:
#   bash prod/check_bot_local.sh
#   bash prod/check_bot_local.sh -ForceRecreate
#
# quickquip-prod is a placeholder SSH host alias; change it via -Server.

set -u

Server="quickquip-prod"
RemoteDir="/opt/QuickQuip"
ForceRecreate=0
while [ $# -gt 0 ]; do
    case "$1" in
        -Server|--server) Server="${2:?missing value for -Server}"; shift ;;
        -RemoteDir|--remote-dir) RemoteDir="${2:?missing value for -RemoteDir}"; shift ;;
        -ForceRecreate|--force-recreate) ForceRecreate=1 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -t 1 ]; then
    C=$'\033[0;36m'; G=$'\033[0;32m'; R=$'\033[0;31m'; Y=$'\033[1;33m'; N=$'\033[0m'
else
    C=''; G=''; R=''; Y=''; N=''
fi
step() { printf '%s%s%s\n' "$C" "$*" "$N"; }
ok()   { printf '%s%s%s\n' "$G" "$*" "$N"; }
err()  { printf '%s%s%s\n' "$R" "$*" "$N" >&2; }

NULL_DEVICE="/d""ev/null"

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ProjectRoot="$(cd "$ScriptDir/.." && pwd)"

invoke_server() {
    local cmd="$1" result rc
    result=$(ssh -o StrictHostKeyChecking=no "$Server" "bash $RemoteDir/prod/check_bot.sh $cmd" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ]; then
        err "SSH failed: $result"
        return 1
    fi
    # trim leading/trailing whitespace
    result="${result#"${result%%[![:space:]]*}"}"
    result="${result%"${result##*[![:space:]]}"}"
    printf '%s' "$result"
}

step "=== QuickQuip Bot status check ==="
printf 'Server: %s\n' "$Server"

step "[1/2] Checking status..."
statusResult="$(invoke_server status)" || exit 1
status="$statusResult"

if [ "$status" = "ONLINE" ] && [ "$ForceRecreate" -eq 0 ]; then
    printf '%sBot status: %s%s\n' "$G" "$status" "$N"
    ok "Bot is online."
    exit 0
fi

printf '%sBot status: %s%s\n' "$Y" "$status" "$N"

if [ "$status" = "IDLE" ] && [ "$ForceRecreate" -eq 0 ]; then
    printf '%sContainer is running but no recent heartbeat/activity was found.%s\n' "$Y" "$N"
    printf '%sSuggested action: [G] restart LLBot to get a new QR code.%s\n' "$Y" "$N"
fi

action=""
if [ "$ForceRecreate" -eq 1 ]; then
    action="f"
else
    printf '\n'
    printf '%sAvailable actions:%s\n' "$Y" "$N"
    printf '  [G] Restart LLBot and get a new QR code\n'
    printf '  [F] Force recreate session data and start fresh\n'
    printf '  [Q] Quit\n'
    while [ "$action" != "g" ] && [ "$action" != "f" ] && [ "$action" != "q" ]; do
        read -r -p "Choose [G/F/Q]: " action
        action="$(printf '%s' "$action" | tr '[:upper:]' '[:lower:]')"
    done
fi

if [ "$action" = "q" ]; then
    echo "Canceled."
    exit 0
fi

step "[2/2] Getting QR code..."
if [ "$action" = "f" ]; then serverCmd="force-recreate"; else serverCmd="gen-qr"; fi
qrResult="$(invoke_server "$serverCmd")" || exit 1

printf '%s\n' "$qrResult"

qrUrl=""
while IFS= read -r line; do
    case "$line" in
        QR:https://*) qrUrl="${line#QR:}"; break ;;
    esac
done <<< "$qrResult"

if [ -z "$qrUrl" ]; then
    err "Could not extract QR URL from LLBot logs."
    printf 'Try WebUI via: ssh -L 3080:127.0.0.1:3080 %s, then open http://127.0.0.1:3080\n' "$Server"
    exit 1
fi

step "QR URL: $qrUrl"
echo "Rendering terminal QR code..."
echo ""

venvPy="$ProjectRoot/.venv/bin/python"
if [ -x "$venvPy" ]; then
    "$venvPy" - "$qrUrl" <<'PY'
import sys
import urllib.parse
from urllib.parse import urlparse, parse_qs

try:
    import qrcode
except ImportError:
    print('qrcode is not installed. Run: pip install qrcode')
    sys.exit(1)

url = sys.argv[1]
try:
    qs = parse_qs(urlparse(url).query)
    if qs.get('data'):
        url = urllib.parse.unquote(qs['data'][0])
except Exception:
    pass

qr = qrcode.QRCode(border=2)
qr.add_data(url)
qr.make(fit=True)
qr.print_ascii(invert=True)
print()
print('Scan the QR code with mobile QQ.')
PY
else
    printf '%sProject venv Python not found (%s)%s\n' "$Y" "$venvPy" "$N"
    printf '\n'
    echo "Copy this URL or use the WebUI tunnel:"
    printf '  %s%s%s\n' "$G" "$qrUrl" "$N"
    printf '  %sssh -L 3080:127.0.0.1:3080 %s%s\n' "$C" "$Server" "$N"
    echo "  then open http://127.0.0.1:3080"
fi

echo ""
step "Waiting for login... (up to 120 seconds)"
loginResult="$(invoke_server "wait-login 120")" || exit 1
loginStatus="$loginResult"
if [ "$loginStatus" = "ONLINE" ]; then
    ok "Bot is online."
else
    err "Timed out. Check whether the QR code was scanned."
    printf '%sIf this repeats, try: bash prod/check_bot_local.sh -ForceRecreate%s\n' "$Y" "$N"
fi
