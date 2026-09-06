# QuickQuip 配置参考

本文档列出 QuickQuip 所有可配置项，按文件和作用域分类。

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
| `MCP_PRTS_WIKI_TOKEN` | prts_wiki MCP 的鉴权 token（见 `config/llm.toml.example` 的 prts_wiki 示例） |

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
| `MCP_PRTS_WIKI_ENABLED` | 是否启用 PRTS Wiki MCP server。默认 `false` |
| `MCP_PRTS_GAMEDATA_MOUNT` | PRTS Wiki 游戏数据卷挂载，格式 `/absolute/path:/data/gamedata:ro` |
| `MCP_PRTS_STORYJSON_MOUNT` | PRTS Wiki 剧情 JSON 卷挂载，格式 `/absolute/path:/data/storyjson:ro` |
其他 `${ENV_VAR}` 与 `${ENV_VAR:-default}` 语法在 `config/llm.toml` 的 MCP server 配置中均可用。

### Web Admin

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEB_ADMIN_PASSWORD` | 管理后台登录口令（必填） | — |
| `WEB_ADMIN_HOST` | 监听地址 | `127.0.0.1` |
| `WEB_ADMIN_PORT` | 监听端口 | `5104` |
| `WEB_ADMIN_SESSION_TTL_HOURS` | session 有效期（小时） | `168` |
| `WEB_ADMIN_COOKIE_SECURE` | 是否下发 Secure cookie：`auto` / `true` / `false` | `auto` |

### Docker 构建相关

| 变量 | 说明 |
|------|------|
| `PIP_INDEX_URL` | pip 安装源（国内镜像加速） |
| `PIP_TRUSTED_HOST` | pip 信任主机 |
| `PLAYWRIGHT_BASE_IMAGE` | Playwright 基础镜像（可含国内代理前缀） |

GHCR 分发镜像和 `prod.example/Dockerfile` 均基于 Playwright Python 镜像构建，并内置 Docker CLI，便于贴吧采集和可选 MCP docker transport 使用。docker transport 仍需显式挂载宿主机 Docker socket，默认 compose 不会挂载。

---

## config/llm.toml

### `[runtime]` — 运行参数

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 全局 LLM 开关（`llm.toml.example` 中显式设为 `true`） | `false` |
| `memory_enabled` | 全局记忆注入开关 | `true` |
| `default_provider` | 默认 provider ID | — |
| `default_persona` | 默认人格 ID | — |
| `history_limit` | 单次调用读取的对话行数兜底——**自 1.14 起语义变更**：不再默认生效（默认路径由会话纪元自动管理）；仅当某会话通过 `/llm context_limit <n>` 显式覆盖时（群聊/私聊均可，上限 1024 条），该会话退化为保留最新 n 行的滚动窗 | `10` |
| `history_max_messages_per_group` | **自 1.14 起废弃（保留解析、不再生效）**：存储裁剪由会话纪元锚点驱动，硬上限统一为 2048 行（`service_parts/constants.py`） | `40` |
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
| `epoch_cold_idle_seconds` | 冷场判定 T：距该键上次 LLM 请求超过此秒数视为缓存已冷（宁短勿长：设短退化为滚动窗形态，设长则每轮全价且窗口更长） | `300` |
| `epoch_cold_target_tokens` | 冷场重置后窗口缩到的 token 估算目标（L_cold） | `4000` |
| `epoch_cold_trigger_tokens` | 冷场重置触发水位：冷场且窗口超过此值才缩（H_cold） | `5000` |
| `epoch_hot_target_tokens` | 触顶重置后窗口缩到的 token 估算目标（L_hot，长话题保护） | `32000` |
| `epoch_cap_tokens` | 窗口硬上限：超过即触发触顶重置（H_hot / cap） | `64000` |
| `recent_context_token_budget` | 【现场】补丁每轮 token 预算：近期消息缓冲服役给 LLM 的上限（从最新往回截） | `800` |
| `recent_context_floor_seconds` | 【现场】滑动保底窗秒数：窗内消息即使已服役过也会重附（增量语义之外的保底） | `300` |
| `request_input_token_budget` | 实际请求输入预算（应用侧估算口径，非模型平台上限）：超限拒绝发起请求 | `96000` |
| `agent_record_retention_days` | 已关闭对话轮（Loop）保留天数，按关闭时间计 | `30` |
| `agent_record_max_loops_per_scope` | 每会话已关闭 Loop 数量上限，先触顶者触发清理最旧完整 Loop | `1000` |
| `agent_record_max_bytes_per_scope` | 每会话 Loop 业务记录字节上限（UTF-8 计量） | `67108864` |
| `agent_delivery_enabled` | 逐 Turn 交付开关：开启后每次模型响应的普通正文先于工具执行分段外发；关闭时仅最终正文单发，记录不受影响 | `false` |
| `reply_split_threshold_chars` | 回复超过该长度（Unicode code point）才进行自然分段 | `800` |
| `reply_chunk_max_chars` | 单段源文本上限，独立于 OneBot 协议报文长度 | `1200` |
| `reply_send_interval_ms` | 同会话相邻发送开始时间的最小间隔（0-10000） | `800` |
| `reply_max_chunks_per_loop` | 单次对话交付条目上限（含文字、媒体与通知，1-256） | `64` |

以上 6 个 `epoch_*` 键均可在 `[[providers]]` 条目里同名覆盖（如 DeepSeek 的缓存存活更久，`epoch_cold_idle_seconds` 可放宽到 `21600`）；未覆盖的键继承 `[runtime]` 值。参数关系需满足 `0 < cold_target < cold_trigger ≤ hot_target < cap` 且 `context_tokens > 0`，非法时回退并记 warning。`recent_context_*` 两键仅全局，不支持 provider 覆盖。

### `[triggers]` — 触发方式

| 键 | 说明 | 默认值 |
|----|------|--------|
| `default_prefix` | 显式触发前缀 | `/ai` |
| `allow_prefix` | 启用前缀触发 | `true` |
| `allow_at` | 启用艾特触发 | `true` |
| `empty_prompt_reply` | 空提示时的默认回复文本 | `请在触发指令或艾特后面补上想说的话。` |

`[triggers.auto_search]` — 自动联网判定：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 是否启用自动联网 | `false` |
| `search_max_calls_per_round` | 单轮最大搜索调用数，范围 1-32 | `3` |

`[triggers.quick_judge]` — 快速判定模型：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `provider_id` | 快速判定专用 provider ID；留空使用默认 provider | `""` |
| `model` | 快速判定专用模型；留空使用 provider 默认模型 | `""` |
| `timeout` | 判定超时秒数 | `2.0` |
| `max_tokens` | 判定最大输出 token | `64` |

快速判定用于 `context_rules` 的 `llm_context`、唤醒模块的相关性/答疑判定等短 prompt 场景。技术失败（超时、provider 异常、空正文、截断、无效 JSON）一律按未触发处理（fail-closed），不会写入 60 秒判定缓存；只有成功解析的业务 true/false 会进缓存。选用带 reasoning 的模型时，reasoning token 计入 `max_tokens` 且延迟更高，需要同时调大 `max_tokens`（如 256）与 `timeout`（如 6 秒），否则会出现“预算被思考耗尽、可见判定为空”与大面积超时。

### `[image_preprocessing]` — 非视觉模型图片转述

当当前主模型出现在所属 provider 的 `non_vision_models` 中时，运行时先调用指定视觉模型，将图片转成带来源和序号的文本，再交给主模型。视觉主模型直接接收原图，不调用该前置层。

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 启用非视觉模型图片转述 | `false` |
| `provider_id` | 提供视觉识别能力的 provider ID | `""` |
| `model` | 视觉模型 ID；留空使用该 provider 的默认模型 | `""` |
| `max_tokens` | 单张图片转述输出上限，运行时限制为 80-2048 | `300` |
| `temperature` | 图片转述温度 | `0.3` |
| `prompt` | 自定义转述 system prompt；留空使用内置提示 | `""` |

单轮最多处理 5 张当前、引用或转发图片。被动唤醒需要近期图片时，会用剩余名额选择最新图片。任一图片转述失败时，本轮不会调用非视觉主模型，用户会收到可重试提示。

### `[tools]` — 工具调用

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 工具名单。为空 `[]` 时暴露默认白名单及全部 MCP 工具；非空时与 `enabled_mode` 配合使用 | `[]` |
| `enabled_mode` | `enabled` 非空时的作用方式：`append` 在默认白名单 + MCP 工具之上追加（启用 `draw_svg` 等可选内置工具用这个）；`replace` 精确过滤，只暴露所列工具 | `append` |
| `discovery_mode` | 工具发现模式：`off` 全量暴露；`on` 仅暴露常驻工具并通过 `tool_search` 按需加载；`auto` 在可延迟工具数超过阈值后启用 | `auto` |
| `discovery_min_tools` | `auto` 模式下触发工具发现的可延迟工具数量阈值 | `10` |
| `discovery_search_limit` | 单次 `tool_search` 最多返回并加载的工具数 | `5` |
| `discovery_max_loaded_tools` | 一次 LLM 工具调用循环中最多动态加载的工具总数 | `12` |
| `always_loaded` | 工具发现开启时仍然常驻暴露的工具名列表 | `["tool_search", "tool_list", "get_identity", "list_memories", "search_web"]` |

`tool_search` 和 `tool_list` 是本地元工具，不依赖 Claude 原生 tool search。接入大量 MCP 工具时，模型会先用 `tool_search` 搜索相关能力；搜索不到时可用 `tool_list` 列出工具组、工具名或按精确工具名加载工具，下一轮再调用被加载的真实工具。

专题配置和排障建议见 [tool-discovery.md](tool-discovery.md)。

**`enabled_mode` 升级说明（v1.11 → v1.12）**：v1.11 及更早版本中，`enabled` 非空表示精确白名单，未列入名单的默认工具与 MCP 工具都会被过滤。自 v1.12 起，`enabled` 非空时默认按 `append` 追加语义处理。各场景影响：

- `enabled = []`（默认）：行为完全不变，仍暴露默认白名单加全部 MCP 工具。
- 用 `enabled` 启用可选内置工具（如 `draw_svg`）：MCP 工具不再被名单误过滤，通常无需改动。
- 需要严格工具白名单的部署：显式设置 `enabled_mode = "replace"`，恢复精确过滤语义。

### `[[providers]]` — Provider 定义（可多个）

每个 provider 一个 `[[providers]]` 条目：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `id` | Provider 唯一标识（如 `openai-main`、`gemini-main`） | — |
| `protocol` | 协议类型：`openai` / `claude` / `gemini` | — |
| `base_url` | API 中转地址 | — |
| `api_key_env` | API key 所在环境变量名 | — |
| `default_model` | 默认模型 ID | — |
| `models` | 可用模型 ID 数组 | — |
| `enabled` | 暂时禁用该 provider：不进 `/llm providers`/`models` 列表、不参与探活、model_cascade 跳过、`/llm use` 拒绝；provider 保留在配置中，改回 `true` 即恢复 | `true` |
| `timeout_seconds` | 请求超时（秒） | `45` |
| `temperature` | 温度参数 | `0.8` |
| `max_output_tokens` | 最大输出 token 数 | `800` |
| `style_overrides` | 可选，多行字符串，追加到每次调用的 system prompt 末尾 | — |
| `style_profile` | 可选，引用 `[style_profiles]` 中预定义的共享 system prompt 段，与 `style_overrides` 拼接 | — |
| `non_vision_models` | 该 provider 下不支持图片输入的模型 ID 列表 | `[]` |
| `stream_enabled` | 是否启用 SSE 流式响应 | `true` |
| `aliases` | 模型短别名映射，如 `{ gpt4 = "gpt-5.4" }`，`/llm use` 时自动解析 | — |
| `headers` | 注入到每次请求的额外 HTTP 头 | — |
| `user_agent` | 自定义 User-Agent 请求头 | — |
| `extra_body` | 注入到每次请求体的额外 JSON 字段（TOML inline table） | — |
| `fallback_urls` | 备用 base URL 列表，主地址 5xx/网络错误时自动切换 | `[]` |
| `proxy` | HTTP(S) 代理地址（如 `http://127.0.0.1:7890`），所有请求均走代理，含 fallback 重试 | — |
| `auth_method` | 认证方式：`api_key` 或 `bearer`。Claude 分别使用 `x-api-key` / `Authorization: Bearer`；Gemini 分别使用兼容中转的 `?key=` / `Authorization: Bearer`；OpenAI 使用 Bearer | `api_key` |
| `prompt_caching` | 启用 Anthropic Prompt Caching（仅 `claude` 协议生效，需中转站支持 CLI 格式） | `false` |
| `cache_ttl` | Claude prompt cache TTL：空值默认 5min，`"1h"` 使用扩展缓存（仅 `claude` 协议生效） | `""` |
| `builtin_search` | 声明 provider 原生搜索工具（仅 `gemini` 协议生效）：请求携带 `google_search` 服务端检索声明，回复末尾自动附上 grounding 来源；开启后该 provider 的会话移除 `search_web` 工具，提示词引导同步切换。其他协议下该键不生效（配置加载时记录 warning）。检索在 provider 侧执行并计费，本地轮次上限与 token 看板不覆盖 grounding 调用本身。注意：`google_search` 与 function calling 在同一请求中组合仅 Gemini 3 系列模型支持；2.x 模型需关闭该 provider 的 `builtin_search` 或全局 `tool_calling_enabled`，否则聊天请求会被 API 拒绝 | `false` |

> **会话纪元覆盖**：`[runtime]` 的 6 个 `epoch_*` 键可在本表同名覆盖（如 `epoch_cold_idle_seconds = 21600` 放宽 DeepSeek 的冷场判定），未覆盖的键继承全局缺省；详见 `[runtime]` 段说明。

> **协议适配说明**：`claude` 协议的请求默认带上完整的 Claude Code 客户端指纹头（`anthropic-version`、`anthropic-beta`、`x-app: cli`、全套 `x-stainless-*` 运行时遥测头、`anthropic-dangerous-direct-browser-access` 等），User-Agent 与 URL（`/messages?beta=true`）均对齐真实 claude-cli 客户端。`x-stainless-os` 按宿主 OS 动态探测。所有指纹头均可通过 `headers` 配置大小写无关地覆盖，`user_agent` 配置项优先级最高。

> **Gemini 工具回放说明**：`gemini` 协议会把模型返回的有序 `parts` 作为 provider opaque data 保留，并在工具结果回送时原样恢复 `thoughtSignature`。并行 `functionCall` 与 `functionResponse` 必须保持完整批次；超过单轮工具上限时本轮 fail-closed，不向 Gemini 发送截断历史。工具结果图片放在完整 `functionResponse` 批次之后的独立 user turn。连接只接受 Bearer token 的原生 Gemini 网关时设置 `auth_method = "bearer"`，避免凭据进入 URL 和代理访问日志。

### `[pricing.models]` — 模型定价（成本统计）

per-MTok（每百万 token，USD）定价表，是 Web Admin LLM 用量页成本统计（`cost_usd`）的价格来源：

```toml
# 纯 model 名 = 官方价默认（所有 provider 的该 model 共享）
[pricing.models."deepseek-chat"]
input_per_mtok = 0.14
output_per_mtok = 0.28
cache_read_per_mtok = 0.003

# "provider_id/model" = per-provider 覆盖（某中转实际价，优先于 model 默认）
[pricing.models."my-provider/deepseek-chat"]
input_per_mtok = 0.20
output_per_mtok = 0.40
```

| 键 | 说明 |
|----|------|
| `input_per_mtok` | 输入价（USD/百万 token） |
| `output_per_mtok` | 输出价（USD/百万 token） |
| `cache_read_per_mtok` | 缓存读价；模型无该缓存机制时省略，计算时回退 input 价 |
| `cache_write_per_mtok` | 缓存写价；同上，无缓存溢价时省略 |

查价顺序：先查 `"provider_id/model"`（per-provider 覆盖），未命中回退纯 `"model"`（官方价默认），再未命中标记未定价（cost=0，用量页显示“未定价”）。第三方中转建议按模型 id 填官方价默认，再按中转实际计费加 provider 覆盖；国产 CNY 价按汇率换算成 USD。

### `[mcp]` — MCP 总开关

| 键 | 说明 |
|----|------|
| `enabled` | 是否启用 MCP |

### `[[mcp.servers]]` — MCP Server 定义（可多个）

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
| `env` | 环境变量键值对，值支持 `${ENV_VAR}` / `${ENV_VAR:-default}` |
| `mounts` | 卷挂载列表，格式 `host:container` 或 `host:container:ro` |
| `docker_args` | 额外 Docker 运行参数 |
| `include_tools` | 该 server 暴露的工具白名单，支持 MCP 原始工具名或 QuickQuip 生成后的工具名 |
| `exclude_tools` | 该 server 排除的工具列表，支持 MCP 原始工具名或 QuickQuip 生成后的工具名 |
| `allowed_tools` | 兼容旧配置的白名单字段，新配置建议使用 `include_tools` |

`include_tools` 为空时默认接入该 MCP server 暴露的全部工具；`exclude_tools` 会在白名单之后生效。接入 GitHub MCP 这类大工具集时，生产环境建议优先使用 `include_tools` 收窄到读类工具，再交给 `tool_search` / `tool_list` 做按需加载。

### `[daily_briefing]` — 每日播报

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
| `model_cascade` | 模型级联列表（provider + model，失败自动降级） |

`model_cascade` 会按顺序尝试；如果某个模型提前截断或以非正常 finish reason 结束，会继续尝试下一项。仅当对应功能 `enabled = true` 时才校验 cascade 引用的 provider 是否存在；功能关闭时跳过校验，不产生 `load_error`。

### `[daily_summary]` — 每日总结

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关（`true` / `false`） |
| `generate_cron` | 生成 cron 表达式 |
| `publish_cron` | 发布 cron 表达式 |
| `min_messages` | 最小消息数（不足时跳过） |
| `summary_length_hint` | 目标字数 |
| `model_cascade` | 模型级联列表（失败自动降级） |

### `[weekly_report]` / `[monthly_report]` — 群周报 / 群月报

每周一（周报）/每月 1 日（月报）自动生成上一周期的群聊回顾。数据源复用词云采集（`wordcloud_msgs`，always-on 不删除），按天采样后套用每日日报同款 LLM 管线。与 `[daily_summary]` 相互独立，可单独开启。

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关（`true` / `false`，默认 `false`） |
| `generate_cron` | 生成 cron（周报默认 `0 9 * * 1` 每周一；月报默认 `0 9 1 * *` 每月 1 日） |
| `publish_cron` | 发布 cron（默认 `0 10 * * *` 每天 10:00；周报/月报共用，每日发布新报告并补发未发布的） |
| `min_messages` | 周期内最小消息数（不足时跳过；周报默认 100，月报默认 300） |
| `length_hint` | 目标字数（周报默认 2000，月报默认 2500） |
| `sample_per_day` | 每天采样消息数上限（控制喂给 LLM 的总量；周报默认 50，月报默认 20） |
| `model_cascade` | 模型级联列表，支持 `@default` 占位符 |

> 周报/月报通过 `/summary weekly|monthly on|off|status|now` 在群内按群开启。period 标识：周报为 ISO 周号（如 `2026-W24`），月报为年月（如 `2026-06`）。

---

## config/generation.toml

此文件不存在时，图片部分回退读取 `config/llm.toml` 中旧版 `[image_generation]` 段。

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

转写文本进入普通 LLM 请求前会经过统一敏感词过滤；原始音频需要先发送给 ASR provider才能得到可扫描文本。

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

LLM 对话中自主调用 `draw_svg` 工具：模型在工具参数中直接写出 SVG 源码，本地 resvg 渲染成 PNG 随回复外发。不需要配置 provider/model（SVG 代码由当前群的对话模型生成），渲染字体沿用 `data/fonts/NotoSansSC-Regular.ttf`（与词云同源）。启用需两步：本段 `enabled = true`，且 `llm.toml [tools] enabled` 中加入 `"draw_svg"`。

| 键 | 默认 | 说明 |
|----|------|------|
| `enabled` | `false` | 功能总开关 |
| `harden` | `true` | 第一层安全（默认启用）：输入硬约束（64KB / 嵌套 ≤2000 / viewBox ≤2048 / 滤镜参数上限）、静态清洗（剥 script、事件属性、外链）、输出尺寸服务端覆盖、渲染子进程 rlimit（地址空间 2GB / CPU 5s）。关闭即自担风险：恶意 SVG 可耗尽内存或 CPU |
| `content_judge` | `false` | 第二层安全（默认关闭）：渲染前用 `[triggers.quick_judge]` 的廉价模型对图片可见文本做内容安全裁决。判定失败（超时 / 非 JSON / 未配置）时放行渲染并记录 WARN（fail-open） |

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

`ChainGameManager` 通用引擎支持捕获组和 OR 候选匹配。

### 自动回复概率

所有限流桶和规则都可配置 `probability`（取值 `[0, 1]`，缺省 `1` 表示行为不变）。命中自动回复后先掷骰再执行：未掷中则本次保持沉默，不消耗限流桶配额，也不花费语境规则的 LLM 判定成本。

适用范围为全部非命令触发的自动回复：文字规则、语境规则、时区回复、被动「xxx了」判定、复读检测、乖女链、接龙、内置游戏、唤醒，以及显式 LLM 回复（@ / 前缀 / 私聊）。斜杠命令（如 `/turmfluch`）不受影响。

取值顺序：规则级 `probability` > 引用桶的 `probability` > `1`。文字规则未掷中时只是该规则本次沉默，低优先级规则仍可竞争；被动「xxx了」和 `llm_context` 语境规则的掷骰发生在 LLM 判定之前。

与限流的分工：概率控制平均密度（"十条命中回五条"），限流桶兜底峰值上限（"每分钟最多 N 条"）。独立随机意味着会出现连续回复和长时间沉默的波动，属预期行为。

独立伯努利试验天然存在连发/连哑（按每日触发量，最长连击/连哑期望约为对数量级）。桶上可选开启两个方差驯化开关，均默认关闭、可按桶独立配置：

- `suppress_after_hit = N`（防连发）：同一规则同一群命中后，接下来 N 次命中强制沉默，专治"刚回完又回"。压制期间不消耗随机数、不计入保底连哑。
- `pity_step = X`（保底）：连哑越多概率越高，`p_eff = probability × (1 + 连哑数 × X)`，给连哑长度一个软上限。

两个开关的计数状态按（规则, 群）隔离（私聊按用户隔离），只存内存、重启即重置；规则级 `probability` 只覆盖基础概率，两个开关始终跟随所在桶。`probability = 1` 搭配 `suppress_after_hit` 会出现"一回一哑"的规律交替，建议与 `probability < 1` 组合使用以保留随机感。

三点语义边界：**"命中"指掷骰通过**，而非回复最终发出——掷骰之后语境判定未通过或限流拒绝时状态不回滚（防连发窗口可能消耗在未发出的回复上，方向保守、密度略低于配置值，语境规则的连哑按快筛命中计）；**状态机类桶不建议配概率**——复读、接龙、内置游戏的进度与得分在匹配阶段即已推进，概率只静默丢弃回复（可能"赢了游戏无反馈但分数已记"）；状态表规模有上限（8192 个规则×群组合），超限整体重置，超大部署下防连发/保底可能周期性失效。

两点注意：覆写系统预定义桶（如 `timezone_wake`、`sts_card_le`）时整个条目需重写，`global_limit` / `user_limit` 一并写全——只写 `probability` 的残缺条目在配置加载时会打警告，且会让限流器构建失败（启动即崩溃），这是既有整条替换语义；`llm_chat` 与唤醒类桶的概率调低后，bot 对直接 @ 也会偶发沉默，仅建议在确实需要全局静音降噪时使用。

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

> ⚠️ **搜索质量免责**：`search_web` 只负责把请求转发给 SearXNG 实例，结果相关性取决于该实例聚合的搜索引擎与出口 IP（机房 IP 下 bing/baidu/sogou 等常大面积失效或风控）。QuickQuip 不为搜索结果质量背书；生产环境建议使用调优过的或自建 SearXNG 实例。

---

## 限流窗口

基础参数在 `src/quickquip/chat/config.py` 中（为代码默认值，`chat_rules.toml` 可覆盖）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 滑动窗口大小（秒） |

---

## 贴吧配置

除 `.env` 变量外，贴吧登录态保存在 `data/tieba/storage_state.json`。首次启用前需按部署指南完成登录态导出。
