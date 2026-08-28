#!/bin/bash
# Server-side helper for check_bot.ps1.
# Usage: bash prod/check_bot.sh [status|gen-qr|force-recreate|wait-login]

REMOTE_DIR="${REMOTE_DIR:-/opt/QuickQuip}"
NULL_DEVICE="/d""ev/null"
cd "$REMOTE_DIR/prod" 2>"$NULL_DEVICE" || { echo "ERROR: cannot cd to $REMOTE_DIR/prod"; exit 1; }

BACKEND="${BACKEND:-llbot}"
cmd="${1:-status}"

COMPOSE=(docker compose --env-file ../.env)

if [ "$cmd" = "status" ]; then
    if ! "${COMPOSE[@]}" ps "$BACKEND" 2>"$NULL_DEVICE" | grep -q 'Up'; then
        echo "OFFLINE"
        exit 0
    fi

    RECENT_DISCONNECT=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>"$NULL_DEVICE" | grep -ciE 'PMHQ WebSocket 连接关闭|PMHQ.*连接错误')
    RECENT_PMHQ=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>"$NULL_DEVICE" | grep -ciE 'PMHQ WebSocket 连接成功')
    HEARTBEAT=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>"$NULL_DEVICE" | grep -ciE 'meta_event')
    ACTIVITY=$("${COMPOSE[@]}" logs --since 5m "$BACKEND" 2>"$NULL_DEVICE" | grep -ciE '\[收-|\[发-')

    if [ "$RECENT_DISCONNECT" -gt 0 ] && [ "$RECENT_PMHQ" -eq 0 ] && [ "$HEARTBEAT" -eq 0 ]; then
        echo "OFFLINE"
    elif [ "$HEARTBEAT" -gt 0 ] || [ "$ACTIVITY" -gt 0 ]; then
        echo "ONLINE"
    elif [ "$RECENT_PMHQ" -gt 0 ]; then
        echo "ONLINE"
    else
        # QQ 进程探测：优先容器内 ps（PATH 解析，不写带 hash 的 nix store 绝对路径——
        # llonebot:latest 重建会漂移），失败回退宿主机 docker top（pmhq 启动参数含
        # /opt/QQ/qq）。按退出码 + 输出双重判定（部分 docker 版本把 exec 失败信息
        # 写到 stdout）；两路都失败说明探测本身失效，输出 UNKNOWN 而非误报
        # OFFLINE（cron_check_bot.sh 对 UNKNOWN 只记录不告警）。
        if ! PS_OUT=$(docker exec "$BACKEND" ps 2>"$NULL_DEVICE"); then
            PS_OUT=""
        fi
        if [ -z "$PS_OUT" ]; then
            if ! PS_OUT=$(docker top "$BACKEND" 2>"$NULL_DEVICE"); then
                PS_OUT=""
            fi
        fi
        if [ -z "$PS_OUT" ]; then
            echo "UNKNOWN"
            exit 0
        fi
        QQ_ALIVE=$(printf '%s\n' "$PS_OUT" | grep -c '/opt/QQ/qq' || true)
        if [ "${QQ_ALIVE:-0}" -gt 0 ] 2>"$NULL_DEVICE"; then
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
        QR=$("${COMPOSE[@]}" logs --tail=200 "$BACKEND" 2>"$NULL_DEVICE" | grep -oP '或浏览器打开二维码网址:\s*\Khttps://[^\s]+' | tail -1)
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
        LOGGED_IN=$("${COMPOSE[@]}" logs --tail=30 "$BACKEND" 2>"$NULL_DEVICE" | grep -cE 'selfNick|Connected to the websocket server')
        if [ "${LOGGED_IN:-0}" -gt 0 ] 2>"$NULL_DEVICE"; then
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
    rm -rf llbot-qq llbot-data 2>"$NULL_DEVICE" || true
    mkdir -p llbot-qq llbot-data
    "${COMPOSE[@]}" up -d "$BACKEND" 2>&1
    sleep 5
    exec bash "$0" gen-qr
fi

echo "ERROR: unknown command '$cmd'"
exit 1
