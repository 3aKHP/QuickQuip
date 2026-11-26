# QuickQuip 云端 Docker 部署指南

本文面向 Linux 服务器上的 Docker Compose 部署，介绍**手动安装、自动发布脚本（`deploy-v4`）、接入协议端、登录后台，以及日常维护**。

> **相关文档导航**：
> - 部署位置（`local`/`cloud`）与运行方式（`source`/`docker`）的定义，以及本地/源码安装入口：见[安装与部署方式](installation.md)
> - LLM 配置的详细操作与版本升级：见[配置管理](llm-configuration.md)
> - 外部 MCP 工具服务接入：见[MCP 接入指南](mcp-servers.md)

---

## 前提条件与服务器选择

### 1. 硬件与软件前提
- **Linux 服务器**：建议从 **2 核 / 2G 内存 + 2G swap** 起步（v1.12.2 全栈验收在此规格下稳态内存占用约 0.7G RSS；后续可根据并发量与启用功能观察内存水位）。
- **容器环境**：已安装 Docker 和 Docker Compose。
- **Node.js + pnpm**：用于构建 Web Admin 前端（如果走手动部署，需安装在服务器上；如果使用 `deploy-v4` 自动部署脚本，只需安装在你执行脚本的本地电脑上）。
- **OneBot V11 协议端**：部署者自行安装并管理 QQ 登录。按[接入说明](onebot-adapters.md#连接-quickquip)准备容器可达的连接。

### 2. 网络与服务器连通性
请按所需的 CPU 架构、资源容量及网络条件选择服务器。在正式开始完整部署前，请先确认服务器能够正常访问以下目标：
- Docker 镜像源与 Python 包镜像源
- QQ 协议端连接
- 所选用的 LLM 模型 API 接口
- 搜索服务（SearXNG）

---

## 部署步骤

> **手动安装 vs 自动部署脚本怎么选？**
> - **首次手动平铺安装**：请直接按下方 **第 1～7 步** 依次操作（先准备配置并启动服务，再登录后台启用 LLM）。
> - **使用 `deploy-v4` 自动部署脚本**：
>   1. 先在**本地项目**准备好下方 **第 3 步** 所列的模板、配置与资产；
>   2. 按[部署工具的 SSH 设置](../../scripts/deploy/README.md#ssh-connection)配置好本地到服务器的 SSH 连接；
>   3. 在服务器上准备独立的 OneBot 协议端和 SearXNG 服务；
>   4. 准备完成后，直接跳到后文的[自动部署与版本回滚](#自动部署与版本回滚)章节，首次部署按场景表选择参数；日常部署使用其后的操作示例。

---

### 1. 服务器上安装 Docker

```bash
# Ubuntu / Debian 一键安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 注意：执行后请重新登录 SSH 会话，使 docker 用户组权限生效
```

---

### 2. 上传项目

在项目结构中：
- `prod.example/`：存放生产环境 Compose 编排与通知配置的公开示例。
- `prod/`（私有目录）：存放服务器真实生效的 Compose 编排、巡检配置和运维通知密钥。
- `scripts/deploy/` 与 `scripts/ops/`：分别存放通用部署程序与巡检程序，随代码仓库版本更新。

如果采用手动安装，推荐从本地准备好的私有工作目录将完整项目上传至服务器：

```bash
scp -r /path/to/QuickQuip user@server:/path/to/QuickQuip
```

---

### 3. 准备生产运维目录和环境变量

手动安装在服务器项目根目录准备这些文件；使用自动部署脚本时，在本地项目准备同样的文件。自建搜索服务的命令仍在服务器执行：

```bash
cd /path/to/QuickQuip
cp .env.example .env
nano .env  # 按下表填写必填项；注意 QUICKQUIP_SEARXNG_BASE_URL 需要取消注释
mkdir -p prod
cp prod.example/docker-compose.yml prod/docker-compose.yml
```

#### 3.1 根目录 `.env` 必填配置项

根目录 `.env` 是 QuickQuip 应用唯一的涉密凭证来源。启动前请填写以下核心变量：

| 环境变量 | 填写说明 |
|---|---|
| `ONEBOT_WS_URLS` | 正向 WebSocket 填入容器可达的地址列表。反向 WebSocket 使用 `[]` |
| `ONEBOT_ACCESS_TOKEN` | 与自备协议端配置相同的访问令牌 |
| `DRIVER` | 使用正向 WebSocket 连接时，保持示例值 `~fastapi+~websockets` |
| `WEB_ADMIN_PASSWORD` | 自定义的 Web Admin 后台登录密码（请替换掉示例占位值） |
| `QUICKQUIP_SEARXNG_BASE_URL` | 从 Bot 容器内部可访问的 SearXNG 搜索服务地址（生产模板启动时**必填**，需取消注释） |
| 所选模型渠道的 API Key | 启用 LLM 时填写对应渠道的变量（例如 `OPENAI_API_KEY`） |

#### 3.2 准备 SearXNG 搜索服务

- **如果已有可用的 SearXNG 服务**：直接将其可达地址填入 `.env` 的 `QUICKQUIP_SEARXNG_BASE_URL` 即可。
- **如果首次在服务器本机自建 SearXNG**：
  1. 在**服务器项目根目录**的 `.env` 中，把 `SEARXNG_SECRET` 改成你自己的随机字符串，并保留示例的 `SEARXNG_BIND_PORT=8888`。
  2. 执行以下 Bash 命令，利用仓库根模板单独启动名为 `quickquip-search` 的搜索容器，并输出对应的网桥地址配置：
     ```bash
     SEARXNG_BIND_ADDRESS="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')" \
       docker compose -p quickquip-search -f docker-compose.example.yml up -d searxng
     docker network inspect bridge --format 'QUICKQUIP_SEARXNG_BASE_URL=http://{{(index .IPAM.Config 0).Gateway}}:8888'
     ```
  3. 将最后一行命令输出的 `QUICKQUIP_SEARXNG_BASE_URL=http://...` 复制写入根目录 `.env`（替换掉原本被注释的那一行）。

> **原理解析**：这条 Linux Docker 路线会将 SearXNG 端口绑定在默认的 Docker 网桥网关地址上，专供同宿主机的 Bot 容器跨网桥访问（关于跨网桥访问已发布端口的原理，详见 [Docker 端口映射说明](https://docs.docker.com/engine/network/port-publishing/)）。因为使用了独立的 Compose 项目名 `quickquip-search`，后续 QuickQuip 应用发布或重启时，这个搜索服务会一直保留运行。

#### 3.3 准备人格与运维配置

- **LLM 默认人格（初次使用必做）**：将 `config/personas.example/` 复制为 `config/personas/`（服务启动后按第 7 步在后台添加渠道并应用配置）。
- **已有部署升级**：请先按[配置管理：初始化与升级](llm-configuration.md#初始化与升级)完成数据库迁移，并保留迁移前的配置与资产备份。
- **生产编排与运维通知**：确认 `prod/docker-compose.yml` 已从模板建立并按服务器环境调整；如需配置 ServerChan 等运维通知，请在 `prod/sendkey.env` 中维护（该文件仅用于运维脚本，不会被 QuickQuip 应用读取）。

其他功能可以在基本部署完成后按[可选配置](#可选功能配置)添加。

#### 3.4 准备协议端

按服务自身的说明启动 OneBot V11 协议端并登录 QQ。将网络和鉴权配置写入双方部署文件。两套 Compose 共用外部网络时，可按[共享网络步骤](onebot-adapters.md#两个独立-compose-使用共享网络)配置。已有部署仍随 QuickQuip 启动 LLBot 时，先按[旧部署迁移步骤](onebot-adapters.md#从随-quickquip-启动的-llbot-迁移)拆分。

### 4. 启动服务

#### 构建前端并启动容器

在启动容器前，需要先构建 Web Admin 前端静态产物（`frontend/dist`，会被 `web-admin` 容器只读挂载）：
- **若使用 `deploy-v4` 部署脚本**：脚本会在你本地电脑上自动构建前端并打包上传，无需在服务器操作。
- **若在服务器手动部署**：需先在服务器上安装 Node.js 和 pnpm，并在项目根目录执行：
  ```bash
  cd frontend && pnpm install --frozen-lockfile && pnpm build
  ```

随后进入 `prod/` 目录，依次执行构建镜像、初始化配置库、后台启动服务：

```bash
cd /path/to/QuickQuip/prod
docker compose --env-file ../.env build quickquip
docker compose --env-file ../.env run --rm --no-deps web-admin python -m quickquip.llm.config_cli init
docker compose --env-file ../.env up -d
```

> **关于中间那条 `init` 初始化命令**：
> 该命令借用了 `web-admin` 容器的可写配置挂载，用于创建初始的空配置库（或将旧版 `llm.toml` 迁移入库），执行完成后容器即自动退出。全新安装完成后 LLM 功能默认保持关闭状态，稍后在第 7 步通过 Web 后台启用；如果是已有配置库的老版本升级，请务必按[初始化与升级](llm-configuration.md#初始化与升级)或[存储迁移步骤](storage-migration.md)的停服和备份要求执行。

### 5. 确认 OneBot 已连接

在服务器的 `prod/` 目录执行：

```bash
docker compose --env-file ../.env logs --tail 80 quickquip
```

日志出现预期账号的 `Bot … connected` 后继续验证收发。若迟迟未连接，检查两端正在使用的 WebSocket 方向、地址及令牌。反向 WebSocket 需确认协议端能访问 Bot 的监听端口；正向 WebSocket 需确认协议端已登录且其端口从 Bot 容器可达。

### 6. 验证基础运行

```bash
# 确认容器均处于正常运行状态
docker compose --env-file ../.env ps

# 实时查看 QuickQuip 运行日志
docker compose --env-file ../.env logs -f quickquip
```

1. **验证基础收发**：在机器人所在的 QQ 群里发送一句“**早安**”，如果收到机器人的时区猜测回复，说明群消息收发与基础规则响应已打通。
2. **验证贴吧功能（如已启用）**：在群内发送 `/tieba status` 和 `/tieba refresh` 进行验证。

---

<a id="7-web-管理后台"></a>

### 7. 登录 Web 管理后台与首次启用 LLM

Compose 启动时会同时运行同镜像的 `env-agent`、`quickquip` 和 `web-admin` 三个容器（其中 `web-admin` 内部运行 `python web_api.py` 监听 `0.0.0.0:5104`，宿主机侧仅绑定在 `127.0.0.1:5104`）。

#### 7.1 建立 SSH 隧道并登录后台

在**自己电脑的另一个终端窗口**建立 SSH 隧道（将 `user@server` 替换为服务器账号与地址）：

```bash
ssh -N -L 5104:127.0.0.1:5104 user@server
```

保持隧道运行，在本地浏览器打开 `http://127.0.0.1:5104/ops/`，输入第 3 步在 `.env` 中设置的 `WEB_ADMIN_PASSWORD` 登录。

进入后台概览页后，请按照[首次启用 LLM](llm-configuration.md#首次启用-llm)的步骤：添加一个模型渠道和模型 → 保存草稿并应用到 Bot → 等待 Bot 加载完成 → 在测试群开启 AI 并收到第一条回复。

#### 7.2 Web Admin 后台功能一览

- **统计与群管**：各群消息统计、活跃用户、规则触发次数；群级规则实时 Toggle 开关；每日总结 / 每日播报群组管理。
- **LLM 工坊与配置**：LLM 结构化配置、保存草稿／应用到 Bot、JSON 导入预览、Bot 实际加载状态监控与配置任务追踪。
- **环境变量在线管理（只写不回显）**：在“系统 → 环境变量”页面维护根目录 `.env` 中的凭据与运行参数，已有变量值不回显，已绑定渠道的 API Key 与贴吧关键词支持热更新（详见[管理环境变量](environment.md)）。
- **独立 TOML 配置在线编辑**：支持在线编辑 `config/generation.toml`、`config/chat_rules.toml`、`config/games.toml`、`config/awakening.toml`、`config/niuniu_text.toml`、`config/niuniu_text_safe.toml`（保存前会自动校验 TOML 语法）。
- **敏感词状态查看（只读）**：后台仅提供敏感词过滤器的只读状态查看；`config/sensitive_words.toml` 词表文件只能通过服务器本地文件或部署流程维护，**不会**在 Web Admin 中回显或允许编辑。
- **业务与监控面板**：记忆、对话、人格、群资料、低频唤醒、LLM 用量统计、MCP 状态、贴吧、词云、群语录、调度器监控、操作审计、金币经济与牛牛游戏面板。
- **日志与 Trace 观测**：实时日志、历史日志归档（读取 `../data/logs`），以及 LLM HTTP 调用索引与请求/响应正文追踪（读取 `../data/llm_trace.db`）。

#### 7.3 配置 HTTPS 反向代理与 Session 参数（可选）

如果需要长期通过域名和 HTTPS 反向代理访问后台，请参考 [Web Admin 反向代理注意事项](web-admin.md#反向代理注意事项)。若你在 Nginx 层额外配置了 `auth_basic`，访问时会有两层认证：
1. **外层 Nginx `auth_basic`**：站点级访问控制，密码文件由你的 Nginx 配置决定。
2. **内层 QuickQuip Web Admin Session**：应用层登录，校验 `.env` 中的 `WEB_ADMIN_PASSWORD` 并在浏览器建立 `HttpOnly` Session Cookie。

你可以在根目录 `.env` 中调整后台 Session 与部署环境参数：

```env
WEB_ADMIN_SESSION_TTL_HOURS=168
WEB_ADMIN_SESSION_MAX_AGE_HOURS=168
QUICKQUIP_DEPLOY_LOCATION=cloud
QUICKQUIP_DEPLOY_RUNTIME=docker
WEB_ADMIN_COOKIE_SECURE=auto
```
> **提示**：`WEB_ADMIN_COOKIE_SECURE=auto` 依赖反向代理传递 `X-Forwarded-Proto` 请求头；如果你的 Nginx 没有传递该 Header，但站点确实运行在 HTTPS 下，请将其显式改为 `true`。

## 可选功能配置

- **多模态生成（图片 / 语音 / 音乐 / ASR）**：确保 `config/generation.toml` 已存在，并填入对应的 provider 与模型。
- **低频唤醒**：确保 `config/awakening.toml` 已存在，并填入唤醒阈值、兴趣话题和按群覆盖规则。
- **敏感词过滤**：确保 `config/sensitive_words.toml` 已存在，并填入部署侧词表。
- **Skill 技能系统**：确保 `skills/` 目录下已放置技能包（预置技能包可从 `skills.example/` 复制，Windows 懒人包首次启动会自动完成复制；若 `skills/` 目录为空或不存在，Skill 工具不会注册，详见 [skills.md](skills.md)）。
- **MCP 外部工具 Sidecar**：如启用 MCP sidecar，需按你的私有 `prod/` 编排补充对应的 API Key。

<a id="41-首次准备贴吧登录态"></a>

<a id="41-首次准备贴吧登录态可选"></a>

### 首次准备贴吧登录态

如果需要使用贴吧相关功能，建议先在有图形界面的**本地电脑**上运行登录命令生成登录态，再通过部署脚本同步到云端：

```bash
python -m quickquip.tieba.login
```

登录成功后会在本地生成 `data/tieba/storage_state.json`。后续在本地执行 `scripts/deploy/deploy-v4.ps1`（Windows）或 `bash scripts/deploy/deploy-v4.sh`（Linux）时，该文件会被自动单独上传到服务器。

---

<a id="42-cjk-字体文件词云与-svg-画图"></a>

<a id="42-准备-cjk-中文字体文件词云与-svg-画图"></a>

### 准备 CJK 中文字体文件（词云、SVG 画图与长消息转图）

词云（`/wordcloud`）、SVG 画图（`draw_svg` 工具）以及长消息合并转发失败时的长图降级渲染（每日总结、周/月报与 `/profile`）共用同一个中文字体文件。该文件不随代码仓库分发，需手动下载放置：

1. 从 [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+SC) 下载 `NotoSansSC-Regular.ttf`。
2. 将其放入项目的 `data/fonts/NotoSansSC-Regular.ttf`（容器化部署时，`data/fonts/` 会随 `data/` 目录自动挂载进容器，上传一次即可持久生效）。

> **缺少字体文件及不同平台的渲染差异**：
> - **若缺失 `NotoSansSC-Regular.ttf`**：执行 `/wordcloud` 时 Bot 会直接回复明确的错误提示；`draw_svg` 会回退使用系统字体（在精简版 Linux 系统上中文可能会渲染成方框）；长消息长图降级会按常见系统路径与 `fc-match :lang=zh` 回退查找中文字体，若宿主机与容器内均无可用中文字体，则长图降级发送会失败并记为投递异常。
> - **渲染引擎与 Emoji 字体**：SVG 渲染引擎 `resvg` 已包含在 `requirements.txt` 中，随 pip 依赖自动安装，无需额外系统构建步骤。文字优先使用上述 NotoSansSC 字体，Emoji 等字符则通过系统字体回退——官方 Playwright 基础镜像和 Windows 系统（微软雅黑 / Segoe UI Emoji）均自带彩色 Emoji 字体，无需额外处理；仅在精简 Linux 宿主机上裸机源码部署时，可能因缺少系统 Emoji 字体导致 Emoji 显示为方框。
> - **渲染子进程资源保护**：渲染子进程的内存地址空间与 CPU 时间硬限制依赖 POSIX `rlimit`，在 Linux 等 POSIX 平台自动生效；Windows 平台则保留 8 秒墙钟超时（wall-clock timeout）兜底。

---

## 自动部署与版本回滚

日常代码发布与配置同步推荐使用仓库自带的 `scripts/deploy/deploy-v4.sh`（Bash）或 `scripts/deploy/deploy-v4.ps1`（PowerShell）。

- **工作原理**：两端脚本共享同一套远端事务执行器，按受控清单上传应用文件，在服务器完成预检和镜像构建后原子切换版本目录（`releases/<id>/`），并自动验证容器状态、OneBot 连接与 Web Admin HTTP 健康检查（完整的参数与目录结构说明见[部署工具指南](../../scripts/deploy/README.md)）。
- **服务器环境要求**：服务器需具备 `rsync`、`flock`、Python ≥ 3.11.8 以及 Docker Compose ≥ 2.27。
- **执行前确认**：本地 `prod/` 已从 `prod.example/` 复制并配好，根目录 `.env` 及所选功能配置已填写完毕，且已在本地 SSH 配置中配好服务器别名（默认为 `quickquip-prod`）。

### 1. 版本目录结构与构建标识
使用 `deploy-v4` 部署的服务器采用版本化目录布局：
- **持久化运行态**：位于部署根目录下的 `data/`、`skills/` 和 `prod/`。
- **代码发行版**：位于 `releases/<id>/`，并通过 `current` 和 `previous` 软链接分别指向当前运行版本与上一个版本（如需在服务器上手动执行 `docker compose` 命令，需先按[模板中的手动访问步骤](../../scripts/deploy/README.md#manual-compose-access)导出部署根目录和版本标识环境变量）。
- **版本追踪标识**：每次发布都会生成一个唯一版本标识（格式为 `pyproject.toml 版本号 + 服务器镜像构建完成时刻`，例如 `1.15.3-dev.2+build.20260909.065235`），记录在事务日志的 `image built` 与 `release complete` 行中，方便将线上 `releases/` 目录与代码提交精确对应。

### 2. 配置同步策略与特殊升级参数
日常直接运行 `deploy-v4` 时，**默认会将本地配置（包含根 `.env`）单向推送到服务器**（但排除本地数据库和旧版 LLM TOML 的原始文件上传）。针对首次部署或老服务器升级，请按场景选用参数（详见[配置同步指南](config-sync.md)与[存储迁移指南](storage-migration.md)）：

| 服务器场景 | Bash 参数 | PowerShell 参数 | 行为说明 |
|---|---|---|---|
| **平铺部署老服务器，且仍在使用 `data/llm_config.db`** | `--migrate --migrate-storage` | `-Migrate -MigrateStorage` | 将平铺目录迁为 release 结构，同时保存基线、停止服务并完成存储拆分迁移（保留服务器现有配置，自动关闭本次配置同步） |
| **平铺部署老服务器，但已完成存储迁移** | `--migrate --config-sync off` | `-Migrate -ConfigSync off` | 仅做目录结构迁移，关闭本次配置同步以保留服务器配置 |
| **全新服务器首次部署，OneBot 已就绪** | `--config-sync off --env local` | `-ConfigSync off -EnvSource local` | 使用本地 `.env` 初始化服务器，并验证应用服务和 OneBot 连接 |
| **全新服务器首次部署，OneBot 将稍后连接** | `--config-sync off --env local --skip-health` | `-ConfigSync off -EnvSource local -SkipHealth` | 使用本地 `.env` 初始化服务器，并跳过首次健康检查；按协议端自己的说明完成 QQ 登录，然后按第 5、6 步核验连接和收发 |
| **回滚到上一版本 / 指定历史版本** | `--rollback` 或 `--rollback <id>` | `-Rollback`（可加 `-ReleaseId <id>`） | 回滚代码版本（完整接口见 `bash scripts/deploy/deploy-v4.sh --help`） |

> **注**：`--env local`（PowerShell：`-EnvSource local`）仅在关闭配置同步（`--config-sync off` 或 `--migrate-storage`）时用于显式指定上传本地 `.env`；普通日常部署已包含 `.env`。首次升级建议先保留线上配置，随后再明确初始同步方向。

### 3. 自动回滚、手动回滚与旧版回退规则
- **部署失败自动恢复**：如果部署中途失败，脚本会自动恢复本次修改的共享文件，并验证旧版本服务依然健康运行。
- **手动执行 `--rollback` 的保留范围**：
  - 手动回滚代码版本时，会保留当前的根 `.env`、数据库以及部署根目录下的共享 `skills/`（即在线安装的 Skill 成果不会随代码回退而丢失；若目标版本的 Compose 同样使用共享 `skills/` 目录，回滚时会将目标 release 中新增的 Skill 非破坏性合并进共享目录；若回滚到使用 release 内部自带 `skills/` 副本的早期历史版本，则该版本继续使用其目录内副本）。
  - **注意**：数据库 schema 迁移与外部副作用不会随代码回滚自动撤销，部署前请核对版本升级说明。
- **配置库的备份与恢复命令**：
  - 备份配置库：`python -m quickquip.llm.config_cli backup data/llm-config-backup.db`（调用 SQLite backup 接口）。
  - 恢复配置库：先停止 Bot 和 Web，备份当前库后运行 `restore --file <备份路径> --services-stopped`（恢复时会自动清除旧的运行租约与心跳）。更多配置回流、导入预览与备份恢复驱动用法见 [LLM 配置管理](llm-configuration.md)。
- **跨大版本回退至 1.16.1 的特别说明**：
  - 如果需要彻底回退到 1.16.1，需使用首次迁移前备份的 TOML 及人格／多模态资产（升级到新版数据库后新增的配置不会反向转换成旧 TOML；新版数据库会保留在原处供日后再次升级）。
  - 升级与回退前请同时备份业务会话库（`data/llm.db`）和追踪库（`data/llm_trace.db`）。如果回退运行过旧版代码后又要再次升级，需执行 Session 身份重置步骤，详见[回退旧版本后再次升级](llm-configuration.md#回退旧版本后再次升级)。

---

### 自动部署操作

以下日常部署命令均在**你本地电脑的项目根目录**下执行（请将示例中的 `quickquip-prod` 替换为你自己配置的 SSH 主机别名）：

```bash
# 1. 本地预演（会在本地构建前端，PowerShell 还会临时打包，但均不会连接远端服务器）
bash scripts/deploy/deploy-v4.sh --dry-run

# 2. 正式执行自动部署
bash scripts/deploy/deploy-v4.sh --host-alias quickquip-prod

# 3. 查看远端服务器当前的发布状态
bash scripts/deploy/deploy-v4.sh --status --host-alias quickquip-prod
```

需要恢复上一个发行版本时，单独执行回滚：

```bash
bash scripts/deploy/deploy-v4.sh --rollback --host-alias quickquip-prod
```

---

## 部署布局与配置挂载

### 当前 Compose 编排做了什么？

`prod/docker-compose.yml` 启动时会完成以下挂载与环境配置：
- **搜索与环境变量**：通过 `../.env` 向 Bot 和 Web Admin 注入应用环境变量，并使用第 3 步配置的 `QUICKQUIP_SEARXNG_BASE_URL` 连接独立 SearXNG 服务。
- **环境变量代理（`env-agent`）与双通信卷**：模板默认启用在线环境变量管理（`QUICKQUIP_ENV_MANAGEMENT_ENABLED: "true"`），运行同镜像的 `env-agent` 服务并将部署根目录单独挂载到 `/host/project`。`env-agent` 不开放网络端口、也不挂载 Docker Socket，通过两个私有 Unix Socket 命名卷隔离权限：`environment-control` 供 `env-agent`、`quickquip` 和 `web-admin` 同步只读环境快照，`environment-write` 仅挂载给 `env-agent` 与 `web-admin` 执行根 `.env` 写入。
- **配置文件挂载**：将 `../config` 只读挂载到 Bot 容器内的 `/app/config`（注：`config/managed/` 由 Bot 和 Web 共享可写）。
- **Skill 目录挂载**：将部署根目录共享的 `skills/`（扁平安装时即项目根 `skills/`，与 `data/` 同级）挂载到容器内 `/app/skills`——其中 `quickquip` 容器为**只读**，`web-admin` 容器为**读写**（供 Web 后台 Skill 页在线管理）。
- **群资料与词表挂载**：将 `../llm_about`（含全局与按群覆盖的 `vocab.yaml` / `identities.yaml`）挂载到 `/app/llm_about`。
- **持久化数据挂载**：将 `../data` 挂载到 `/app/data`（存放统计数据、规则开关、运行期数据库等）。
- **贴吧采集与基础镜像**：直接基于预装了浏览器与系统依赖的 Playwright Python 镜像运行贴吧采集，从 `/app/data/tieba/storage_state.json` 读取跨平台登录态；构建时通过构建参数将 pip 源切到国内镜像以减少云端拉取超时，也可通过 `PLAYWRIGHT_BASE_IMAGE` 自定义适合当前网络环境的 Playwright 基础镜像。

### OneBot 连接与配置重载

- **OneBot 连接**：按照[接入说明](onebot-adapters.md#连接-quickquip)在根 `.env` 和协议端配置 WebSocket 及令牌。修改地址、驱动或令牌后，使用新环境重建 Bot 容器，并重新核对连接。
- **配置库共享与在线热重载机制**：
  - Bot 和 Web 共享本机的 `config/managed/config.db`。自动部署脚本会保留生产环境数据库（本地配置库和旧 TOML 由各自的配置运维流程管理），并在切换发行版目录（release）后强制重建一次应用容器，确保源码和配置挂载指向最新发行目录。
  - **LLM 配置生效方式**：Bot 启动或重启时只读取**已发布快照（Published）**；在 Web Admin“LLM 配置”页修改配置后，需点击“保存草稿”并“应用”，等待配置任务完成及 Bot 确认实际加载版本。修改模型价格等无关字段时不会断开现有的 MCP 连接；若修改了 MCP 配置，其连接状态会独立回报。
  - **手动命令重载与探活**：在群内发送 `/llm reload` 会重新加载已发布配置及相关独立资产，并向当前模型发起一次探活请求（可能按渠道计费）。此外，Bot 每 30 秒会自动检查一次 `awakening.toml` 的文件修改时间并自动热重载。

---

### 服务挂载权限对照

| 宿主机路径或命名卷 | 容器内路径 | `web-admin` 权限 | 用途说明 |
|---|---|---|---|
| `../data` | `/app/data` | **读写** | 业务库、日志、Trace 库等运行期数据 |
| `../config` | `/app/config` | **读写** | 在线编辑独立 TOML 配置及首次迁移提取资产（同目录下的 `sensitive_words.toml` 不开放 Web 读写） |
| `../llm_about` | `/app/llm_about` | **读写** | 在后台“资料”页在线编辑群词表与成员身份 |
| `${QUICKQUIP_ROOT:-..}/skills`（扁平安装即 `../skills`） | `/app/skills` | **读写** | 在后台“Skill”页在线安装、编辑和同步预置技能包 |
| `environment-control`（命名卷） | `/run/quickquip-environment` | **读写** | 连接 `env-agent` 只读通道同步环境变量快照 |
| `environment-write`（命名卷） | `/run/quickquip-environment-write` | **读写** | 连接 `env-agent` 管理通道提交根 `.env` 修改 |
| `../frontend/dist` | `/app/frontend/dist` | 只读 | 前端静态构建产物 |
| `../web_api.py` | `/app/web_api.py` | 只读 | Web 后端入口脚本 |
| `../src` | `/app/src` | 只读 | Hybrid 混合模式下热更新 Python 源码 |

> **权限隔离边界**：`quickquip`（Bot 主容器）对 `../config`、`../llm_about` 和共享 `skills/` 均保持**只读挂载（`:ro`）**，仅挂载可写的 `config/managed/` 与只读快照通道 `environment-control`（不挂载 `environment-write`）；`env-agent` 单独将部署根目录挂载到 `/host/project` 执行根 `.env` 事务写入，不挂载业务数据库或开放外部端口。

---

### 自动部署脚本会同步哪些文件？

当你使用自动部署脚本发布时，以下文件会被一并同步并用于容器运行：
- 根目录 `.env`
- `config/` 目录下的运行配置（如 `generation.toml`、`awakening.toml`、`sensitive_words.toml`、`games.toml` 等）
- `skills/` 目录：每次部署会将本地 `skills/` 中**新增**的 Skill **非破坏性合并**进服务器部署根目录的共享 `skills/` 中（即：服务器上已存在的同名文件不会被覆盖、本地删除不会传播到线上；已安装 Skill 的更新与删除请通过 Web Admin 管理页或在服务器上手动维护）
- `llm_about/vocab.yaml`、`llm_about/identities.yaml` 以及群级目录 `llm_about/{群号}/vocab.yaml`、`llm_about/{群号}/identities.yaml`
- `data/tieba/storage_state.json`（如果本地存在该文件，部署脚本会将其单独上传到云端，供贴吧功能复用本地导出的登录态）

---

## 代码更新与历史数据回灌

### 1. Hybrid 混合模式的代码更新策略

本项目容器采用 **Hybrid（构建烘焙 + 源码挂载）混合模式**：
- **镜像构建时**：`pip install --no-deps .` 会将 `src/` 下的 `quickquip` 和 `plugins` 安装到容器内的 `site-packages` 中作为兜底（baked fallback）。
- **容器运行时**：`docker-compose` 将宿主机的 `../src` 挂载到 `/app/src`，并通过 `PYTHONPATH=/app/src` 使其优先级高于 `site-packages`，从而支持**源码热更新**。

因此，手动维护时可根据改动范围选择最快生效方式：

| 你修改了什么内容？ | 需要执行的生效命令（在 `prod/` 目录下） | 是否需要重建镜像？ |
|---|---|---|
| **仅修改了 `src/quickquip/` 或 `src/plugins/` 下的现有 Python 业务代码** | `docker compose --env-file ../.env restart quickquip web-admin` | **不需要**（重启即生效） |
| **仅重新构建了 `frontend/dist` 前端静态文件** | `docker restart quickquip-web-admin` | **不需要** |
| **修改了 `pyproject.toml`、`requirements.txt`、`Dockerfile`、`environment` 模块，或在 `src/` 下新增/删除了文件** | `docker compose --env-file ../.env build quickquip`<br>`docker compose --env-file ../.env up -d` | **需要重建镜像** |

---

### 2. 历史数据回灌脚本（可选）

`scripts/maintenance/` 目录下随镜像分发了两个历史数据迁移回灌脚本：
1. `backfill_record_identities.py`：为存量的记忆、语录和留言补齐正文片段与群成员引用索引（详细说明见 [record-identities.md](record-identities.md)）。
2. `backfill_chat_archive.py`：将 v1.15.2 之前退役的旧版每日消息 / 词云 JSONL 文件（位于 `data/daily_msgs/`、`data/wordcloud_msgs/`）导入到统一的聊天记录归档库 `data/chat_archive.db` 中（导入完成且零失败后，即可安全清理旧的 JSONL 目录；主机与 Windows 懒人包用法见[数据与资产维护](../../scripts/maintenance/README.md)）。

在服务器容器内运行聊天归档回灌的命令如下：

```bash
# 第一步：加 --dry-run 仅预览统计结果（新增、归因回填、已存在、跳过与写入失败数）
docker compose --env-file ../.env exec -T quickquip python scripts/maintenance/backfill_chat_archive.py --dry-run

# 第二步：确认预览结果符合预期后，去掉 --dry-run 正式执行（若有写入失败会返回非零退出码；确认失败数为 0 后再删除旧 JSONL）
docker compose --env-file ../.env exec -T quickquip python scripts/maintenance/backfill_chat_archive.py
```

---

## 日常维护

启用环境变量在线管理（生产模板默认开启）后，通过 Web Admin“系统 → 环境变量”或 `qqsync` 更新已绑定渠道的 API Key 与贴吧关键词会在运行中自动热更新，无需重建容器。当你在服务器手动修改了根目录 `.env` 中的启动期参数（如 `ONEBOT_*` 连接配置、监听端口、`WEB_ADMIN_PASSWORD`）或调整了 Compose 编排与卷挂载时，需在实际 Compose 所在目录重新执行 `up -d` 创建容器使其生效（若仅修改了 `WEB_ADMIN_PASSWORD`，可单独重建 `web-admin` 容器）。

> **提示**：如果是通过 `deploy-v4` 部署的版本目录（release）结构，在服务器手动执行以下命令前，请先按[手动访问步骤](../../scripts/deploy/README.md#manual-compose-access)导出环境变量，并将下方命令中的 `--env-file ../.env` 替换为 `--env-file "$QUICKQUIP_ENV_FILE"`。

### 常用维护命令速查（平铺生产部署）

进入 `prod/` 目录后，按维护场景执行对应命令：

| 任务 | 命令 |
|---|---|
| 修改启动期 `.env` 参数或 Compose 后重新创建服务 | `docker compose --env-file ../.env up -d` |
| 修改已挂载 Python 源码后重启 | `docker compose --env-file ../.env restart quickquip web-admin` |
| 查看实时日志（Ctrl+C 退出查看） | `docker compose --env-file ../.env logs -f` |
| 停止并移除容器，保留挂载的数据目录 | `docker compose --env-file ../.env down` |

依赖、Dockerfile 或 `pyproject.toml` 修改后，需先重新构建镜像再更新全部应用服务（含 `env-agent`、`quickquip` 和 `web-admin`）：

```bash
docker compose --env-file ../.env build quickquip
docker compose --env-file ../.env up -d
```

---

## 常见问题 (FAQ)

### 1. 是否需要在云端服务器上安装 Codex？
**不需要。**
QuickQuip 直接通过模型 API 提供对话能力，并通过 MCP 协议接入外部工具服务：
- 内置网页搜索（`search_web`）由 SearXNG 提供；
- Tavily 等外部扩展工具通过 MCP 接入（只需在后台将 MCP 服务配置到 `settings.mcp.servers` 后保存并应用；相关 API 凭据写入根 `.env`，宿主机路径与 sidecar 容器编排在私有 `prod/` 中维护即可，详见 [MCP 接入指南](mcp-servers.md)）。

### 2. 协议端掉线后怎么办？

先在协议端自身的管理界面或日志中检查 QQ 在线状态，按协议端文档完成重连或重新扫码登录，再回到 QuickQuip 日志确认连接已恢复；若协议端显示 QQ 已在线但 QuickQuip 仍未连上，请核对双方配置的 WebSocket 方向、连接地址与访问令牌是否一致。

### 3. 如何降低 QQ 账号被风控/冻结的概率？
- 避免使用刚注册的新号，建议使用有一定正常使用历史的 QQ 号。
- 当登录地点、服务器 IP 或设备环境发生变化后，注意观察账号状态，必要时按手机 QQ 弹窗提示完成安全验证恢复登录。
- 避免在短时间内高频、大量地群发消息。

### 4. 宿主机端口冲突怎么办？
- Web Admin 端口冲突时修改 `prod/docker-compose.yml` 的宿主机侧端口。协议端端口在其自身编排中调整，之后更新连接它的地址。
- Bot 容器内监听 `8080`。仅在协议端需要从容器网络外反向连接时，为 Bot 添加所需的端口映射。

### 5. 为什么配好了 LLM 却不生效 / 群里没反应？
请按以下清单逐一排查：
1. **检查配置发布状态与心跳**：进入 Web Admin“LLM 配置”页，确认配置库 schema 受支持、修改后的**草稿已点击“应用到 Bot”**（注意：单纯重启容器不会应用未发布的草稿！），且顶部显示的 `published_revision`（已发布版本）与 Bot 的 `loaded_revision`（实际加载版本）一致、Bot 心跳处于新鲜状态。若应用任务卡住或报错，点开该任务查看具体报错阶段。
2. **检查 `.env` 必填项**：确认 `.env` 中已正确填写当前渠道所需的 API Key 环境变量，以及已启用 MCP 服务所需的 API Key。
3. **检查 SearXNG 连通性**：确认搜索服务正在运行，且从 `quickquip` 容器内部能够正常访问 `.env` 中配置的 `QUICKQUIP_SEARXNG_BASE_URL`。
4. **检查群身份索引文件（`identities.yaml`）**：确认 `llm_about/identities.yaml`（或群级覆盖 `llm_about/{群号}/identities.yaml`）存在且 YAML 格式正确。你可以在 Bot 启动日志中搜索对应提示来确认加载状态：文件缺失会记录 `INFO`、文件存在但仍是空模板会记录 `WARNING`、正常加载会打印 `已加载 N 条身份`。
5. **查看容器报错日志**：运行 `docker compose --env-file ../.env logs -f quickquip`，检查是否有配置文件缺失或 API Key 缺失的明确报错。
6. **重载独立资产与执行模型探活**：
   - 如果你修改的是本地人格（Persona）或词表文件，需在群内发送 `/llm reload`（或通过对应重载入口）使其生效。
   - `/llm reload` 会在重载后自动探活当前群实际生效的 `provider/model`；如果你需要对所有渠道做全量连通性巡检，可在群内发送 `/llm probe`，或在 Web Admin 诊断页点击“**探活 Provider**”（这会对所有已配置的 provider 各发送一次 `max_tokens=16` 的真实请求，可能按渠道计费）。
