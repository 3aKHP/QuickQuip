<!-- Generated from docs/dev/mcp-integration.md; do not edit -->

# QuickQuip MCP 集成说明

本文面向维护 LLM 工具链和部署 MCP 的开发者，说明工具来源、运行时资源代际、传输选型与工具结果处理契约。部署与接入步骤见[管理员指南](../admin/mcp-servers.md)，协议入门与完整字段说明见 [MCP 教程](mcp-tutorial.md)。

类型化结果归一化与内容交付边界的设计依据见 [ADR-0018](adr/0018-mcp-result-normalization.md)。

文中的配置片段取自导出 JSON 结构；可在 Web Admin“LLM 配置”工作台中编辑，也可合入完整导出 JSON 后执行导入预览、保存草稿并单独应用。完整配置交换流程见 [LLM 配置管理](../admin/llm-configuration.md)。

## 1. 配置归属

QuickQuip 内置的 MCP 客户端负责发现外部 MCP 服务暴露的工具，并将它们桥接进与本地工具共用的 `ToolRegistry`。项目全部 MCP 配置保存在 `config/managed/config.db` 的 `settings.mcp` 域中。

外部编码助手（如 Codex CLI）自身的宿主配置文件仅作用于其本地环境；部署 QuickQuip 时统一通过项目配置服务与 `src/quickquip/llm/mcp/` 传输层管理外部 MCP 连接。

---

## 2. 工具来源选择

项目按能力边界选择工具接入方式：

1. 访问机器人本地存储与状态的能力（如 `get_identity`、长期记忆、群历史查询、`query_group_quotes` 等）采用内置本地工具实现。
2. 默认网页检索工具 `search_web` 对接项目内 SearXNG（或按渠道配置切换为模型原生搜索）。
3. Tavily 检索能力通过 MCP 侧接入（`tavily_search` / `tavily_crawl` / `tavily_research`）。
4. GitHub、arXiv、PRTS Wiki 等外部知识与平台接口按需作为 MCP 服务接入。
5. 内置工具、直连 API 工具与 MCP 工具共用同一套多轮工具调用循环与敏感词安全管线。

---

## 3. 部署权限与传输选择

### 3.1 Docker Socket 的取舍

GHCR 官方镜像与生产构建模板均内置 Docker CLI。若在容器化部署中使用 `docker` transport，还需将宿主机 `/var/run/docker.sock` 挂载进业务容器；由于 Docker Socket 等效授予宿主机容器控制权，该方式仅适合受控的可信宿主机。

生产环境已具备现成 HTTPS MCP 网关时，优先通过 `http` transport 远程接入；需要随栈自建服务时，推荐在同一 Compose 网络中部署独立 sidecar 容器，由 Bot 通过内部 HTTP 或 SSE 端点连接。

---

## 4. 运行时架构

### 4.1 三层结构

MCP 集成由三层组成：

1. **编排与注册层**：`src/quickquip/llm/service_parts/mcp_lifecycle.py` 与 `src/quickquip/llm/tool_registry.py`
2. **协议与传输层**：`src/quickquip/llm/mcp/`（负责版本协商、四种传输、分页工具发现、调用执行与结果安全归一化）
3. **持久化配置层**：`config/managed/config.db` 中的 `settings.mcp.servers`

运行时按配置快照管理 MCP 连接代际与任务租约：修改与 MCP 无关的配置字段时复用现有连接；当 MCP 配置变更触发重连时，已在执行中的对话任务继续持有原代际连接直至该轮结束，新进入的请求切换至新代际资源。

### 4.2 当前项目配置形式

导出 JSON 在 `settings.mcp.servers` 下声明 MCP 服务列表，保存草稿后经应用任务生效：

```json
{
  "settings": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "id": "github",
          "transport": "docker",
          "image": "ghcr.io/github/github-mcp-server",
          "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
          },
          "include_tools": [
            "search_repositories",
            "search_code",
            "get_file_contents"
          ]
        },
        {
          "id": "arxiv",
          "transport": "docker",
          "image": "arxiv-mcp-server:latest",
          "mounts": [
            "${MCP_ARXIV_PAPERS_MOUNT:-arxiv-papers:/root/.arxiv-mcp-server/papers}"
          ]
        }
      ]
    }
  }
}
```

将该片段合入完整导出 JSON 时，请一并保留其他配置域及仍需使用的既有 MCP 服务条目。

---

## 5. 远程部署准备

接入前需确认目标服务的传输协议、启动入口与认证凭据：`stdio` 要求 Bot 运行环境内存在对应可执行程序与运行时依赖；`docker` 要求可达的 Docker Daemon、目标镜像与持久化卷；`http` 与 `sse` 要求 Bot 网络可直连对应服务端点。四种传输的逐项示例见 [MCP 教程](mcp-tutorial.md#3-四种-transport-逐一实例)。

---

## 6. 控制模型工具集合

MCP 总开关与单服务 `enabled` 控制连接装载，全局开关 `settings.runtime.tool_calling_enabled`（默认 `false`）控制是否向模型开放工具调用。

接入包含大量工具的 MCP 服务时，建议先在 `settings.mcp.servers` 中用 `include_tools`／`exclude_tools` 裁剪需要注册的子集，再由 `settings.tools` 管理请求装载策略。默认 `discovery_mode = "auto"` 在可延迟工具数量超过 `discovery_min_tools` 或可延迟工具 Schema 估算总体积超过 `discovery_min_schema_tokens` 时自动开启按需发现：首轮请求携带 `always_loaded` 常驻工具与当前纪元已加载工具，模型通过 `tool_search`（支持关键词检索与 `select:` 精确批量加载）或 `tool_list` 按需装载目标 MCP 工具，装载结果进入下一轮请求并在同一会话纪元内跨轮保留。

若将 `settings.tools.enabled_mode` 设为严格的 `"replace"` 白名单，须同时列入 `tool_search`、`tool_list` 及所需 MCP 工具的生成别名。工具发现的完整契约与测试入口见 [`tool-discovery.md`](tool-discovery.md)。

---

## 7. 扩展与维护

新增外部 MCP 服务时，依次核对传输方式、协议协商模式、过滤后的工具别名清单与返回内容类型。认证凭据统一放入仓库根目录 `.env`，配置数据库中仅保存 `${ENV_VAR}` 引用；容器卷挂载在 Compose 编排层声明。后续协议扩展规划记录在 [`ROADMAP.md`](../../ROADMAP.md)。

---

## 8. 工具结果内容边界

所有 MCP `tools/call` 返回值都会先经 `src/quickquip/llm/mcp/` 归一化为受控内部结构，再进入统一的 `tool_result_pipeline.py` 安全处理管线：

- **纯文本与结构化回退**：文本块逐项去除首尾空白、跳过空串后以换行拼接；仅当响应不含任何可见文本时，才将 `structuredContent` 序列化为紧凑 JSON 文本作为回退结果。
- **内联图片（`ImageContent`）**：每张图片必须通过严格 base64 解码、单张解码后不超过 5 MiB、PNG／JPEG／GIF／WebP 四种格式魔数校验，且声明的 MIME 必须与实际图像格式一致；单次工具返回最多接纳 5 张有效图片，超出或校验未通过的条目计入稳定省略提示。有效图片仅驻留在当前工具调用循环内存中，服务于下一轮模型推理（不直接作为 QQ 消息外发给群友）：视觉主模型按协议格式直接读取图片，非视觉主模型调用前置图片转述器并将转述结果二次送检敏感词过滤器（转述不可用时保留工具文本并注明省略图片）。当工具本身报错（`isError=true`）或文本结果命中敏感词整体拦截时，同批图片一并丢弃。
- **内联资源（`resource`）与其他内容类型**：当内联 `resource` 的 MIME 属于文本族（`text/*` 前缀及 JSON、XML、YAML、TOML、JavaScript 等白名单类型，缺省 MIME 按文本处理）时，正文纳入工具文本管线并在超过 60,000 个码点时截断附注；二进制 `blob`、非文本 MIME、空白资源、`audio`、`link`／`resource_link` 及未知内容块统一转换为简短的省略计数提示（系统仅消费响应内联文本，不自动发起外部 URI 下载，也不把资源 URI 拼入正文）。

仓库提供可选的固定版本 PRTS MCP 实网验收测试（使用本地桩序列化器校验归一化结果，不消耗付费 LLM 额度），配置连接参数后可手动执行：

```bash
QUICKQUIP_MCP_ACCEPTANCE=1 \
QUICKQUIP_MCP_PRTS_URL=https://example.test/mcp \
QUICKQUIP_MCP_PRTS_TOKEN=... \
QUICKQUIP_MCP_PRTS_OPERATOR=能天使 \
.venv/bin/python -m pytest -m network tests/integration/test_mcp_prts_acceptance.py -q
```

测试依次验证 MCP `initialize`、`tools/list` 以及 `operator_artwork` 的列表与详情调用；缺少任一环境变量时自动跳过。请勿将真实访问令牌写入测试夹具、Issue 或 PR。

## 9. 双协议纪元（Dual-Era）支持

自 MCP `2026-07-28` 规范起，HTTP 传输划分为两个协议纪元：

- **Legacy era**（`2025-11-25` 及更早版本）：通过 `initialize` 握手建立有状态会话，后续请求携带 `mcp-session-id`。
- **Modern era**（`2026-07-28` 起）：采用无握手、无会话设计，每个请求内联携带 `_meta`（协议版本、客户端身份与能力声明）及路由请求头（`MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`）。

HTTP 类型的 MCP 服务通过 `negotiation` 字段控制协商策略：

| 模式 | 行为 |
|---|---|
| `legacy`（默认） | 直接执行 `initialize` 握手并维护服务端下发的会话 ID，兼容传统 MCP 服务 |
| `auto` | 先发送 `server/discover` 探测：返回合法 `DiscoverResult` 时采用 modern 模式；收到 legacy 特征响应（JSON-RPC 错误，或不含 modern 错误体的 HTTP `400`／`404`／`405`）时回退至 legacy 模式；遇到 `401`／`403`／`5xx` 或连接超时则直接报错 |
| `modern` | 强制使用 modern 无状态协议，探测不兼容时直接报告协商失败 |

### 配置示例

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

### 协商规则

- `stdio`、`docker`、`sse` 三种传输仅支持 `legacy` 模式；若误配为 `auto` 或 `modern`，配置保存与导入预览会直接返回字段校验错误。
- 选择 `auto` 或 `modern` 时必须提供非空的 `supported_protocol_versions` 列表。静态字段缺失在保存或导入阶段即被拦截；远端网络不可达或版本无交集则在运行期装载时记录到对应 server 的错误状态中。
- `auto` 模式的探测结论在当前资源装载周期内固定复用：会话过期触发自动重连时沿用已确定的纪元模式，执行 `/llm mcp reload`、`/llm reload` 或应用新 MCP 配置时重新探测。
- 客户端声明版本与服务端 `supportedVersions` 无交集时明确报告协议协商失败。
- modern 模式下若 `tools/call` 收到要求补充输入的 `InputRequiredResult`（MRTR），客户端返回稳定的不支持提示。

### 过期会话处理（Legacy HTTP）

当携带 `mcp-session-id` 的请求收到 HTTP `404`（表示服务端已回收该会话）时：

- `tools/list` 等只读请求会在有界次数（最多 2 次）内自动重新执行 `initialize` 握手换取新 `mcp-session-id`，且新连接与旧会话 ID、旧请求序号完全隔离。
- `tools/call` 为防止外部工具产生重复副作用，遇到会话过期时直接返回失败并标记连接需要重建，不在底层自动重放调用。

### 安全与脱敏

- `_describe_server` 在生成状态快照前自动剥离 HTTP／SSE URL 中的查询参数（query string）、片段（fragment）与用户信息。
- 写入 `data/mcp_status.json` 或应用日志的异常消息均经过长度截断与凭据清洗。
- 跨服务工具别名碰撞采取默认拒绝（fail-closed）策略：发生重名的绑定整组跳过注册，并将对应服务标记为 `failure_kind = "config"`。
