<!-- Generated from scripts/ops/README.md; do not edit -->

# Bot 巡检

这些程序由仓库维护；通知配置放在 `prod/sendkey.env`，应用凭据放在根 `.env`。

| 程序 | 执行位置与用途 |
|---|---|
| `check_bot_local.sh`、`check_bot.ps1` | 本地通过 SSH 查看 Bot 状态 |
| `check_bot.sh` | 检查服务器上的 Bot 容器、正向 WebSocket 连接和 OneBot 账号状态 |
| `cron_check_bot.sh` | 服务器定时巡检，按通知配置发送离线告警 |
| `host_metrics_collector.py` | 服务器采集宿主机指标到 `data/host_metrics.json` |

使用正向 WebSocket 的部署在 `prod/sendkey.env` 中设置 `ONEBOT_STATUS_API_URL`，填入 Bot 容器可访问的 OneBot HTTP API 根地址。HTTP 与 WebSocket 使用同一主机名。HTTP 使用独立令牌时，在该文件中填写 `ONEBOT_STATUS_API_TOKEN`。同一令牌的部署沿用 Bot 容器内的 `ONEBOT_ACCESS_TOKEN`。

`ONLINE` 表示 Bot 与配置的协议端已连接，且 OneBot 报告账号在线。配置了 `QQ_ACCOUNT` 时还会核对账号。`OFFLINE` 会触发离线通知。`UNKNOWN` 表示巡检无法判断，例如 HTTP API 拒绝鉴权，`UNCONFIGURED` 表示尚未设置巡检地址。协议端登录和恢复按其自身的部署说明操作。

本地命令在项目根目录执行，连接设置取自根 `.env`，也可传 `-Server` 和 `-RemoteDir`：

```bash
bash scripts/ops/check_bot_local.sh
```

新版部署将服务器程序安装到部署根的 `scripts/ops/`。配置 cron 时使用该目录，例如：

```cron
*/5 * * * * /bin/bash /opt/QuickQuip/scripts/ops/cron_check_bot.sh
* * * * * /usr/bin/python3 /opt/QuickQuip/scripts/ops/host_metrics_collector.py
```

已有 cron 指向旧位置时，在部署这些程序后调整为新路径。自定义部署根通过 `REMOTE_DIR`（巡检）和 `QUICKQUIP_ROOT`（指标采集）设置。完整配置与部署步骤见[部署指南](../../docs/admin/deployment.md)。
