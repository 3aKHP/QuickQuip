# NapCat → LLBot 迁移指南

QuickQuip 设计之初即以 NapCat（Docker 镜像 `mlikiowa/napcat-docker`）作为推荐的 OneBot V11 QQ 协议适配器。截至 2026 年 5 月中下旬，NapCat 遭遇腾讯高强度风控打击，社区和我们的生产环境均反复出现以下问题：

1. **频繁 KickedOffLine**：上线后数小时内被强制踢下线
2. **静默掐断**：QQ 连接无任何错误日志直接停止推送消息，手机端 QQ 同步被踢，疑似封号前兆
3. 尝试 NapCat 反检测构建（[PR #1768](https://github.com/NapNeko/NapCatQQ/pull/1768)）后仍无法稳定

社区反馈（[Issue #1728](https://github.com/NapNeko/NapCatQQ/issues/1728)）确认此问题广泛存在。经评估其他 OneBot V11 方案后，推荐迁移至 [LLBot](https://github.com/LLOneBot/LuckyLilliaBot)（LuckyLilliaBot）。

## 为什么选 LLBot

| | NapCat | LLBot |
|---|---|---|
| 原理 | DLL 注入 QQ 进程 | PMHQ 外部内存 Hook（独立进程） |
| 被检测面 | QQ 进程内 DLL 模块可被扫描 | QQ 进程空间无修改，更难检测 |
| Docker 镜像 | `mlikiowa/napcat-docker`（~1.2GB） | `initialencounter/llonebot:latest`（~880MB） |
| 签名服务器 | 无需（QQ 自带） | 无需（QQ 自带） |
| 社区活跃度 | 9k+ stars | 3.3k+ stars，日更 |
| OneBot V11 兼容 | 反向 WS、正向 WS | 反向 WS、正向 WS、HTTP、HTTP POST |

核心区别：NapCat 把 DLL **塞进 QQ 进程内部**，腾讯可以扫描进程空间检测到外挂模块。LLBot 使用 **PMHQ（Pure Memory Hook for QQNT）**——一个独立进程通过 Linux 内存机制从外部与 QQ 交互，QQ 进程本身干干净净。

**QuickQuip 核心业务代码无需任何改动**——两者均通过标准 OneBot V11 反向 WebSocket 与 NoneBot 通信，接口完全一致。

## 迁移步骤

以下步骤基于 `docker-compose.example.yml` 的结构。如果你的部署使用了自定义 compose 文件，请对应调整。

### 1. 在 `docker-compose.yml` 中新增 LLBot 服务

```yaml
services:
  llbot:
    image: initialencounter/llonebot:latest
    container_name: llbot
    entrypoint:
      - /entrypoint.sh
    environment:
      - QUICK_LOGIN_QQ=${QQ_ACCOUNT:?请设置 QQ 号}
      - TZ=Asia/Shanghai
    ports:
      - "127.0.0.1:3001:3001"       # OneBot WebSocket（正向，备用）
      - "127.0.0.1:3080:3080"       # WebUI（扫码登录 / 配置管理）
    volumes:
      - ./llbot-qq:/root/.config/QQ        # 登录态持久化（关键，切勿丢失）
      - ./llbot-data:/root/llonebot         # 配置文件 + 运行时数据
      - ./llbot-entrypoint.sh:/entrypoint.sh:ro   # DNS 修复 wrapper
    restart: unless-stopped
```

**重要**：LLBot 镜像的入口脚本会将容器 DNS 指向公网服务器，导致无法解析 Docker Compose 内部服务名。需挂载修复脚本（见下方）。

### 2. 创建 DNS 修复脚本

在 compose 同目录下创建 `llbot-entrypoint.sh`：

```bash
#!/bin/sh
echo 'nameserver 127.0.0.11' > /etc/resolv.conf
echo 'options ndots:0' >> /etc/resolv.conf
exec /bin/llonebot-service
```

```bash
chmod +x llbot-entrypoint.sh
```

### 3. 创建 OneBot 配置文件

LLBot 的配置为 JSON 格式，位于 `llbot-data/default_config.json`。最小配置（启用反向 WS）：

```json
{
  "webui": { "enable": true, "host": "", "port": 3080 },
  "ob11": {
    "enable": true,
    "connect": [
      {
        "type": "ws-reverse",
        "enable": true,
        "url": "ws://quickquip:8080/onebot/v11/ws/",
        "heartInterval": 60000,
        "token": "",
        "messageFormat": "array"
      }
    ]
  },
  "log": true,
  "msgCacheExpire": 120
}
```

> **注意**：容器首次启动时入口脚本会用内置默认配置覆盖此文件。建议先启动容器完成首次登录，再通过 WebUI（`http://<服务器IP>:3080`）配置反向 WS，或使用 `docker exec` 修改 `data/config_<QQ号>.json`。

### 4. 更新 QuickQuip 服务

在 compose 中将 QuickQuip 的 `depends_on` 和 `ONEBOT_WS_URLS` 更新为指向 LLBot：

```yaml
quickquip:
  depends_on:
    - llbot
  environment:
    ONEBOT_WS_URLS: '${ONEBOT_WS_URLS:-["ws://llbot:3001/"]}'
```

### 5. 启动并扫码登录

```bash
docker compose up -d llbot
# 查看日志获取二维码或访问 WebUI
docker compose logs -f llbot
# 或者浏览器打开 http://<服务器IP>:3080
```

扫码完成后重启 QuickQuip 建立新连接：

```bash
docker compose restart quickquip
```

验证连接成功：

```bash
docker compose logs quickquip | grep "Bot.*connected"
# 应输出: OneBot V11 | Bot <你的QQ号> connected
```

### 6. 移除旧 NapCat 服务（验证稳定后）

```bash
docker compose stop napcat
# 观察 24-48 小时确认稳定后
docker compose rm napcat
```

NapCat 的登录态和数据卷（`napcat-data/`）建议在确认稳定前保留，以便快速回退。

## OneBot WS 模式说明

LLBot 同时支持正向和反向 WebSocket。QuickQuip 的默认 `~fastapi` driver 使用**反向 WS**——LLBot 作为客户端连接到 QuickQuip 的 `/onebot/v11/ws/` 端点。这与 NapCat 时期的行为完全一致，无需调整 NoneBot 配置。

正向 WS（端口 3001）作为备用保留，`ONEBOT_WS_URLS` 中的默认值即指向此端口。

## 已知差异

| 项 | NapCat | LLBot | 影响 |
|---|---|---|---|
| 长消息限制 | ~667 汉字截断 | 更高（未实测） | 800 字分块策略对两者均有效 |
| QQ 版本 | 3.2.28 | 3.2.25 | 略旧，腾讯可能未来强制升级 |
| 自动登录 | `ACCOUNT` 环境变量 | `QUICK_LOGIN_QQ` 环境变量（可能不生效） | 重启后可能需要重新扫码 |
| WebUI 端口 | 6099 | 3080 | SSH 隧道端口变更 |
| 日志格式 | `账号状态变更为在线` | `PMHQ WebSocket 连接成功` | 如有自定义监控需适配 |

## 回退步骤

如 LLBot 出现严重问题：

```bash
# 停止 LLBot
docker compose stop llbot

# 恢复 ONEBOT_WS_URLS
# 将 .env 或 compose 中的 ws://llbot:3001/ 改回 ws://napcat:6099

# 恢复 depends_on（如有改动）

# 重启 QuickQuip
docker compose restart quickquip

# 启动 NapCat
docker compose start napcat
```

## 参考

- [LLBot 官方文档](https://luckylillia.com)
- [NapCat Issue #1728 - 风控掉线讨论](https://github.com/NapNeko/NapCatQQ/issues/1728)
- [NapCat PR #1768 - 反检测实验分支](https://github.com/NapNeko/NapCatQQ/pull/1768)
