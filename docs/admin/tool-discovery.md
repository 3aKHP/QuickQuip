# LLM 工具发现配置

本文面向部署者和管理员，说明如何配置本地 `tool_search` 工具发现。该功能适合接入大量 MCP 工具时使用，例如 GitHub MCP 一次暴露几十个工具的场景。

---

## 1. 功能作用

工具发现开启后，QuickQuip 不会在每次 LLM 请求里暴露全部工具定义。初始请求只包含少量常驻工具；模型需要其它能力时，先调用 `tool_search` 搜索工具目录，工具循环会把匹配到的真实工具加入下一轮请求。

这可以降低 prompt 和 tool schema 体积，并减少模型在大量工具中选错工具的概率。

---

## 2. 推荐配置

在 `config/llm.toml` 中配置：

```toml
[tools]
enabled = []

discovery_mode = "auto"
discovery_min_tools = 10
discovery_search_limit = 5
discovery_max_loaded_tools = 12
always_loaded = ["tool_search", "tool_list", "get_identity", "list_memories", "search_web"]
```

字段说明：

| 键 | 说明 |
|----|------|
| `enabled` | 工具白名单。为空时启用内置工具和已连接的 MCP 工具 |
| `discovery_mode` | `off` 全量暴露；`on` 强制工具发现；`auto` 超过阈值后自动启用 |
| `discovery_min_tools` | `auto` 模式下，可延迟工具数超过该值才启用工具发现 |
| `discovery_search_limit` | 单次 `tool_search` 最多返回并加载的工具数 |
| `discovery_max_loaded_tools` | 一次工具调用循环中最多动态加载的工具总数 |
| `always_loaded` | 工具发现开启时仍然直接暴露的常驻工具 |

`tool_search` 用于按能力描述搜索工具；`tool_list` 用于列出工具组、工具名、工具摘要，并可用 `mode = "load"` 按精确名称加载工具。

---

## 3. 模式选择

### `discovery_mode = "auto"`

推荐默认值。小工具集继续全量暴露；接入大量 MCP 工具后自动启用工具发现。

### `discovery_mode = "on"`

适合部署环境中已经确认工具数量较多，且希望稳定控制每轮请求体积的场景。

### `discovery_mode = "off"`

用于排障或兼容旧行为。关闭后所有启用工具都会直接传给模型。

---

## 4. 常驻工具建议

建议保留：

- `tool_search`
- `tool_list`
- `get_identity`
- `list_memories`
- `search_web`

如果某个 MCP 工具使用频率很高，也可以加入 `always_loaded`。例如：

```toml
always_loaded = [
  "tool_search",
  "tool_list",
  "get_identity",
  "list_memories",
  "search_web",
  "mcp_github_search_repositories"
]
```

---

## 5. GitHub MCP 场景

GitHub MCP 工具数量较多时，建议：

```toml
[tools]
discovery_mode = "auto"
discovery_min_tools = 10
discovery_search_limit = 5
discovery_max_loaded_tools = 12
always_loaded = ["tool_search", "tool_list", "get_identity", "list_memories", "search_web"]
```

如果希望模型总是先搜索 GitHub 能力，再调用具体 GitHub 工具，保持 GitHub MCP 工具不在 `always_loaded` 中即可。

生产环境建议在 MCP server 层先收窄工具集合，再启用工具发现。例如只接入常用读类工具：

```toml
[[mcp.servers]]
id = "github"
transport = "http"
tool_prefix = "github"
url = "https://mcp.example.com/github/mcp"
headers = { Authorization = "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}" }
include_tools = [
  "search_repositories",
  "search_code",
  "get_file_contents",
  "list_issues",
  "issue_read",
  "list_pull_requests",
  "pull_request_read",
  "actions_list",
  "actions_get",
]
```

被 `include_tools` / `exclude_tools` 过滤掉的工具不会进入 QuickQuip 工具注册表，因此也不会出现在 `tool_search`、`tool_list` 或真实工具调用路径中。

---

## 6. 排障

### 模型直接调用未加载工具

开启工具发现后，模型应先调用 `tool_search`。如果它直接调用延迟工具，QuickQuip 会返回错误提示，要求先搜索并加载相关工具。

### 搜不到工具

检查：

- `[tools].enabled` 是否把目标工具排除
- MCP server 是否连接成功
- `/llm mcp status` 是否能看到对应工具
- 提问里是否包含工具来源或能力关键词

如果工具确实存在但 `tool_search` 没命中，可让模型按以下顺序兜底：

1. `tool_list mode="groups"` 查看工具组
2. `tool_list mode="group" group="mcp:github"` 查看某组摘要
3. `tool_list mode="load" names=["目标工具名"]` 精确加载工具

### 想临时恢复旧行为

设置：

```toml
[tools]
discovery_mode = "off"
```

然后重载 LLM 配置。
