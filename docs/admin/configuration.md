# QuickQuip 配置参考

本文档列出 QuickQuip 所有可配置项，按文件和作用域分类。

---

## .env 环境变量

### 基础运行

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DRIVER` | NoneBot2 驱动器；使用 LLBot 正向 WebSocket 时需包含 `~websockets` | `~fastapi+~websockets` |
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
| `TAVILY_API_KEY` | Tavily 搜索 API key（备用搜索后端） |

### 搜索

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SEARXNG_BASE_URL` | Bot 内置 `search_web` 和 `/search` 使用的 SearXNG 服务地址 | `http://127.0.0.1:8888` |
| `QUICKQUIP_SEARXNG_BASE_URL` | Docker Compose 内注入给 QuickQuip / Web Admin 的 SearXNG 容器内地址；避免把本地直跑的 `127.0.0.1` 地址带入容器 | `http://searxng:8080` |
| `SEARXNG_SAFE_SEARCH` | 传给 SearXNG 的安全搜索级别：`0` / `1` / `2` | `0` |
| `SEARXNG_LANGUAGE` | 传给 SearXNG 的搜索语言；空值时使用 `all` | `all` |
| `SEARXNG_PUBLIC_BASE_URL` | compose 中 SearXNG 对外展示的 base URL | `http://127.0.0.1:8888/` |
| `SEARXNG_BIND_ADDRESS` | compose 暴露 SearXNG 时绑定的宿主地址 | `127.0.0.1` |
| `SEARXNG_BIND_PORT` | compose 暴露 SearXNG 时绑定的宿主端口 | `8888` |
| `SEARXNG_SECRET` | SearXNG 实例密钥，用于容器环境变量 | — |

`search_web` 固定走项目内 SearXNG。普通本地运行读取 `SEARXNG_BASE_URL`；`docker-compose.example.yml` 和 `prod.example/docker-compose.yml` 会优先把 `QUICKQUIP_SEARXNG_BASE_URL` 注入为容器内的 `SEARXNG_BASE_URL`。Tavily 等外部搜索能力建议通过 MCP sidecar 暴露为工具。

### LLM 调试

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_TRACE_FLAG_FILE` | 触发 LLM 请求/响应 trace 的 flag 文件路径；文件存在时会记录共享 trace，供 Web Admin 的 LLM Trace 页面读取 | — |

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
| `enabled` | 全局 LLM 开关 | `true` |
| `memory_enabled` | 全局记忆注入开关 | `true` |
| `default_provider` | 默认 provider ID | — |
| `default_persona` | 默认人格 ID | — |
| `history_limit` | 单次调用读取的对话轮数上限 | `10` |
| `history_max_messages_per_group` | 单群存储的对话消息硬上限 | `20` |
| `memory_limit` | 单次调用注入的记忆条数上限 | — |
| `memory_max_items_per_group` | 单群存储的记忆条数硬上限 | — |
| `max_prompt_chars` | system prompt 最大字符数 | — |
| `tool_calling_enabled` | 是否允许工具调用 | `false` |
| `tool_max_rounds` | 单次工具调用循环最大轮数 | `8` |
| `tool_max_calls_per_round` | 单轮最多执行工具调用数 | `16` |
| `auto_memory_enabled` | 自动记忆抽取全局默认开关 | `false` |
| `auto_memory_prompt` | 自动记忆抽取自定义判定 prompt | `""` |
| `auto_memory_max_tokens` | 自动记忆抽取判定最大输出 token | `256` |

### `[triggers]` — 触发方式

| 键 | 说明 | 默认值 |
|----|------|--------|
| `default_prefix` | 显式触发前缀 | `/ai` |
| `allow_prefix` | 启用前缀触发 | `true` |
| `allow_at` | 启用艾特触发 | `true` |
| `empty_prompt_reply` | 空提示时的默认回复文本 | — |

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

快速判定用于 `context_rules` 的 `llm_context`、唤醒模块的相关性/答疑判定等短 prompt 场景。

### `[tools]` — 工具调用

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 工具白名单。为空 `[]` 时暴露所有内建及 MCP 工具；填写后按工具名精确过滤 | `[]` |
| `discovery_mode` | 工具发现模式：`off` 全量暴露；`on` 仅暴露常驻工具并通过 `tool_search` 按需加载；`auto` 在可延迟工具数超过阈值后启用 | `auto` |
| `discovery_min_tools` | `auto` 模式下触发工具发现的可延迟工具数量阈值 | `10` |
| `discovery_search_limit` | 单次 `tool_search` 最多返回并加载的工具数 | `5` |
| `discovery_max_loaded_tools` | 一次 LLM 工具调用循环中最多动态加载的工具总数 | `12` |
| `always_loaded` | 工具发现开启时仍然常驻暴露的工具名列表 | `["tool_search", "tool_list", "get_identity", "list_memories", "search_web"]` |

`tool_search` 和 `tool_list` 是本地元工具，不依赖 Claude 原生 tool search。接入大量 MCP 工具时，模型会先用 `tool_search` 搜索相关能力；搜索不到时可用 `tool_list` 列出工具组、工具名或按精确工具名加载工具，下一轮再调用被加载的真实工具。

专题配置和排障建议见 [tool-discovery.md](tool-discovery.md)。

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
| `auth_method` | 认证方式：`api_key`（x-api-key 头，默认）或 `bearer`（Authorization: Bearer 头） | `api_key` |
| `prompt_caching` | 启用 Anthropic Prompt Caching（仅 `claude` 协议生效，需中转站支持 CLI 格式） | `false` |

> **协议适配说明**：`claude` 协议的请求默认带上完整的 Claude Code 客户端指纹头（`anthropic-version`、`anthropic-beta`、`x-app: cli`、全套 `x-stainless-*` 运行时遥测头、`anthropic-dangerous-direct-browser-access` 等），User-Agent 与 URL（`/messages?beta=true`）均对齐真实 claude-cli 客户端。`x-stainless-os` 按宿主 OS 动态探测。所有指纹头均可通过 `headers` 配置大小写无关地覆盖，`user_agent` 配置项优先级最高。

### `[mcp]` — MCP 总开关

| 键 | 说明 |
|----|------|
| `enabled` | 是否启用 MCP |

### `[[mcp.servers]]` — MCP Server 定义（可多个）

| 键 | 说明 |
|----|------|
| `id` | Server 唯一标识 |
| `transport` | 传输方式：`stdio` / `docker` / `http` / `sse` |
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

`model_cascade` 会按顺序尝试；如果某个模型提前截断或以非正常 finish reason 结束，会继续尝试下一项。

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
| `display_name` | 展示名 |
| `model_id` | 模型 ID |
| `supported_sizes` | 支持的尺寸列表 |
| `supported_aspect_ratios` | 支持的比例列表 |
| `default_quality` | 默认质量 |
| `return_format` | 返回格式（`url` / `b64_json`） |

### `[audio]` — 语音生成

| 键 | 说明 |
|----|------|
| `enabled` | 全局开关 |
| `default_model` | 默认模型名 |
| `prompt_blocklist` | 文本黑名单 |

`[[audio.providers]]` 和 `[[audio.providers.models]]` 结构类似图片，额外包含 `supported_formats`、`default_sample_rate`、`default_bitrate`、`default_voice`、`voice_style_options` 等语音特有字段。

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

`[[music.providers]]` 和 `[[music.providers.models]]` 结构类似，额外包含 `supported_output_formats`、`lyrics_optimization` 等音乐特有字段。

`api_key_env` 由每个 provider 自行声明；示例配置中常见的键名包括 `MINIMAX_API_KEY`、`VOLCENGINE_API_KEY` 和 OpenAI-compatible ASR 使用的 `OPENAI_API_KEY`。

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
| `boredom_check_interval` | 无聊唤醒定时检查间隔秒数 | `300` |
| `boredom_dnd_start` | 免打扰开始时间，格式 `HH:MM`，空值关闭 | `""` |
| `boredom_dnd_end` | 免打扰结束时间，格式 `HH:MM`，空值关闭 | `""` |
| `interest_topics` | 兴趣话题关键词列表，命中后触发 `awakening_interest` | `[]` |
| `relevance_threshold` | 相关性唤醒判定阈值，`>= 1` 关闭 LLM 判定 | `1.0` |
| `qa_threshold` | 答疑唤醒判定阈值，`>= 1` 关闭 LLM 判定 | `1.0` |

`extend_duration` 只会在群友通过前缀或艾特等显式 LLM 入口触发后生效。兴趣、兜底、无聊、相关性和答疑唤醒不会打开延长窗口；延长窗口内的图片-only、CQ-only、短语气词和过短无实义文本也会被忽略。

被动唤醒会携带群内近期历史图片（延长、兴趣、相关性和答疑唤醒注入，兜底和无聊唤醒不注入）。

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
context_type = 'regex_context'
context_window = 5
context_conditions = ['请假', '调休', '申请', '审批']
reply_template = '竟然不许！？'
```

| 字段 | 说明 |
|------|------|
| `context_type` | `regex_context`（正则判定）或 `llm_context`（LLM 判定） |
| `context_window` | 回溯最近 N 条消息判定语境 |
| `context_conditions` | `regex_context` 时：每个 pattern 命中即通过 |
| `llm_prompt` | `llm_context` 时：发给 LLM 的判定 prompt |

### `[[chain_games]]` — 自定义接龙游戏

```toml
[[chain_games]]
name = 'my_game'
start_pattern = '^开始(.+?)接龙$'
steps = ['第一', '第二', '第三']
```

`ChainGameManager` 通用引擎支持捕获组和 OR 候选匹配。

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
| `config/niuniu_text.toml` | 自用层（gitignore） | 部署者自定义文案（复制 example 后修改） |
| `config/niuniu_text_safe.toml.example` | 分发层（追踪） | 和谐版文案模板，字段与 default 一致但措辞中性化 |
| `config/niuniu_text_safe.toml` | 自用层（gitignore） | 部署者自定义和谐版文案 |

文案 TOML 结构中，`safe` 模式可仅填写需要覆写的字段，缺失字段自动从 `default` 继承。

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

Persona 文件支持自由扩展字段，运行时只使用已识别的键。

---

## SearXNG 配置

项目内置 `docker-compose.searxng.yml` 和服务配置 `docker/searxng/settings.yml`：

```yaml
# docker/searxng/settings.yml
search:
  formats:
    - html
    - json
server:
  bind_address: "0.0.0.0"
  secret_key: "change-me"
```

默认暴露在 `http://127.0.0.1:8888`，开启 JSON 接口供 bot 直接调用。

---

## 限流窗口

基础参数在 `src/quickquip/chat/config.py` 中（为代码默认值，`chat_rules.toml` 可覆盖）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 滑动窗口大小（秒） |

---

## 贴吧配置

除 `.env` 变量外，贴吧登录态保存在 `data/tieba/storage_state.json`。首次启用前需按部署指南完成登录态导出。
