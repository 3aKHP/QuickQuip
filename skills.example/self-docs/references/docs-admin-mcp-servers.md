<!-- Generated from docs/admin/mcp-servers.md; do not edit -->

# MCP Server 接入指南

QuickQuip 可以把外部 MCP server 提供的工具桥接给 AI，在对话的工具调用循环中按需使用。本文面向部署者，给出把现成 MCP server 接入 QuickQuip 的操作清单；MCP 协议概念与字段详解见 [docs/dev/mcp-tutorial.md](../dev/mcp-tutorial.md)，server 开发不在本文范围。

## Transport 怎么选

| transport | 适用场景 | 关键字段 |
|---|---|---|
| `http` | 远程 MCP Streamable HTTP 服务（自建网关或第三方），单端点 POST | `url`、`headers` |
| `stdio` | 与 bot 同机的本地进程，随 bot 启停 | `command`、`args`、`env` |
| `docker` | 宿主机 Docker 直接运行官方未提供 http/sse 入口的社区镜像；需要原生 Docker daemon 与 docker.sock，容器化部署默认不推荐 | `image`、`mounts`、`env` |
| `sse` | 经典 HTTP+SSE 远程服务（旧式 sidecar） | `url` |

远程服务默认选 `http`：生产容器优先经已鉴权的 HTTPS Streamable HTTP 网关复用宿主机上的 MCP 服务。`sse` 用于只提供旧式入口的服务，`stdio` / `docker` 用于本机部署。

## 接入清单

1. **拿到连接信息**：远程 server 记下端点 URL 与鉴权凭证（如 Bearer token）；本地 server 记下启动命令或镜像名，以及所需环境变量。
2. **写配置**：在 `config/llm.toml` 打开总开关并声明 server 条目，可参照 `config/llm.toml.example` 的 `[[mcp.servers]]` 注释段：

   ```toml
   [mcp]
   enabled = true

   [[mcp.servers]]
   id = "my_server"
   transport = "http"
   timeout_seconds = 30
   url = "https://mcp.example.com/mcp"
   ```

   `id` 在全部 server 间唯一，重复条目会被跳过并记录告警；`transport` 缺省为 `stdio`，`timeout_seconds` 缺省为 30，单个 server 的 `enabled` 缺省为 `true`，设为 `false` 可临时停用而保留配置。
3. **凭证走环境变量**：server 条目内的字符串值（`url`、`headers`、`env`、`mounts` 等）支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}` 展开——未设置的 `${ENV_VAR}` 展开为空串，`${ENV_VAR:-default}` 展开为默认值。凭证一律写在仓库根 `.env`，禁止明文写进 toml：

   ```toml
   env = { GITHUB_TOOLSETS = "${GITHUB_TOOLSETS:-context,repos,issues}" }
   ```

   上例在 `.env` 未定义 `GITHUB_TOOLSETS` 时取默认值，定义后取环境变量的值。
4. **生效**：重启 bot，或群内执行 `/llm reload`（管理员）重载 `config/llm.toml` 并重连全部 MCP server；`/llm mcp reload`（管理员）只重连 MCP，且对 docker transport 强制拉取最新镜像。`.env` 变量的新增与修改需要重启 bot 进程。
5. **验证装载**：群内 `/llm mcp status` 查看，输出形如：

   ```text
   MCP 状态
   总开关：ON
   连接数：1/2
   工具数：7
   - prts_wiki [http] ON tools=7 server=ExampleMCPServer 1.0
   - fetch [sse] ERROR tools=0 error=连接超时
   ```

   `ON` 表示已连接，`OFF` 表示该 server 被停用，`ERROR` 表示装载失败；聊天面的 `error=` 只显示失败类别，脱敏后的具体错误文本在 Web Admin「MCP」页查看。配置了 `negotiation` 的 http server 会在 transport 后附带协议纪元标记（如 `[http/auto/modern]`），表示协商模式与实际协商结果。
6. **健康检查与用量观察**：`/llm probe`（管理员）并发探活全部 LLM provider，确认模型侧链路可用（每次调用按 provider 计费）。MCP 工具在 LLM 工具循环内执行，相关用量与成本在 Web Admin「用量」页按 provider / 模型 / 功能 / 群 / 人格维度查看。

## 最小 http 示例

一个带 Bearer token 的远程 server，token 全部走环境变量引用：

```toml
[mcp]
enabled = true

[[mcp.servers]]
id = "prts_wiki"
transport = "http"
timeout_seconds = 30
url = "https://mcp.example.com/mcp"
headers = { Authorization = "Bearer ${MCP_PRTS_WIKI_TOKEN}" }
```

对应 `.env` 条目（体例同 `.env.example`）：

```bash
# prts_wiki MCP 的鉴权 token，见 config/llm.toml.example。
MCP_PRTS_WIKI_TOKEN=<你的 token>
```

## 常用进阶配置

| 字段 | 说明 |
|---|---|
| `include_tools` / `exclude_tools` | server 级工具过滤：`include_tools` 为空时接入该 server 全部工具，`exclude_tools` 在白名单之后生效；两项都支持 MCP 原始工具名或 QuickQuip 生成的工具名 |
| `allowed_tools` | 兼容旧配置的白名单字段，作用同 `include_tools`，新配置使用 `include_tools` |
| `tool_prefix` | 自定义工具名前缀；缺省按 server id 生成 `mcp_<id>_<工具名>` |
| `protocol_version` | legacy 握手的协议版本 pin，默认 `"2025-03-26"` |
| `negotiation` | 协议协商模式，仅 `http` transport 生效：`legacy`（默认）/ `auto` / `modern`；`auto` / `modern` 需同时配置 `supported_protocol_versions` |
| `image` / `mounts` | docker transport 的镜像与卷挂载，格式 `host:container` 或 `host:container:ro`，值支持 `${ENV_VAR}` 展开 |

字段全集与默认值见 [configuration.md](configuration.md) 的 `[mcp]` 段，语义详解见 [mcp-tutorial.md](../dev/mcp-tutorial.md)。接入 GitHub MCP 这类大工具集时，建议先用 `include_tools` 收窄到读类工具，再交给 `tool_search` / `tool_list` 做按需发现加载。

## 排障

- **装载失败**：先看 `/llm mcp status` 的 `error=` 类别（配置错误 / 认证失败 / 连接超时 / 传输错误等）；显示「总开关：OFF」时检查 `[mcp] enabled = true` 是否已设。脱敏后的具体错误文本与手动重连入口在 Web Admin「MCP」页和「诊断」页。启动时的瞬时连接失败会自动重试（最多 3 次、间隔 2 秒），认证与配置类错误直接失败。
- **别名冲突**：不同 server 生成相同工具名时按 fail-closed 处理，冲突工具全部不注册，status 标为配置错误；用 `tool_prefix` 区分。
- **server 已连接但工具没出现**：检查该 server 的 `include_tools` / `exclude_tools` 过滤，以及 `[tools]` 的 `enabled` / `enabled_mode` 是否把 MCP 工具从工具面过滤掉。
- **stale session（http legacy）**：会话过期后 `tools/list` 等只读请求会在有界次数内（最多 2 次）自动重连；`tools/call` 不自动重放，当次调用失败，下一次调用走新会话。
- **工具结果大小边界**：resource 文本超过 60,000 code point 截断并附固定标记；图片单张上限 5 MiB、每个工具结果最多交付 5 张（仅 PNG / JPEG / GIF / WebP）。
- 深入排查见 [mcp-integration.md](../dev/mcp-integration.md)。

## 延伸阅读

- [docs/dev/mcp-tutorial.md](../dev/mcp-tutorial.md) — MCP 概念教程
- [configuration.md](configuration.md) — `config/llm.toml` 字段全集
- [docs/dev/mcp-integration.md](../dev/mcp-integration.md) — MCP 集成设计与决策
