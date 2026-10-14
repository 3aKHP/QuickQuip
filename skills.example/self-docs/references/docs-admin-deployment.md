<!-- Generated from docs/admin/deployment.md; do not edit -->

# QuickQuip 云端部署指南

本文面向 Linux 服务器部署者，介绍自动发布与手动安装、首次登录及日常维护。LLM 配置与升级见[配置管理](llm-configuration.md)，外部工具接入见[MCP 接入指南](mcp-servers.md)。

## 前提条件

- 一台 Linux 服务器，建议从 2 核／2G 内存及 2G swap 起步。v1.12.2 全栈验收在此规格下稳态约 0.7G RSS，后续按并发量与启用功能观察内存
- 已安装 Docker 和 Docker Compose
- Node.js + pnpm（手动部署构建前端用；deploy 脚本路径本机需有）
- QQ 账号（用于 OneBot 协议端登录；当前部署模板默认适配器为 LLBot，各适配器状态见 [onebot-adapters.md](onebot-adapters.md)）

## 选择服务器

按所需架构、资源容量及网络条件选择服务器。部署主机需要访问镜像源、QQ 协议端、所用模型 API 和搜索服务；先确认这些连接可用，再准备完整部署。费用按服务商当前报价核对。

## 部署步骤

首次手动安装按下方 1–7 步进行，先准备配置并启动服务，再登录后台启用 LLM。选择部署脚本时，先在本地准备第 3 步所列的模板、配置与资产，并按[生产模板的 SSH 设置](../../prod.example/README.md#ssh-connection)配置服务器连接；搜索服务需先在服务器上准备。准备完成后使用本文后面的[自动部署与版本回滚](#自动部署与版本回滚)。

### 1. 服务器上安装 Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效
```

### 2. 上传项目

这套 Docker 与部署脚本以 `prod.example/` 作为公共模板，以私有 `prod/` 目录作为实际生产运维目录。不要把 `prod/` 中的真实脚本配置、通知密钥或运行态目录提交到公共仓库。

```bash
# 推荐：从本地私有工作目录上传完整项目
scp -r /path/to/QuickQuip user@server:/path/to/QuickQuip
```

### 3. 准备生产运维目录和环境变量

```bash
cd /path/to/QuickQuip
cp .env.example .env
nano .env  # 按下表填写；QUICKQUIP_SEARXNG_BASE_URL 需取消注释
cp -r prod.example prod  # prod/ 已存在时会嵌套成 prod/prod.example（部署脚本会中止并提示），详见 prod.example/README.md
```

启动前在根 `.env` 填写：

| 配置 | 填写方法 |
|---|---|
| `QQ_ACCOUNT` | 用于机器人登录的 QQ 号 |
| `ONEBOT_ACCESS_TOKEN` | 自己设置的连接口令；第 5 步在 LLBot 填入同一值 |
| `DRIVER` | 正向 WebSocket 使用示例值 `~fastapi+~websockets` |
| `WEB_ADMIN_PASSWORD` | 自己设置的后台登录口令，替换示例占位值 |
| `QUICKQUIP_SEARXNG_BASE_URL` | 从 Bot 容器可访问的 SearXNG 地址，生产模板启动时必填 |
| 所选渠道的 API key | 启用 LLM 时填写该渠道使用的变量，例如 `OPENAI_API_KEY` |

已有 SearXNG 时填写它的地址。首次自建可以在**服务器项目根目录**用仓库根模板单独启动搜索服务：在 `.env` 中把 `SEARXNG_SECRET` 改成自己的随机字符串，保留示例的 `SEARXNG_BIND_PORT=8888`，执行下面的 Bash 命令。

```bash
SEARXNG_BIND_ADDRESS="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')" \
  docker compose -p quickquip-search -f docker-compose.example.yml up -d searxng
docker network inspect bridge --format 'QUICKQUIP_SEARXNG_BASE_URL=http://{{(index .IPAM.Config 0).Gateway}}:8888'
```

将最后一行输出写入根 `.env`，替换注释中的 `QUICKQUIP_SEARXNG_BASE_URL`。这条 Linux Docker 路线将搜索端口绑定在默认 Docker 网桥地址，供 Bot 容器访问；[Docker 的端口映射说明](https://docs.docker.com/engine/network/port-publishing/)解释了跨网桥访问已发布端口的方式。`quickquip-search` 使用独立 Compose 项目名，后续应用发布会保留这个搜索服务。已有搜索服务的部署直接填写其可达地址即可。

LLM 初次使用将 `config/personas.example/` 复制为 `config/personas/`；服务启动后按第 7 步添加渠道并应用配置。其他功能按需准备：

- 如启用 MCP sidecar，再按你的私有 `prod/` 编排补充对应 API key
- 已有部署升级时按[配置管理](llm-configuration.md#初始化与升级)完成数据库迁移，保留迁移前配置与资产备份
- 如启用图片、语音、音乐或 ASR，`config/generation.toml` 已存在并填入对应 provider 与模型
- 如启用低频唤醒，`config/awakening.toml` 已存在并填入阈值、兴趣话题和按群覆盖
- 如启用敏感词过滤，`config/sensitive_words.toml` 已存在并填入部署侧词表
- 如启用 Skill 系统，`skills/` 目录已放置技能包（预置包从 `skills.example/` 复制，Windows 懒人包首启自动完成；目录为空或不存在时 Skill 工具不注册，详见 [skills.md](skills.md)）
- `prod/` 已由 `prod.example/` 复制而来，并按服务器环境调整 compose、部署脚本或巡检脚本
- 如需 ServerChan 等运维通知，在 `prod/sendkey.env` 中维护；该文件不被 QuickQuip 应用读取

自动部署会把：

- 根 `.env`
- `config/` 目录下的运行配置（如 `generation.toml`、`awakening.toml`、`sensitive_words.toml`、`games.toml`）
- `skills/` 目录（Skill 系统技能包，从 `skills.example/` 复制预置包或自建；每次部署把其中新增的 Skill 非破坏性合并进服务器部署根共享 `skills/`：已存在文件不被覆盖、删除不传播，已安装 Skill 的更新与删除经 Web 管理页或服务器手动维护）
- `llm_about/vocab.yaml`
- `llm_about/identities.yaml`
- `llm_about/{群号}/vocab.yaml`
- `llm_about/{群号}/identities.yaml`

一并用于容器运行。

若存在 `data/tieba/storage_state.json`，部署脚本还会把它单独上传到云端，供贴吧功能复用本地导出的登录态。

根目录 `.env` 是 QuickQuip 应用的唯一涉密凭证来源。`prod/` 只承载部署脚本、compose 编排、巡检脚本和运维通知密钥。

### 4. 启动服务

启动前需先构建 Web Admin 前端（`cd frontend && pnpm install --frozen-lockfile && pnpm build`），产物 `frontend/dist` 会被 web-admin 容器只读挂载。手动部署路径需在服务器安装 Node.js + pnpm 后构建；使用 `prod/deploy-v4.sh` / `prod/deploy-v4.ps1` 部署脚本则在本机自动完成。

```bash
cd /path/to/QuickQuip/prod
docker compose --env-file ../.env build quickquip
docker compose --env-file ../.env run --rm --no-deps web-admin python -m quickquip.llm.config_cli init
docker compose --env-file ../.env up -d
```

中间的初始化命令借用 Web 容器的可写配置挂载，建立空配置库或迁移旧 TOML，完成后退出。新安装保持 LLM 关闭，在第 7 步通过后台启用；已有配置库的升级按[初始化与升级](llm-configuration.md#初始化与升级)的停服和备份要求执行。

当前 compose 会：

- 通过第 3 步设置的 `QUICKQUIP_SEARXNG_BASE_URL` 连接独立 SearXNG 服务
- 通过 `../.env` 向 bot 和 Web Admin 提供应用环境变量
- 把 `../config` 只读挂载到容器内 `/app/config`
- 把部署根共享 `skills/` 挂载到容器内 `/app/skills`（Skill 技能包目录，与 `data/` 同级：`quickquip` 只读、`web-admin` 读写以支撑 Skill 页在线管理；扁平安装时即项目根 `skills/`；目录为空或不存在时 Skill 工具不注册，详见 [skills.md](skills.md)）
- 把 `../llm_about` 挂载到容器内 `/app/llm_about`
  - 其中包含全局 `vocab.yaml` / `identities.yaml` 与可选群级覆盖目录
- 把 `../data` 挂载到容器内 `/app/data`，用于持久化统计、规则开关、LLM 数据库
- 让贴吧运行时从 `/app/data/tieba/storage_state.json` 读取跨平台登录态
- 直接基于 Playwright Python 镜像运行贴吧采集，镜像内已预装浏览器与系统依赖
- 通过构建参数把 Python 包安装源切到国内镜像，减少云端拉取超时
- 可通过 `PLAYWRIGHT_BASE_IMAGE` 指定适合当前网络环境的 Playwright 基础镜像

补充说明：

- **`DRIVER` 以 `.env` 为最终生效值**：compose 的 `environment:` 插值与 `env_file:` 都会读到同一份 `.env`，在其中写 `DRIVER=~fastapi` 会同时穿透两层覆盖模板默认。要让 QuickQuip 正向 WebSocket 连接协议端（`ONEBOT_WS_URLS` 指向适配器的 WS 服务端，当前默认模板为 `ws://llbot:3001/`），`DRIVER` 必须是 `~fastapi+~websockets`（纯 `~fastapi` 无 WS client 能力，`ONEBOT_WS_URLS` 会被忽略并告警）。替代拓扑：在适配器管理界面启用反向 WS 指向 QuickQuip 的 `ws://<bot地址>:8080/onebot/v11/ws`，此时 QuickQuip 侧不需要 WS client（连接拓扑详见 [onebot-adapters.md](onebot-adapters.md)）。deploy 脚本在 `prod/llbot-data` 存在时会自动把 `ONEBOT_ACCESS_TOKEN` 同步进 LLBot 反向 WS 配置，正反拓扑可并存。
- Bot 和 Web 共享本机 `data/llm_config.db`。手动安装使用上面的初始化命令准备配置与独立资产；已有部署升级按[迁移步骤](llm-configuration.md#初始化与升级)执行。部署脚本保留生产库，本地配置库和旧 TOML 由各自的配置运维流程管理。Bot 重启读取已发布快照，草稿通过后台单独应用。Bot 每 30 秒检查 `awakening.toml` 的修改时间并重载。
- 部署脚本在切换发行目录后强制重建应用容器一次，使源码和配置挂载指向本次发行目录
- 在线调整 LLM 配置通过 Web Admin“LLM 配置”保存草稿并应用，等待任务完成及 Bot 实际版本确认。修改价格等无关字段保持 MCP 连接；MCP 改动的连接状态独立回报。`/llm reload` 重载已发布配置及相关独立资产，并探活当前模型，可能计费。

### 4.1 首次准备贴吧登录态

贴吧登录态建议先在本地机器生成，再通过部署脚本同步到云端：

```bash
python -m quickquip.tieba.login
```

成功后会生成：

```text
data/tieba/storage_state.json
```

后续执行 `prod/deploy-v4.ps1`（Windows）或 `bash prod/deploy-v4.sh`（Linux）时，该文件会自动单独上传到云端。

### 4.2 CJK 字体文件（词云与 SVG 画图）

词云与 SVG 画图（`draw_svg` 工具）共用同一个 CJK 字体文件，不随代码仓库分发，需手动放置：

1. 从 [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+SC) 下载 `NotoSansSC-Regular.ttf`
2. 放置到 `data/fonts/NotoSansSC-Regular.ttf`

容器化部署时，`data/fonts/` 目录应通过 `data/` bind mount 挂载到容器内，字体文件上传一次后即可持久使用。若字体文件缺失，执行 `/wordcloud` 时 bot 会回复明确的错误提示；SVG 画图则回退系统字体，精简系统上中文可能渲染为方框，建议同样放置该文件。

SVG 画图的依赖与平台差异：

- 渲染引擎 resvg 以 pip 依赖随 `requirements.txt` 安装，Docker 镜像与 Windows 懒人包均随依赖安装自动获得，无需额外系统依赖或构建步骤。
- 文本渲染优先使用上述 NotoSansSC 字体；emoji 等字符依赖系统字体回退。官方 Playwright 基础镜像自带常用字体（含彩色 emoji），Docker 部署一般无需处理；裸机源码部署在精简系统上可能缺少 emoji 字体，图中 emoji 会显示为方框；Windows 使用系统字体（微软雅黑、Segoe UI Emoji），一般无需处理。
- 渲染子进程的资源硬限制（地址空间 / CPU 时间）依赖 POSIX `rlimit`，在 Linux 等 POSIX 平台生效；Windows 保留 8 秒墙钟超时兜底。

### 5. 首次登录 OneBot 协议端

协议端首次启动需要扫码登录。以下以当前默认适配器 **LLBot 7.3.2** 为例（完整 profile、版本 pin 原因与其他适配器状态见 [onebot-adapters.md](onebot-adapters.md)）：

```bash
# 查看协议端日志，找到登录二维码
docker compose --env-file ../.env logs -f llbot
```

日志中会出现二维码或登录链接，用手机 QQ 扫码确认。模板的 WebUI 端口绑定服务器本机；需要浏览器操作时，在本地终端建立 SSH 隧道，将 `user@server` 替换为服务器账号与地址：

```bash
ssh -N -L 3080:127.0.0.1:3080 user@server
```

保持隧道运行，在本地浏览器打开 `http://127.0.0.1:3080` 扫码。登录态持久化在 `prod/llbot-qq/`，配置在 `prod/llbot-data/`。

**镜像版本与 pin**：compose 模板固定使用 `initialencounter/llonebot:v7.12.14-7.3.2-45758`，版本选择与升级事项见 [onebot-adapters.md](onebot-adapters.md) 的 LLBot profile。

**WebUI 启用 OneBot 对接**：新部署的 LLBot 四种网络对接方式（正向 WS / 反向 WS / HTTP / HTTP 上报）默认全部关闭。在上述 WebUI 中启用所需方式——正向 WebSocket（服务端）的 token 为必填项，须与根目录 `.env` 的 `ONEBOT_ACCESS_TOKEN` 同值，QuickQuip 侧才连得上。

**重启与快速登录**：`llbot-qq/` 登录态目录完好时，容器重启后 LLBot 可能走快速登录（`QUICK_LOGIN_QQ` 生效，免扫码），也可能要求重新扫码——快速登录存在时效性（验收中两种情况都出现过）。登录异常时先用 `docker compose --env-file ../.env restart llbot` 重启，保留 `llbot-qq/` 登录态；扫码后若消息无响应且日志出现 `getSelfNick` 等 TypeError，restart 一次触发快速登录即可恢复。

### 6. 验证运行

```bash
# 查看两个容器是否正常运行
docker compose --env-file ../.env ps

# 查看 QuickQuip 日志
docker compose --env-file ../.env logs -f quickquip
```

在群里发送“早安”，收到时区猜测回复即确认基本群消息收发与规则响应可用。启用的 LLM 和其他功能按下方检查。

如果还启用了贴吧功能，可以继续验证：

```text
/tieba status
/tieba refresh
```

### 7. Web 管理后台

compose 会同时启动 `web-admin` 容器（`python web_api.py`，容器内监听 `0.0.0.0:5104`，宿主侧绑定 `127.0.0.1:5104`）。首次管理在**自己电脑的另一个终端**建立隧道，将 `user@server` 替换为服务器账号与地址：

```bash
ssh -N -L 5104:127.0.0.1:5104 user@server
```

保持隧道窗口运行，在自己电脑的浏览器打开 `http://127.0.0.1:5104/ops/`，输入第 3 步设置的 `WEB_ADMIN_PASSWORD`。进入概览后，按[首次启用 LLM](llm-configuration.md#首次启用-llm)添加一个渠道和模型、保存并应用，等待 Bot 加载，再在测试群开启 AI 并收到第一条回复。

后台提供：

- 消息统计（各群消息数、活跃用户、规则触发次数）
- 群级规则开关（toggle 开关，实时生效）
- 每日总结 / 每日播报群组管理
- LLM 结构化配置、保存／应用、JSON 导入预览、实际 Bot 状态和配置任务
- `config/generation.toml`、`config/chat_rules.toml`、`config/games.toml`、`config/awakening.toml`、`config/niuniu_text.toml`、`config/niuniu_text_safe.toml` 在线编辑（保存前校验 TOML 语法）
- 敏感词过滤器只读状态查看；`config/sensitive_words.toml` 只通过服务器本地文件或部署流程维护，不在 Web Admin 中回显或编辑
- 记忆、对话、人格、资料、唤醒、LLM 用量、MCP、贴吧、词云、语录、调度器监控、审计、金币经济和牛牛面板
- 实时日志 / LLM Trace / 日志归档面板（日志读取 `../data/logs`，LLM HTTP 调用索引和正文读取 `../data/llm_trace.db`）

长期通过 HTTPS 反向代理访问时，按 [Web Admin 的代理说明](web-admin.md#反向代理注意事项)配置站点。配置 nginx `auth_basic` 的部署有两层门：

- nginx `auth_basic`：外层站点访问控制，密码文件位置由你的反代配置决定
- QuickQuip Web Admin session：应用层登录，会读取 `WEB_ADMIN_PASSWORD` 并在浏览器里建立 `HttpOnly` session cookie

后台登录口令已在第 3 步设置，其他登录参数可在根 `.env` 调整：

```env
WEB_ADMIN_SESSION_TTL_HOURS=168
WEB_ADMIN_COOKIE_SECURE=auto
```

`WEB_ADMIN_COOKIE_SECURE=auto` 依赖反代传递 `X-Forwarded-Proto`；若你的 nginx 未传该 header，但站点本身跑在 HTTPS 下，则把它显式设为 `true`。

`web-admin` 容器挂载：

| 宿主路径 | 容器路径 | 权限 |
|---|---|---|
| `../data` | `/app/data` | 读写 |
| `../config` | `/app/config` | **读写**（独立配置在线编辑与首次迁移资产提取） |
| `../llm_about` | `/app/llm_about` | **读写**（资料页在线编辑需要） |
| `${QUICKQUIP_ROOT:-..}/skills`（扁平安装即 `../skills`） | `/app/skills` | **读写**（Skill 页在线安装/编辑/预置同步落盘） |
| `../frontend/dist` | `/app/frontend/dist` | 只读 |
| `../web_api.py` | `/app/web_api.py` | 只读 |
| `../src` | `/app/src` | 只读（hybrid 源码热更新） |

> 注意：`quickquip` 容器的 `config`、`llm_about` 与共享 `skills/` 挂载保持只读（`:ro`），只有 `web-admin` 需要写权限。
> `config/sensitive_words.toml` 即使位于同一挂载目录，也不会通过 Web Admin 配置编辑器读取或写入。

## 自动部署与版本回滚

日常部署推荐使用 `prod/deploy-v4.sh`（Bash）或 `prod/deploy-v4.ps1`（PowerShell）。两端共享远端事务执行器，按清单上传应用文件，预检和构建成功后切换版本目录，并验证容器、OneBot 连接与 Web Admin HTTP。完整前提、参数与目录结构见 [生产模板说明](../../prod.example/README.md)。服务器需具备 rsync、flock、Python ≥ 3.11.8 和 Docker Compose ≥ 2.27。

执行前，`prod/` 已从 `prod.example/` 复制，根 `.env` 和所选功能配置已填写，`quickquip-prod` 已替换为自己的 SSH 连接名称。首次准备见第 3 步；日常命令位于[自动部署操作](#自动部署操作)。

已有平铺部署首次使用 `--migrate`：先保存服务器上的旧代码与运行镜像作为基线，再部署候选版本。新服务器首次尚未扫码时可显式使用 `--skip-health`，之后完成扫码与健康核验。PowerShell 使用同名参数，指定回滚版本时使用 `-Rollback -ReleaseId <id>`；完整接口见 `bash prod/deploy-v4.sh --help`。

每次发布携带一个版本标识：部署的 `pyproject.toml` 版本加上服务器镜像构建完成时刻（如 `1.15.3-dev.2+build.20260909.065235`），出现在事务日志的 `image built` 与 `release complete` 行中，便于将线上 release 目录与代码版本对上号。

部署失败时自动恢复本次修改的共享文件并验证旧版本健康；手动回滚保留当前根 `.env`、数据库与部署根共享 `skills/`（Skill 安装成果不随代码版本回退；目标 compose 使用共享目录时，回滚把目标 release 中新增的 Skill 非破坏性合并进共享目录）。回滚到挂载 release 自带 `skills/` 副本的历史版本时，该版本继续使用其目录内副本。数据迁移与外部副作用不随代码回滚，部署前应核对版本升级说明。`--dry-run` 会本地构建前端，PowerShell 还会临时打包，两者均不连接远端。

配置备份使用 `python -m quickquip.llm.config_cli backup data/llm-config-backup.db` 的 SQLite backup 接口。恢复数据库前停止 Bot 和 Web，先备份当前库，再运行 `restore --file <备份路径> --services-stopped`；恢复会清除旧运行租约与心跳。配置回流、导入预览、应用及备份恢复可使用模板的 Bash／PowerShell 配置运维驱动，完整命令见 [LLM 配置管理](llm-configuration.md)。

回退至 1.16.1 使用首次迁移前的 TOML 及人格／多模态资产备份；升级后新增的配置不会反向转换成 TOML。新库保留供再次升级，回退应同时核对运行代码与迁移前配置资产。升级与回退前还需备份会话库和追踪库；旧代码运行后再次升级的 Session 身份维护步骤见[回退旧版本后再次升级](llm-configuration.md#回退旧版本后再次升级)。

运行态位于部署根目录的 `data/`、`skills/` 和 `prod/`，版本内容位于 `releases/<id>/`，`current` 与 `previous` 指向当前和前一版本。运维命令需按 [模板中的手动访问步骤](../../prod.example/README.md#manual-compose-access) 导出部署根目录和版本标识。手动平铺安装按上方 1–7 步进行，版本目录部署由脚本管理。

### 自动部署操作

以下命令在**本地项目根目录**执行。首次准备见第 3 步及[SSH 设置](../../prod.example/README.md#ssh-connection)；`quickquip-prod` 使用自己的连接名称。先单独运行预览，确认上传内容，再执行部署：

```bash
bash prod/deploy-v4.sh --dry-run
```

```bash
bash prod/deploy-v4.sh --host-alias quickquip-prod
bash prod/deploy-v4.sh --status --host-alias quickquip-prod
```

新服务器首次需要扫码时，首次部署使用 `--skip-health`，之后按第 5、7 步登录，并按[生产模板的首次健康检查](../../prod.example/README.md#commands)核验。版本目录服务器执行 Compose 命令前，按[手动访问说明](../../prod.example/README.md#manual-compose-access)设置路径与版本变量；上面的手动安装命令使用平铺目录。

回滚由需要恢复上一版本的部署单独执行：

```bash
bash prod/deploy-v4.sh --rollback --host-alias quickquip-prod
```

## 代码更新

项目采用 **hybrid 混合模式**部署：

- **镜像构建时** `pip install --no-deps .` 将 `src/` 下的 `quickquip` 和 `plugins` 安装至 site-packages，作为 baked fallback。
- **运行时** docker-compose 将 `../src` 挂载到 `/app/src` 并通过 `PYTHONPATH=/app/src` 使其优先于 site-packages，实现**源码热更新**。

因此：

- 改了 `src/quickquip/` 或 `src/plugins/` 下的 Python 代码后，**重启容器即可生效**，无需重建镜像：

  ```bash
  cd /path/to/QuickQuip/prod
  docker compose --env-file ../.env restart quickquip web-admin
  ```

- 改动了 `pyproject.toml`、`requirements.txt`、`Dockerfile` 或 `src/` 下新增/删除了文件时，**需重建镜像**：

  ```bash
  cd /path/to/QuickQuip/prod
  docker compose --env-file ../.env build quickquip
  docker compose --env-file ../.env up -d quickquip web-admin
  ```

- 只改了 `frontend/dist`（前端静态文件）时，`docker restart quickquip-web-admin` 即可，无需重建。

**历史数据回灌（可选）**：`scripts/` 随镜像分发两个一次性回灌脚本——`backfill_record_identities.py` 为存量记忆、语录和留言补齐正文片段与成员引用索引（专文见 [record-identities.md](record-identities.md)）；`backfill_chat_archive.py` 把 1.15.2 之前退役的旧每日消息 / 词云 JSONL（`data/daily_msgs/`、`data/wordcloud_msgs/`）导入聊天记录归档库 `data/chat_archive.db`（导入完成后旧 JSONL 目录方可清理）。服务器容器内运行：

```bash
docker compose --env-file ../.env exec -T quickquip python scripts/backfill_chat_archive.py --dry-run
```

`--dry-run` 仅预览；确认统计符合预期后去掉该参数正式执行。脚本统计新增、归因回填、已存在、跳过与写入失败，存在写入失败时返回非零——确认失败为零后再清理旧 JSONL。Windows 懒人包的对应说明见 [README.md](../../README.md)。

## 日常维护

修改根 `.env` 或 Compose 配置后，在实际 Compose 所在目录重新创建服务，使新环境变量和挂载生效。平铺生产部署执行：

```bash
docker compose --env-file ../.env up -d quickquip web-admin
```

版本目录部署先按[手动访问步骤](../../prod.example/README.md#manual-compose-access)设置变量，沿用 `--env-file "$QUICKQUIP_ENV_FILE"`。使用根模板或自定义 Compose 的部署沿用启动时的 `-f` 等参数；仅改后台口令时可只更新 `web-admin`。下面的 `restart` 用于重新加载已挂载的 Python 源码。

```bash
# 更新 Python 源码后重启（hybrid 模式下无需重建）
cd /path/to/QuickQuip/prod
docker compose --env-file ../.env restart quickquip web-admin

# 更新依赖/Dockerfile/pyproject 后重建
cd /path/to/QuickQuip/prod
docker compose --env-file ../.env build quickquip
docker compose --env-file ../.env up -d quickquip web-admin

# 查看日志
docker compose --env-file ../.env logs -f

# 停止
docker compose --env-file ../.env down
```

## 常见问题

### 是否需要在云端安装 Codex

不需要。

QuickQuip 通过模型 API 提供对话，通过 MCP 接入外部工具服务。将 MCP 服务配置到 `settings.mcp.servers` 后保存并应用；凭据写入根 `.env`，宿主路径和 sidecar 编排在私有 `prod/` 中维护。

当前项目通过 SearXNG 提供内置 `search_web` 搜索，通过 MCP 扩展接入 Tavily 等外部工具。MCP 集成的正式约定见 [docs/dev/mcp-integration.md](../../docs/dev/mcp-integration.md)。

### LLBot 登录态过期

换 IP 或长时间未活动后可能需要重新扫码：

```bash
docker compose --env-file ../.env restart llbot
docker compose --env-file ../.env logs -f llbot  # 找新的二维码
```

### QQ 风控/冻结

- 新注册的 QQ 号容易被风控，建议用有一定使用历史的号
- 登录地点、IP 或设备变化后观察账号状态，必要时按 QQ 提示恢复登录
- 避免短时间内大量发消息

### 端口冲突

如果服务器上 OneBot 协议端端口（LLBot 默认 3001/3080）或 Web Admin 的 5104 已被占用，在 `docker-compose.yml` 中修改 compose 端口映射的宿主机侧即可；8888 仅当同机自建/自跑 searxng 时才相关。QuickQuip 的 8080 端口只用于容器内部通信，不需要对外暴露。

### LLM 配置不生效

优先检查以下几项：

- 配置库 schema 是否受支持；草稿是否已单独应用，published_revision 与 Bot loaded_revision 是否一致，心跳是否新鲜
- `.env` 中是否填了当前所选渠道的密钥环境变量
- `.env` 中是否填了 `QQ_ACCOUNT` 以及启用 MCP 时需要的 API key
- 搜索服务是否运行，QuickQuip 容器内是否能访问配置里的 `SEARXNG_BASE_URL`
- `llm_about/identities.yaml` 是否存在且格式正确；如只使用群级覆盖，也确认 `llm_about/{群号}/identities.yaml` 存在。文件缺失（INFO）、存在但为空模板（WARNING）、正常加载（`已加载 N 条身份`）在 bot 日志中均有对应记录，可据此核对身份索引是否生效
- `docker compose --env-file ../.env logs -f quickquip` 中是否出现配置文件缺失或 API key 缺失提示
- 如果渠道／模型修改未生效，检查原应用任务的阶段与错误，并确认 Bot 心跳；单独重启不会应用草稿。人格或词表文件修改通过 `/llm reload` 或对应独立重载入口生效。
- `/llm reload` 会在重载后探活当前群实际生效的 provider/model；如需全量巡检，在群内执行 `/llm probe` 或在 Web Admin 诊断页点击“探活 Provider”，会对所有已配置 provider 各发一次 max_tokens=1 的真实请求，可能产生 provider 计费
