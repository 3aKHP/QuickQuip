# 安装与部署方式

本文帮助部署者选择 QuickQuip 的运行位置和运行方式，并找到首次安装教程。部署按两个独立维度描述：**本地／云端**与**源码／Docker**。

配置工具通过根 `.env` 中的两个部署枚举选择工作方式，设置方法见 [qqsync 指南](config-sync.md#先设置部署方式)。

## 确定部署方式

部署位置相对于执行配置或部署命令的电脑定义：

- **本地**：在当前项目的主机上运行，直接操作当前项目的真实配置和服务。
- **云端**：在另一台服务器上运行，通过 SSH 操作该服务器上的配置和服务；自建远程主机也归入此类。

运行方式以 QuickQuip 的 Bot 和 Web Admin 为准：

- **源码**：直接使用主机上的 Python 环境运行应用。Windows 懒人包使用随包 Python，归入同一类主机进程运行方式。
- **Docker**：在容器内运行应用，项目模板使用 Docker Compose 管理服务。从源码构建镜像、挂载 Python 源码的 hybrid 部署也归入此类。

LLBot、SearXNG 和 MCP 服务可以分别选择自己的运行方式。例如，主机上的 Python Bot 连接容器中的 LLBot，QuickQuip 仍属于源码运行。

| 组合 | 应用运行位置与方式 | 安装入口 |
|---|---|---|
| 本地源码 | 当前项目的主机 Python 进程 | [源码安装](#源码安装)；[Windows 懒人包](../../README.md#windows-懒人包) |
| 本地 Docker | 当前项目的 Compose 服务 | [本地 Docker 安装](#本地-docker-安装) |
| 云端源码 | SSH 服务器上的 Python 进程 | [云端源码安装](#云端源码安装) |
| 云端 Docker | SSH 服务器上的 Compose 服务 | [云端 Docker 部署指南](deployment.md) |

## 源码安装

需要 Python 3.11+ 和 OneBot V11 协议端；启用 Web Admin 时还需 Node.js 与 pnpm 构建前端。在项目根目录按 [README 的安装步骤](../../README.md#安装步骤)完成虚拟环境、依赖、根 `.env`、配置初始化及 Bot／Web 启动。使用 Windows 懒人包时，按 [Windows 安装说明](../../README.md#windows-懒人包)准备配置并运行 `start.bat`。

主机 Python 使用根 `.env` 中的 `ONEBOT_WS_URLS` 连接协议端，地址需从运行 Bot 的主机可达。例如，同机协议端已开放正向 WebSocket 的 `3001` 端口时使用：

```env
DRIVER=~fastapi+~websockets
ONEBOT_WS_URLS=["ws://127.0.0.1:3001/"]
```

在协议端填写与 `.env` 相同的 `ONEBOT_ACCESS_TOKEN`。反向 WebSocket 与其他连接方式见 [OneBot 连接拓扑](onebot-adapters.md#quickquip-的-onebot-v11-边界)。

## 云端源码安装

需要 SSH 访问服务器，并在服务器准备源码安装所需的 Python 环境；构建 Web 前端时同时准备 Node.js 与 pnpm。先在本地终端连接服务器，将账号与地址替换为实际值：

```bash
ssh user@server
```

在服务器上按[源码安装](#源码安装)完成克隆、依赖、根 `.env`、配置初始化和启动。命令、虚拟环境及配置文件均位于服务器上。先在终端运行 Bot 和 Web，确认收发消息与后台可用，再接入自己的服务管理器以便后台运行和重启。

首次访问 Web Admin 时，在自己电脑的另一个终端建立隧道：

```bash
ssh -N -L 5104:127.0.0.1:5104 user@server
```

保持隧道运行，在本地浏览器打开 `http://127.0.0.1:5104/ops/`，用服务器根 `.env` 中的 `WEB_ADMIN_PASSWORD` 登录。接着按[首次启用 LLM](llm-configuration.md#首次启用-llm)完成模型设置与第一条回复验证。

`deploy-v4` 的代码发布面向云端 Docker。云端源码的程序更新由部署者管理；新版标准入口启动的 Bot/Web 支持通过 qqsync 同步配置和暂停／恢复服务，见[配置同步](config-sync.md)。

## 本地 Docker 安装

以下步骤适用于首次安装，需已安装 Docker 与 Docker Compose，并取得项目文件。应用镜像包含 Python、依赖和前端。在项目根目录执行以下 Bash 命令准备配置；PowerShell 使用 `Copy-Item .env.example .env` 与 `Copy-Item -Recurse config/personas.example config/personas`。

```bash
cp .env.example .env
cp -r config/personas.example config/personas
```

编辑根 `.env`，填写 `QQ_ACCOUNT`、`ONEBOT_ACCESS_TOKEN`、`WEB_ADMIN_PASSWORD` 和自己的 `SEARXNG_SECRET`，启用模型时再填写相应 API key。根 Compose 模板提供容器间的 OneBot 和搜索地址；从源码配置迁入时，核对 `ONEBOT_WS_URLS` 与 `QUICKQUIP_SEARXNG_BASE_URL`，容器中的 `127.0.0.1` 指向容器自身。

在同一项目根目录启动：

```bash
docker compose -f docker-compose.example.yml up -d
docker compose -f docker-compose.example.yml ps --all
docker compose -f docker-compose.example.yml logs --tail 80 quickquip web-admin
```

模板先通过 `config-init` 初始化配置，再启动 Bot 和 Web；该初始化服务成功后显示退出码 `0`，其他服务保持运行。已有数据库升级按[存储迁移](storage-migration.md)执行。

打开 `http://127.0.0.1:3080`，在 LLBot 中扫码登录并启用正向 WebSocket，端口使用 `3001`，token 与根 `.env` 的 `ONEBOT_ACCESS_TOKEN` 相同。连接方式和适配器版本见 [OneBot 说明](onebot-adapters.md)。在测试群发送“早安”，收到规则回复后，打开 `http://127.0.0.1:5104/ops/` 登录后台，按[首次启用 LLM](llm-configuration.md#首次启用-llm)继续配置。

根模板将 `config/`、`data/`、`llbot-qq/` 和 `llbot-data/` 保存在当前项目。按模板注释启用可选的资料和 Skill 挂载。修改根 `.env` 后，在项目根目录重新创建应用容器：

```bash
docker compose -f docker-compose.example.yml up -d quickquip web-admin
```

停止服务使用 `docker compose -f docker-compose.example.yml down`，配置和主机目录中的数据继续保留。

## 安装后编辑与同步配置

本地编辑使用 [qqconf 工作副本](config-workspace.md)，配置字段见[配置参考](configuration.md)。现有云端 Docker 部署的同步操作见[配置同步](config-sync.md)，代码发布与回滚见[生产模板](../../prod.example/README.md)。
