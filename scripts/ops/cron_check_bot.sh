#!/bin/bash
# QuickQuip Bot health check for cron.
set -e

REMOTE_DIR="${REMOTE_DIR:-/opt/QuickQuip}"
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
        curl -s -X POST "https://sctapi.ftqq.com/${SENDKEY}.send" -d "title=$title" -d "desp=$desp" -o /dev/null
    fi
    if [ -n "${SERVER3_URL:-}" ]; then
        curl -s -X POST "$SERVER3_URL" -d "title=$title" -d "desp=$desp" -o /dev/null
    fi
}

FLAG_FILE="/tmp/quickquip_bot_offline_flag"
LOG_FILE="/tmp/quickquip_bot_check.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

STATUS=$(REMOTE_DIR="$REMOTE_DIR" bash "$REMOTE_DIR/scripts/ops/check_bot.sh" status 2>/dev/null || echo UNKNOWN)
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
            _notify "QuickQuip Bot offline" "The Bot container or its OneBot connection is offline. Check QuickQuip and the configured OneBot service. $(date '+%Y-%m-%d %H:%M:%S')"
            touch "$FLAG_FILE"
            log "Bot offline, notification sent"
        fi
        ;;
    *)
        log "Status check inconclusive: $STATUS"
        ;;
esac
