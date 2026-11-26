<!-- Generated from docs/dev/tool-discovery.md; do not edit -->

# LLM 工具发现实现说明

本文面向开发者，说明 QuickQuip 本地工具发现的数据流、启用条件、检索与点名规则、会话纪元粘性边界以及回归测试入口。

---

## 1. 设计目标

QuickQuip 在服务层维护统一的工具目录，OpenAI Chat、Claude、Gemini 与 OpenAI Responses 四类协议适配器共用同一套工具发现结果，再按各自协议格式序列化工具定义与调用：

- 请求初始阶段仅下发常驻工具（`always_loaded`）与当前会话纪元已动态装载的粘性工具，避免大体积工具 Schema 挤占上下文
- 模型通过 `tool_search` 按能力关键词检索工具清单，或通过 `select:` 语法按工具名精确批量加载
- 搜索未命中时，模型可调用 `tool_list` 分组浏览工具目录、查看摘要或按精确名称兜底加载
- 工具循环将新命中的工具加入下一轮 `LLMRequest.tools`，并在回合结束时按序写回当前会话纪元供后续轮次复用

---

## 2. 关键文件

| 文件 | 职责 |
|------|------|
| `src/quickquip/llm/tools.py` | 定义 `LLMToolSpec` 与工具目录条目 `ToolManifestEntry` |
| `src/quickquip/llm/tool_registry.py` | 保存真实工具定义与执行函数，生成工具目录清单并执行关键词打分检索 |
| `src/quickquip/llm/service_parts/tools.py` | 注册内置工具与 `tool_search` / `tool_list` 元工具 handler，计算当前会话的已启用工具集合、常驻集合、已装载集合与延迟池按名公告 |
| `src/quickquip/llm/tool_discovery.py` | 维护单次工具循环内的已加载工具列表（`loaded_names`），解析 `select:` 与裸工具名显式点名请求 |
| `src/quickquip/llm/epoch.py` | 在 `EpochState.loaded_tool_names` 中按会话纪元（`scope × provider × model`）跨轮粘性保留动态加载的工具 |
| `src/quickquip/llm/reply_chain.py` | 组装首轮与预算降级请求时合并当前纪元的粘性已加载工具，并同步更新当轮信封中的延迟工具公告 |
| `src/quickquip/llm/tool_loop.py` | 编排多轮工具调用循环，拦截未装载工具调用，并将新加载的工具带入下一轮请求 |
| `src/quickquip/llm/prompting.py` | 在工具发现开启时渲染静态发现引导与当轮信封尾部的延迟工具按名公告 |
| `src/quickquip/llm/config.py`、`config_document.py` | 定义、校验并编译 `settings.tools` 下的工具白名单与工具发现参数 |

---

## 3. 数据流

1. `LLMService` 启动时注册内置工具；MCP 同步完成后将外部 MCP 工具桥接进同一个 `ToolRegistry`。
2. `ToolRegistry.register()` 记录每个工具的 `LLMToolSpec`、执行 handler、来源（`source`）、分组（`category`）与检索关键词（`keywords`）。
3. `_get_enabled_tool_names()` 结合群聊／私聊作用域、Skill 开关、群历史查询开关与搜索路由，算出当前会话允许使用的已启用工具集合。
4. `_is_tool_discovery_enabled()` 根据 `discovery_mode`、可延迟工具数量及 Schema 估算体积判断是否开启工具发现。
5. 开启发现后，请求组装器合并 `always_loaded` 常驻工具与当前会话纪元 `EpochState.loaded_tool_names` 中的粘性工具，生成首轮 `LLMRequest.tools`（静态 `system_prompt` 仍仅渲染 `always_loaded` 常驻工具，确保前缀缓存稳定）。
6. 当轮 `user` 消息头部的 `【轮次上下文】` 信封附带当前尚未装载的可延迟工具名称列表。
7. 模型调用 `tool_search`（关键词检索或 `select:` 批量点名），或调用 `tool_list` 浏览目录并加载工具。
8. `ToolDiscovery` 将新加载且未超上限的工具追加进 `loaded_names`，下一轮 `LLMRequest.tools` 立即携带这些真实工具定义供模型调用。
9. 本轮对话完成后，新装载的工具按序记入当前会话纪元的 `loaded_tool_names`，在同一纪元的后续对话轮次中继续生效。

---

## 4. 检索与显式点名策略

`ToolRegistry.search_manifest()` 采用轻量字符串权重打分：

- 工具名称精确命中或子串命中权重最高，`keywords` 与 `description` 命中次之，参数名、`category` 与 `source` 命中作为补充；支持按 `enabled_names` 白名单、`exclude_names` 排除项及 `category`（如 `mcp:github`）过滤范围。
- `tool_search` 的 `query` 参数支持 `select:名称1,名称2` 逗号分隔批量精确加载，使模型能够在单次工具回合内一次装载多个所需工具；当 `query` 恰好无歧义匹配某个已启用工具名时，同样走精确按名加载快路径（精确大小写匹配优先，仅在小写形式唯一命中时做大小写容错）。重复点名已装载工具视作幂等空操作；若触及 `discovery_max_loaded_tools` 上限或点名了未启用的工具，工具返回文本会追加纠正提示，明确列出未能装载的名称。

启用工具发现时，当轮 `【轮次上下文】` 信封末尾会附带一行**延迟池按名公告**（仅列出工具名称，不下发 Schema），使模型无需盲搜即可获知“当前还有哪些可延迟加载的工具”，配合 `select:` 一轮完成按名装载。公告名单等于已启用工具集合减去常驻工具集合、当前纪元已粘性加载工具及两个发现元工具；剩余名称超过 20 项时截断展示。

`tool_list` 提供五种目录兜底模式：

- `mode="groups"`：列出所有工具分组及每组代表工具
- `mode="names"`：分页列出工具名称
- `mode="summaries"`：分页列出工具名称、参数名与简短说明
- `mode="group"`：列出指定分组下的工具摘要
- `mode="load"`：按 `names` 数组精确加载指定工具

---

## 5. 模式语义

工具发现策略位于 `settings.tools`，经草稿保存与应用任务生效：

- `discovery_mode = "off"`：关闭按需发现，当前会话全部已启用工具直接随 `LLMRequest.tools` 下发。
- `discovery_mode = "on"`：只要已启用工具集合多于常驻工具集合，即开启按需发现。
- `discovery_mode = "auto"`（默认）：统计不在 `always_loaded` 中的可延迟工具；当可延迟工具数量大于 `discovery_min_tools`（默认 `6`），或者这些可延迟工具的协议中立 Schema 估算体积总和大于 `discovery_min_schema_tokens`（默认 `2000`，设为 `0` 可关闭按体积触发）时开启按需发现；两者均未超过阈值的小工具集直接全量下发。

全局工具调用总开关 `settings.runtime.tool_calling_enabled` 默认关闭，开启后才会向模型暴露工具。若自定义 `settings.tools.enabled` 白名单（尤其是 `enabled_mode = "replace"`）排除了 `tool_search`，按需发现会自动停用；配置严格工具白名单时应同时保留 `tool_search` 与 `tool_list`。

---

## 6. 边界与限制

- `tool_search` 与 `tool_list` 只负责检索和装载工具定义，模型需在装载完成后的后续轮次发起目标工具调用；若模型直接调用尚未装载的工具，工具循环会拦截调用并返回未装载提示。
- 动态加载的工具在当前会话纪元（`scope × provider × model`）内跨轮粘性保留在进程内存中，不写入 SQLite 数据库；当发生纪元推进或重建、切换模型（`/llm use`）、切换人格（`/llm persona use`）、清空上下文（`/llm clear_context`）或进程重启时自动清空。
- 每次新增装载工具时，系统将常驻工具与动态工具合并计数并与 `discovery_max_loaded_tools`（上限钳制在 `1..64`）比较；达到上限后停止接纳新工具，已装载集合保持不变。
- 本地 `search_web`、群历史查询与群语录查询各自的调用次数或 Token 额度由对应工具的执行器独立控制。

---

## 7. 测试覆盖

核心回归测试入口：

- `tests/unit/llm/test_tool_registry.py`：验证工具目录打分排序，以及 `enabled` / `excluded` / `category` / `limit` 过滤与 Schema 体积估算。
- `tests/unit/llm/test_epoch.py` 与 `tests/integration/test_llm_service.py`：验证同一会话纪元内的动态工具跨轮粘性保留、延迟池公告扣除以及切换人格／清空会话／纪元推进时的清理行为。
- `tests/integration/test_llm_mcp.py`：验证外部 MCP 工具经 `tool_search`（含 `select:` 批量加载）或 `tool_list`（`groups` / `group` / `load`）动态装载并在下一轮成功调用。
- `tests/unit/llm/test_config_document.py` 与 `tests/unit/llm/test_config_env_expand.py`：验证 `settings.tools` 字段约束与旧版 TOML 迁移兼容。

修改工具发现相关实现后，建议至少运行：

```bash
.venv/bin/python -m pytest tests/unit/llm tests/integration/test_llm_service.py tests/integration/test_llm_search.py tests/integration/test_llm_mcp.py
```
