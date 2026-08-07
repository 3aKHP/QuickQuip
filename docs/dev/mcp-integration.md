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

GHCR 分发镜像和生产模板镜像已内置 Docker CLI，以便需要时启用 `docker` transport。真正启用还必须显式挂载 `/var/run/docker.sock`，这会放大权限范围，仅适合开发环境或可信宿主机。

容器化部署推荐走纯 sidecar 模式：在部署编排中将 MCP server 作为独立 service 跑在同一网络里，bot 通过 `transport = "sse"` 或 `transport = "http"` 直连。代码中的四种 transport 均已完整实现，部署时无需依赖 Docker socket。

---

## 4. 推荐架构

### 4.1 三层结构

建议未来按三层来接 MCP：

1. `src/quickquip/app/message_pipeline.py` / `src/quickquip/llm/tool_registry.py`
2. `src/quickquip/llm/mcp/`（包，v1.8.9 从单文件 `mcp.py` 拆分而来）
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
include_tools = ["search_repositories", "search_code", "get_file_contents"]

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
- 大批量 MCP 工具
  - 在 `[[mcp.servers]]` 上用 `include_tools` / `exclude_tools` 先治理工具集合
  - 通过 `[tools] discovery_mode = "auto"` 走本地 `tool_search` 按需发现
  - `tool_search` 搜不到但工具存在时，可用 `tool_list` 列工具组并按精确名称加载
  - 初始请求只暴露 `always_loaded` 中的常驻工具，匹配到的 MCP 工具会在下一轮工具调用中加载

也就是说：

- 现有工具调用框架先服务项目内部工具
- MCP 后续作为可插拔扩展层加入
- MCP 工具数量较多时，先用 MCP server 级过滤控制能力面，再用工具发现控制提示词体积
- 不要为了 MCP 而重写已经稳定工作的直连能力

工具发现的实现边界与测试覆盖见 [tool-discovery.md](tool-discovery.md)。

---

## 7. 后续实现建议

如果继续扩展 MCP，建议顺序如下：

1. 补充 `tools/list_changed` 的动态刷新
2. 为 Docker 型 server 增加更细的状态诊断
3. 把部分 `env` 从 `config/llm.toml` 进一步抽到更细的部署层
4. 按需要继续接新的 MCP server

不要一开始就同时接多个 server。

---

## 8. 工具结果内容边界

MCP 工具调用会先在 `src/quickquip/llm/mcp/` 归一化为受控的内部结果，再交给现有工具调用链。当前文本结果保持逐项去除首尾空白、忽略空项并以换行连接；仅在没有可见文本时，`structuredContent` 保持现有 JSON 文本回退行为。

`ImageContent`、resource、audio、link 和未知内容不会被原样 JSON 序列化为工具文本。系统只向模型提供稳定的有限提示，例如图片尚未交付或某类内容尚未支持；不会自动下载 resource/link，也不会把资源正文、blob、完整 URL query、音频数据或图片编码注入模型请求。

这项安全降级只处理非文本 MCP 内容的边界。MCP 图片的正式模型交付会在后续独立变更中实现；在此之前，它们不会作为图片发送给模型或 QQ 用户。

## 9. 当前文档结论

QuickQuip 当前已经可以接 MCP，但实际部署时仍应把它视为项目自己的外部工具后端，并通过项目自己的私有部署环境变量、卷挂载和云端开关来管理。
