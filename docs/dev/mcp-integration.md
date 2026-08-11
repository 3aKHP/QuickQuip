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

生产环境若已有宿主机上的 Streamable HTTP MCP 服务，优先通过现有 HTTPS MCP 网关复用它们，避免在 QuickQuip Compose 内重复运行 MCP sidecar。只有没有可复用的宿主机 HTTP 服务时，才采用纯 sidecar 模式：在部署编排中将 MCP server 作为独立 service 跑在同一网络里，bot 通过 `transport = "sse"` 或 `transport = "http"` 直连。代码中的四种 transport 均已完整实现，部署时无需依赖 Docker socket。

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

`ImageContent` 会先严格校验 base64、5 MiB 单图大小、真实图片格式和声明 MIME；首期仅支持 PNG、JPEG、GIF、WebP，每个 MCP 工具结果最多交付 5 张。校验通过的图片只在当前工具调用循环的内存中保存：视觉模型按各 provider 的受支持格式接收；非视觉模型使用已配置的图片转述器，转述失败或服务不可用时保留安全工具文本并明确省略图片。工具错误或被敏感词整体拦截的结果不会交付图片。图片像素本身不在本地敏感词审核范围，转述文本会在进入主模型前再次扫描。

resource、audio、link 和未知内容不会被原样 JSON 序列化为工具文本。系统只向模型提供稳定的有限提示；不会自动下载 resource/link，也不会把资源正文、blob、完整 URL query 或音频数据注入模型请求。MCP 图片只服务下一轮模型推理，不会直接作为 QQ 最终消息发送给用户。

可选的固定版本 PRTS MCP 验收不会调用付费 LLM。提供连接信息后运行：

```bash
QUICKQUIP_MCP_ACCEPTANCE=1 \
QUICKQUIP_MCP_PRTS_URL=https://example.test/mcp \
QUICKQUIP_MCP_PRTS_TOKEN=... \
QUICKQUIP_MCP_PRTS_OPERATOR=能天使 \
.venv/bin/python -m pytest -m network tests/integration/test_mcp_prts_acceptance.py -q
```

测试会执行 MCP initialize、tools/list 和 `operator_artwork` 的 list/get，再用本地 stub serializer 检查结果请求结构。缺少任一环境变量时会明确 skip；不要把 token 写入测试 fixture、Issue 或 PR。

## 9. 双协议纪元（Dual-Era）支持

自 MCP `2026-07-28` 规范起，协议分为两个纪元：

- **Legacy era**（`2025-11-25` 及之前）：通过 `initialize` 握手建立会话，使用 `mcp-session-id`。
- **Modern era**（`2026-07-28` 起）：无握手、无 session，每个请求携带 `_meta`（协议版本、客户端身份、capabilities）和 routing headers（`MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`）。

QuickQuip 的 `negotiation` 字段控制每个 HTTP MCP Server 的协商模式：

| 模式 | 行为 |
|---|---|
| `legacy`（默认） | 只走 `initialize` + session，兼容所有旧 Server。缺省时自动生效，行为与旧版完全一致。 |
| `auto` | 先发 `server/discover` 探测；如果 Server 返回 DiscoverResult 就走 modern；如果返回 legacy 信号（JSON-RPC error、400/404/405 无 modern error body）就回退 legacy。401/403/5xx/超时直接失败，不回退。 |
| `modern` | 只走 modern 协议，不回退。 |

### 配置示例

```toml
[[mcp.servers]]
id = "modern_api"
transport = "http"
negotiation = "auto"
supported_protocol_versions = ["2026-07-28"]
url = "https://modern-mcp.example.com/mcp"
```

### 协商规则

- `stdio`、`docker`、`sse` transport 只支持 legacy。配置 `auto`/`modern` 会在配置校验阶段被跳过并记录 warning。
- `supported_protocol_versions` 为空时 `auto`/`modern` 也会被跳过。
- `auto` 探测的 verdict 在单次进程生命周期内保存。
- modern version 无交集时明确报 negotiation failure。
- `tools/call` 在 modern 模式下收到 `InputRequiredResult`（MRTR）时返回稳定的 unsupported 结果。

### Stale session 处理（legacy HTTP）

带 `mcp-session-id` 的请求收到 HTTP 404 时：

- `tools/list` 等只读请求在有界次数内（≤2）触发重连：重新 `initialize` 获取新 session-id。
- `tools/call` 不自动重放，直接失败并标记需重连，避免重复副作用。
- 新连接不继承旧 session-id 或旧 request-id。

### 安全

- `_describe_server` 对 HTTP/SSE URL 脱敏（去除 query string 和 fragment）。
- 异常消息中的 URL 和凭据经过清洗后才进入 status JSON 或日志。
- alias 冲突采用 fail-closed：冲突的 binding 全部不注册，status 标记 `failure_kind = "config"`。

## 10. 当前文档结论

QuickQuip 当前已经可以接 MCP，但实际部署时仍应把它视为项目自己的外部工具后端，并通过项目自己的私有部署环境变量、卷挂载和云端开关来管理。
