# QuickQuip 云端部署指南

LLM 模块的详细结构、边界和群内命令说明见 [../dev/llm-module.md](../dev/llm-module.md)。如果后续需要把外部工具后端接成 MCP，另见 [../dev/mcp-integration.md](../dev/mcp-integration.md)。

## 前提条件

- 一台 Linux 服务器（1 核 1G 即可）
- 已安装 Docker 和 Docker Compose
- QQ 账号（用于 NapCat 登录）

## 推荐服务器

| 方案 | 价格 | 优缺点 |
|------|------|--------|
| Oracle Cloud Free Tier | 免费 | ARM 1 核 1G 永久免费，注册看运气，IP 可能被风控 |
| 腾讯云/阿里云轻量 | 50-100 元/年 | 国内网络延迟低，稳定，大促时性价比高 |
| 雨云/狗云等小厂 | 30-60 元/年 | 更便宜，稳定性看运气 |

## 部署步骤

### 1. 服务器上安装 Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效
```

### 2. 上传项目

这套 Docker 与部署脚本是**私有部署工具**，默认不面向公共仓库使用。不要假设可以只靠公共 GitHub 仓库直接还原完整部署环境。

```bash
# 推荐：从本地私有工作目录上传完整项目
scp -r /path/to/QuickQuip user@server:/path/to/QuickQuip
```

### 3. 配置环境变量

```bash
cd /path/to/QuickQuip
cp .env.example .env
nano .env  # 填入 QQ 号、OneBot 配置和 API key
```

同时确认：

- 根目录下的 `.env` 已存在，并填入 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`
- 如果仍需保留 Tavily 作为备用搜索后端，再额外填入 `TAVILY_API_KEY`
- 根目录下的 `config/llm.toml` 已存在并填入真实 provider / model / base_url 配置
- 如使用私有部署编排，相关环境变量文件不应进入公共仓库

当前部署会把：

- 根 `.env`
- `config/llm.toml`
- `llm_about/vocab.yaml`
- `llm_about/identities.yaml`
- `llm_about/{群号}/vocab.yaml`
- `llm_about/{群号}/identities.yaml`

一并用于容器运行。
若存在 `data/tieba/storage_state.json`，部署脚本还会把它单独上传到云端，供贴吧功能复用本地导出的登录态。

### 4. 启动服务

```bash
cd /path/to/QuickQuip
docker compose up -d
```

当前 compose 会：

- 按你的私有编排连接搜索服务
- 把 `quickquip` 容器内的 `SEARXNG_BASE_URL` 覆盖为可访问的搜索服务地址
- 把 `../config` 只读挂载到容器内 `/app/config`
- 把 `../llm_about` 挂载到容器内 `/app/llm_about`
  - 其中包含全局 `vocab.yaml` / `identities.yaml` 与可选群级覆盖目录
- 把 `../data` 挂载到容器内 `/app/data`，用于持久化统计、规则开关、LLM 数据库
- 让贴吧运行时从 `/app/data/tieba/storage_state.json` 读取跨平台登录态
- 直接基于 Playwright Python 镜像运行贴吧采集，镜像内已预装浏览器与系统依赖
- 通过构建参数把 Python 包安装源切到国内镜像，减少云端拉取超时
- 可通过 `PLAYWRIGHT_BASE_IMAGE` 指定适合当前网络环境的 Playwright 基础镜像

补充说明：

- `config/llm.toml`、`llm_about/vocab.yaml`、`llm_about/identities.yaml` 及群级覆盖文件虽然是 bind mount，但 `quickquip` 会在进程启动时把它们读入内存
- 因此部署脚本在同步文件后会额外强制重建 `quickquip` 容器，避免新 persona 或词表已经上传但运行时仍在使用旧配置
- 如果只是在线微调配置而不走部署脚本，也可以在群里手动执行 `/llm reload`

### 4.1 首次准备贴吧登录态

贴吧登录态建议先在本地机器生成，再通过部署脚本同步到云端：

```bash
# 运行项目自带的贴吧登录脚本（位于开发工作区中），按提示完成扫码登录
```

成功后会生成：

```text
data/tieba/storage_state.json
```

后续执行你的私有部署脚本时，该文件会自动单独上传到云端。

### 4.2 词云字体文件

词云功能需要一个 CJK 字体文件，不随代码仓库分发，需手动放置：

1. 从 [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+SC) 下载 `NotoSansSC-Regular.ttf`
2. 放置到 `data/fonts/NotoSansSC-Regular.ttf`

容器化部署时，`data/fonts/` 目录应通过 `data/` bind mount 挂载到容器内，字体文件上传一次后即可持久使用。若字体文件缺失，执行 `/wordcloud` 时 bot 会回复明确的错误提示。

### 5. 首次登录 NapCat

NapCat 首次启动需要扫码登录：

```bash
# 查看 NapCat 日志，找到登录二维码
docker compose logs -f napcat
```

日志中会出现二维码或登录链接，用手机 QQ 扫码确认。登录成功后，登录态会持久化在 `napcat-data/` 目录中。

### 6. 验证运行

```bash
# 查看两个容器是否正常运行
docker compose ps

# 查看 QuickQuip 日志
docker compose logs -f quickquip
```

在群里发一条"早安"，如果 bot 回复了时区猜测，说明部署成功。

如果还启用了贴吧功能，可以继续验证：

```text
/tieba status
/tieba refresh
```

### 7. Web 管理后台

compose 会同时启动 `web-admin` 容器（`python web_api.py`，默认监听 `127.0.0.1:5104`）。通过 nginx 反代后即可打开管理界面，提供：

- 消息统计（各群消息数、活跃用户、规则触发次数）
- 群级规则开关（toggle 开关，实时生效）
- 每日总结 / 每日播报群组管理
- `config/llm.toml` 在线编辑（保存前校验 TOML 语法）

管理界面同时有两层门：

- nginx `auth_basic`：外层站点访问控制，密码文件位置由你的反代配置决定
- QuickQuip Web Admin session：应用层登录，会读取 `WEB_ADMIN_PASSWORD` 并在浏览器里建立 `HttpOnly` session cookie

建议在私有环境变量文件中补充：

```env
WEB_ADMIN_PASSWORD=change-this-admin-password
WEB_ADMIN_SESSION_TTL_HOURS=168
WEB_ADMIN_COOKIE_SECURE=auto
```

`WEB_ADMIN_COOKIE_SECURE=auto` 依赖反代传递 `X-Forwarded-Proto`；若你的 nginx 未传该 header，但站点本身跑在 HTTPS 下，则把它显式设为 `true`。

`web-admin` 容器挂载：

| 宿主路径 | 容器路径 | 权限 |
|---|---|---|
| `../data` | `/app/data` | 读写 |
| `../config` | `/app/config` | **读写**（llm.toml 在线编辑需要） |
| `../llm_about` | `/app/llm_about` | **读写**（资料页在线编辑需要） |
| `../frontend/dist` | `/app/frontend/dist` | 只读 |

> 注意：`quickquip` 容器的 `config` 和 `llm_about` 挂载仍可保持只读（`:ro`），只有 `web-admin` 需要写权限。

### web-admin 代码更新

`quickquip/` 下的 Python 代码是**打进镜像**的，不是 bind mount。因此：

- 改了 `quickquip/app/web/` 或其他 Python 代码后，**必须重建镜像**，`docker restart` 不够：

  ```bash
  cd /path/to/QuickQuip
  docker compose build web-admin
  docker compose up -d web-admin
  ```

- 只改了 `frontend/dist`（前端静态文件）时，`docker restart quickquip-web-admin` 即可，无需重建。

## 日常维护

```bash
# 更新代码后重新构建
cd /path/to/QuickQuip
docker compose up -d --build

# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down
```

## 常见问题

### 是否需要在云端安装 Codex

不需要。

如果未来要给 QuickQuip 接 MCP，应该把 MCP 视为 QuickQuip 自己的外部工具后端。当前项目已经支持把 Codex 里常用的 Docker 型 MCP server 镜像到 `config/llm.toml`，但部署时仍要按 QuickQuip 自己的私有环境变量来管理密钥和宿主路径。

当前项目已经同时保留 Tavily 直连能力和 MCP 扩展能力。MCP 集成的正式约定见 [../dev/mcp-integration.md](../dev/mcp-integration.md)。

### NapCat 登录态过期

换 IP 或长时间未活动后可能需要重新扫码：

```bash
docker compose restart napcat
docker compose logs -f napcat  # 找新的二维码
```

### QQ 风控/冻结

- 新注册的 QQ 号容易被风控，建议用有一定使用历史的号
- 海外 IP 更容易触发风控，国内服务器会稳定很多
- 避免短时间内大量发消息

### 端口冲突

如果服务器上 6099 或 8080 端口已被占用，在 `docker-compose.yml` 中修改端口映射即可。QuickQuip 的 8080 端口不需要对外暴露（容器内部通信）。

### LLM 配置不生效

优先检查以下几项：

- `config/llm.toml` 是否存在且内容正确
- `.env` 中是否填了 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`
- 私有环境变量文件中是否把 `SEARCH_BACKEND` 设为 `searxng`
- 私有环境变量文件中是否填了 `QQ_ACCOUNT`、`GITHUB_PERSONAL_ACCESS_TOKEN` 与云端 MCP 覆盖值
- 搜索服务是否运行，QuickQuip 容器内是否能访问配置里的 `SEARXNG_BASE_URL`
- `llm_about/identities.yaml` 是否存在且格式正确；如只使用群级覆盖，也确认 `llm_about/{群号}/identities.yaml` 存在
- `docker compose logs -f quickquip` 中是否出现配置文件缺失或 API key 缺失提示
- 如果文件内容已经更新，但 `/llm personas`、`/llm providers` 或词表行为仍旧是旧版本，先执行 `/llm reload`，或确认部署脚本是否已经把 `quickquip` 容器重建
