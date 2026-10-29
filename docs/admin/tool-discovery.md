# LLM 工具发现配置

本文面向部署者和管理员，说明如何让模型从大量工具中按需搜索并加载能力。适合 GitHub MCP 等工具较多的服务。

先在“LLM 配置 → 工具与技能”开启工具调用。下方示例为完整导出 JSON 的字段片段，可在页面中编辑，或合入完整导出文件后预览导入。保存草稿并单独应用，确认 Bot 已加载目标版本。完整流程见[LLM 配置管理](llm-configuration.md)。

---

## 1. 功能作用

工具发现开启后，初始请求包含常驻工具，模型需要其他能力时先调用 `tool_search` 搜索目录。匹配的工具加入下一轮请求，模型随后调用这些工具。

按需加载可以减少每轮发送的工具定义数量。

---

## 2. 推荐配置

在 Web Admin“LLM 配置”编辑 `settings.tools`，或在完整导出 JSON 中配置以下字段：

```json
{
  "settings": {
    "tools": {
      "enabled": [],
      "discovery_mode": "auto",
      "discovery_min_tools": 10,
      "discovery_search_limit": 5,
      "discovery_max_loaded_tools": 12,
      "always_loaded": [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "search_web",
        "activate_skill"
      ]
    }
  }
}
```

字段说明：

| 键 | 说明 |
|----|------|
| `enabled` | 工具名单。空列表启用默认内置工具和已连接的 MCP 工具；非空时默认追加，`enabled_mode = "replace"` 按名单精确过滤，见[配置参考](configuration.md#settingstools--工具调用) |
| `discovery_mode` | `off` 全量暴露；`on` 强制工具发现（`tool_search` 被白名单排除或当前没有可延迟工具时不生效）；`auto` 超过阈值后自动启用 |
| `discovery_min_tools` | `auto` 模式下，可延迟工具数超过该值才启用工具发现 |
| `discovery_search_limit` | 单次 `tool_search` 最多返回并加载的工具数；同一上限也约束 `tool_list mode = "load"` 的单次加载数 |
| `discovery_max_loaded_tools` | 新增工具时比较当前已加载总数，`always_loaded` 常驻工具计入；达到该值后停止新增，已有集合保留 |
| `always_loaded` | 工具发现开启时直接提供给模型的常驻工具。未配置时回退内置默认集：`tool_search` / `tool_list` / `get_identity` / `list_memories` / `read_memory` / `write_memory` / `delete_memory` / `search_web` / `activate_skill` |

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

推荐配置中的六个常驻工具提供搜索、目录、身份、记忆、联网与 Skill 激活能力，可按实际使用需求调整。

如果某个 MCP 工具使用频率很高，也可以加入 `always_loaded`。例如：

```json
{
  "settings": {
    "tools": {
      "always_loaded": [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "search_web",
        "mcp_github_search_repositories"
      ]
    }
  }
}
```

---

## 5. GitHub MCP 场景

使用上方推荐的 `auto` 配置，让 GitHub 工具进入按需加载目录。需要每轮直接提供的高频工具可加入 `always_loaded`。

生产环境建议在 MCP server 层先收窄工具集合，再启用工具发现。例如只接入常用读类工具：

```json
{
  "settings": {
    "mcp": {
      "servers": [
        {
          "id": "github",
          "transport": "http",
          "url": "https://mcp.example.com/github/mcp",
          "headers": {
            "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
          },
          "include_tools": [
            "search_repositories",
            "search_code",
            "get_file_contents",
            "list_issues",
            "issue_read",
            "list_pull_requests",
            "pull_request_read",
            "actions_list",
            "actions_get"
          ]
        }
      ]
    }
  }
}
```

被 `include_tools` / `exclude_tools` 过滤掉的工具不会进入 QuickQuip 工具注册表，因此也不会出现在 `tool_search`、`tool_list` 或真实工具调用路径中。

---

## 6. 排障

### 模型直接调用未加载工具

开启工具发现后，模型应先调用 `tool_search`。如果它直接调用延迟工具，QuickQuip 会返回错误提示，要求先搜索并加载相关工具。

### 搜不到工具

检查：

- `settings.tools.enabled` 是否把目标工具排除
- MCP server 是否连接成功
- `/llm mcp status` 是否能看到对应工具
- 提问里是否包含工具来源或能力关键词

如果工具确实存在但 `tool_search` 没命中，可让模型按以下顺序兜底：

1. `tool_list mode="groups"` 查看工具组
2. `tool_list mode="group" group="mcp:github"` 查看某组摘要
3. `tool_list mode="load" names=["目标工具名"]` 精确加载工具

### 临时直接提供全部工具

设置：

```json
{
  "settings": {
    "tools": {
      "discovery_mode": "off"
    }
  }
}
```

然后保存草稿并应用；等待配置任务完成并确认 Bot 实际加载版本。
