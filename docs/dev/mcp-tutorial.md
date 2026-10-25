# 从零理解 MCP —— 以 QuickQuip 项目为例

本文解释 MCP 的概念、传输方式和 QuickQuip 的协议行为。第一次接入服务可先完成[本地 echo 练习](../admin/mcp-servers.md#首次接入本地-echo-练习)，再对照本文理解连接与调用过程。

配置示例是完整导出 JSON 中的字段片段。使用 Web Admin 时，在“工具与技能 → MCP 服务与状态”添加服务并按示例填写字段。使用 JSON 时，先导出完整配置，将服务对象追加到 `settings.mcp.servers`，保留其他字段与已有服务，再预览导入、保存草稿并应用。完整交换流程见 [LLM 配置管理](../admin/llm-configuration.md)。

> **面向读者：** 听说过 MCP、尚未实际接触过协议本身的开发者与高级部署者。
>
> **前置要求：** 会阅读 JSON 配置；对 QuickQuip 的 LLM 工具调用链路有大致印象（可先浏览 [`llm-module.md`](llm-module.md)）。
>
> **源码指引：** 协议实现位于 `src/quickquip/llm/mcp/`，配置校验与编译位于 `src/quickquip/llm/config_document.py`，运行期生命周期位于 `src/quickquip/llm/service_parts/mcp_lifecycle.py`，命令入口位于 `src/quickquip/adapters/nonebot/command_parts/llm.py`。配置权威模板为 `config/llm.json.example`。

---

## 目录

1. [MCP 是什么：解决什么问题](#1-mcp-是什么解决什么问题)
2. [QuickQuip 的接入模型](#2-quickquip-的接入模型)
3. [四种 transport 逐一实例](#3-四种-transport-逐一实例)
4. [配置全解](#4-配置全解)
5. [协议细节：QuickQuip 视角](#5-协议细节quickquip-视角)
6. [排障实录](#6-排障实录)
7. [延伸阅读](#7-延伸阅读)

---

## 1. MCP 是什么：解决什么问题

假设你问机器人：“某个仓库的 README 写了什么？”模型可以提出读取文件的工具请求，QuickQuip 把请求交给仓库服务，服务读取文件并返回内容，模型再据此组织回复。模型负责判断需要什么信息，QuickQuip 负责联系工具服务，服务负责执行具体操作。

MCP（Model Context Protocol，模型上下文协议）规定应用与工具服务如何介绍能力、发送请求和返回结果。工具提供方（搜索引擎、代码托管平台、数据服务……）各自暴露一套私有接口时，M 个工具与 N 个应用需要 M×N 份专门的对接代码；MCP 让双方复用一套协议实现。

MCP 把这层关系标准化：工具提供方实现 **MCP server**，把能力以 **tools**（可调用工具）和 **resources**（只读资源）的形式声明出来；AI 应用方实现 **MCP client**，按协议完成发现、协商与调用。接入新的服务时，应用复用这套协议实现，再配置兼容的传输、版本、凭据与工具范围。

### 1.1 四个核心概念

| 概念 | 含义 | 在 QuickQuip 中的落点 |
|------|------|----------------------|
| client | 向工具服务发送请求并接收结果的调用方 | `MCPClient`（每个 server 一个实例，`mcp/client.py`） |
| server | 工具提供方，声明并执行工具 | GitHub MCP、arXiv MCP、Tavily MCP 等 |
| tools | server 暴露的可调用能力（名称 + 描述 + 参数 schema） | 桥接进 `ToolRegistry` 的 `mcp_*` 工具 |
| resources | server 暴露的只读数据 | QuickQuip 只消费工具结果中内联的 resource 文本（见 §5.4） |

承载模型与工具调用循环的应用称为 host。QuickQuip 进程就是 host：它的 LLM 服务层在内部为每个配置的 server 建一个 client。

### 1.2 一次调用的生命周期

```text
QuickQuip（client）                          MCP Server
    │  ① 发现+协商：initialize 握手（legacy）        │
    │     或 server/discover 探测（modern）          │
    │──────────────────────────────────────────────▶│  返回 serverInfo、能力声明、
    │◀──────────────────────────────────────────────│  协议版本、session（legacy）
    │  ② 发现：tools/list（分页拉取工具清单）         │
    │──────────────────────────────────────────────▶│
    │◀──────────────────────────────────────────────│  工具名、描述、参数 schema
    │  ③ 调用：tools/call {name, arguments}          │
    │──────────────────────────────────────────────▶│  执行工具
    │◀──────────────────────────────────────────────│
    │  ④ 结果：content（text / image / resource）    │  归一化后交给模型下一轮
```

1. **发现与协商**：client 连上 server，确定双方共用的协议版本与会话方式；
2. **工具清单**：`tools/list` 拉取该 server 的全部工具定义（`nextCursor` 分页循环）；
3. **调用**：模型决定使用某工具后，host 通过 client 发出 `tools/call`，携带工具名与参数；
4. **结果**：server 返回 content 列表，client 做安全归一化（§5.4）后交回工具调用循环。

QuickQuip 用 `initialize` 与 `notifications/initialized` 完成 legacy 握手，用 `server/discover` 发现 modern 服务，再通过 `tools/list` 和 `tools/call` 发现和调用工具。transport 承载这些消息，项目工具注册表将发现的能力提供给模型。

---

## 2. QuickQuip 的接入模型

QuickQuip 把 MCP 作为工具后端来源之一：MCP 工具与内置工具进入同一个 `ToolRegistry`，对模型呈现统一的工具调用接口。接入在配置声明、启动装载、运行可见性三层展开。

### 2.1 启动时发生了什么

`MCPClientManager.sync()`（`mcp/client.py`）在启动或重载时逐个处理 `settings.mcp.servers`：

1. 建立连接：每个 server 最多尝试 3 次，间隔 2 秒。认证失败（401/403）、配置类错误与 4xx 直接报告失败；超时、网络错误与 5xx 按瞬态错误重试，可处理 Compose 冷启动时服务尚未就绪的情况；
2. `tools/list` 拉取工具清单（分页循环），生成工具别名并按 server 级名单过滤（§4.2）；
3. 桥接注册：`mcp_lifecycle.py` 把每个工具按别名注册进 `ToolRegistry`，来源与分类标记为 `mcp:<server_id>`，描述冠以 `[MCP/<server_id>]` 前缀；
4. 写出状态文件（`data/mcp_status.json`），供 Web Admin 展示同一份装载结果。

别名规则：`mcp_<server>_<tool>`（`tool_prefix` 可替换其中的 server 段）。名称里 `[A-Za-z0-9_-]` 之外的字符归一为 `_`；总长超过 64 字符时截断并追加 8 位摘要后缀。两个 server 的工具若归一后撞名，采取 fail-closed：冲突的绑定全部不注册，状态标记为配置错误。

### 2.2 工具可见性的三层过滤

| 层 | 配置 | 生效时机 |
|----|------|---------|
| server 级 | `include_tools` / `exclude_tools` | 桥接前，决定哪些 MCP 工具被注册 |
| 全局级 | `settings.tools.enabled` + `enabled_mode` | 组装请求时，决定暴露给模型的工具集合 |
| 请求加载策略 | `settings.tools.discovery_mode` | 全局配置决定首轮携带哪些工具，单次工具循环按需加载其他工具 |

模型使用工具前，需开启 `settings.runtime.tool_calling_enabled`，其默认值为 `false`。全局级的行为是：`enabled = []` 时使用默认名单加全部已注册 MCP 工具；非空名单中，`enabled_mode = "append"` 在默认集合上追加所列工具，`enabled_mode = "replace"` 按所列名称精确过滤，MCP 工具同样受该名单约束。空名单在两种模式下都使用默认集合。

`discovery_mode = "auto"`（默认）在可延迟工具数超过 `discovery_min_tools` 时开启发现机制：首轮请求携带 `always_loaded` 常驻工具，模型用 `tool_search` 搜索，或用 `tool_list` 查看目录、按精确名称加载。新加载的 MCP 工具在下一轮请求中生效；小工具集直接发送全部启用工具。接入大批量 MCP 工具时，先用 server 级 `include_tools` 选择能力，再通过发现机制控制工具定义体积。实现细节见[工具发现说明](tool-discovery.md)。

### 2.3 查看装载结果：`/llm mcp status`

```text
MCP 状态
总开关：ON
连接数：1/2
工具数：3
- prts_wiki [http] ON tools=3 server=prts-mcp 1.2.0
- github [docker] ERROR tools=0 error=认证失败
```

- 聊天面显示失败分类，如 `认证失败`；Web Admin 的状态页提供清洗后的错误详情；
- transport 后面的 `/modern`、`/auto/legacy` 等角标是双协议纪元标记（§5.1）；
- `/llm mcp reload`（管理员）：重连全部 server，docker transport 会先强制拉取最新镜像；
- LLM 配置通过草稿应用任务接纳；仅 MCP 配置改变时准备新资源代际。人格热重载与价格更新保持当前 MCP 连接。

---

## 3. 四种 transport 逐一实例

`transport` 决定 client 与 server 之间消息怎么传输。四种都封装在 `mcp/transport.py`，共用协议层。以下示例用于对照传输方式与字段；服务准备、表单填写和实际调用步骤见[管理员接入指南](../admin/mcp-servers.md)。

### 3.1 stdio —— 本地子进程

适用场景：与 bot 同机的命令行 MCP server（`uvx` 拉起的 Python server、`npx` 拉起的 Node server 等），进程随 bot 启停。

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "fetch",
          "transport": "stdio",
          "command": "uvx",
          "args": [
            "mcp-server-fetch"
          ]
        }
      ]
    }
  }
}
```

机制：QuickQuip 派生子进程，stdin/stdout 上交换 JSON-RPC（按行分隔，自动兼容 `Content-Length` 帧格式），stderr 逐行写入日志；`env` 在当前进程环境之上合并注入。

验证：`/llm mcp status` 出现 `fetch [stdio] ON tools=N`；子进程的诊断输出可在日志里按 `MCP stderr [fetch]` 检索。

### 3.2 docker —— 容器子进程

适用场景：社区只提供 CLI 镜像、没有 http/sse 端点的 server。需要本机 Docker CLI 与 daemon；容器化部署默认不挂载 docker.sock，仅适合裸机或可信宿主机。

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "github",
          "transport": "docker",
          "timeout_seconds": 30,
          "image": "ghcr.io/github/github-mcp-server",
          "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
          },
          "include_tools": [
            "search_repositories",
            "get_file_contents",
            "search_code"
          ]
        }
      ]
    }
  }
}
```

机制：QuickQuip 执行 `docker run -i --rm --pull <pull_policy> ...` 拉起容器；`env` 写入一块 0600 权限的临时 `--env-file` 传给容器，启动完成后立即删除，凭证不出现在进程命令行里。

验证：`/llm mcp status`；镜像拉取失败时日志有 `docker pull ... 失败` 记录，`/llm mcp reload` 可强制重新拉取。

### 3.3 http —— 远程 Streamable HTTP（推荐）

适用场景：自建或第三方的 HTTPS MCP 服务、宿主机 MCP 网关。生产环境首选。

端点是服务提供方给 MCP 客户端使用的完整 URL，通常含 `/mcp`；按该服务的说明填写。下面的 `mcp.example.com` 是占位地址，`MCP_PRTS_WIKI_TOKEN` 代表该服务签发的凭据。服务地址和凭据取得后替换示例；可直接启动的练习服务见[本地 echo 练习](../admin/mcp-servers.md#首次接入本地-echo-练习)。

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "prts_wiki",
          "transport": "http",
          "timeout_seconds": 30,
          "url": "https://mcp.example.com/mcp",
          "headers": {
            "Authorization": "Bearer ${MCP_PRTS_WIKI_TOKEN}"
          }
        }
      ]
    }
  }
}
```

机制：请求发往同一 POST 端点，响应为 JSON 或内联 SSE。默认 legacy 模式下，服务器可从响应头下发 `mcp-session-id`，后续请求携带该头；modern 模式按 §5.1 的逐请求元数据通信。

验证：可先用 curl 模拟一次 legacy 握手确认端点与凭证可达：

```bash
curl -i -sS --max-time 10 -X POST "https://mcp.example.com/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer ${MCP_PRTS_WIKI_TOKEN}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

在 Bash 中执行该命令，先设置令牌环境变量，并将示例 URL 换成实际端点。Streamable HTTP 请求须通过 `Accept` 声明同时接收 JSON 与 SSE，[协议要求见此](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)。`-i` 显示 HTTP 状态和响应头，`--max-time 10` 在 10 秒后结束探测。

正常响应为 HTTP 200：`Content-Type: application/json` 时，正文包含初始化 `result`；`text/event-stream` 时，事件的 `data:` 中包含同一 JSON-RPC 结果。部分 legacy 服务还返回 `Mcp-Session-Id` 响应头。401/403 时核对凭据，404/405 时核对 MCP 端点与传输方式；随后通过 `/llm mcp status` 查看 Bot 装载状态，按接入指南发起一次工具调用。探测本地 echo 时，URL 使用 `http://127.0.0.1:8017/mcp`，省略 `Authorization` 头。

### 3.4 sse —— 经典 HTTP+SSE

适用场景：提供经典 SSE 端点的远程 server。

下例假定你已在 Bot 所在网络启动名为 `mcp-tavily` 的服务，且该服务提供 8080 端口的 `/sse` 入口；容器名、端口和路径按实际服务调整。

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "tavily",
          "transport": "sse",
          "timeout_seconds": 30,
          "url": "http://mcp-tavily:8080/sse"
        }
      ]
    }
  }
}
```

机制：GET 打开一条长连接事件流，服务器发出 `endpoint` 事件告知 POST 地址（相对路径会按 SSE URL 解析），请求的响应从 `message` 事件回流。等待 `endpoint` 事件超过 `timeout_seconds` 会报「等待 endpoint 事件超时」。

验证：`curl -N "http://mcp-tavily:8080/sse"` 能看到 `event: endpoint` 行即端点存活；装载结果看 `/llm mcp status`。

---

## 4. 配置全解

配置通过共享应用服务保存到 `config/managed/config.db`，校验与编译见 `src/quickquip/llm/config_document.py`。总开关 `settings.mcp.enabled` 默认 `false`；关闭时 `sync()` 直接返回，一个连接也不建立。

### 4.1 `settings.mcp.servers` 全字段表

默认值以 `MCPServerConfig` 为准；JSON 写入约束由 `config_document.py` 校验。保存与导入预览返回具体字段错误，修正后才能保存整份草稿。

**通用字段**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `id` | （必填） | server 唯一标识；缺失或重复会使配置校验失败，也是工具别名与 `mcp:<id>` 分类的来源 |
| `transport` | `"stdio"` | `stdio` / `docker` / `http` / `sse` |
| `enabled` | `true` | 单 server 开关；`false` 时状态记为 disabled，不参与连接 |
| `timeout_seconds` | `30` | 连接、探测与每次请求等待的上限秒数（float） |
| `tool_prefix` | 空（按 `id`） | 工具别名前缀覆盖，如 `tool_prefix = "gh"` 生成 `mcp_gh_*` |

**stdio 专属**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `command` | `""` | 可执行文件（必填） |
| `args` | `[]` | 命令参数 |
| `cwd` | 空 | 子进程工作目录 |
| `env` | `{}` | 注入子进程的环境变量（在进程环境之上合并） |

**docker 专属**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `image` | `""` | 镜像（必填） |
| `docker_command` | `"docker"` | Docker CLI 命令 |
| `docker_args` | `[]` | 追加到 `docker run` 的额外参数 |
| `pull_policy` | `"missing"` | `always` / `missing` / `never`，映射 `docker run --pull` |
| `mounts` | `[]` | 卷挂载，格式 `host:container` 或 `host:container:ro`，逐条映射 `-v` |
| `network` | 空 | `--network` 值 |
| `container_workdir` | 空 | 容器工作目录（`-w`） |

docker 的 `args` 附加在镜像名之后，作为 server 自身参数；`env` 走临时 `--env-file`（§3.2）。

**http / sse 专属**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `url` | `""` | 服务端点（两者均必填） |
| `headers` | `{}` | 注入请求的 HTTP 头，值支持环境变量展开 |

**工具过滤**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `include_tools` | `[]` | 白名单；为空表示接入该 server 全部工具。匹配 MCP 原始工具名或生成后的别名均可 |
| `exclude_tools` | `[]` | 排除名单，在白名单之后生效，匹配规则同上 |
| `allowed_tools` | `[]` | 旧配置兼容写法，等价 `include_tools`；两者同时非空时以 `include_tools` 为准 |

**协议协商**

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `protocol_version` | `"2025-03-26"` | legacy 握手时声明的协议版本 pin |
| `negotiation` | `"legacy"` | `legacy` / `auto` / `modern`，仅 `http` transport 生效（§5.2） |
| `supported_protocol_versions` | `[]` | `auto` / `modern` 模式下客户端声明的可接受版本列表；这两种模式必填非空，缺失使配置校验失败 |

### 4.2 `${ENV_VAR}` 展开规则与时机

配置值（含嵌套的字符串、列表、字典，覆盖 `env`、`headers`、`mounts` 等）支持两种占位：

```text
${ENV_VAR}             引用环境变量；未设置时展开为空字符串
${ENV_VAR:-default}    带默认值；未设置时展开为 default（默认值可为空）
```

- 变量名需匹配 `[A-Za-z_][A-Za-z0-9_]*`；占位符支持嵌在更长字符串里（如 `"Bearer ${TOKEN}"`）；
- 展开发生在**配置解析时**：Bot 编译已发布快照或应用指定快照时展开，运行期不重读环境变量；
- `.env` 只在进程启动时加载一次：快照编译从 Bot 当前进程环境读取变量，改动 `.env` 需要重启 bot 进程生效。

### 4.3 凭证安全惯例

- 凭证一律放进程环境（部署上以仓库根目录 `.env` 为唯一涉密来源），JSON 和配置数据库里只写 `${ENV_VAR}` 占位，任何真实 token 不进配置文件；
- http/sse 用 `headers` 注入 `Authorization`，stdio 用 `env`，docker 的 `env` 经临时 `--env-file` 注入，凭证不暴露在进程命令行；
- 状态与日志对 URL 去除 query、fragment 和 userinfo，对异常文本做截断和凭据清洗。使用环境变量引用配置凭据，避免把令牌写进 URL。

---

## 5. 协议细节：QuickQuip 视角

### 5.1 双协议纪元

MCP 规范自 `2026-07-28` 版起划分为两个纪元，QuickQuip 两者都支持：

| | legacy（默认） | modern |
|---|---|---|
| 建连方式 | `initialize` 握手 + `notifications/initialized` 通知 | 无握手；先发 `server/discover` 探测 |
| 会话 | 服务器下发 `mcp-session-id`，后续请求携带 | 无 session，每个请求自包含 |
| 版本与身份 | 握手结果里的 `protocolVersion` | 每个请求携带 `_meta`（协议版本、客户端身份、能力）与路由头（`MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`） |

`protocol_version` 配置的是 legacy pin；`supported_protocol_versions` 声明的是 modern 可接受版本列表。`stdio`、`docker`、`sse` 只走 legacy。

### 5.2 自动协商（`negotiation`，仅 http）

| 模式 | 行为 |
|------|------|
| `legacy`（默认） | 只走握手 + session，兼容所有旧 server |
| `auto` | 先发 `server/discover` 探测：返回 DiscoverResult 就走 modern；收到 legacy 信号（JSON-RPC error，或 400/404/405 且响应体无 modern 错误码 -32022/-32020）就回退 legacy。401/403/5xx/超时直接失败不回退 |
| `modern` | 只走 modern；探测判定为 legacy 时报协议协商失败 |

- `negotiation` 配了 `auto`/`modern` 但 `transport` 非 `http`，或 `supported_protocol_versions` 为空：保存校验返回字段错误，修复后才可保存并应用；
- modern 版本协商取客户端声明列表与服务器 `supportedVersions` 的交集，交集为空时报「modern 版本无交集」；
- modern 模式下收到 `InputRequiredResult`（MRTR，响应带 `inputRequests`）按「暂不支持」返回稳定错误；
- 协商在连接资源准备时执行（进程启动、MCP 配置应用、`/llm mcp reload`）；session 过期重连沿用当前装载周期的协商结论，不重新探测。

```json
{
  "settings": {
    "mcp": {
      "servers": [
        {
          "id": "modern_api",
          "transport": "http",
          "negotiation": "auto",
          "supported_protocol_versions": [
            "2026-07-28"
          ],
          "url": "https://modern-mcp.example.com/mcp"
        }
      ]
    }
  }
}
```

### 5.3 stale session 处理（legacy HTTP）

带 `mcp-session-id` 的请求收到 HTTP 404，说明服务器已丢弃该会话：

- `tools/list` 等只读请求：有界重连，最多 2 次——重新 `initialize` 换取新 session-id；新连接不继承旧 session-id 与旧 request-id；
- `tools/call`：**不自动重放**，直接失败并报「session 过期，未自动重放」。工具调用可能有副作用，重放会造成重复执行。

工具清单遇到会话过期时在上述次数内重连；工具调用返回失败并标记需要重连，后续请求建立新会话。反复出现会话过期时，检查服务器会话保留时间和网络状态。

### 5.4 工具结果内容边界

工具结果在 `mcp/types.py` 归一化为受控的内部结构后才进入模型上下文：

- **文本项**：逐项去除首尾空白、丢弃空项后以换行连接；完全没有可见文本时，`structuredContent` 以 JSON 文本兜底；
- **resource 内联正文**：MIME 属于文本族（`text/*` 前缀与 `application/json`、`xml`、`yaml`、`x-yaml`、`toml`、`javascript` 白名单；缺省 MIME 视为文本）时交付，超过 60,000 code point 截断并附固定标记 `…[MCP resource 正文超长，已截断]`；blob、非文本 MIME、空白正文扣留，只给稳定提示；
- **图片**：严格校验后才交付——base64 严格解码、PNG/JPEG/GIF/WebP 格式白名单、声明 MIME 与实际格式一致、单张解码后不超过 5 MiB、解压炸弹防护；每个工具结果最多交付 5 张，超出或未通过校验的计入省略提示；
- **audio / link / resource_link**：扣留不交付，只保留稳定有限提示；系统不自动下载 resource/link，资源 URI 也不随正文渲染；
- **isError 结果**：只交付文本与省略提示，不交付图片。

交付的图片只服务下一轮模型推理：视觉模型按其支持的格式接收，非视觉模型走已配置的图片转述器。图片不会直接作为 QQ 消息发送给用户。

---

## 6. 排障实录

### 6.1 场景一：server 装载失败，看什么

**现象**：`/llm mcp status` 里某 server 显示 `ERROR`，`tools=0`。

**第一步：读分类。** 聊天面的 `error=` 是失败分类标签，对应关系（`service_parts/health.py`）：`配置错误`（config）、`探活失败`（probe）、`协议握手失败`（legacy-handshake）、`协议协商失败`（modern-negotiation）、`认证失败`（auth，401/403）、`连接超时`（timeout）、`路由错误`（routing）、`传输错误`（transport）、兜底 `连接失败`。需要清洗后的原始错误文本时看 Web Admin 状态页。

**第二步：查日志。** 装载失败会记录 `Failed to initialize MCP server <id>: ...`；stdio/docker 的子进程 stderr 以 `MCP stderr [<id>]` 前缀进日志，多数启动失败（缺依赖、凭证无效、端口不通）在这里能看到 server 自己的报错。

**第三步：对常见根因。**

| 根因 | 表现 |
|------|------|
| `url` / `command` / `image` 缺失 | 对应 transport 装载时返回配置错误，日志明示缺失字段；补齐连接配置后保存并应用 |
| `id` 重复 | 整份配置校验失败，调整为唯一 ID 后再保存 |
| `negotiation = "auto"/"modern"` 但 transport 非 http，或未填 `supported_protocol_versions` | 配置校验失败；http 的新纪元模式需声明非空版本列表 |
| 两个 server 的工具归一后同名 | fail-closed，冲突绑定全部不注册，error 为「alias 冲突」 |
| compose 冷启动竞态 | 超时/5xx 自动重试 3 次，通常自愈；认证/4xx 不重试 |
| 凭证无效 | 认证失败，检查 `.env` 与 `headers`/`env` 占位是否展开（展开为空串时服务器侧表现为匿名请求） |

### 6.2 场景二：工具调用超时怎么办

**现象**：模型调用了 MCP 工具，回复里带 `MCP 工具 xxx 调用失败：MCP server <id> 调用 tools/call 超时`。

**机制**：`timeout_seconds` 同时约束 HTTP 客户端超时与每次 JSON-RPC 请求的等待时长，默认 30 秒；启动阶段的连接失败有 3 次重试，运行期单次调用超时不会自动重试，`tools/call` 因副作用保护尤其不重放（§5.3）。

**处置**：

1. 慢工具（深度调研、大范围爬取类）给所在 server 单独调大 `timeout_seconds`，保存并应用后生效；
2. docker transport 首次调用前可能需要拉镜像：检查 `pull_policy`，用 `/llm mcp reload` 强制拉取；
3. 间歇性超时优先排查 server 端负载与网络；持续超时且 `tools/list` 正常，多半是单个工具执行确实超过阈值。

### 6.3 场景三：结果被截断或图片被丢

**现象**：工具文本末尾出现 `…[MCP resource 正文超长，已截断]`，或提示 `MCP 工具省略了 N 个无效或超出限制的图片项` / `MCP 工具省略了尚未支持的内容：N 个 resource 项`。

**解释**：结果处理按 §5.4 的规则交付可用文本和有效图片，对截断、无效或暂不支持的内容附加省略提示。

**处置**：

- 截断：需要完整正文时在 server 侧收窄返回范围（分段、分页、按需读取）；60,000 code point 的上限对齐项目对单条工具结果的预算；
- 图片被丢：逐项核对四条硬边界——格式在 PNG/JPEG/GIF/WebP 之内、单张不超过 5 MiB、每个结果不超过 5 张、声明 MIME 与图片实际格式一致（`.jpg` 文件声明成 `image/png` 会被拒）；
- resource/blob/audio/link 类提示：相应内容类型当前不交付，属预期行为；让 server 改返回文本或图片项即可。

---

## 7. 延伸阅读

- [`docs/admin/mcp-servers.md`](../admin/mcp-servers.md)：本地 echo 首次练习、服务配置与工具调用验证；
- [`mcp-integration.md`](mcp-integration.md)：设计决策与边界——目标边界、推荐路线、docker socket 取舍与安全决策的记录；
- [`tool-discovery.md`](tool-discovery.md)：工具发现的策略、数据流与测试覆盖；
- [`docs/admin/configuration.md`](../admin/configuration.md)：`config/managed/config.db` 全量字段参考（含 `settings.mcp` 段）；
- MCP 上游规范：<https://modelcontextprotocol.io>——协议方法、传输定义与各版本规范的权威来源。

---
