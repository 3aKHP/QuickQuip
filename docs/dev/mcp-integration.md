# QuickQuip MCP 集成说明

## 当前状态

项目当前已经具备以下 MCP 能力：

- `config/llm.toml` 内可直接声明 `[[mcp.servers]]`
- 支持 `stdio`、`docker`、`http`、`sse` 四种 transport
- 配置值支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}` 展开
- 启动时自动发现 MCP tools，并桥接到现有 `ToolRegistry`
- `/llm mcp status` 可查看当前 server 装载结果

---

## 1. 目标边界

QuickQuip 把 MCP 作为项目自己的工具后端来源之一，而不是把 Codex 的本地运行方式原样搬进云端。

这两者不是一回事：

- Codex 的 `config.toml` 是 Codex 自己的 MCP client 配置
- QuickQuip 需要的是项目内的 MCP client / tool backend 集成

因此，远程服务器不需要安装 Codex。

---

## 2. 当前推荐路线

当前项目已经具备标准化工具调用能力，推荐优先级如下：

1. 内建工具（get_identity、list_memories 等）继续走本地实现
2. `search_web` 硬编码走 SearXNG
3. Tavily 搜索能力走 MCP 侧 `tavily_search` / `tavily_crawl` / `tavily_research`
4. GitHub、arXiv、PRTS Wiki 等按需作为 MCP 接入
5. 不为统一形式强行把所有工具都改成 MCP

---

## 3. 不推荐的方式

### 3.1 不推荐直接读取 Codex 的 `config.toml`

原因：

- 它是 Codex 的宿主配置，不是项目配置
- 里面的 server 定义、env 处理、项目 trust 逻辑都不属于 QuickQuip
- 它混有与当前项目无关的本机路径和个人开发环境信息

QuickQuip 应该维护自己的项目配置。当前实现已经把 MCP 配置并入：

- `config/llm.toml`

### 3.2 Docker Socket 的取舍

如果 QuickQuip 容器内直接执行：

```bash
docker run -i --rm ...
```

那通常意味着：

- 容器里要装 Docker CLI
- 容器要挂载 `/var/run/docker.sock`

这会显著放大权限范围。

`docker` transport 需要在容器内安装 Docker CLI 并挂载 `/var/run/docker.sock`，这会放大权限范围，仅适合开发环境或可信宿主机。

生产部署推荐走纯 sidecar 模式：在 `docker-compose.yml` 中将 MCP server 作为独立 service 跑在同一 compose 网络，bot 通过 `transport = "sse"` 或 `transport = "http"` 直连。代码中的四种 transport 均已完整实现，生产无需依赖 Docker socket。

当前生产环境已采用此模式——MCP server（tavily、fetch 等）以 sidecar 容器形式运行，经 compose 默认网络暴露 SSE 端点。

---

## 4. 推荐架构

### 4.1 三层结构

建议未来按三层来接 MCP：

1. `quickquip/app/message_pipeline.py` / `quickquip/llm/tool_registry.py`
2. `quickquip/llm/mcp.py`
3. `config/llm.toml` 内的 `[[mcp.servers]]` 定义

这样可以保持：

- 工具调用抽象稳定
- MCP 只是工具来源的一种
- 未来也能同时混用直连 API 工具和 MCP 工具

### 4.2 当前项目配置形式

当前项目使用 `config/llm.toml` 配置 MCP server：

```toml
[mcp]
enabled = true

[[mcp.servers]]
id = "github"
transport = "docker"
image = "ghcr.io/github/github-mcp-server"
env = { GITHUB_PERSONAL_ACCESS_TOKEN = "${GITHUB_PERSONAL_ACCESS_TOKEN}" }

[[mcp.servers]]
id = "arxiv"
transport = "docker"
image = "arxiv-mcp-server:latest"
mounts = ["${MCP_ARXIV_PAPERS_MOUNT:-arxiv-papers:/root/.arxiv-mcp-server/papers}"]
```

这份配置只服务于 QuickQuip，不混入 Codex 配置。

---

## 5. 远程部署准备

如果某个 MCP server 要接入 QuickQuip，远程服务器应提前准备：

1. 安装 Docker
2. 预拉对应镜像
3. 预建所需卷
4. 准备所需 API key / token
5. 明确 QuickQuip 将通过哪种方式访问这些 MCP

### 5.1 三种接法

#### A. 内建实现

适用：

- `get_identity` → 本地词表
- `list_memories` → 本地 SQLite / store

优点：

- 最稳
- 最简单

#### B. QuickQuip 自己作为 MCP client，按需启动 server

适用：

- GitHub MCP
- arXiv MCP
- PRTS Wiki MCP
- Tavily MCP（搜索、爬取、调研）

优点：

- 与现有工具调用框架契合
- 后续可扩展更多 server

代价：

- 要处理进程拉起、超时、stderr、重试
- `docker` transport 需要宿主机 Docker daemon 与 `docker.sock`

#### C. 宿主机单独桥接

适用：

- 不希望业务容器直接碰 Docker 权限

优点：

- 安全边界更清晰

代价：

- 要额外维护一层 bridge / launcher

---

## 6. 对当前项目的明确建议

现阶段建议如下：

- `search_web`
  - 继续硬编码走 SearXNG
- `get_identity`
  - 继续走本地词表
- `list_memories`
  - 继续走本地 SQLite / store
- Tavily 搜索
  - 走 MCP 侧 `tavily_search` / `tavily_crawl` / `tavily_research`
- GitHub / arXiv / PRTS Wiki
  - 已支持作为 MCP 接入
  - 是否启用由 `config/llm.toml` 与环境变量控制

也就是说：

- 现有工具调用框架先服务项目内部工具
- MCP 后续作为可插拔扩展层加入
- 不要为了 MCP 而重写已经稳定工作的直连能力

---

## 7. 后续实现建议

如果继续扩展 MCP，建议顺序如下：

1. 补充 `tools/list_changed` 的动态刷新
2. 为 Docker 型 server 增加更细的状态诊断
3. 把部分 `env` 从 `config/llm.toml` 进一步抽到更细的部署层
4. 按需要继续接新的 MCP server

不要一开始就同时接多个 server。

---

## 8. 当前文档结论

QuickQuip 当前已经可以接 MCP，但实际部署时仍应把它视为项目自己的外部工具后端，并通过项目自己的 `.env` / `dev/.env` 管理密钥、卷挂载和云端开关。
