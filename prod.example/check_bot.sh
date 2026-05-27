#!/bin/bash
# Server-side helper for check_bot.ps1.
# Usage: bash prod/check_bot.sh [status|gen-qr|force-recreate|wait-login]

REMOTE_DIR="${REMOTE_DIR:-/opt/QuickQuip}"
cd "$REMOTE_DIR/prod" 2>/dev/null || { echo "ERROR: cannot cd to $REMOTE_DIR/prod"; exit 1; }

BACKEND="${BACKEND:-llbot}"
cmd="${1:-status}"

COMPOSE=(docker compose --env-file ../.env)

if [ "$cmd" = "status" ]; then
    if ! "${COMPOSE[@]}" ps "$BACKEND" 2>/dev/null | grep -q 'Up'; then
        echo "OFFLINE"
        exit 0
    fi

    RECENT_DISCONNECT=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>/dev/null | grep -ciE 'PMHQ WebSocket 连接关闭|PMHQ.*连接错误')
    RECENT_PMHQ=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>/dev/null | grep -ciE 'PMHQ WebSocket 连接成功')
    HEARTBEAT=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>/dev/null | grep -ciE 'meta_event')
    ACTIVITY=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>/dev/null | grep -ciE '\[收-|\[发-')

    if [ "$RECENT_DISCONNECT" -gt 0 ] && [ "$RECENT_PMHQ" -eq 0 ] && [ "$HEARTBEAT" -eq 0 ]; then
        echo "OFFLINE"
    elif [ "$HEARTBEAT" -gt 0 ] || [ "$ACTIVITY" -gt 0 ]; then
        echo "ONLINE"
    elif [ "$RECENT_PMHQ" -gt 0 ]; then
        echo "ONLINE"
    else
        QQ_ALIVE=$(docker exec "$BACKEND" /nix/store/8kk5nd62m32vmqx70jg37dmnypf9iddf-busybox-1.36.1/bin/ps aux 2>/dev/null | grep -c '/opt/QQ/qq')
        if [ "${QQ_ALIVE:-0}" -gt 0 ] 2>/dev/null; then
            echo "IDLE"
        else
            echo "OFFLINE"
        fi
    fi
    exit 0
fi

if [ "$cmd" = "gen-qr" ]; then
    echo "Restarting $BACKEND to generate new QR code..."
    "${COMPOSE[@]}" restart "$BACKEND" 2>&1
    sleep 5

    for i in $(seq 1 30); do
        sleep 1
        QR=$("${COMPOSE[@]}" logs --tail=200 "$BACKEND" 2>/dev/null | grep -oP '或浏览器打开二维码网址:\s*\Khttps://[^\s]+' | tail -1)
        if [ -n "$QR" ]; then
            echo "QR:$QR"
            exit 0
        fi
    done
    echo "ERROR: QR code URL not found in $BACKEND logs after 30s"
    exit 1
fi

if [ "$cmd" = "wait-login" ]; then
    max_wait="${2:-120}"
    for i in $(seq 1 "$max_wait"); do
        sleep 1
        LOGGED_IN=$("${COMPOSE[@]}" logs --tail=30 "$BACKEND" 2>/dev/null | grep -cE 'selfNick|Connected to the websocket server')
        if [ "${LOGGED_IN:-0}" -gt 0 ] 2>/dev/null; then
            echo "ONLINE"
            exit 0
        fi
    done
    echo "TIMEOUT"
    exit 1
fi

if [ "$cmd" = "force-recreate" ]; then
    echo "Force recreating $BACKEND container (fresh device fingerprint)..."
    "${COMPOSE[@]}" rm -sf "$BACKEND" 2>&1
    rm -rf llbot-qq llbot-data 2>/dev/null || true
    mkdir -p llbot-qq llbot-data
    "${COMPOSE[@]}" up -d "$BACKEND" 2>&1
    sleep 5
    exec bash "$0" gen-qr
fi

echo "ERROR: unknown command '$cmd'"
exit 1
