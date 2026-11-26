# Bot 巡检

本目录存放仓库统一维护的 Bot 在线状态检查、定时告警与宿主机指标采集脚本；巡检通知密钥保存在 `prod/sendkey.env`（参考 `prod.example/sendkey.env.example`），应用运行凭据保存在根目录 `.env`。

| 程序 | 执行位置与用途 |
|---|---|
| `check_bot_local.sh`、`check_bot.ps1` | 在本地电脑通过 SSH 查看服务器上的 Bot 状态 |
| `check_bot.sh` | 在服务器上检查 Bot 容器、正向 WebSocket 连接和 OneBot 账号状态 |
| `cron_check_bot.sh` | 服务器定时巡检入口，检测到离线时按通知配置发送告警 |
| `host_metrics_collector.py` | 服务器定时采集宿主机指标并写入 `data/host_metrics.json` |

采用正向 WebSocket 连接外部协议端时，请在 `prod/sendkey.env` 中设置 `ONEBOT_STATUS_API_URL`，填入从 Bot 容器内可访问的 OneBot HTTP API 根地址（主机名需与正向 WebSocket 地址保持一致）。若协议端的 HTTP API 使用独立鉴权令牌，可同时填写 `ONEBOT_STATUS_API_TOKEN`；共用同一令牌时会自动沿用 Bot 容器内的 `ONEBOT_ACCESS_TOKEN`。

巡检输出包含四种状态：`ONLINE` 表示 Bot 已连上配置的协议端且协议端回报 QQ 账号在线（配置了 `QQ_ACCOUNT` 时还会核对登录账号是否匹配）；`OFFLINE` 表示连接断开或账号离线，定时巡检会触发告警通知；`UNKNOWN` 表示无法完成状态判定（例如 HTTP API 拒绝鉴权）；`UNCONFIGURED` 表示尚未设置 `ONEBOT_STATUS_API_URL`。协议端自身的登录与重连请按所用协议端文档操作。

在本地电脑查看远端状态时，在项目根目录执行以下命令（默认从根目录 `.env` 读取 SSH 连接设置，也可显式传入 `-Server` 与 `-RemoteDir`）：

```bash
bash scripts/ops/check_bot_local.sh
```

使用 `deploy-v4` 发布后，服务端脚本会自动安装到服务器部署根目录下的 `scripts/ops/`。配置宿主机 `crontab` 时请指向该目录（以默认部署根目录 `/opt/QuickQuip` 为例）：

```cron
*/5 * * * * /bin/bash /opt/QuickQuip/scripts/ops/cron_check_bot.sh
* * * * * /usr/bin/python3 /opt/QuickQuip/scripts/ops/host_metrics_collector.py
```

若服务器上已有指向旧路径的定时任务，请在完成新版发布后更新为上述路径。使用自定义部署根目录时，可通过环境变量 `REMOTE_DIR`（巡检脚本）与 `QUICKQUIP_ROOT`（指标采集脚本）指定路径；完整配置与部署步骤见[云端部署指南](../../docs/admin/deployment.md)。
