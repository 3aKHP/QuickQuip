# NapCat → LLBot 迁移指南

> **历史迁移记录**：本文档记录 QuickQuip 2026-05 从 NapCat 迁移到 LLBot 时的决策背景、迁移步骤与回退思路，保留当时的版本与环境前提。当前适配器状态与选择见 [onebot-adapters.md](onebot-adapters.md)，现行部署流程见 [deployment.md](deployment.md)。

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
| Docker 镜像 | `mlikiowa/napcat-docker`（迁移时实测 ~1.2GB） | `initialencounter/llonebot:v7.12.14-7.3.2-45758`（迁移时实测 ~880MB） |
| 签名服务器 | 无需（QQ 自带） | 无需（QQ 自带） |
| 社区活跃度 | 9k+ stars（迁移时） | 3.3k+ stars，日更（迁移时） |
| OneBot V11 兼容 | 反向 WS、正向 WS | 反向 WS、正向 WS、HTTP、HTTP POST |

核心区别：NapCat 把 DLL **塞进 QQ 进程内部**，腾讯可以扫描进程空间检测到外挂模块。LLBot 使用 **PMHQ（Pure Memory Hook for QQNT）**——一个独立进程通过 Linux 内存机制从外部与 QQ 交互，QQ 进程本身干干净净。

**QuickQuip 核心业务代码无需任何改动**——两者均通过标准 OneBot V11 WebSocket（QuickQuip 默认正向，也支持反向）与 NoneBot 通信，接口完全一致。

## 迁移步骤

以下步骤面向已有 NapCat 部署者，基于当时 `docker-compose.example.yml` 的结构，示例统一使用反向 WS。命令在已有部署的 `docker-compose.yml` 所在目录执行；自定义服务名、文件路径和连接配置按原部署调整。先保留原 Compose 与 `.env` 的副本，供回退时恢复。

### 1. 在 `docker-compose.yml` 中新增 LLBot 服务

```yaml
services:
  llbot:
    image: initialencounter/llonebot:v7.12.14-7.3.2-45758  # 版本选择与 pin 原因见 onebot-adapters.md 的 LLBot profile
    container_name: llbot
    entrypoint:
      - /bin/sh
      - -c
      - "(sleep 5 && echo 'nameserver 127.0.0.11' > /etc/resolv.conf && echo 'options ndots:0' >> /etc/resolv.conf) & exec /bin/llonebot-service"
    environment:
      - QUICK_LOGIN_QQ=${QQ_ACCOUNT:?请设置 QQ 号}
      - TZ=Asia/Shanghai
    ports:
      - "127.0.0.1:3001:3001"       # 正向 WS 可选端口，本示例不启用
      - "127.0.0.1:3080:3080"       # WebUI（扫码登录 / 配置管理）
    volumes:
      - ./llbot-qq:/root/.config/QQ        # 登录态持久化（关键，切勿丢失）
      - ./llbot-data:/root/llonebot         # 配置文件 + 运行时数据
    restart: unless-stopped
```

> 注意：LLBot 镜像的入口脚本会将容器 DNS 指向公网服务器，导致无法解析 Docker Compose 内部服务名。上方 `entrypoint` 已通过内联 `/bin/sh -c` 在启动前修复 DNS，无需额外文件。

### 2. 配置 OneBot 反向 WS

先启动 LLBot，查看日志中的二维码或登录链接：

```bash
docker compose up -d llbot
docker compose logs -f llbot
```

WebUI 端口绑定服务器本机。需要浏览器扫码和配置时，在自己的电脑上另开终端，将 `user@server` 替换为服务器账号与地址：

```bash
ssh -N -L 3080:127.0.0.1:3080 user@server
```

保持隧道运行，在本地浏览器打开 `http://127.0.0.1:3080`，完成扫码登录后启用 OneBot V11 的反向 WS（`ws-reverse`），连接地址为 `ws://quickquip:8080/onebot/v11/ws/`。token 填现有根目录 `.env` 中的 `ONEBOT_ACCESS_TOKEN`；该值为空时，先设置一个非空 token，两侧保持同值。

LLBot 配置为 JSON 格式。下方是当时 `llbot-data/default_config.json` 的最小结构示例，`token` 替换为上述值：

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
        "token": "替换为ONEBOT_ACCESS_TOKEN的值",
        "messageFormat": "array"
      }
    ]
  },
  "log": true,
  "msgCacheExpire": 120
}
```

容器首次启动时入口脚本可能用内置默认配置覆盖 `default_config.json`。上述顺序先完成首次启动和登录，再通过 WebUI 修改当前账号配置；当时也可在容器内编辑 `data/config_<QQ号>.json`。

### 3. 更新 QuickQuip 服务

将 QuickQuip 的协议端依赖从 NapCat 改为 LLBot，保留其他依赖与配置。下方是合入现有 `quickquip` 服务的片段：清空正向 WS 目标，让 LLBot 按 §2 主动连接，并把根 `.env` 的 token 传给 QuickQuip。

```yaml
quickquip:
  depends_on:
    - llbot
  environment:
    DRIVER: "${DRIVER:-~fastapi+~websockets}"
    ONEBOT_WS_URLS: '[]'
    ONEBOT_ACCESS_TOKEN: "${ONEBOT_ACCESS_TOKEN:?请设置 OneBot token}"
```

### 4. 应用配置并验证连接

按更新后的 Compose 重建 QuickQuip，使新依赖与环境变量生效：

```bash
docker compose up -d quickquip
```

单纯 `restart` 重启原容器；修改 Compose 或环境变量后使用 `up -d` 应用配置。

验证连接成功：

```bash
docker compose logs quickquip | grep "Bot.*connected"
# 应输出: OneBot V11 | Bot <你的QQ号> connected
```

### 5. 移除旧 NapCat 服务（验证稳定后）

```bash
docker compose stop napcat
# 观察 24-48 小时确认稳定后
docker compose rm napcat
```

NapCat 的登录态和数据卷（`napcat-data/`）建议在确认稳定前保留，以便快速回退。

## OneBot WS 模式说明

LLBot 同时支持正向和反向 WebSocket。本文步骤采用反向 WS：LLBot 主动连接 QuickQuip，QuickQuip 的 `ONEBOT_WS_URLS` 为空数组。

当时的 `docker-compose.example.yml` 默认采用正向 WS：QuickQuip 通过 `ONEBOT_WS_URLS='["ws://llbot:3001/"]'` 连接 LLBot 的 3001 端口。选择正向模式时，需在 LLBot WebUI 启用正向 WS 服务端，两侧 token 同值，QuickQuip 的 `DRIVER` 包含 `~websockets`。现行新部署步骤见[部署指南](deployment.md)。

## 已知差异

| 项 | NapCat | LLBot | 影响 |
|---|---|---|---|
| 长消息限制 | ~667 汉字截断 | 更高（未实测） | 800 字分块策略对两者均有效 |
| QQ 版本 | 3.2.28 | 3.2.25 | 略旧，腾讯可能未来强制升级 |
| 自动登录 | `ACCOUNT` 环境变量 | `QUICK_LOGIN_QQ` 环境变量（有效但有时效性） | 重启后可能需要重新扫码；restart 可触发快速登录 |
| WebUI 端口 | 6099 | 3080 | SSH 隧道端口变更 |
| 日志格式 | `账号状态变更为在线` | `PMHQ WebSocket 连接成功` | 如有自定义监控需适配 |

## 回退步骤

如 LLBot 出现严重问题，先停止它，并恢复迁移前保存的 Compose 与 `.env` 配置，包括协议端依赖、WS 目标和 token：

```bash
# 停止 LLBot
docker compose stop llbot

# 恢复迁移前的 Compose 与 .env 后，重新启动 NapCat
docker compose up -d napcat

# 应用恢复后的 QuickQuip 配置
docker compose up -d quickquip
```

## 参考

- [LLBot 官方文档](https://luckylillia.com)
- [NapCat Issue #1728 - 风控掉线讨论](https://github.com/NapNeko/NapCatQQ/issues/1728)
- [NapCat PR #1768 - 反检测实验分支](https://github.com/NapNeko/NapCatQQ/pull/1768)
