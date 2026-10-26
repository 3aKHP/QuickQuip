# 巡检与登录维护

这些程序由仓库维护；通知配置放在 `prod/sendkey.env`，应用凭据放在根 `.env`。

| 程序 | 执行位置与用途 |
|---|---|
| `check_bot_local.sh`、`check_bot.ps1` | 本地通过 SSH 检查服务、展示登录二维码 |
| `check_bot.sh` | 服务器端登录状态与二维码操作 |
| `cron_check_bot.sh` | 服务器定时巡检，按通知配置发送离线告警 |
| `host_metrics_collector.py` | 服务器采集宿主机指标到 `data/host_metrics.json` |

本地命令在项目根目录执行，连接设置取自根 `.env`，也可传 `-Server` 和 `-RemoteDir`：

```bash
bash scripts/ops/check_bot_local.sh
```

新版部署将服务器程序安装到部署根的 `scripts/ops/`。配置 cron 时使用该目录，例如：

```cron
*/5 * * * * /bin/bash /opt/QuickQuip/scripts/ops/cron_check_bot.sh
* * * * * /usr/bin/python3 /opt/QuickQuip/scripts/ops/host_metrics_collector.py
```

已有 cron 指向旧位置时，在部署这些程序后调整为新路径。自定义部署根通过 `REMOTE_DIR`（巡检）和 `QUICKQUIP_ROOT`（指标采集）设置。完整配置与登录步骤见[部署指南](../../docs/admin/deployment.md)。
