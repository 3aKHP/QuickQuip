<!-- Generated from docs/dev/mcp-integration.md; do not edit -->

# QuickQuip MCP 集成说明

本文面向维护 LLM 工具链和部署 MCP 的开发者，说明工具来源、运行时资源、部署选择与结果处理契约。接入步骤见[管理员指南](../admin/mcp-servers.md)，协议入门与完整配置字段见[MCP 教程](mcp-tutorial.md)。

类型化结果与内容交付边界的选择依据见 [ADR-0018](adr/0018-mcp-result-normalization.md)。

配置示例为导出 JSON 中的字段片段；请在 Web Admin「LLM 配置」中编辑，或修改完整导出文件后预览导入、保存草稿并单独应用。完整交换格式见 [LLM 配置管理](../admin/llm-configuration.md)。

## 1. 配置归属

QuickQuip 的 MCP client 发现外部服务工具，并将它们桥接到与内置工具共用的 `ToolRegistry`。项目 MCP 配置保存在 `data/llm_config.db` 的 `settings.mcp` 中。

Codex 的 `config.toml` 属于 Codex 宿主，包含它自己的环境、路径与信任设置。部署 QuickQuip 时，使用项目配置服务和下文的传输实现。

---

## 2. 工具来源选择

按工具职责选择实现来源：

1. 内建工具（get_identity、list_memories 等）使用本地实现
2. `search_web` 使用 SearXNG
3. Tavily 搜索能力走 MCP 侧 `tavily_search` / `tavily_crawl` / `tavily_research`
4. GitHub、arXiv、PRTS Wiki 等按需作为 MCP 接入
5. 内置工具、直连 API 工具与 MCP 工具共用工具调用循环

---

## 3. 部署权限与传输选择

### 3.1 Docker Socket 的取舍

GHCR 分发镜像和生产模板镜像内置 Docker CLI。容器中的 `docker` transport 还需要显式挂载 `/var/run/docker.sock`；该挂载赋予业务容器控制宿主机 Docker 的权限，适合可信宿主机。

生产环境已有 HTTPS MCP 网关时，可通过 HTTP 复用宿主机或外部服务。需要独立部署服务时，可在同一 Compose 网络运行 sidecar，Bot 通过其 HTTP 或 SSE 端点连接。

---

## 4. 运行时架构

### 4.1 三层结构

MCP 集成分为三部分：

1. `src/quickquip/llm/service.py`（MCP 生命周期归属 `service_parts/mcp_lifecycle.py`）/ `src/quickquip/llm/tool_registry.py`
2. `src/quickquip/llm/mcp/`：协议协商、传输、工具发现、调用与结果归一化
3. `data/llm_config.db` 内的 `settings.mcp.servers` 定义

配置运行层管理 MCP 资源代际及租约；连接与工具发现由 `service_parts/mcp_lifecycle.py` 装配。无关字段修改保持已有连接，正在执行的任务持有原资源直到结束。

内置工具、直连 API 工具与 MCP 工具在同一注册表中管理，对模型提供统一的调用接口。

### 4.2 当前项目配置形式

当前项目在导出 JSON 的 `settings.mcp.servers` 配置 MCP server，保存草稿后单独应用：

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

此片段合入完整导出文件时，保留其他设置与需要继续使用的服务。

---

## 5. 远程部署准备

接入前先确认服务提供的端点或启动方式，并准备凭据。`stdio` 需要 Bot 环境中的可执行命令及依赖；`docker` 需要 Docker daemon、镜像和卷；`http`、`sse` 需要 Bot 可访问的服务端点。具体配置见[MCP 教程](mcp-tutorial.md#3-四种-transport-逐一实例)。

---

## 6. 控制模型工具集合

模型使用 MCP 工具需要开启 `settings.runtime.tool_calling_enabled`，默认值为 `false`。MCP 总开关和对应服务开关控制连接，工具调用总开关控制模型调用。

对于工具较多的服务，先在 `settings.mcp.servers` 中使用 `include_tools` 和 `exclude_tools` 选择需要注册的工具，再通过 `settings.tools` 管理模型可见的集合。`discovery_mode = "auto"` 在可延迟工具数超过 `discovery_min_tools` 时启用发现：首轮发送 `always_loaded` 常驻工具，模型用 `tool_search` 搜索能力，或用 `tool_list` 查看目录、按精确名称加载。新增工具进入下一轮请求。

严格工具名单应包含发现元工具和需要使用的 MCP 别名。

工具发现的实现边界与测试覆盖见 [tool-discovery.md](tool-discovery.md)。

---

## 7. 扩展与维护

新增服务按传输、协商模式、工具清单和结果类型逐项核对。凭据通过根目录 `.env` 提供，配置库保存变量引用；卷挂载由部署编排准备。MCP 扩展计划集中记录在[ROADMAP](../../ROADMAP.md)。

---

## 8. 工具结果内容边界

MCP 工具调用会先在 `src/quickquip/llm/mcp/` 归一化为受控的内部结果，再交给现有工具调用链。当前文本结果保持逐项去除首尾空白、忽略空项并以换行连接；仅在没有可见文本时，`structuredContent` 保持现有 JSON 文本回退行为。

`ImageContent` 会先严格校验 base64、5 MiB 单图大小、真实图片格式和声明 MIME；首期仅支持 PNG、JPEG、GIF、WebP，每个 MCP 工具结果最多交付 5 张。校验通过的图片只在当前工具调用循环的内存中保存：视觉模型按各 provider 的受支持格式接收；非视觉模型使用已配置的图片转述器，转述失败或服务不可用时保留安全工具文本并明确省略图片。工具错误或被敏感词整体拦截的结果不会交付图片。图片像素本身不在本地敏感词审核范围，转述文本会在进入主模型前再次扫描。

resource 的内联文本在 MIME 属于文本族（text/* 前缀与常见文本 application 类型，MIME 缺省视为文本）时有界交付：正文进入工具文本管线，超过 60,000 code point 截断并附固定标记；blob、非文本 MIME、空白正文、audio、link 和未知内容保持只提供稳定的有限提示，不会被原样 JSON 序列化为工具文本。系统不会自动下载 resource/link，也不会把 blob、完整 URL query 或音频数据注入模型请求；资源 URI 不随正文渲染。MCP 图片只服务下一轮模型推理，不会直接作为 QQ 最终消息发送给用户。

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
| `legacy`（默认） | 使用 `initialize` 握手和服务器提供的 session；适用于 legacy Server。 |
| `auto` | 先发 `server/discover` 探测；如果 Server 返回 DiscoverResult 就走 modern；如果返回 legacy 信号（JSON-RPC error、400/404/405 无 modern error body）就回退 legacy。401/403/5xx/超时直接失败，不回退。 |
| `modern` | 只走 modern 协议，不回退。 |

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

- `stdio`、`docker`、`sse` transport 只支持 legacy；配置 `auto`/`modern` 时保存或导入预览返回字段错误，须修正后再保存草稿。
- `auto`/`modern` 要求非空 `supported_protocol_versions`；缺失时整个配置校验失败。运行时连接与协商失败通过对应 server 状态报告，配置校验和网络装载分别处理。
- `auto` 探测的结论在当前装载周期内保持：session 过期重连不重新探测，`/llm mcp reload` 或 `/llm reload` 触发的重新装载会重新探测。
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
