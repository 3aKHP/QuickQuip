# QuickQuip 配置参考

本文档列出 QuickQuip 所有可配置项，按文件和作用域分类。

---

## .env 环境变量

### 基础运行

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DRIVER` | NoneBot2 驱动器 | `~fastapi` |
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
| `SEARCH_BACKEND` | 搜索后端选择：`auto` / `searxng` / `tavily` | `auto` |
| `SEARXNG_BASE_URL` | SearXNG 服务地址 | `http://127.0.0.1:8888` |

`SEARCH_BACKEND=auto` 时，若 `SEARXNG_BASE_URL` 已设置则优先使用 SearXNG。

### 贴吧

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TIEBA_ENABLED` | 是否启用贴吧功能 | `false` |
| `TIEBA_FORUM_KEYWORDS` | 多贴吧来源，逗号/分号/竖线/换行分隔 | — |
| `TIEBA_FORUM_KEYWORD` | 单贴吧来源（旧字段，多来源时优先用 `FORUM_KEYWORDS`） | — |
| `TIEBA_SYNC_INTERVAL_SECONDS` | 同步间隔（秒） | `900` |
| `TIEBA_BROWSER_HEADLESS` | 浏览器是否无头模式 | `true` |

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
| `search_max_calls_per_round` | 单轮最大搜索调用数 | — |

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

| 键 | 说明 |
|----|------|
| `id` | Provider 唯一标识（如 `openai-main`、`gemini-main`） |
| `protocol` | 协议类型：`openai` / `anthropic` / `gemini` |
| `base_url` | API 中转地址 |
| `api_key_env` | API key 所在环境变量名 |
| `default_model` | 默认模型 ID |
| `models` | 可用模型 ID 数组 |
| `timeout_seconds` | 请求超时（秒） |
| `temperature` | 温度参数 |
| `max_output_tokens` | 最大输出 token 数 |
| `style_overrides` | 可选，多行字符串，追加到每次调用的 system prompt 末尾 |

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

基础参数在 `quickquip/chat/config.py` 中（为代码默认值，`chat_rules.toml` 可覆盖）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 滑动窗口大小（秒） |

---

## 贴吧配置

除 `.env` 变量外，贴吧登录态保存在 `data/tieba/storage_state.json`。首次启用前需按部署指南完成登录态导出。
