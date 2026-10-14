<!-- Generated from docs/dev/tool-discovery.md; do not edit -->

# LLM 工具发现实现说明

本文面向开发者，说明 QuickQuip 本地工具发现的数据流、启用条件、调用规则和测试入口。

---

## 1. 设计目标

QuickQuip 在服务层维护本地工具目录，四类协议适配器共用工具发现结果，并按各自的工具调用协议发送请求：

- 初始请求只暴露常驻工具
- `tool_search` 根据 query 搜索工具 manifest
- `tool_list` 在搜索失败时列出工具组、名称、摘要，或按精确名称加载工具
- 工具循环把匹配到的真实工具加入下一轮 `LLMRequest.tools`
- provider 适配层按对应协议序列化工具定义与调用

---

## 2. 关键文件

| 文件 | 责任 |
|------|------|
| `src/quickquip/llm/tools.py` | 定义 `ToolManifestEntry` |
| `src/quickquip/llm/tool_registry.py` | 保存真实工具 spec/handler，生成 manifest，执行搜索 |
| `src/quickquip/llm/service_parts/tools.py` | 注册 `tool_search` / `tool_list`，决定启用工具列表和常驻工具列表 |
| `src/quickquip/llm/tool_discovery.py` | 持有单次循环的已加载工具集（`loaded_names`），实现 `tool_search` / `tool_list` 元工具 handler |
| `src/quickquip/llm/tool_loop.py` | 工具调用循环本体，把命中或精确加载的工具交给发现状态并带进下一轮请求 |
| `src/quickquip/llm/prompting.py` | discovery 模式下生成工具发现提示 |
| `src/quickquip/llm/config.py`、`config_document.py` | 定义配置对象，校验并编译 `settings.tools` 下的工具发现配置 |

---

## 3. 数据流

1. `LLMService` 启动时注册内置工具，MCP sync 后把 MCP binding 桥接进同一个 `ToolRegistry`。
2. `ToolRegistry.register()` 保存 `LLMToolSpec`、handler、source、category、keywords 等 manifest 元数据。
3. `_get_enabled_tool_names()` 得到当前会话允许使用的完整工具集合。
4. `_is_tool_discovery_enabled()` 根据 `discovery_mode` 和可延迟工具数决定是否启用工具发现。
5. 启用后，首轮 `LLMRequest.tools` 只包含 `always_loaded`。
6. 模型调用 `tool_search`，或用 `tool_list` 兜底查看工具目录。
7. `ToolRegistry.search_manifest()` 按工具名、描述、参数名、分类和关键词打分。
8. `ToolDiscovery` 把命中的工具名，或 `tool_list mode="load"` 指定的精确工具名，加入 `loaded_names`。
9. 下一轮 `LLMRequest.tools` 包含常驻工具和新加载工具。

---

## 4. 搜索策略

当前是轻量字符串打分：

- 工具名精确/包含命中权重最高
- `keywords` 和 description 命中次之
- 参数名、category、source 命中作为补充
- 支持 `enabled_names` 白名单和 `exclude_names`
- `category` 参数可限制搜索范围，例如 `mcp:github`

搜索在现有 manifest 上进行字符串匹配和排序。

`tool_list` 提供目录式兜底：

- `mode="groups"`：列出工具组和每组示例工具
- `mode="names"`：分页列出工具名
- `mode="summaries"`：分页列出工具名、参数名和一句话说明
- `mode="group"`：列出指定组下的工具摘要
- `mode="load"`：按精确工具名加载少量工具

---

## 5. 模式语义

`discovery_mode = "off"`：

- 所有启用工具直接进入 `LLMRequest.tools`

`discovery_mode = "on"`：

- 只要完整工具集合比常驻工具集合更多，就启用 discovery

`discovery_mode = "auto"`：

- 统计不在 `always_loaded` 里的可延迟工具数量
- 当可延迟工具数大于 `discovery_min_tools` 时启用
- 小工具集直接发送全部启用工具

配置位于 `settings.tools`，由草稿保存与应用流程生效。工具调用总开关 `settings.runtime.tool_calling_enabled` 默认关闭，开启后才向模型提供工具。`settings.tools.enabled` 排除 `tool_search` 时，发现机制关闭；配置严格名单时应同时保留 `tool_search` 和 `tool_list`。

---

## 6. 边界与限制

- `tool_search` 和 `tool_list` 发现或加载工具；模型在后续调用中请求执行目标工具。
- 动态加载只在当前工具调用循环内有效，不写入数据库。
- 模型直接调用未加载工具时，工具循环返回错误提示。
- 动态添加工具时，用 `discovery_max_loaded_tools` 与当前已加载工具数比较；常驻工具计入，达到上限后停止新增工具，已有集合保留。
- `search_web` 的调用上限由独立的搜索保护逻辑执行。

---

## 7. 测试覆盖

相关测试：

- `tests/unit/llm/test_tool_registry.py`
  - manifest 搜索排序
  - enabled/excluded/category/limit 过滤
- `tests/integration/test_llm_mcp.py`
  - MCP 工具先被 `tool_search` 找到，再在下一轮动态加载并执行
  - `tool_list` 通过 groups/group/load 兜底加载 MCP 工具并执行
- `tests/unit/llm/test_config_env_expand.py`
  - 旧 TOML 的工具发现配置读取与迁移输入兼容

数据库配置校验另见 `tests/unit/llm/test_config_document.py`。

建议修改该功能后至少运行：

```bash
.venv/bin/python -m pytest tests/unit/llm tests/integration/test_llm_service.py tests/integration/test_llm_search.py tests/integration/test_llm_mcp.py
```
