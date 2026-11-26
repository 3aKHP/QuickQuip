<!-- Generated from docs/admin/tool-discovery.md; do not edit -->

# LLM 工具发现配置

本文面向部署者和管理员，说明如何让模型从大量工具中按需搜索并动态加载能力，适合接入 GitHub MCP 等工具数量较多或单个 Schema 较大的场景。

先在“LLM 配置 → 工具与技能”开启工具调用。下方示例为完整导出 JSON 的字段片段，可在页面表单中直接编辑，或合入完整导出文件后预览导入。保存草稿并应用到 Bot 后，确认顶部状态显示 Bot 已加载目标版本（完整流程见[LLM 配置管理](llm-configuration.md)）。

---

## 1. 功能作用

开启工具发现后，初始请求只向模型发送 `always_loaded` 常驻工具的完整 Schema 定义，并在当轮上下文信封中自动附上其余可延迟工具的名称清单（如 MCP 工具、非常驻的 Skill 资源工具以及群聊下的 `query_group_quotes` 等）。模型需要额外能力时，既可按功能关键词调用 `tool_search` 搜索目录，也可直接传入 `select:名称1,名称2` 在一轮内按名批量加载所需工具。

动态加载的工具在下一轮模型请求中立即可用，并在**同一会话纪元（`scope × provider × model`）内跨轮次粘性保留**，避免围绕同一话题连续追问时反复搜索加载；静态 `system_prompt` 仍只描述常驻工具，不会破坏提示词前缀缓存。当会话纪元推进或重建、切换人格、清空会话上下文或重启 Bot 时，动态加载集合会自动清空并回到常驻工具集。

---

## 2. 推荐配置

在 Web Admin“LLM 配置 → 工具与技能”编辑 `settings.tools`，或在完整导出 JSON 中配置以下字段：

```json
{
  "settings": {
    "tools": {
      "enabled": [],
      "discovery_mode": "auto",
      "discovery_min_tools": 6,
      "discovery_min_schema_tokens": 2000,
      "discovery_search_limit": 5,
      "discovery_max_loaded_tools": 12,
      "always_loaded": [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "read_memory",
        "write_memory",
        "delete_memory",
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
| `enabled` | 工具名单。留空 `[]` 时启用全部默认内置工具（群聊下包含 `query_group_quotes` 等群聊专属工具）和已连接的 MCP 工具；非空时默认按 `append` 追加，设为 `enabled_mode = "replace"` 则仅保留名单内工具，详见[配置参考](configuration.md#settingstools--工具调用) |
| `discovery_mode` | `off` 始终全量发送工具定义；`on` 只要存在可延迟工具且未排除 `tool_search` 即启用工具发现；`auto` 在达到数量或体积阈值时自动启用 |
| `discovery_min_tools` | `auto` 模式的数量阈值：可延迟工具数量超过该值时启用工具发现（默认 `6`） |
| `discovery_min_schema_tokens` | `auto` 模式的 Schema 体积阈值：可延迟工具的估算 Schema Token 总量超过该值时，即使工具个数不多也会启用工具发现（与 `discovery_min_tools` 满足任一条件即触发；设为 `0` 关闭体积判断） |
| `discovery_search_limit` | 单次 `tool_search` 关键词搜索最多返回并加载的工具数；同时限制 `tool_list` 在 `mode = "load"` 下单次加载的工具数 |
| `discovery_max_loaded_tools` | 当前会话同时挂载的工具总数上限，包含 `always_loaded` 常驻工具与同一会话纪元内已粘性加载的工具；达到上限后停止新增，已加载集合继续保留 |
| `always_loaded` | 工具发现开启时每轮固定提供完整定义的常驻工具。留空时采用内置默认集合：`tool_search`、`tool_list`、`get_identity`、`list_memories`、`read_memory`、`write_memory`、`delete_memory`、`search_web`、`activate_skill` |

`tool_search` 既支持按能力描述关键词搜索工具目录，也支持根据当轮信封公布的工具名，用 `query = "select:名称1,名称2"`（或单个精确工具名）直接点名加载；`tool_list` 用于浏览工具分组和组内摘要，也可通过 `mode = "load"` 按精确名称列表加载工具。

---

## 3. 模式选择

### `discovery_mode = "auto"`

推荐默认值。少量内置工具保持直接可用；接入 MCP 工具、开启群聊历史查询或挂载体积较大的工具 Schema 后会自动切换为按需发现。

### `discovery_mode = "on"`

适合部署环境中已经明确接入较多外部工具、希望始终控制每轮请求工具体积的场景。

### `discovery_mode = "off"`

适合排障或工具总数很少的环境，关闭后所有已启用工具都会在每轮请求中完整传给模型。

---

## 4. 常驻工具建议

默认推荐的九个常驻工具覆盖了工具搜索与目录浏览、成员身份识别、长期记忆读写、联网搜索及 Skill 激活能力，日常对话无需额外加载即可直接使用，可按实际需求增减。

如果某个 MCP 工具在群内使用频率很高，也可以一并加入 `always_loaded`（自定义列表时请保留需要的默认常驻工具）：

```json
{
  "settings": {
    "tools": {
      "always_loaded": [
        "tool_search",
        "tool_list",
        "get_identity",
        "list_memories",
        "read_memory",
        "write_memory",
        "delete_memory",
        "search_web",
        "activate_skill",
        "mcp_github_search_repositories"
      ]
    }
  }
}
```

---

## 5. GitHub MCP 场景

使用上方推荐的 `auto` 配置即可让低频 GitHub 工具留在按需加载目录中，仅将每轮高频使用的工具放入 `always_loaded`。

生产环境建议先在 MCP 服务配置层用 `include_tools` 收窄允许接入的工具范围，再配合工具发现按需装载。例如只接入常用只读工具：

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

被 `include_tools` / `exclude_tools` 过滤掉的工具不会进入 QuickQuip 工具注册表，也不会出现在当轮延迟清单、`tool_search`、`tool_list` 或实际调用路径中。

---

## 6. 群聊历史查询工具

`search_group_history`、`read_group_history` 与 `investigate_group_history` 三个只读工具仅在群聊会话中提供（私聊固定不启用），开启后默认归入延迟加载目录。

群聊历史查询遵循**群级显式设置优先覆盖全局默认**的规则：全局配置 `settings.group_history.enabled` 默认为 `false`，群管理员可在群内执行 `/llm history on|off|reset`，或由系统管理员在 Web Admin“群 LLM”页单独开启、关闭本群的历史查询（设为 `reset` 时恢复跟随全局默认）。因此即使全局开关保持关闭，单独为某个群开启后，该群即可正常发现和调用这三个工具。群级开关保存在本地运行数据库中，与 `config/managed/config.db` 中的其他群设置分开存储。

面对跨越多天记录或需要多轮核实的复杂提问，主模型可调用 `investigate_group_history` 委派独立的调查子任务。子任务默认跟随当前对话的渠道与模型，也可在 `settings.group_history` 中配置专用渠道（`investigation_provider_id`）、专用模型（`investigation_model`）及运行预算（默认时限 `240` 秒、模型调用上限 `10` 次、历史工具调用上限 `30` 次）。子任务内部仅可使用本群历史的搜索、原文读取和全量计数三项只读能力——其中全量计数不受搜索分页上限约束，返回 `0` 条即可确认指定时间窗内从未出现目标词。若子任务触及预算上限提前收束，返回报告会如实注明“部分完成”，由主模型决定是否补查。调查运行期间，同群后续的 AI 回复会排队等待；同时受全局最多 `2` 个、每群最多 `1` 个的并发上限保护，超限时直接返回繁忙提示。

历史查询返回的消息正文与检索词按临时工具结果处理（详见 [ADR-0005](../dev/adr/0005-tool-result-retention.md)），仅在当轮工具循环内供模型阅读，落库记录只保留调用事实与统计元数据，不会把历史聊天原文重复写入执行记录库。

---

## 7. 排障

### 模型直接调用未加载工具

开启工具发现后，模型需要先加载延迟工具才能调用。如果模型直接调用尚未加载的工具，QuickQuip 会返回未加载提示，引导模型先通过 `tool_search`（含 `select:工具名`）或 `tool_list` 完成加载。

### 搜不到或装不进目标工具

请依次检查：

- `settings.tools.enabled` 与 `enabled_mode` 是否将目标工具排除在外；
- 当前会话已加载工具总数是否已达到 `discovery_max_loaded_tools` 上限（同一会话纪元内粘性保留的工具同样计入上限）；
- 对应的 MCP 服务是否连接正常（可在群内用 `/llm mcp status` 核对工具数）；
- 如果是群聊历史工具，确认本群历史查询已开启（`/llm history status`）。

若工具已注册但关键词搜索未命中，可引导模型按以下方式直接定位加载：

1. 直接使用当轮信封中列出的精确名称调用 `tool_search`：`query="select:目标工具名"`；
2. 或依次执行 `tool_list mode="groups"` 查看分组、`tool_list mode="group" group="mcp:github"` 查看组内摘要，再用 `tool_list mode="load" names=["目标工具名"]` 加载。

### 临时直接提供全部工具

排查问题期间如需跳过按需发现，可将 `discovery_mode` 设为 `"off"`：

```json
{
  "settings": {
    "tools": {
      "discovery_mode": "off"
    }
  }
}
```

保存草稿并应用到 Bot，等待顶部状态显示 Bot 已加载目标版本即可生效。
