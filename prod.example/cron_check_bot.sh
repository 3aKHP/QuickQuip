#!/bin/bash
# QuickQuip bot health check, intended for cron.
set -e

REMOTE_DIR="${REMOTE_DIR:-/opt/QuickQuip}"
NULL_DEVICE="/d""ev/null"
cd "$REMOTE_DIR/prod"

if [ -f "$REMOTE_DIR/prod/sendkey.env" ]; then
    source "$REMOTE_DIR/prod/sendkey.env"
fi
if [ -z "${SENDKEY:-}" ] && [ -z "${SERVER3_URL:-}" ]; then
    echo "ERROR: neither SENDKEY nor SERVER3_URL set"
    exit 1
fi

_notify() {
    local title="$1" desp="$2"
    if [ -n "${SENDKEY:-}" ]; then
        curl -s -X POST "https://sctapi.ftqq.com/${SENDKEY}.send" -d "title=$title" -d "desp=$desp" -o "$NULL_DEVICE"
    fi
    if [ -n "${SERVER3_URL:-}" ]; then
        curl -s -X POST "$SERVER3_URL" -d "title=$title" -d "desp=$desp" -o "$NULL_DEVICE"
    fi
}

FLAG_FILE="/tmp/quickquip_bot_offline_flag"
LOG_FILE="/tmp/quickquip_bot_check.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

STATUS=$(bash "$REMOTE_DIR/prod/check_bot.sh" status 2>&1 || echo "ERROR")
log "status=$STATUS"

case "$STATUS" in
    ONLINE)
        if [ -f "$FLAG_FILE" ]; then
            rm -f "$FLAG_FILE"
            log "Bot is back online"
        fi
        ;;
    OFFLINE)
        if [ ! -f "$FLAG_FILE" ]; then
            touch "$FLAG_FILE"
            log "Bot offline, sending notification"
            _notify "Bot offline - QR login required" "QuickQuip Bot status: $STATUS. $(date '+%Y-%m-%d %H:%M:%S')%0a%0aRun: .\prod\check_bot.ps1"
        else
            log "Bot still offline, notification already sent"
        fi
        ;;
    IDLE)
        if [ ! -f "$FLAG_FILE" ]; then
            touch "$FLAG_FILE"
            log "Bot idle, sending notification"
            _notify "Bot may be silently disconnected" "QuickQuip Bot status: $STATUS. $(date '+%Y-%m-%d %H:%M:%S')%0a%0aRun: .\prod\check_bot.ps1"
        else
            log "Bot still idle, notification already sent"
        fi
        ;;
    UNKNOWN|ERROR)
        log "Status check inconclusive: $STATUS"
        ;;
esac
