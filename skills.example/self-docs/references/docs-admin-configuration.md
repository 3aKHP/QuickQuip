<!-- Generated from docs/admin/configuration.md; do not edit -->

# QuickQuip 配置参考

LLM 配置示例为导出 JSON 中的字段片段；请在 Web Admin“LLM 配置”中编辑，或修改完整导出文件后预览导入、保存草稿并单独应用。完整交换格式见 [LLM 配置管理](llm-configuration.md)。

本文面向部署者，按配置文件与作用范围列出可配置项。环境变量在根 `.env` 中维护并通过重启生效；LLM 草稿保存后单独应用；独立 TOML 文件的生效方式见对应部署与管理说明。

---

## .env 环境变量

### 基础运行

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DRIVER` | NoneBot2 驱动器；正向 WebSocket 连接 OneBot 协议端时需包含 `~websockets` | `~fastapi+~websockets` |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `8080` |
| `QQ_ACCOUNT` | QQ 号（云端部署必填） | — |
| `ONEBOT_WS_URLS` | OneBot V11 WebSocket 地址列表 | — |
| `ONEBOT_ACCESS_TOKEN` | OneBot 接入令牌 | — |
| `TZ` | 容器与进程时区（日志、定时任务展示时间等） | `Asia/Shanghai` |

### LLM API Keys

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI 兼容 API key |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub PAT（MCP 用） |
| `GITHUB_TOOLSETS` | GitHub MCP 启用的工具集，逗号分隔。可选：`context`, `repos`, `issues`, `pull_requests`, `users`, `actions` |
| `GITHUB_READ_ONLY` | 设为非空时限制 GitHub MCP 为只读 |
| `TAVILY_API_KEY` | Tavily API key（供 MCP sidecar 的 Tavily 工具使用，未启用 MCP Tavily 时无需填写） |
| `MCP_PRTS_WIKI_TOKEN` | prts_wiki MCP 的鉴权 token（见 [MCP 接入指南](mcp-servers.md) 的 prts_wiki 示例） |

### 搜索

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SEARXNG_BASE_URL` | Bot 内置 `search_web` 和 `/search` 使用的 SearXNG 服务地址；代码无内置默认，未设置时调用直接报错 | —（`http://127.0.0.1:8888` 仅为 `.env.example` 给出的示例值） |
| `QUICKQUIP_SEARXNG_BASE_URL` | Docker Compose 内注入给 QuickQuip / Web Admin 的 SearXNG 容器内地址；避免把本地直跑的 `127.0.0.1` 地址带入容器 | `http://searxng:8080` |
| `SEARXNG_SAFE_SEARCH` | 传给 SearXNG 的安全搜索级别：`0` / `1` / `2` | `0` |
| `SEARXNG_LANGUAGE` | 传给 SearXNG 的搜索语言；空值时使用 `all` | `all` |
| `SEARXNG_PUBLIC_BASE_URL` | compose 中 SearXNG 对外展示的 base URL；仅 docker-compose.example.yml（自包含模板）使用 | `http://127.0.0.1:8888/` |
| `SEARXNG_BIND_ADDRESS` | compose 暴露 SearXNG 时绑定的宿主地址；仅 docker-compose.example.yml（自包含模板）使用 | `127.0.0.1` |
| `SEARXNG_BIND_PORT` | compose 暴露 SearXNG 时绑定的宿主端口；仅 docker-compose.example.yml（自包含模板）使用 | `8888` |
| `SEARXNG_SECRET` | SearXNG 实例密钥，用于容器环境变量 | — |

LLM 工具 `search_web` 与 `/search` 命令固定走项目内 SearXNG。普通本地运行读取 `SEARXNG_BASE_URL`；`docker-compose.example.yml` 和 `prod.example/docker-compose.yml` 会优先把 `QUICKQUIP_SEARXNG_BASE_URL` 注入为容器内的 `SEARXNG_BASE_URL`。Tavily 等外部搜索能力建议通过 MCP sidecar 暴露为工具。

开启 `builtin_search` 的 gemini provider 不依赖 SearXNG：联网检索由 provider 侧 grounding 完成，`/llm health` 的搜索项在 SearXNG 缺失时按内置搜索覆盖判定为 ok。

### LLM 调试

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_TRACE_FLAG_FILE` | LLM HTTP Trace 持久开关文件路径；文件存在时按调用记录完整请求/响应 JSON 文本到 `data/llm_trace.db`，供 Web Admin 的 LLM Trace 页面按需读取 | — |
| `LLM_TRACE_MEDIA_MIN_BYTES` | 内联 base64 媒体载荷的截断门槛（字节）。达到门槛、且载荷构成被引号正确闭合的完整 JSON 字符串时，载荷本体写入 `data/trace_blobs/` 下的内容寻址副本，正文替换为 `[qq:blob sha256=<hex> bytes=<n>]` 占位符；同一份载荷在请求、重组响应与原始 SSE 中只落盘一份。未设置或为 `0` 时原样存储。进程启动时读取 | `0` |

### 贴吧

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TIEBA_ENABLED` | 是否启用贴吧功能 | `false` |
| `TIEBA_FORUM_KEYWORDS` | 多贴吧来源，逗号/分号/竖线/换行分隔 | — |
| `TIEBA_FORUM_KEYWORD` | 单贴吧来源（旧字段，多来源时优先用 `FORUM_KEYWORDS`） | — |
| `TIEBA_SYNC_INTERVAL_SECONDS` | 同步间隔（秒） | `900` |
| `TIEBA_MAX_POOL_SIZE` | 每个来源最多保留的帖子数，最小 `20` | `240` |
| `TIEBA_RECENT_SENT_LIMIT` | 最近发送记录保留数量，最小 `1` | `30` |
| `TIEBA_DETAIL_FETCH_LIMIT` | 单次抓取详情的帖子数量上限，最小 `1` | `18` |
| `TIEBA_RANDOM_AVOID_RECENT` | 随机抽帖时避开最近 N 条发送记录 | `30` |
| `TIEBA_PREFER_IMAGE_THREADS` | 随机抽帖时优先选择带图帖子 | `true` |
| `TIEBA_BROWSER_HEADLESS` | 浏览器是否无头模式 | `true` |
| `TIEBA_BROWSER_CHANNEL` | Playwright 浏览器 channel；空值使用默认 Chromium | — |

### MCP 挂载与开关

| 变量 | 说明 |
|------|------|
| `MCP_ARXIV_PAPERS_MOUNT` | arXiv MCP server 论文保存卷挂载，格式 `host-path:container-path`。默认 `arxiv-papers:/root/.arxiv-mcp-server/papers` |

MCP server 的普通字段支持 `${ENV_VAR}` 与 `${ENV_VAR:-default}`；认证字段使用 `${ENV_VAR}` 保存引用，密钥值维护在根 `.env`。

### Web Admin

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEB_ADMIN_PASSWORD` | 管理后台登录口令（必填） | — |
| `WEB_ADMIN_HOST` | 监听地址 | `127.0.0.1` |
| `WEB_ADMIN_PORT` | 监听端口 | `5104` |
| `WEB_ADMIN_SESSION_TTL_HOURS` | session 有效期（小时） | `168` |
| `WEB_ADMIN_SESSION_MAX_AGE_HOURS` | session 绝对寿命（小时），自创建起超过后必须重新登录 | `168` |
| `WEB_ADMIN_COOKIE_SECURE` | 是否下发 Secure cookie：`auto` / `true` / `false` | `auto` |

### Docker 构建相关

| 变量 | 说明 |
|------|------|
| `PIP_INDEX_URL` | pip 安装源（国内镜像加速） |
| `PIP_TRUSTED_HOST` | pip 信任主机 |
| `PLAYWRIGHT_BASE_IMAGE` | Playwright 基础镜像（可含国内代理前缀） |

GHCR 分发镜像和 `prod.example/Dockerfile` 均基于 Playwright Python 镜像构建，并内置 Docker CLI，便于贴吧采集和可选 MCP docker transport 使用。使用 docker transport 时须自行挂载宿主机 Docker socket；默认 compose 保持该 socket 未挂载。

---

## LLM 配置数据库

`data/llm_config.db` 是运行时的配置来源，JSON 是配置交换格式。通过 Web Admin“LLM 配置”或 `python -m quickquip.llm.config_cli` 修改草稿，再单独提交应用；Bot 启动加载已发布快照。`draft_revision`、`published_revision` 与 Bot 回报的 `loaded_revision` 分别表示草稿、发布和实际运行版本。旧 `config/llm.toml` 只作为首次迁移输入及 1.16.1 回退资产保留。完整流程、备份与回退说明见 [LLM 配置管理](llm-configuration.md)。

下文路径对应完整 JSON 文档，认证字段只保存根 `.env` 的变量名或引用。字段范围、枚举和继承能力由 `/ops/api/llm-configuration/metadata` 提供；新增写入拒绝非法值。

### `settings.runtime` — 运行参数

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 全局 LLM 开关（`config/llm.json.example` 中显式设为 `true`） | `false` |
| `memory_enabled` | 全局记忆注入开关 | `true` |
| `default_provider` | 默认 provider ID | — |
| `default_persona` | 默认人格 ID | — |
| `client_cluster` | 可选部署群标识，仅使用可打印 ASCII；由 QuickQuip Profile 投影为品牌请求头，见[请求指纹 Profile](client-fingerprints.md) | `""` |
| `claude_code_device_id` | 可选 Claude Code 设备身份，填写 64hex 字符串；留空使用数据目录中的持久随机身份 | `""` |
| `gemini_cli_install_id` | 可选 Gemini CLI 安装 UUIDv4；留空使用持久随机身份，见[请求指纹 Profile](client-fingerprints.md) | `""` |
| `history_limit` | 兼容字段，解析但不参与窗口计算。默认由会话纪元自动管理；群聊或私聊通过 `/llm context_limit <n>` 设置固定窗口时，保留最新 n 行，上限 1024 条 | `10` |
| `history_max_messages_per_group` | 兼容字段，解析后忽略其值。对话存储按会话纪元锚点裁剪，硬上限 2048 行 | `40` |
| `memory_limit` | 单次调用注入的记忆条数上限 | `6` |
| `memory_max_items_per_group` | 单群存储的记忆条数硬上限 | `200` |
| `max_prompt_chars` | system prompt 最大字符数 | `4000` |
| `tool_calling_enabled` | 是否允许工具调用 | `false` |
| `tool_max_rounds` | 单次工具调用循环最大轮数 | `8` |
| `tool_max_calls_per_round` | 单轮最多执行工具调用数 | `16` |
| `retry_max_attempts` | LLM 请求失败时的最大尝试次数（含首次调用；仅对上游 429/5xx/网络错误生效） | `3` |
| `retry_base_delay` | 重试退避的基础延迟秒数（按指数递增） | `1.0` |
| `retry_jitter` | 重试退避的随机抖动比例（0-1，0 为关闭抖动） | `0.5` |
| `auto_memory_enabled` | 自动记忆抽取全局默认开关 | `false` |
| `auto_memory_prompt` | 自动记忆抽取自定义判定 prompt | `""` |
| `auto_memory_max_tokens` | 自动记忆抽取判定最大输出 token | `256` |
| `epoch_context_tokens` | 会话纪元标尺（标准 CTX）：懒初始化与 `/llm use` 新键的锚点跨度 | `8000` |
| `epoch_cold_idle_seconds` | 冷场缩窗等待时间 T：距该会话／渠道／模型最近一次调用开始或结束超过此秒数，且窗口超过冷场触发水位时缩窗；工具续轮、失败及取消也更新活动时间 | `300` |
| `epoch_cold_target_tokens` | 冷场重置后窗口缩到的 token 估算目标（L_cold） | `4000` |
| `epoch_cold_trigger_tokens` | 冷场重置触发水位：冷场且窗口超过此值才缩（H_cold） | `5000` |
| `epoch_hot_target_tokens` | 触顶重置后窗口缩到的 token 估算目标（L_hot，长话题保护） | `32000` |
| `epoch_cap_tokens` | 窗口硬上限：超过即触发触顶重置（H_hot / cap） | `64000` |
| `recent_context_token_budget` | 【现场】补丁每轮 token 预算：近期消息缓冲服役给 LLM 的上限（从最新往回截） | `800` |
| `recent_context_floor_seconds` | 【现场】滑动保底窗秒数：窗内消息即使已服役过也会重附（增量语义之外的保底） | `300` |
| `request_input_token_budget` | 实际请求输入预算（应用侧估算口径）：按“provider 显式覆盖 > 模型窗口推导（窗口−输出预留）> 本缺省”解析。超限时主链先缩到热水位，无法缩窗时进一步减少历史回放，重组重试一次；仍超限则拒绝发起。工具续轮超限立即中止。可在渠道或模型 `parameters` 覆盖（null 表示继承） | `96000` |
| `agent_record_retention_days` | 已关闭对话轮（Loop）保留天数，按关闭时间计 | `30` |
| `agent_record_max_loops_per_scope` | 每会话已关闭 Loop 数量上限；数量或字节先触顶者触发清理最旧完整 Loop，并推进受影响的活动纪元 | `1000` |
| `agent_record_max_bytes_per_scope` | 每会话 Loop 业务记录字节上限（UTF-8 计量） | `67108864` |
| `agent_replay_loop_tokens` | 整个历史 Loop 回放预算的推导下限（token 估算，512-4194304）：实际预算按“请求输入预算 − 纪元可见窗上限 − system/工具预留 − 当前 Loop 比例预留”推导。可在渠道或模型 `parameters` 中硬覆盖。超限时重建纪元并保留完整历史后缀，目标为预算的 `epoch_hot_target_tokens / epoch_cap_tokens`；最新单个 Loop 仍超限时按既有阶梯精简并冻结表达 | `4096` |
| `agent_delivery_intermediate_enabled` | 中间轮交付的全局默认：开启后工具调用多轮回复中非最终轮的普通正文照常先于工具执行外发；关闭时非最终正文只记录不发送（`suppressed_by_policy`） | `false` |
| `agent_delivery_final_enabled` | 最终轮分段的全局默认：开启后最终正文按自然段拆成多条消息发送；关闭时最终正文整条发送。两域独立；旧迁移输入中的 `agent_delivery_enabled` 按两域同值转换。各群/私聊会话可用 `/llm delivery intermediate/final/all …` 或 Web Admin“群 LLM”按会话覆盖 | `false` |
| `reply_split_threshold_chars` | 回复超过该长度（Unicode code point）才进行自然分段 | `800` |
| `reply_chunk_max_chars` | 单段源文本上限，独立于 OneBot 协议报文长度 | `1200` |
| `reply_send_interval_ms` | 同会话相邻发送开始时间的最小间隔（0-10000） | `800` |
| `reply_max_chunks_per_loop` | 单次对话交付条目上限（含文字、媒体与通知，1-256） | `64` |
| `mention_cooldown_seconds` | 出站“@名字”艾特的同目标冷却秒数：窗内重复艾特同一人降级为纯文本（0 关闭冷却，0-86400） | `600` |

以上 6 个 `epoch_*` 键均可在渠道或模型的 `parameters` 对象内同名覆盖；未覆盖的键继承 `settings.runtime` 值。参数关系需满足 `0 < cold_target < cold_trigger ≤ hot_target < cap` 且 `context_tokens > 0`，新写入的非法组合由校验拒绝。冷场时间决定应用何时缩窗，调整时结合用量页的缓存指标与纪元事件观察。`recent_context_*` 两键仅全局，不支持 provider 覆盖。

### `settings.triggers` — 触发方式

| 键 | 说明 | 默认值 |
|----|------|--------|
| `default_prefix` | 显式触发前缀 | `/ai` |
| `allow_prefix` | 启用前缀触发 | `true` |
| `allow_at` | 启用艾特触发 | `true` |
| `empty_prompt_reply` | 空提示时的默认回复文本 | `请在触发指令或艾特后面补上想说的话。` |

`settings.auto_search` — 自动联网判定：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 是否启用自动联网 | `false` |
| `search_max_calls_per_round` | 单轮最大搜索调用数，范围 1-32 | `3` |

`settings.quick_judge` — 快速判定模型：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `provider_id` | 快速判定专用 provider ID；留空使用默认 provider | `""` |
| `model` | 快速判定专用模型；留空使用 provider 默认模型 | `""` |
| `timeout` | 判定超时秒数 | `2.0` |
| `max_tokens` | 判定最大输出 token | `64` |

快速判定用于 `context_rules` 的 `llm_context`、唤醒模块的相关性/答疑判定等短 prompt 场景。技术失败（超时、provider 异常、空正文、截断、无效 JSON）一律按未触发处理（fail-closed），不会写入 60 秒判定缓存；只有成功解析的业务 true/false 会进缓存。选用带 reasoning 的模型时，reasoning token 计入 `max_tokens` 且延迟更高，需要同时调大 `max_tokens`（如 256）与 `timeout`（如 6 秒），否则会出现“预算被思考耗尽、可见判定为空”与大面积超时。

### `settings.image_preprocessing` — 非视觉模型图片转述

当当前主模型条目的 `vision` 为 `false` 时，运行时先调用指定视觉模型，将图片转成带来源和序号的文本，再交给主模型。视觉主模型直接接收原图，不调用该前置层。

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 启用非视觉模型图片转述 | `false` |
| `provider_id` | 提供视觉识别能力的 provider ID | `""` |
| `model` | 视觉模型 ID；留空使用该 provider 的默认模型 | `""` |
| `max_tokens` | 单张图片转述输出上限，写入范围为 80-2048 | `300` |
| `temperature` | 图片转述温度 | `0.3` |
| `prompt` | 自定义转述 system prompt；留空使用内置提示 | `""` |

单轮最多处理 5 张当前、引用或转发图片。被动唤醒需要近期图片时，会用剩余名额选择最新图片。任一图片转述失败时，本轮不会调用非视觉主模型，用户会收到可重试提示。

### `settings.tools` — 工具调用

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 工具名单。为空 `[]` 时暴露默认白名单及全部 MCP 工具；非空时与 `enabled_mode` 配合使用 | `[]` |
| `enabled_mode` | `enabled` 非空时的作用方式：`append` 在默认白名单 + MCP 工具之上追加（启用 `draw_svg` 等可选内置工具用这个）；`replace` 精确过滤，只暴露所列工具 | `append` |
| `discovery_mode` | 工具发现模式：`off` 全量暴露；`on` 仅暴露常驻工具并通过 `tool_search` 按需加载；`auto` 在可延迟工具数超过阈值后启用 | `auto` |
| `discovery_min_tools` | `auto` 模式下触发工具发现的可延迟工具数量阈值 | `10` |
| `discovery_search_limit` | 单次 `tool_search` 最多返回并加载的工具数 | `5` |
| `discovery_max_loaded_tools` | 新增工具时比较当前已加载总数，常驻工具计入；达到该值后停止新增，已有集合保留 | `12` |
| `always_loaded` | 工具发现开启时直接提供给模型的常驻工具名列表；未配置时回退下表内置默认集 | `["tool_search", "tool_list", "get_identity", "list_memories", "search_web", "activate_skill"]` |

`tool_search` 和 `tool_list` 是本地元工具，不依赖 Claude 原生 tool search。接入大量 MCP 工具时，模型会先用 `tool_search` 搜索相关能力；搜索不到时可用 `tool_list` 列出工具组、工具名或按精确工具名加载工具，下一轮再调用被加载的真实工具。

专题配置和排障建议见 [tool-discovery.md](tool-discovery.md)。

**`enabled_mode` 升级说明（v1.11 → v1.12）**：v1.11 及更早版本中，`enabled` 非空表示精确白名单，未列入名单的默认工具与 MCP 工具都会被过滤。自 v1.12 起，`enabled` 非空时默认按 `append` 追加语义处理。各场景影响：

- `enabled = []`（默认）：行为完全不变，仍暴露默认白名单加全部 MCP 工具。
- 用 `enabled` 启用可选内置工具（如 `draw_svg`）：MCP 工具不再被名单误过滤，通常无需改动。
- 需要严格工具白名单的部署：显式设置 `enabled_mode = "replace"`，恢复精确过滤语义。

### `providers` — Provider 定义（可多个）

`providers` 是有序渠道数组。协议、地址、身份和认证字段在渠道层维护；请求参数保存在渠道 `parameters` 中，模型 `parameters` 可覆盖全部同名请求参数。优先级为调用／会话覆盖 → 模型 → 渠道 → 具有覆盖职责的全局设置 → 内置默认；null 继承，空字符串、空对象、false 与合法零值均为显式值。`extra_body` 整体替换对象。

渠道固定字段位于 `providers[]` 对象：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `id` | Provider 唯一标识（如 `openai-main`、`gemini-main`） | — |
| `protocol` | 协议类型：`openai` / `claude` / `gemini` / `openai_responses` | — |
| `base_url` | API 中转地址 | — |
| `api_key_env` | API key 所在环境变量名 | — |
| `default_model` | 默认模型 ID | — |
| `models` | 有序模型对象数组：`model`、`enabled`、`vision`、`context_window`、`parameters` | `[]` |
| `enabled` | 暂时禁用该 provider：不进 `/llm providers`/`models` 列表、不参与探活、级联候选跳过、`/llm use` 拒绝；provider 保留在配置中，改回 `true` 即恢复 | `true` |
| `aliases` | 有序别名对象数组，如 `[{"alias":"gpt4","model":"gpt-5.4"}]` | `[]` |
| `headers` | 注入到每次请求的额外 HTTP 头 | — |
| `client_fingerprint` | 渠道固定字段，选择请求指纹 Profile；见[请求指纹 Profile](client-fingerprints.md) | `default` |
| `fallback_urls` | 备用 base URL 列表，主地址 5xx/网络错误时自动切换 | `[]` |
| `proxy` | HTTP(S) 代理地址（如 `http://127.0.0.1:7890`），所有请求均走代理，含 fallback 重试 | — |
| `auth_method` | 认证方式：`api_key` 或 `bearer`。Claude 分别使用 `x-api-key` / `Authorization: Bearer`；Gemini 的 API Key 传输由 Profile 决定：新默认使用 `x-goog-api-key`，legacy-gemini 使用 `?key=`；显式 bearer 使用 `Authorization: Bearer`；OpenAI 使用 Bearer | `api_key` |
| `parameters` | 渠道请求参数对象；模型的同名对象可覆盖参数 | `{}` |

模型对象位于 `models[]`：`model` 为实际请求模型名，`enabled` 控制可用性，`vision` 声明图片能力（缺省 true），`context_window` 声明容量，`parameters` 保存模型请求参数覆盖。别名对象与模型清单均在渠道层维护。

以下请求参数位于渠道或模型的 `parameters` 对象：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `timeout_seconds` | 请求超时（秒） | `45` |
| `temperature` | 温度参数 | `0.8` |
| `max_output_tokens` | 最大输出 token 数 | `800` |
| `style_overrides` | 可选，多行字符串，追加到每次调用的 system prompt 末尾 | — |
| `style_profile` | 可选，引用 `style_profiles` 中预定义的共享 system prompt 段，与 `style_overrides` 拼接 | — |
| `stream_enabled` | 是否启用 SSE 流式响应 | `true` |
| `user_agent` | 自定义 User-Agent 请求头 | — |
| `extra_body` | 注入到每次请求体的额外 JSON 对象，模型覆盖时整体替换 | — |
| `prompt_caching` | 启用 Anthropic Prompt Caching（仅 `claude` 协议生效，需中转站支持 CLI 格式） | `false` |
| `cache_ttl` | Claude prompt cache TTL：空值默认 5min，`"1h"` 使用扩展缓存（仅 `claude` 协议生效） | `""` |
| `builtin_search` | 声明 provider 原生搜索工具（仅 `gemini` 协议生效）：请求携带 `google_search` 服务端检索声明，回复末尾自动附上 grounding 来源；开启后该 provider 的会话移除 `search_web` 工具，提示词引导同步切换。其他协议下该键不生效（配置加载时记录 warning）。检索在 provider 侧执行并计费，本地轮次上限与 token 看板不覆盖 grounding 调用本身。注意：`google_search` 与 function calling 在同一请求中组合仅 Gemini 3 系列模型支持；2.x 模型需关闭该 provider 的 `builtin_search` 或全局 `tool_calling_enabled`，否则聊天请求会被 API 拒绝 | `false` |
| `responses_profile` | `openai_responses` 协议专属：后端能力位。`openai-public`（官方 `/v1/responses`）或 `codex-http-relay`（Codex 形态中转，不发 `service_tier`、容忍 `codex.*` 结构事件、终态缺省字段时以流式完整 item 为回放基准） | `openai-public` |
| `reasoning_effort` | 思考档位（全协议生效）：`low` / `medium` / `high` / `xhigh` / `max` / `ultra`，留空不发送思考参数（模型默认档）。到 wire 参数的翻译按协议与后端能力自动完成，超档自动钳制（详见下文“思考档位跨协议映射”）。群内可用 `/llm effort <档>` 按群覆盖本配置（`/llm effort default` 恢复跟随；`/llm status` 与 `/llm effort status` 展示配置档 / 覆盖档 / 生效档三层口径）；Web Admin“LLM 配置”页提供渠道及模型的结构化参数编辑，“群 LLM”页提供按群三态覆盖 | `""` |

> **会话纪元覆盖**：`settings.runtime` 的 6 个 `epoch_*` 键可在本表同名覆盖（如 `epoch_cold_idle_seconds = 21600` 放宽 DeepSeek 的冷场判定），未覆盖的键继承全局缺省；详见 `settings.runtime` 段说明。

> **预算与模型容量覆盖**：`request_input_token_budget` 与 `agent_replay_loop_tokens` 可在渠道或模型 `parameters` 中覆盖。每个模型的 `context_window` 声明上下文容量，null 时按现有模型家族注册表自动解析；未命中时标为容量未知。有效参数接口同时返回配置值、最终值及来源。


#### 渠道与模型的 JSON 层级

以下为结构片段；编辑完整导出文件时更新对应渠道，保留其他渠道及被引用的模型。固定连接字段位于渠道对象，模型温度覆盖位于该模型的 `parameters`：

```json
{
  "providers": [
    {
      "id": "openai-main",
      "protocol": "openai",
      "base_url": "https://your-openai-relay.example/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-5.4",
      "client_fingerprint": "default",
      "parameters": {"temperature": 0.8, "max_output_tokens": 2048},
      "models": [
        {"model": "gpt-5.4", "parameters": {"temperature": 0.5}}
      ]
    }
  ]
}
```

#### 思考档位跨协议映射

`reasoning_effort` 的内部六档到各协议 wire 参数的映射与钳制如下（`ultra` 为 Codex 订阅产品层档位，公开 API 词表止于 `max`，一切渠道自动降 `max`）：

| 内部档 | openai chat（顶层 `reasoning_effort`） | claude 4.7+（adaptive `output_config.effort`） | claude 4.6（Opus/Sonnet） | claude ≤4.5（旧式 `budget_tokens`） | gemini 3.x（`thinkingLevel`） | gemini 2.5（`thinkingBudget`） |
|---|---|---|---|---|---|---|
| `low` | low | low | low | 1024 | LOW | 1000 |
| `medium` | medium | medium | medium | 2000 | MEDIUM | 2000 |
| `high` | high | high | high | 8000 | HIGH | 8000 |
| `xhigh` | xhigh | xhigh | high（钳制） | 16000 | HIGH | 16000 |
| `max` | max | max | max | 32000 | HIGH | 32000 |
| `ultra` | max | max | max | 32000 | HIGH | 32000 |

openai chat 渠道再按模型家族钳制：DeepSeek / GLM-5.3 / Kimi k3 三档系（`medium`→`high`、`xhigh`→`high`、`max`/`ultra`→`max`，DeepSeek 附带 `thinking.type=enabled` 开关）；MiniMax 五档全集；xAI 止于 `xhigh`；其余后端透传。claude 旧式 budget 固定值表须满足 budget ≥1024 且小于 `max_output_tokens`；`max_output_tokens` 过小使预算跌破 1024 时该请求不发送思考参数并记 warning，这是归一化层唯一的不发送场景，其余组合一律按表照发。claude 思考开启时上游只接受默认温度：非默认 `temperature` 不下发并记日志。gemini 2.5 Flash 系的 `thinkingBudget` 上限 24576（Pro 系 32768），超出自动钳制。`openai_responses` 协议按 profile 词表降档：`openai-public` 已核对范围到 `xhigh`，`codex-http-relay` 五档恒等（`ultra` 降 `max`，2026-10 实测中转网关校验层拒绝 `ultra`）。

#### 各协议思考参数支持面

QuickQuip 按上表转换思考档位，Claude 旧式预算须满足 1024 的下限；其他组合会把转换后的参数提交给后端。后端不支持某档位时上游返回 400 等 4xx 错误，即为不支持的信号。群内用 `/llm effort default` 清除会话覆盖并恢复跟随 provider 配置；provider 配置档也不受支持时，清除该 provider 的 `reasoning_effort` ，保存草稿并应用，让模型使用自身默认档。以下为 2026-10 调研的各后端支持面结论，供排障参考：

- **claude 协议**：Anthropic 官方 extended thinking 自 3.7 代际引入，3.5 及更早代际无思考能力（照发旧式 budget 形态会被上游拒绝）；4.7+/5 系只接受 `adaptive + effort`，旧式 `type:"enabled"` 直接 400。
- **claude 兼容端点**：Kimi（k3，思考词表 low/high/max）、MiMo（m2.5）、GLM Coding Plan 等均提供面向 Claude Code 类客户端的 Anthropic 形态端点，对 `adaptive + effort` 形态有实测旁证（端点把 Claude Code 的 effort 标签映射到自家思考档位）。照发意味着同时适用 Anthropic 温度契约：档位生效期间非默认 `temperature` 不下发，上游若实际忽略思考参数，温度配置也会随之不生效。个别端点对历史回放中的 thinking 内容块有特殊要求，QuickQuip 的历史回放分三层：无工具调用的对话轮与一切降级路径（owner 失配、敏感命中、预算精简、档案投影）为纯文本，不带 thinking；带工具调用的已关闭 Loop 在 owner 五元组匹配且结构有效时走原生回放，跨轮携带 thinking 内容（claude 签名块 / gemini thought parts / responses reasoning 密文）。对 claude 兼容端点的实际避坑机制是签名有效性闸门：无签名的 thinking 块自动降级为纯文本档案。注意 claude 协议暂无 openai_responses 式的“上游 400 时剥历史推理降级重试”兜底，返回签名块却拒绝历史 thinking 的端点存在暴露面。
- **gemini 协议**：`thinkingLevel` 为 3.x 形态；2.x 只认 `thinkingBudget`，其中 2.0 系无思考参数支持（照发会被上游拒绝）；level 与 budget 不可同传。
- **openai chat**：`reasoning_effort` 词表按家族见上表；词表外档位被上游忽略或拒绝，表现以后端为准。
- **openai_responses**：profile 词表即支持面（降档口径见上节）。

> **内联媒体预算**：`max_inline_media_bytes`（渠道或模型 `parameters` 中的键，缺省 `5242880`，`0` 表示不限）限制单次请求全部内联图片的解码字节总量，用户消息与各批工具结果共享预算和内容去重。发送前 GIF 自动取首帧转静态 PNG。超出单图上限或请求额度的图片先自动降采样重编码为 JPEG 压入剩余额度（原始尺寸优先、长边阶梯递减；额度低于 96KB 时不再压缩）；压缩后仍装不下的第一张图片及其后低优先级图片全部跳过并记录日志。优先保留最新用户消息中的图片（当前 → 引用 → 近期），再按新到旧处理工具结果与历史用户图片。每次请求组装独立计算预算，协议中的消息与工具结果顺序保持完整。该预算同时决定请求体上限（图片 base64 膨胀约 4/3，缺省值对应最坏约 6.7MiB 请求体）；上游网关按更紧的请求体或 token 口径风控（部分网关把图片 base64 按文本估算 token）的部署应显式配置更小的值。

> **协议适配说明**：内置 `default` 的 Chat、Responses、Anthropic 和 Gemini 分别使用 OpenCode 2、轻量 Codex、Claude Code 和 Gemini CLI 策略；`legacy-claude` 与 `legacy-gemini` 提供通用行为回退。Profile 的版本、UA、Header 和 Body 特征由随包 TOML 定义，本地同名模板整份覆盖，修改后重启 Bot 与 Web。附加头按大小写无关覆盖，`user_agent` 参数优先级最高；自动 Session 与 Body 结构字段受到覆盖保护。`quickquip` Profile 使用自有品牌，四个专有头由该 Profile 管理；全局 `settings.runtime.client_cluster` 可配置部署群标识，`settings.runtime.claude_code_device_id` 可填写 CC 设备身份。详情见[请求指纹 Profile](client-fingerprints.md)。

> **Gemini 工具回放说明**：`gemini` 协议会把模型返回的有序 `parts` 作为 provider opaque data 保留，并在工具结果回送时原样恢复 `thoughtSignature`。并行 `functionCall` 与 `functionResponse` 必须保持完整批次；超过单轮工具上限时本轮 fail-closed，不向 Gemini 发送截断历史。工具结果图片放在完整 `functionResponse` 批次之后的独立 user turn。连接只接受 Bearer token 的原生 Gemini 网关时设置 `auth_method = "bearer"`，避免凭据进入 URL 和代理访问日志。

> **Responses 协议说明**（1.16 起）：`openai_responses` 协议采用 `store:false` 手动上下文管理，每轮全量回放 input items；reasoning 模型的当前工具循环会把 reasoning 密文与原生 output items（保序）原样回传，保证官方端点的连续工具调用可续接；工具批次超出单轮执行限额时整批拒绝（与 Gemini 同款 fail-closed）。跨轮 reasoning 密文回放已启用：owner 身份维度为 provider / 协议 / 模型 / profile / 端点（不含档位），同一 owner 的会话保留完整推理连续性，历史工具循环按原生形态回放；切换档位时新旧密文混档共存、回放估算按各密文生成档位逐条计量，切换其余维度自动降级为通用投影（工具事实保留），历史损坏或预算不足时按精简阶梯处理，上游拒绝历史形状时自动去除历史推理重试一次。部分思考系模型只接受默认温度，如遇请求被拒可把该 provider 的 `temperature` 调回 `1.0`。

### `style_profiles` — 共享风格段

定义可被多个 provider 复用的 system prompt 风格段（多行字符串），provider 通过 `style_profile` 键引用：

```json
{
  "style_profiles": {
    "my_family": "……风格条目……\n"
  },
  "providers": [
    {
      "id": "my-provider",
      "parameters": {
        "style_profile": "my_family",
        "style_overrides": "……"
      }
    }
  ]
}
```

- 拼接顺序：`style_profile` 段在前，`style_overrides` 追加在后，整体附加到每次调用的 system prompt 末尾。
- 家族内容为空串是合法形态：声明家族占位、不注入任何内容，引用方等价于无风格附加块（例如为后续调校预留条目）。
- 引用未定义的 `style_profile` 会导致保存失败并返回依赖冲突；删除被引用的风格前应处理引用。
- 内置示例四家族（`openai_family` / `gemini_family` / `claude_family` / `general`）随 `config/llm.json.example` 分发，按模型谱系对位命名，可直接复用或改写。

### `pricing` — 模型定价（成本统计）

per-MTok（每百万 token，USD）定价表，是 Web Admin LLM 用量页成本统计（`cost_usd`）的价格来源。下例使用示意单价，假设 `deepseek` 与 `my-provider` 是两个已配置渠道，均提供 `deepseek-chat`；请按实际渠道 ID 和请求模型名修改完整导出文件的 `pricing` 数组：

```json
{
  "pricing": [
    {
      "provider_id": "deepseek",
      "model": "deepseek-chat",
      "input_per_mtok": 0.14,
      "output_per_mtok": 0.28,
      "cache_read_per_mtok": 0.003
    },
    {
      "provider_id": "my-provider",
      "model": "deepseek-chat",
      "input_per_mtok": 0.2,
      "output_per_mtok": 0.4
    }
  ]
}
```

| 键 | 说明 |
|----|------|
| `provider_id` | 已存在的渠道 ID，须为非空字符串 |
| `model` | 该渠道实际请求发出的模型 ID，同名模型在各渠道单独定价 |
| `input_per_mtok` | 输入价（USD/百万 token） |
| `output_per_mtok` | 输出价（USD/百万 token） |
| `cache_read_per_mtok` | 缓存读价；模型无该缓存机制时省略，计算时回退 input 价 |
| `cache_write_per_mtok` | 缓存写价；同上，无缓存溢价时省略 |

价格按 `(provider_id, model)` 唯一匹配，模型名取本次请求实际发送的值；上游响应中改写的模型名不影响定价。免费模型填写零价格；缺少匹配记录时标记“未定价”，成本暂计为 0。同名模型在不同渠道分别配置，第三方渠道按实际计费填写 USD 单价。缓存价格为 null 或省略时回退输入价。

JSON 交换格式当前为整数 `format_version: 2`。导入旧格式 1 时，后端将可明确归属的全渠道价格转换到渠道，并在预览中列出归属和移除结果；导入前核对报告，保存草稿后单独应用。升级与导入规则见 [LLM 配置管理](llm-configuration.md#模型参数与引用)。

### `settings.skills` — Skill 系统

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | Skill 系统总开关 | `true` |
| `catalog_dir` | Skill 目录；留空 = 项目根 `skills/`，相对路径按项目根解析 | `""` |
| `catalog_max_bytes` | 系统提示中 Skill 清单的字节预算上限，实际预算取 min(模型上下文窗口 2%, 此值) | `8192` |
| `resource_max_bytes` | `read_skill_resource` 单次读取上限（字节） | `65536` |
| `search_max_results` | `search_skill_resources` 命中条数上限 | `50` |
| `search_max_output_bytes` | `search_skill_resources` 输出字节上限 | `32768` |
| `script_timeout_ms` | `run_skill_script` 默认超时（毫秒）；单次调用可另行指定，硬上限 120000 | `30000` |
| `script_max_output_bytes` | 脚本 stdout/stderr 各自的输出字节上限，超限截断 | `65536` |

新写入的非法取值由字段校验拒绝，并返回字段路径及约束。`skills/` 为空目录或不存在时工具不注册、系统提示不变。部署方式、目录约定与安全模型见 [skills.md](skills.md)。

### `settings.mcp` — MCP 总开关

| 键 | 说明 |
|----|------|
| `enabled` | 是否启用 MCP |

### `settings.mcp.servers` — MCP Server 定义（可多个）

| 键 | 说明 |
|----|------|
| `id` | Server 唯一标识 |
| `transport` | 传输方式：`stdio` / `docker` / `http` / `sse` |
| `enabled` | 是否启用该 server，默认 `true` |
| `timeout_seconds` | 连接/请求超时秒数，默认 `30` |
| `url` | 服务端点 URL（`transport = "http"` / `"sse"` 时必填） |
| `headers` | 注入请求的 HTTP 头，值支持 `${ENV_VAR}` / `${ENV_VAR:-default}` |
| `tool_prefix` | 自定义该 server 生成工具名的前缀；留空时按 server id 生成 |
| `protocol_version` | `legacy` 协商时 initialize 握手使用的协议版本 pin，默认 `"2025-03-26"` |
| `negotiation` | 协议协商模式（仅 `http` transport 生效）：`legacy`（默认）/ `auto` / `modern` |
| `supported_protocol_versions` | `auto` / `modern` 协商时客户端声明的可接受版本列表（这两种模式必填） |
| `image` | Docker 镜像（`transport = "docker"` 时） |
| `command` | 启动命令（`transport = "stdio"` 时） |
| `args` | 命令参数（`transport = "stdio"` 时） |
| `cwd` | `stdio` 子进程工作目录；留空使用默认 |
| `env` | 环境变量键值对，值支持 `${ENV_VAR}` / `${ENV_VAR:-default}` |
| `mounts` | 卷挂载列表，格式 `host:container` 或 `host:container:ro` |
| `docker_args` | 额外 Docker 运行参数 |
| `docker_command` | docker transport 调用的 Docker 命令 | `docker` |
| `pull_policy` | 镜像拉取策略：`always` / `missing` / `never` | `missing` |
| `network` | 容器网络（如 `host`）；留空使用默认 | — |
| `container_workdir` | 容器工作目录；留空使用镜像默认 | — |
| `include_tools` | 该 server 暴露的工具白名单，支持 MCP 原始工具名或 QuickQuip 生成后的工具名 |
| `exclude_tools` | 该 server 排除的工具列表，支持 MCP 原始工具名或 QuickQuip 生成后的工具名 |
| `allowed_tools` | 兼容旧配置的白名单字段，新配置建议使用 `include_tools` |

`include_tools` 为空时默认接入该 MCP server 暴露的全部工具；`exclude_tools` 会在白名单之后生效。接入 GitHub MCP 这类大工具集时，生产环境建议优先使用 `include_tools` 收窄到读类工具，再交给 `tool_search` / `tool_list` 做按需加载。

### `settings.daily_briefing` — 每日播报

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关（`true` / `false`） |
| `morning_cron` | 早报 cron 表达式 |
| `noon_cron` | 午报 cron 表达式 |
| `evening_cron` | 晚报 cron 表达式 |
| `min_messages_for_llm` | 触发 LLM 的最小消息数 |
| `active_users_limit` | 活跃用户数量上限 |
| `hot_words_limit` | 热词数量上限 |
| `sample_messages_limit` | 消息样本数量上限 |
| `max_context_chars` | 送给模型的上下文字符上限 |
| `max_output_chars` | 最大输出字符数 |
| `routes.daily_briefing` | 独立的模型级联候选列表（失败自动降级） |

`routes.<报告类型>` 候选会按顺序尝试；如果某个模型提前截断或以非正常 finish reason 结束，会继续尝试下一项（不完整的正文一律不放行）。聊天记录容量与输出上限按**每跳模型自己的上下文窗口**逐跳推导（容量未知回退保守缺省）；输出上限缺省请求：日报 16384、简报与周/月报 8192，输出配额低于该值的模型会在该跳直接报错——级联模型需能接受相应输出上限。所有级联引用在保存时均检查存在性，包括关闭的功能。JSON 候选使用 `{"provider_id":"渠道","model":"wire 模型名"}`，`@default` 保持运行时动态解析。

### `settings.daily_summary` — 每日总结

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关（`true` / `false`） |
| `generate_cron` | 生成 cron 表达式 |
| `publish_cron` | 发布 cron 表达式 |
| `min_messages` | 最小消息数（不足时跳过） |
| `summary_length_hint` | 目标字数 |
| `routes.daily_summary` | 独立的有序模型候选列表（失败自动降级） |

### `settings.weekly_report` / `settings.monthly_report` — 群周报 / 群月报

每周一（周报）／每月 1 日（月报）自动生成上一周期的群聊回顾。数据源为聊天记录归档 `data/chat_archive.db`，持续采集全部群的消息，应用不自动清理历史。

周报将全周期记录按天分节，合并同分钟连发、折叠复读并缩短 URL，再交给模型生成。月报按自然周分配字符预算：周内先完整保留记录较少的平静日，再按消息数量从多到少处理高活跃日；能放入剩余额度时完整保留，放不下时等距抽样，额度耗尽时跳过剩余日期。默认终稿输入预算约 24 万字符。周报、月报与 `settings.daily_summary` 相互独立，可单独开启。

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关（`true` / `false`，默认 `false`） |
| `generate_cron` | 生成 cron（周报默认 `0 9 * * 1` 每周一；月报默认 `0 9 1 * *` 每月 1 日） |
| `publish_cron` | 发布 cron（默认 `0 10 * * *` 每天 10:00；周报/月报共用，每日发布新报告并补发未发布的） |
| `min_messages` | 周期内最小消息数（不足时跳过；周报默认 100，月报默认 300） |
| `length_hint` | 目标字数（周报默认 2000，月报默认 2500） |
| `input_char_budget` | 月报终稿聊天记录字符预算（默认 240000，最小 8000；按自然周分配，周内先保留平静日，再处理高活跃日） |
| `routes.weekly_report` / `routes.monthly_report` | 独立的有序模型候选列表，支持 `@default` |

> 周报/月报通过 `/summary weekly|monthly on|off|status|now` 在群内按群开启。period 标识：周报为 ISO 周号（如 `2026-W24`），月报为年月（如 `2026-06`）。

---

## config/generation.toml

此文件负责图片、语音、音乐、ASR 和 SVG 的独立配置。首次迁移会将旧 TOML 中的内联多模态段提取到这里；已存在的独立文件保留其权威性。文件缺失时各能力使用关闭状态的默认配置。

图片、语音和音乐的 `prompt_blocklist` 是生成业务专属限制。配置了`config/sensitive_words.toml` 时，生成 prompt、标题、歌词和引用文本还会经过部署级统一敏感词过滤。该检查只处理文本，不审核输入或输出的图片像素、音频波形和音乐成品。

### `[image]` — 图片生成

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关 |
| `default_model` | 默认模型名 |
| `prompt_blocklist` | 提示词黑名单（数组） |

### `[[image.providers]]` — 图片 provider（可多个）

| 键 | 说明 |
|----|------|
| `id` | Provider ID |
| `protocol` | 协议类型 |
| `base_url` | API 地址 |
| `api_key_env` | API key 环境变量名 |
| `timeout_seconds` | 超时（秒） |

每个 provider 下用 `[[image.providers.models]]` 定义模型：

| 键 | 说明 |
|----|------|
| `id` | 模型唯一标识，用于 `default_model` 引用和 `/draw <id>` 选模型 |
| `label` | 可选展示名 |
| `model` | 调用 API 时传入的模型 ID |
| `size` | 图片尺寸（`openai_images` / `gemini_imagen` 如 `1024x1024`；`minimax_images` 填宽高比） |
| `quality` | 质量档（`openai_images` 协议下有效，如 `standard` / `hd`） |
| `response_format` | 返回格式（`openai_images` 协议下有效：`b64_json` 默认 / `url`） |

### `[audio]` — 语音生成

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关 |
| `default_model` | 默认模型名 |
| `prompt_blocklist` | 文本黑名单 |

`[[audio.providers]]` 和 `[[audio.providers.models]]` 结构类似图片，model 额外包含 `voice_id`、`sample_rate`、`bitrate`、`format`、`channel`、`speed`、`vol`、`pitch`、`emotion`、`output_format`、`extra_body` 等语音特有字段。

当前支持的 provider protocol：

| protocol | 说明 |
|----------|------|
| `minimax_t2a_http` | MiniMax 同步 TTS，响应体含 hex 编码音频 |
| `minimax_t2a_async` | MiniMax 异步 TTS，创建任务→轮询→取文件 |
| `openai_tts` | OpenAI TTS 兼容协议（`POST /audio/speech`），响应体为音频 bytes。覆盖 edge-tts / GPT-SoVITS / piper 等本地服务的 OpenAI 兼容包装。`api_key_env` 可省略（本地无鉴权时不附加 Authorization 头） |
| `http_tts` | 原始 HTTP POST，请求体字段从 model 的 `extra_body` 模板派生，支持 `{text}` / `{voice}` 占位符替换，适配非 OpenAI 格式的本地服务。以下划线开头的键（`__path` 请求路径、`__method` HTTP 方法）是内部控制字段，不进入请求体 |

`openai_tts` / `http_tts` 的完整配置示例见 `config/generation.toml.example`。

### `[asr]` — 语音识别

ASR 用于把 OneBot V11 `record` 语音消息转写为文字，并注入 LLM 上下文。协议端若已在消息段中提供 `text` / `transcript` / `transcription` 字段，QuickQuip 会优先使用该文本；否则通过 OneBot `get_record` 获取音频文件，再调用 ASR provider。

转写文本进入普通 LLM 请求前会经过统一敏感词过滤；原始音频需要先发送给 ASR provider 才能得到可扫描文本。

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关 |
| `default_model` | 默认 ASR 模型 ID |
| `max_audio_bytes` | 单条语音最大字节数，超过后跳过转写 |

当前支持的 provider protocol：

| protocol | 说明 |
|----------|------|
| `openai_transcriptions` | OpenAI-compatible `POST /audio/transcriptions`，使用 multipart/form-data 上传音频 |

`[[asr.providers]]` 字段：

| 键 | 说明 |
|----|------|
| `id` | Provider ID |
| `protocol` | 协议类型，当前为 `openai_transcriptions` |
| `base_url` | API 地址，如 `https://api.openai.com/v1` |
| `api_key_env` | API key 环境变量名 |
| `timeout_seconds` | 超时（秒） |

每个 provider 下用 `[[asr.providers.models]]` 定义模型：

| 键 | 说明 |
|----|------|
| `id` | 模型唯一 ID，用于 `default_model` 引用 |
| `label` | 展示名 |
| `model` | 上游模型 ID |
| `language` | 可选语言提示，如 `zh` |
| `prompt` | 可选上下文提示 |
| `response_format` | 返回格式，支持 `json` / `text` |

### `[music]` — 音乐生成

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关 |
| `default_model` | 默认模型名 |
| `prompt_blocklist` | 文本黑名单 |

`[[music.providers]]` 和 `[[music.providers.models]]` 结构类似，model 额外包含 `format`、`output_format`、`add_watermark`、`lyrics_optimizer` 等音乐特有字段。

`api_key_env` 由每个 provider 自行声明；示例配置中常见的键名包括 `MINIMAX_API_KEY`、`VOLCENGINE_API_KEY` 和 OpenAI-compatible ASR 使用的 `OPENAI_API_KEY`。

### `[svg]` — SVG 画图（`draw_svg` 工具）

LLM 对话中自主调用 `draw_svg` 工具：模型在工具参数中直接写出 SVG 源码，本地 resvg 渲染成 PNG 随回复外发。不需要配置 provider/model（SVG 代码由当前群的对话模型生成），渲染字体沿用 `data/fonts/NotoSansSC-Regular.ttf`（与词云同源）。启用需两步：本段 `enabled = true`，且 `settings.tools.enabled` 中加入 `"draw_svg"`。

| 键 | 默认 | 说明 |
|----|------|------|
| `enabled` | `false` | 功能总开关 |
| `harden` | `true` | 第一层安全（默认启用）：输入硬约束（64KB / 嵌套 ≤2000 / viewBox ≤2048 / 滤镜参数上限）、静态清洗（剥 script、事件属性、外链）、输出尺寸服务端覆盖、渲染子进程 rlimit（地址空间 2GB / CPU 5s）。关闭即自担风险：恶意 SVG 可耗尽内存或 CPU |
| `content_judge` | `false` | 第二层安全（默认关闭）：渲染前用 `settings.quick_judge` 的廉价模型对图片可见文本做内容安全裁决。判定失败（超时 / 非 JSON / 未配置）时放行渲染并记录 WARN（fail-open） |

渲染始终在独立子进程内执行（结构性防段错误，不受 `harden` 开关影响）；渲染限流为全局 10 次/分钟、单用户 2 次/分钟，单次回复最多外发 3 张图片。

平台能力差异：`harden` 的子进程资源硬限制（地址空间 2GB / CPU 5s）依赖 POSIX `rlimit`，在 Linux 等 POSIX 平台生效；Windows 无对应机制，保留 8 秒墙钟超时兜底（超时即终止子进程）。输入清洗、输出尺寸覆盖与渲染限流在所有平台一致。字体与部署注意事项见 [deployment.md](deployment.md#42-cjk-字体文件词云与-svg-画图)。

---

## config/awakening.toml

唤醒模块默认关闭，复制 `config/awakening.toml.example` 为 `config/awakening.toml` 后按需启用。配置支持全局默认值和按群覆盖。

### `[awakening.defaults]`

| 键 | 说明 | 默认值 |
|----|------|--------|
| `extend_duration` | 显式触发 AI 后继续回应同一用户的秒数；`0` 关闭 | `0` |
| `fallback_probability` | 普通消息低概率触发回应的概率；`0` 关闭 | `0` |
| `boredom_silence_seconds` | 群聊沉寂多少秒后允许无聊唤醒；`0` 关闭 | `0` |
| `boredom_probability` | 无聊检查命中时发送冒泡消息的概率 | `0` |
| `boredom_scan_interval` | 无聊唤醒定时扫描周期秒数；未设置时回退 `boredom_check_interval` | `300` |
| `boredom_check_interval` | 群级无聊唤醒成功后的冷却秒数 | `300` |
| `boredom_dnd_start` | 免打扰开始时间，格式 `HH:MM`，空值关闭 | `""` |
| `boredom_dnd_end` | 免打扰结束时间，格式 `HH:MM`，空值关闭 | `""` |
| `interest_topics` | 兴趣话题关键词列表，命中后触发 `awakening_interest` | `[]` |
| `relevance_threshold` | 相关性唤醒判定阈值，`<= 0` 或 `>= 1` 关闭 LLM 判定 | `1.0` |
| `qa_threshold` | 答疑唤醒判定阈值，`<= 0` 或 `>= 1` 关闭 LLM 判定 | `1.0` |

`extend_duration` 只会在群友通过前缀或艾特等显式 LLM 入口触发后生效。兴趣、兜底、无聊、相关性和答疑唤醒不会打开延长窗口；延长窗口内的图片-only、CQ-only、短语气词和过短无实义文本也会被忽略。

无聊唤醒的扫描与冷却分离：`boredom_scan_interval` 只控制定时扫描周期（修改后经 Web Admin 保存或 `awakening_reload` 自动生效，无需重启）；`boredom_check_interval` 是群级成功唤醒后的冷却。进程启动后未观察到某群消息时该群沉寂状态未知，不会触发无聊唤醒；群取消无聊唤醒 opt-in 后其沉寂与冷却状态立即清除。

被动唤醒会携带群内近期历史图片（延长、兴趣、相关性、答疑和无聊唤醒注入，兜底唤醒不注入）。

### `[[awakening.group_overrides]]`

按群覆盖任意默认值：

```toml
[[awakening.group_overrides]]
group_id = "123456"
extend_duration = 10
interest_topics = ["编程", "Python"]
relevance_threshold = 0.5
qa_threshold = 0.88
```

`interest_topics` 还可写在 persona TOML 的扩展字段中：

```toml
[awakening]
interest_topics = ["角色相关关键词"]
```

### 群内管理

`/awakening status` 会展示本群六类唤醒规则的规则开关状态和已解析配置。`/awakening on <rule>` 与 `/awakening off <rule>` 复用规则开关系统；无聊唤醒还需要 `/awakening boredom on` 将本群加入 `data/awakening_boredom_groups.json`。

---

## config/sensitive_words.toml

敏感词过滤器默认在词表缺失或为空时静默放行。复制 `config/sensitive_words.toml.example` 为 `config/sensitive_words.toml` 后，按部署环境填充 block/soft 两级词表。

| 区段 | 行为 |
|------|------|
| `[block.<category>]` | 命中后阻断 LLM 输入、替换 LLM 输出，或在工具调用链路拒绝执行/替换结果 |
| `[soft.<category>]` | 只记录日志，不阻断请求 |

每个类别使用 `words = ["..."]` 定义词表。命中日志只记录类别与哈希，不记录原文。完整接入点和运维建议见 [sensitive-filter.md](sensitive-filter.md)。

---

## config/chat_rules.toml

### `[rate_limit_rules]` — 限流桶定义

每个限流桶一个键值对：

```toml
[rate_limit_rules]
my_rule = { global_limit = 6, user_limit = 3 }
my_global_rule = { global_limit = 3, user_limit = 1, scope = "global" }
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `global_limit` | 每分钟全局上限 | — |
| `user_limit` | 每分钟单用户上限 | — |
| `scope` | `"group"`（按群分桶）或 `"global"`（全群合并） | `"group"` |
| `window` | 滑动窗口秒数 | `60` |
| `probability` | 桶级触发概率 `[0, 1]`，命中后先掷骰再进桶（见[自动回复概率](#自动回复概率)） | `1` |
| `suppress_after_hit` | 防连发：同一规则同一群命中后，接下来 N 次命中强制沉默 | `0`（关闭） |
| `pity_step` | 保底步进：`p_eff = p × (1 + 连哑数 × 步进)`，连哑越多概率越高 | `0`（关闭） |

### `[[rules]]` — 回复规则（可多个）

```toml
[[rules]]
name           = 'my_rule'
patterns       = ['正则表达式']
reply_template = '回复模板'
rate_limit_key = 'my_rule'
priority       = 50
```

| 字段 | 说明 |
|------|------|
| `name` | 规则唯一名称 |
| `patterns` | 触发正则数组（支持多条） |
| `reply_template` | 回复模板（与 `reply_templates` 互斥） |
| `rate_limit_key` | 使用的限流桶名 |
| `priority` | 优先级（数字越大越先触发） |
| `probability` | 规则级触发概率 `[0, 1]`，覆盖桶级值；写 `0` 等价于全局停用该规则 |
| `blocked_named_groups` | 命名捕获组黑名单：捕获值在列表中时该规则不触发，如 `{ target = ["bot"] }` |
| `blocked_groups` | 按捕获组序号的黑名单，键为组序号字符串，如 `{ "1" = ["xxx"] }` |

### `[[rules.reply_templates]]` — 加权随机回复（可选）

```toml
[[rules.reply_templates]]
template = '回复A'
weight   = 2

[[rules.reply_templates]]
template = '回复B'
weight   = 1
```

替代 `reply_template`，按权重随机选择。

### `[[context_rules]]` — 语境感知规则

```toml
[[context_rules]]
name    = 'caocao_qiushou'
patterns = ['竟然不许[！!]*']
type = 'regex_context'
context_window = 5
context_conditions = ['请假', '调休', '申请', '审批']
reply_template = '竟然不许！？'
```

| 字段 | 说明 |
|------|------|
| `type` | `regex_context`（正则判定）或 `llm_context`（LLM 判定），缺省 `regex_context` |
| `context_window` | 回溯最近 N 条消息判定语境 |
| `context_conditions` | `regex_context` 时：最近 N 条消息中任意一条命中任意一个条件即放行；空条件永不放行 |
| `llm_judge_prompt` | `llm_context` 时：发给 LLM 的判定 prompt |
| `llm_timeout` | `llm_context` 判定超时秒数，默认 `2.0` |
| `llm_cache_ttl` | `llm_context` 判定结果缓存秒数，默认 `60` |
| `probability` | 规则级触发概率 `[0, 1]`，覆盖桶级值；掷骰发生在语境判定（含 LLM 判定）之前 |

### `[[chain_games]]` — 自定义接龙游戏

```toml
[[chain_games]]
name = 'my_game'
trigger_pattern = '^开始(.+?)接龙$'
chain = ['第一', '第二', '第三']
```

接龙支持正则捕获组，以及一个步骤接受多个候选词的匹配方式。

### 自动回复概率

所有限流桶和规则都可配置 `probability`（取值 `[0, 1]`，缺省 `1` 表示行为不变）。命中自动回复后先掷骰再执行：未掷中则本次保持沉默，不消耗限流桶配额，也不花费语境规则的 LLM 判定成本。

适用范围为全部非命令触发的自动回复：文字规则、语境规则、时区回复、被动“xxx了”判定、复读检测、乖女链、接龙、内置游戏、唤醒，以及显式 LLM 回复（@ / 前缀 / 私聊）。斜杠命令（如 `/turmfluch`）不受影响。

取值顺序：规则级 `probability` > 引用桶的 `probability` > `1`。文字规则未掷中时只是该规则本次沉默，低优先级规则仍可竞争；被动“xxx了”和 `llm_context` 语境规则的掷骰发生在 LLM 判定之前。

与限流的分工：概率控制平均密度（"十条命中回五条"），限流桶兜底峰值上限（"每分钟最多 N 条"）。独立随机意味着会出现连续回复和长时间沉默的波动，属预期行为。

独立伯努利试验天然存在连发/连哑（按每日触发量，最长连击/连哑期望约为对数量级）。桶上可选开启两个方差驯化开关，均默认关闭、可按桶独立配置：

- `suppress_after_hit = N`（防连发）：同一规则同一群命中后，接下来 N 次命中强制沉默，专治"刚回完又回"。压制期间不消耗随机数、不计入保底连哑。
- `pity_step = X`（保底）：连哑越多概率越高，`p_eff = probability × (1 + 连哑数 × X)`，给连哑长度一个软上限。

两个开关的计数状态按（规则, 群）隔离（私聊按用户隔离），只存内存、重启即重置；规则级 `probability` 只覆盖基础概率，两个开关始终跟随所在桶。`probability = 1` 搭配 `suppress_after_hit` 会出现"一回一哑"的规律交替，建议与 `probability < 1` 组合使用以保留随机感。

调整防连发与保底时，请同时考虑：

- 计数中的“命中”指掷骰通过。后续语境判定或限流拒绝时保留计数，防连发窗口可能消耗在未发出的回复上；语境规则的连哑按快筛命中计算。
- 复读、接龙和内置游戏先推进进度与得分，再决定是否发送回复。为这些桶设置概率可能造成已记分却未发送结果，建议保留全量回复。
- 计数最多保存 8192 个规则与群组合，超限会整体重置；大规模部署应考虑重置对防连发与保底的影响。

覆写系统预定义桶（如 `timezone_wake`、`sts_card_le`）时整个条目需重写，`global_limit` / `user_limit` 一并写全——只写 `probability` 的残缺条目在配置加载时会打警告，且会让限流器构建失败（启动即崩溃），这是既有整条替换语义；`llm_chat` 与唤醒类桶的概率调低后，bot 对直接 @ 也会偶发沉默，仅建议在确实需要全局静音降噪时使用。

随仓库分发的 `config/chat_rules.toml.example` 已按推荐密度预置各桶概率（含系统内置桶的覆写条目），并按触发词日常频率为新三国系列逐条分层配置规则级概率；未配置的规则行为与历史版本一致。

### 模板变量

| 变量 | 说明 |
|------|------|
| `{sender_name}` | 发送者昵称 |
| `{current_time}` | 当前北京时间（`YYYY-MM-DD HH:MM`） |
| `{user_id}` | 发送者 QQ 号 |
| `$1`, `$2`, … | 正则捕获组 |
| `{命名捕获组}` | 命名捕获组（如 `(?P<target>...)` → `{target}`） |

---

## config/games.toml

游戏参数配置文件，详见 [game-config.md](game-config.md) 和 `config/games.toml.example`。

### 牛牛文案预设文件

在 `games.toml` 中设置 `niuniu_text_path` 和 `niuniu_safe_text_path` 可指向自定义 TOML 文案文件。

| 文件 | 层 | 说明 |
|------|-----|------|
| `config/niuniu_text.toml.example` | 分发层（追踪） | 自定义牛牛文案模板，含所有事件消息、长度评价、运势提示、CD 消息 |
| `config/niuniu_text.toml` | 分发层（git 追踪，随模板分发，勿写入私有内容） | 默认自定义文案（上游维护，可按需调整但勿写私有内容） |
| `config/niuniu_text_safe.toml.example` | 分发层（追踪） | 和谐版文案模板，字段与 default 一致但措辞中性化 |
| `config/niuniu_text_safe.toml` | 分发层（git 追踪，随模板分发，勿写入私有内容） | 默认和谐版文案（上游维护，可按需调整但勿写私有内容） |

私有自用文案请放在未被 git 追踪的独立文件中，并用 `niuniu_text_path` 指向。

文案 TOML 结构中，`safe` 模式可仅填写需要覆写的条目：事件按 `name`、长度评价与运势提示按区间、消息字典按键覆盖，未覆写的条目自动从 `default` 继承。

---

## config/admins.toml

全局管理员注册表，详见 [global-admins.md](global-admins.md) 和 `config/admins.toml.example`。`global_admins` 列表填 QQ 号数字字符串，热重载生效；文件缺失或为空即功能关闭。

---

## config/personas/

每个 `.toml` 文件定义一个人格，`_shared.toml` 为自动注入所有人格的共享行为准则。

```toml
id           = 'my-persona'
display_name = '我的角色'
system_prompt = '''
你是一个……
'''
style_prompt = '''
回复风格：……
'''
scope = ['group']  # 可选：'group' / 'private'，不设则两端均显示
```

Persona 文件支持自由扩展字段：平面字段之外，structured v2 扩展表同样会被消费。structured v2 格式参见 `config/personas.example/structured.toml`，其中 `[identity]`、`[biography]`、`[cognition]`、`[instinct]`、`[voice]` 等扩展表会被运行时渲染进 system prompt。

---

## SearXNG 配置

项目内置 `docker-compose.example.yml`（含 searxng 服务）和服务配置 `docker/searxng/settings.yml`：

```yaml
# docker/searxng/settings.yml（节选）
search:
  formats:
    - html
    - json
server:
  bind_address: "0.0.0.0"
  secret_key: "change-this-secret"
```

默认暴露在 `http://127.0.0.1:8888`，开启 JSON 接口供 bot 直接调用。

搜索结果由所配置的 SearXNG 实例聚合。结果为空或相关性差时，先检查该实例的搜索引擎状态、网络出口与查询设置，再用同一关键词复测。

---

## 限流窗口

基础参数在 `src/quickquip/chat/config.py` 中（为代码默认值，`chat_rules.toml` 可覆盖）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 滑动窗口大小（秒） |

---

## 贴吧配置

除 `.env` 变量外，贴吧登录态保存在 `data/tieba/storage_state.json`。首次启用前需按部署指南完成登录态导出。
