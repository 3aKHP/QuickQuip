# QuickQuip 配置参考

本文面向部署与运维人员，按**配置文件与作用范围**完整列出 QuickQuip 的所有可配置项。

> **不同配置的维护位置与生效方式总览**：
> 1. **根目录 `.env` 环境变量**：保存端口、连接口令、API Key 等涉密凭据与基础运行参数；修改后需**重启进程或重建容器**生效。
> 2. **LLM 结构化配置数据库（`config/managed/config.db`）**：本文下方的 JSON 片段均为数据库导出 JSON 中的字段结构。通过 Web Admin **“LLM 配置”** 页面编辑或导入完整 JSON 时，保存草稿后需单独应用（完整交换格式见 [LLM 配置管理](llm-configuration.md)）。使用 [qqconf 工作副本](config-workspace.md) 时，先执行 `qqconf pack`：`local` 模式生成暂存，`cloud` 模式写入本地真实配置，再用 `qqsync push` 部署生效。
> 3. **独立 TOML / YAML 配置文件**（如 `generation.toml`、`awakening.toml`、`chat_rules.toml` 等）：按各自章节说明支持热重载或重启生效。

---

## 按任务查找配置

| 想调整什么 | 从这里查 |
|---|---|
| 连接地址、API Key、后台口令 | [.env 环境变量](#env-环境变量) |
| 模型、请求参数和思考档位 | [渠道与模型](#providers--模型渠道与请求参数定义支持多个) |
| 上下文长度、消息分段和记忆 | [全局运行参数](#settingsruntime--全局运行与上下文纪元参数) |
| 工具、Skill 与 MCP | [工具名单](#settingstools--工具调用)、[Skill](#settingsskills--skill-系统)、[MCP](#settingsmcp-与-settingsmcpservers--外部-mcp-工具服务) |
| 定时播报与总结 | [报告设置](#定时群聊报告每日播报--每日总结--群周报--群月报) |
| 图片、语音、音乐与 ASR | [多模态配置](#configgenerationtoml--多模态生成asr-与-svg-画图) |
| 主动搭话、文本回复和游戏 | [唤醒](#configawakeningtoml--群聊低频主动唤醒)、[回复规则](#configchat_rulestoml--正则规则语境规则与接龙)、[游戏配置](game-config.md) |

字段表用于查询。首次配置一个功能时，可先按对应教程完成操作，再回到这里调整参数。

## .env 环境变量

### 基础运行

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DRIVER` | NoneBot2 驱动器；使用正向 WebSocket 连接 OneBot 协议端时必须包含 `~websockets` | `~fastapi+~websockets` |
| `HOST` | QuickQuip 监听地址 | `0.0.0.0` |
| `PORT` | QuickQuip 监听端口 | `8080` |
| `QQ_ACCOUNT` | 机器人 QQ 号（使用项目 Compose 模板启动 LLBot 时必填） | — |
| `ONEBOT_WS_URLS` | OneBot V11 正向 WebSocket 服务端地址列表 | — |
| `ONEBOT_ACCESS_TOKEN` | OneBot 接入鉴权令牌 | — |
| `TZ` | 容器与进程时区（影响日志时间戳、定时任务展示时间等） | `Asia/Shanghai` |

### LLM API Keys 与 MCP 凭据

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI 兼容渠道 API Key |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) 渠道 API Key |
| `GEMINI_API_KEY` | Google Gemini 渠道 API Key |
| `DEEPSEEK_API_KEY` | DeepSeek 渠道 API Key |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub PAT（供 GitHub MCP 服务使用） |
| `GITHUB_TOOLSETS` | GitHub MCP 启用的工具集（逗号分隔），可选：`context`, `repos`, `issues`, `pull_requests`, `users`, `actions` |
| `GITHUB_READ_ONLY` | 设为任意非空值时，强制限制 GitHub MCP 为只读模式 |
| `TAVILY_API_KEY` | Tavily API Key（供 MCP sidecar 的 Tavily 工具使用；未启用 MCP Tavily 时无需填写） |
| `MCP_PRTS_WIKI_TOKEN` | `prts_wiki` MCP 服务的鉴权 Token（详见 [MCP 接入指南](mcp-servers.md) 中的示例） |

### 搜索（SearXNG）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SEARXNG_BASE_URL` | Bot 内置 `search_web` 工具和 `/search` 命令使用的 SearXNG 地址（代码中无内置默认值，未设置时调用会直接报错） | —（`.env.example` 中给出的 `http://127.0.0.1:8888` 仅为示例） |
| `QUICKQUIP_SEARXNG_BASE_URL` | Docker Compose 环境中注入给 QuickQuip / Web Admin 容器内部的 SearXNG 地址（用于避免把宿主机本地直跑的 `127.0.0.1` 错误带进容器内） | `http://searxng:8080` |
| `SEARXNG_SAFE_SEARCH` | 传给 SearXNG 的安全搜索级别：`0` / `1` / `2` | `0` |
| `SEARXNG_LANGUAGE` | 传给 SearXNG 的搜索语言（留空时使用 `all`） | `all` |
| `SEARXNG_PUBLIC_BASE_URL` | Compose 中 SearXNG 对外展示的 Base URL（仅自包含模板 `docker-compose.example.yml` 使用） | `http://127.0.0.1:8888/` |
| `SEARXNG_BIND_ADDRESS` | Compose 暴露 SearXNG 时绑定的宿主机地址（仅 `docker-compose.example.yml` 使用） | `127.0.0.1` |
| `SEARXNG_BIND_PORT` | Compose 暴露 SearXNG 时绑定的宿主机端口（仅 `docker-compose.example.yml` 使用） | `8888` |
| `SEARXNG_SECRET` | SearXNG 实例密钥（用于 SearXNG 容器环境变量） | — |

> **搜索路由与 Gemini 原生搜索补充说明**：
> - 内置工具 `search_web` 与群命令 `/search` 固定调用项目配置的 SearXNG（本地源码直跑读取 `SEARXNG_BASE_URL`；而 `docker-compose.example.yml` 和 `prod.example/docker-compose.yml` 会优先将 `QUICKQUIP_SEARXNG_BASE_URL` 映射注入为容器内的 `SEARXNG_BASE_URL`。Tavily 等外部搜索建议通过 MCP sidecar 暴露为扩展工具）。
> - **Gemini 原生联网特例**：开启了 `builtin_search = true` 的 Gemini 渠道不依赖 SearXNG（联网检索由 Google 服务端 Grounding 直接完成；此时若未配 SearXNG，`/llm health` 中的搜索健康项仍会按内置搜索覆盖判定为 `ok`）。

### LLM 调试与 Trace

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_TRACE_FLAG_FILE` | LLM HTTP Trace 持久化开关文件路径；当该文件存在时，系统会将每次调用的完整请求/响应 JSON 文本记录到 `data/llm_trace.db`，供 Web Admin 的 LLM Trace 页面按需查阅 | — |
| `LLM_TRACE_MEDIA_MIN_BYTES` | Trace 内联媒体自动去重抽取门槛（按载荷原文 UTF-8 字节数计），**推荐启用值为 `65536`（64KB）**；未设置或设为 `0` 时关闭（Bot 和 Web 在启动时读取，详见下一小节） | `0` |

### Trace 媒体存储

当开启 LLM Trace 时，请求正文中若包含图片等 Base64 媒体数据，会导致数据库体积急剧膨胀。你可以在根目录 `.env` 中设置 **`LLM_TRACE_MEDIA_MIN_BYTES=65536`** 并重启 Bot 与 Web，启用**内联媒体去重抽取**：

- **工作原理**：对重启后新产生的 Trace 记录，凡是达到该字节门槛的内联媒体（支持完整 JSON 及 SSE 单行 JSON 中的 `data:` URI 与明确媒体字段），正文中会自动替换为轻量占位符，而原始媒体二进制载荷则按内容哈希去重保存在 **`data/trace_blobs/`** 目录中（启用前已存在的旧记录继续按原格式读取）。
- **数据库与媒体一起备份**：
  - 备份与恢复时，**必须将 `data/llm_trace.db` 数据库与 `data/trace_blobs/` 目录作为同一个整体**：停服后同时备份，恢复时同时还原（标准部署模板已直接挂载整个 `data/` 目录，无需额外配置挂载）。
  - 每个独立的 Trace 数据库使用自己的 `trace_blobs/` 目录，避免一个数据库清理掉另一个仍引用的媒体。
- **关闭与版本回退说明**：
  - 将 `LLM_TRACE_MEDIA_MIN_BYTES` 改回 `0` 并重启，即可停止对新记录做媒体抽取，且当前版本依然能正常读取和还原之前已抽取的记录。
  - 如果需要回退到不支持该去重格式的老版本程序，老程序查看已抽取的记录时只会显示占位符——如果你需要在老版本中查看完整历史报文，请先在当前版本导出原文，或恢复启用该功能前的 Trace 备份（存量历史大记录的离线批量转换另行安排）。
- **管理员还原与附件下载接口**（均需携带有效的 Web Admin 登录会话）：
  - **获取还原后的完整 JSON 正文**：访问 `/ops/api/logs/trace/calls/{call_id}?restore=true`（`call_id` 填详情记录中的实际 ID）。
  - **单独下载媒体附件**：访问 `/ops/api/logs/trace/blobs/{sha256}`（使用占位符中的 SHA-256 摘要；仅允许下载当前仍被有效 Trace 记录引用的媒体载荷）。
  - 在后台执行“清空 Trace”时，会自动删除数据库记录并同步清理无引用的孤立媒体文件；若遇到文件缺失或 SHA-256 校验失败，请优先检查 `llm_trace.db` 与 `trace_blobs/` 是否来自同一次备份。

### 贴吧采集

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TIEBA_ENABLED` | 是否启用贴吧功能 | `false` |
| `TIEBA_FORUM_KEYWORDS` | 监听的多个贴吧名称，支持用逗号、分号、竖线或换行分隔 | — |
| `TIEBA_FORUM_KEYWORD` | 单个贴吧名称（旧版兼容字段，配置多贴吧时优先使用 `TIEBA_FORUM_KEYWORDS`） | — |
| `TIEBA_SYNC_INTERVAL_SECONDS` | 后台自动同步间隔（秒） | `900` |
| `TIEBA_MAX_POOL_SIZE` | 每个贴吧来源在本地池中最多保留的帖子数（最小值为 `20`） | `240` |
| `TIEBA_RECENT_SENT_LIMIT` | 最近已发送帖子记录的保留数量（最小值为 `1`） | `30` |
| `TIEBA_DETAIL_FETCH_LIMIT` | 单次同步抓取帖子详情的数量上限（最小值为 `1`） | `18` |
| `TIEBA_RANDOM_AVOID_RECENT` | 随机抽帖时自动避开最近发送过的 N 条帖子 | `30` |
| `TIEBA_PREFER_IMAGE_THREADS` | 随机抽帖时是否优先选择带图的帖子 | `true` |
| `TIEBA_BROWSER_HEADLESS` | Playwright 浏览器是否以无头模式（Headless）运行 | `true` |
| `TIEBA_BROWSER_CHANNEL` | 指定 Playwright 浏览器 Channel（留空则使用内置默认 Chromium） | — |

### MCP 挂载与环境变量引用

| 变量 | 说明 |
|------|------|
| `MCP_ARXIV_PAPERS_MOUNT` | arXiv MCP Server 论文保存目录的容器卷挂载，格式为 `host-path:container-path`（默认值为 `arxiv-papers:/root/.arxiv-mcp-server/papers`） |

> **MCP 环境变量插值规则**：在配置 MCP Server 时，普通非涉密字段支持 `${ENV_VAR}` 与带默认值的 `${ENV_VAR:-default}` 语法；而涉密认证字段仅支持使用 `${ENV_VAR}` 保存变量引用，真实密钥明文统一在根目录 `.env` 中维护。

### Web Admin 管理后台

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEB_ADMIN_PASSWORD` | Web 管理后台登录口令（**必填**） | — |
| `WEB_ADMIN_HOST` | 后台服务监听地址 | `127.0.0.1` |
| `WEB_ADMIN_PORT` | 后台服务监听端口 | `5104` |
| `WEB_ADMIN_SESSION_TTL_HOURS` | 会话空闲滑动续期有效期（小时） | `168` |
| `WEB_ADMIN_SESSION_MAX_AGE_HOURS` | 会话绝对寿命上限（小时），自创建起超过该时长后必须重新登录 | `168` |
| `WEB_ADMIN_COOKIE_SECURE` | 是否为会话 Cookie 附加 `Secure` 属性：`auto` / `true` / `false` | `auto` |

### Docker 镜像构建相关

| 变量 | 说明 |
|------|------|
| `PIP_INDEX_URL` | 构建镜像时的 pip 安装源（用于配置国内镜像源加速） |
| `PIP_TRUSTED_HOST` | pip 信任的镜像源主机名 |
| `PLAYWRIGHT_BASE_IMAGE` | 自定义 Playwright 基础镜像名称（可包含国内镜像代理前缀） |

> **关于 Docker CLI 与 Socket 挂载**：官方 GHCR 分发镜像和 `docker/Dockerfile.prod` 均基于 Playwright Python 镜像构建，并在镜像内预装了 Docker CLI，以便支持贴吧采集和可选的 MCP `docker` transport。如果你需要使用 MCP 的 `docker` transport，必须在 Compose 中自行将宿主机的 Docker Socket（`/var/run/docker.sock`）挂载进容器（默认 Compose 模板出于安全考虑保持未挂载状态）。

---

## LLM 配置数据库（`config/managed/config.db`）

`config/managed/config.db` 是运行时唯一权威的 LLM 结构化配置来源（JSON 为标准导入/导出交换格式，旧版 `config/llm.toml` 仅作为首次迁移输入及回退到 v1.16.1 时的历史资产保留）。
- **版本管道**：修改配置先保存为草稿（`draft_revision`），点击应用后生成已发布快照（`published_revision`），Bot 进程加载成功后回报实际运行版本（`loaded_revision`）。完整操作、备份与回退说明见 [LLM 配置管理](llm-configuration.md)。
- **字段校验**：下文所有路径均对应完整导出 JSON 的结构；涉密认证字段仅保存根 `.env` 中的环境变量名或 `${变量}` 引用；所有字段的取值范围、枚举与继承能力均由后端 `/ops/api/llm-configuration/metadata` 接口严格定义，越界或非法值在写入时会被直接拒绝。

---

### `settings.runtime` — 全局运行与上下文纪元参数

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 全局 LLM 总开关（注：`config/llm.json.example` 示例中显式设为了 `true`） | `false` |
| `memory_enabled` | 全局长期记忆注入开关 | `true` |
| `default_provider` | 全局默认渠道（Provider）ID | — |
| `default_persona` | 全局默认人格（Persona）ID | — |
| `client_cluster` | 可选的部署集群标识（仅允许可打印 ASCII 字符）；在 `quickquip` Profile 下会映射为 `x-quickquip-cluster` 请求头，见[请求指纹 Profile](client-fingerprints.md) | `""` |
| `claude_code_device_id` | 可选的 Claude Code 设备身份（64 位小写 hex 字符串）；留空时自动使用 `data/client_identity.json` 中的持久化随机身份 | `""` |
| `gemini_cli_install_id` | 可选的 Gemini CLI 安装 UUIDv4；留空时自动使用持久化随机身份，见[请求指纹 Profile](client-fingerprints.md) | `""` |
| `history_limit` | **历史兼容字段**（仅解析，不再参与窗口计算）。默认由下方的“会话纪元（Epoch）”自动管理；当群聊或私聊通过 `/llm context_limit <n>` 手动固定窗口行数时，保留最新 `n` 行（上限 `1024` 条） | `10` |
| `history_max_messages_per_group` | **历史兼容字段**（解析后忽略其值）。对话存储现按会话纪元锚点裁剪，单会话硬上限为 `2048` 行 | `40` |
| `memory_limit` | 单次模型调用最多注入的长期记忆条数 | `6` |
| `memory_max_items_per_group` | 单个群聊最多存储的长期记忆条数硬上限 | `200` |
| `max_prompt_chars` | System Prompt 最大字符数限制 | `4000` |
| `tool_calling_enabled` | 是否允许模型发起工具调用（Tool Calling） | `false` |
| `tool_max_rounds` | 单次对话中工具调用循环（Tool Loop）的最大轮数 | `8` |
| `tool_max_calls_per_round` | 单轮循环内最多允许并发执行的工具调用次数 | `16` |
| `retry_max_attempts` | LLM 请求失败时的最大尝试次数（含首次调用；仅对上游返回 429 / 5xx 或网络错误生效） | `3` |
| `retry_base_delay` | 重试指数退避的基础等待秒数 | `1.0` |
| `retry_jitter` | 重试退避的随机抖动比例（范围 `0`～`1`，设为 `0` 表示关闭抖动） | `0.5` |
| `auto_memory_enabled` | 自动长期记忆抽取的全局默认开关 | `false` |
| `auto_memory_prompt` | 自动记忆抽取的自定义判定 Prompt | `""` |
| `auto_memory_max_tokens` | 自动记忆抽取判定的最大输出 Token 数 | `256` |
| `epoch_context_tokens` | **会话纪元标尺（标准 CTX）**：会话懒初始化与 `/llm use` 切换新模型时的初始锚点 Token 跨度 | `8000` |
| `epoch_cold_idle_seconds` | **冷场缩窗等待时间（T）**：距离该会话／渠道／模型最近一次调用（含工具续轮、失败或取消）开始或结束超过此秒数，且当前窗口大小超过 `epoch_cold_trigger_tokens` 时，触发冷场缩窗 | `300` |
| `epoch_cold_target_tokens` | **冷场目标水位（`L_cold`）**：触发冷场重置后，上下文窗口收缩到的目标 Token 估算值 | `4000` |
| `epoch_cold_trigger_tokens` | **冷场触发水位（`H_cold`）**：进入冷场状态后，窗口 Token 超过此值才会执行缩窗 | `5000` |
| `epoch_hot_target_tokens` | **热聊触顶目标水位（`L_hot`）**：热聊期间窗口触及硬上限重置后，收缩保留到的目标 Token 估算值（用于保护长话题不断片） | `32000` |
| `epoch_cap_tokens` | **窗口硬上限（`H_hot` / `cap`）**：上下文窗口一旦超过此 Token 数，立即触发触顶缩窗重置 | `64000` |
| `recent_context_token_budget` | 单次群聊请求额外带入近期群消息的 token 预算，从最新消息往前选取。仅支持全局设置 | `800` |
| `recent_context_floor_seconds` | 最近多少秒内的群消息可再次补入请求，帮助模型理解当前聊天语境。仅支持全局设置 | `300` |
| `request_input_token_budget` | 单次请求输入预算（应用估算）。优先使用渠道／模型覆盖，其次由模型容量减输出预留推导，最后使用此默认值。超限会先缩减历史；仍超限时停止请求 | `96000` |
| `agent_record_retention_days` | 已结束的对话轮（Closed Loop）在数据库中的保留天数（按结束时间计算） | `30` |
| `agent_record_max_loops_per_scope` | 每个会话最多保留的已结束 Loop 数量上限（当数量或下方字节数任一触顶时，自动清理最旧的完整 Loop，并同步推进受影响的活动纪元） | `1000` |
| `agent_record_max_bytes_per_scope` | 每个会话的 Loop 业务记录最大字节数上限（按 UTF-8 字节计量，默认 64 MiB） | `67108864` |
| `agent_replay_loop_tokens` | 历史工具对话回放预算的推导下限，范围 `512`～`4194304` token；渠道或模型可显式覆盖实际回放预算。超限时精简较早历史，计算过程见[预算实现](../dev/llm-module.md#预算参数与历史收缩) | `4096` |
| `agent_delivery_intermediate_enabled` | **多轮工具调用“中间过程回复”全局默认开关**：设为 `true` 时，模型在调用工具前输出的非最终轮过渡文字会实时先发到群里；设为 `false` 时，中间轮文字仅记录在数据库中不外发（标记为 `suppressed_by_policy`） | `false` |
| `agent_delivery_final_enabled` | **最终回复“按自然段拆分多条发送”全局默认开关**：设为 `true` 时，最终长回复会按自然段拆成多条 QQ 消息依次发送；设为 `false` 时整条合并发送。<br>*(注：以上两个交付开关相互独立；从旧版迁移时原有的 `agent_delivery_enabled` 会同时赋给这两个开关。各群或私聊可通过 `/llm delivery intermediate/final/all ...` 命令或后台“群 LLM”页按会话单独覆盖。)* | `false` |
| `reply_split_threshold_chars` | 开启分段发送后，回复总长度超过多少个字符（Unicode code points）才触发自然分段 | `800` |
| `reply_chunk_max_chars` | 分段发送时，单段源文本的最大字符数上限（独立于 OneBot 协议报文限制） | `1200` |
| `reply_send_interval_ms` | 同一会话内连续发送多段消息时，相邻两次发送开始时间的最小间隔毫秒数（范围 `0`～`10000`） | `800` |
| `reply_max_chunks_per_loop` | 单次对话循环最多允许向外交付的消息条目总数上限（含文本段、图片/媒体与提示通知，范围 `1`～`256`） | `64` |
| `mention_cooldown_seconds` | 机器人出站 `@群成员` 的同目标冷却秒数：在冷却时间窗内重复 `@` 同一个人会被自动降级为纯文本称呼（范围 `0`～`86400`，设为 `0` 关闭冷却） | `600` |

> **会话纪元（`epoch_*`）覆盖与数学约束**：
> - 上表中的 **6 个 `epoch_*` 参数**均支持在单个渠道或模型的 `parameters` 对象中同名覆盖（例如为缓存较长但对冷场不敏感的渠道单独调大 `epoch_cold_idle_seconds`），未覆盖的字段自动继承全局 `settings.runtime` 的值；而 2 个 `recent_context_*` 参数仅限全局配置，不支持渠道覆盖。
> - **合法性不等式约束**：所有生效的纪元水位必须严格满足 **`0 < cold_target < cold_trigger ≤ hot_target < cap`** 且 **`context_tokens > 0`**，违反该大小关系的写入会被配置校验直接拒绝。建议结合后台“用量”页的缓存命中率与“纪元”页的重建事件来微调冷场时间。

---

### `settings.triggers` / `auto_search` / `quick_judge` — 触发与快速判定

#### 1. `settings.triggers` — 群聊触发方式

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `default_prefix` | 显式唤醒 AI 的命令前缀 | `/ai` |
| `allow_prefix` | 是否允许通过命令前缀触发 | `true` |
| `allow_at` | 是否允许通过 `@机器人` 触发 | `true` |
| `empty_prompt_reply` | 用户只发了前缀或只 `@` 了机器人但没说话时的默认提示语 | `请在触发指令或艾特后面补上想说的话。` |

#### 2. `settings.auto_search` — 自动联网判定

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 是否启用自动联网搜索判定 | `false` |
| `search_max_calls_per_round` | 单轮对话最多允许执行的搜索调用次数（范围 `1`～`32`） | `3` |

#### 3. `settings.quick_judge` — 轻量快速判定模型

用于 `chat_rules.toml` 中的 `llm_context` 语境规则判定、以及低频唤醒模块中的“话题相关性 / 答疑唤醒”等超短 Prompt 分类场景：

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `provider_id` | 快速判定专用的渠道 ID（留空则使用全局默认渠道） | `""` |
| `model` | 快速判定专用的模型名（留空则使用对应渠道的默认模型） | `""` |
| `timeout` | 单次判定请求超时秒数 | `2.0` |
| `max_tokens` | 单次判定最大输出 Token 数 | `64` |

> **快速判定的容错与思考模型避坑指南**：
> - **Fail-Closed 与缓存策略**：如果快速判定发生任何技术性失败（超时、API 报错、返回空正文、输出被截断、或返回了非法 JSON），系统一律按**“未触发（false）”**安全处理，且**不会**将这次失败写入 60 秒判定结果缓存中；只有成功解析出明确的业务 `true` / `false` 结果时才会写入缓存。
> - **切勿直接用默认参数跑带 Reasoning（思考）的模型！** 如果你把快速判定指向了一个强制开启思考链的模型，思考过程消耗的 reasoning tokens 也会计入 `max_tokens` 且首字延迟更高——请务必同时调大 `max_tokens`（如设为 `256`）和 `timeout`（如设为 `6.0` 秒），否则会出现“Token 预算全被内部思考耗尽、最终可见判定输出为空”以及大面积超时。

---

### `settings.image_preprocessing` — 非视觉模型图片转述

当当前群聊所使用的主对话模型不支持视觉能力（即模型条目配置了 `vision = false`）时，系统会自动先调用这里指定的**前置视觉模型**，将消息中的图片转述为带有来源和序号标签的文字描述，再拼入上下文交给非视觉主模型回答（若主模型本身 `vision = true`，则直接接收原图，完全不经过此转述层）。

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 是否启用非视觉模型的前置图片转述功能 | `false` |
| `provider_id` | 提供视觉识别能力的渠道 ID | `""` |
| `model` | 视觉模型 ID（留空则使用该渠道的默认模型） | `""` |
| `max_tokens` | 单张图片转述文本的最大输出 Token 上限（允许写入范围：`80`～`2048`） | `300` |
| `temperature` | 图片转述请求的采样温度 | `0.3` |
| `prompt` | 自定义图片转述 System Prompt（留空则使用内置默认提示词） | `""` |

- **单轮图片上限与失败处理**：单轮请求最多转述处理 **5 张**图片（按“当前消息图片 $\rightarrow$ 引用消息图片 $\rightarrow$ 合并转发图片”顺序选取；被动唤醒需要附带近期群图片时，会利用剩余名额挑选最新图片）。如果本轮中**有任何一张图片转述失败**，为避免主模型基于残缺信息胡言乱语，本轮将中止调用主模型，并向用户返回可重试提示。

---

<a id="settingstools--工具调用"></a>

### `settings.tools` — 工具白名单与按需发现（Tool Discovery）

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | 自定义工具名单列表。为空数组 `[]` 时，默认暴露所有内置默认白名单工具 + 全部已启用的 MCP 工具；非空时按下方 `enabled_mode` 规则生效 | `[]` |
| `enabled_mode` | 当 `enabled` 非空时的作用模式：<br>• **`append`（默认，追加模式）**：在内置默认白名单 + 全部 MCP 工具的基础上，额外启用列入的可选内置工具（例如开启 `draw_svg` 画图工具只需用此模式）；<br>• **`replace`（替换模式）**：严格精确白名单，仅向模型暴露 `enabled` 中明确列出的工具 | `append` |
| `discovery_mode` | 工具按需发现模式（用于节省海量 MCP 工具占用的上下文 Token）：<br>• `off`：全量直接暴露所有工具定义；<br>• `on`：仅暴露常驻工具（`always_loaded`），其余工具通过 `tool_search` 按需动态加载；<br>• `auto`（默认）：当可延迟加载的工具数量超过 `discovery_min_tools` 阈值时自动启用按需发现 | `auto` |
| `discovery_min_tools` | `auto` 模式下触发按需发现的“可延迟工具”数量阈值 | `10` |
| `discovery_search_limit` | 模型单次调用 `tool_search` 最多返回并加载的工具数量 | `5` |
| `discovery_max_loaded_tools` | 单次会话中允许同时加载的工具总数上限（含常驻工具；达到该上限后停止新增加载，已加载的工具集合保持可用） | `12` |
| `always_loaded` | 开启工具发现时，第一轮就直接暴露给模型的常驻工具名列表（未配置时使用右侧内置默认集合） | `["tool_search", "tool_list", "get_identity", "list_memories", "search_web", "activate_skill"]` |

> **本地元工具工作原理与 v1.12 升级提示**：
> - `tool_search` 和 `tool_list` 是 QuickQuip 本地实现的元工具（不依赖 Claude 原生的服务端 tool search 特性）。当接入了庞大的 MCP 工具集时，模型会先调用 `tool_search` 按关键词搜索相关工具；若搜不到，还可调用 `tool_list` 浏览工具分组、工具名称或按精确名称加载工具，然后在下一轮 Tool Loop 中直接调用刚刚被加载进上下文的真实工具（详见专题文档 [tool-discovery.md](tool-discovery.md)）。
> - **`enabled_mode` 历史版本升级说明（v1.11 $\rightarrow$ v1.12）**：在 v1.11 及更早版本中，只要 `enabled` 非空就会变成严格的 `replace` 替换白名单，导致没写进去的 MCP 工具被全部过滤掉。自 v1.12 起默认改为了 **`append`（追加模式）**——因此启用 `draw_svg` 等可选工具时不再会误杀 MCP 工具；如果你确实需要严格的精确白名单过滤，请显式设置 `enabled_mode = "replace"`。

---

### `providers` — 模型渠道与请求参数定义（支持多个）

`providers` 是一个有序的渠道数组。其中**协议、接口地址、客户端指纹与认证方式**固定在渠道（Provider）层维护；而**请求参数（`parameters`）**既可以在渠道层设置默认值，也可以在单个模型（`models[].parameters`）中按同名字段覆盖。

- **五层参数优先级（从高到低）**：`单次调用/群会话覆盖 → 模型级 parameters → 渠道级 parameters → 负责该字段的全局设置 → 系统内置默认`。
- **空值语义**：覆盖字段设为 `null` 代表继承上一层；显式设为 `""`、`{}`、`false` 或合法的 `0` 均代表明确覆盖为该值（`extra_body` 在模型层覆盖时采用**整块对象替换**）。

#### 1. 渠道层固定字段（`providers[]`）

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `id` | 渠道唯一标识 ID（如 `openai-main`、`gemini-main`） | — |
| `protocol` | 协议类型：`openai` / `claude` / `gemini` / `openai_responses` | — |
| `base_url` | 上游 API 根地址 | — |
| `api_key_env` | 存放 API Key 的根目录 `.env` 环境变量名称 | — |
| `default_model` | 该渠道的默认模型 ID | — |
| `models` | 有序的模型对象数组，每个元素可包含：`model`（实际模型名）、`enabled`（是否启用）、`vision`（是否支持图片输入，默认 `true`）、`context_window`（上下文窗口容量，`null` 时按内置模型家族表自动识别）、`parameters`（模型级参数覆盖） | `[]` |
| `enabled` | 是否启用该渠道。设为 `false` 停用后：不会出现在群内 `/llm providers` 或 `/llm models` 列表中、不参与探活、路由级联自动跳过、且拒绝 `/llm use` 切换；但渠道配置本身保留在库中，随时改回 `true` 即可恢复 | `true` |
| `aliases` | 有序的模型别名数组，例如 `[{"alias": "gpt4", "model": "gpt-5.4"}]` | `[]` |
| `headers` | 注入到每次 HTTP 请求中的额外自定义请求头 | — |
| `client_fingerprint` | 选择该渠道使用的请求指纹 Profile（详见[请求指纹 Profile](client-fingerprints.md)） | `default` |
| `fallback_urls` | 备用 Base URL 列表；当主地址返回 5xx 或发生网络错误时自动按序切换重试 | `[]` |
| `proxy` | HTTP(S) 代理服务器地址（如 `http://127.0.0.1:7890`），该渠道的所有请求（含 Fallback 重试）均走此代理 | — |
| `auth_method` | 鉴权传输方式：`api_key` 或 `bearer`。<br>• **Claude**：分别对应 `x-api-key` 头与 `Authorization: Bearer` 头；<br>• **Gemini**：选 `api_key` 时由 Profile 决定（新版默认 `gemini-cli` 使用 `x-goog-api-key` 头，`legacy-gemini` 使用 URL `?key=`），显式选 `bearer` 时使用 `Authorization: Bearer` 头；<br>• **OpenAI / Responses**：统一使用 Bearer 头 | `api_key` |
| `parameters` | 渠道级默认请求参数对象（见下表；模型内的同名 `parameters` 可覆盖） | `{}` |

#### 2. 渠道与模型共享的请求参数（`parameters` 对象）

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `timeout_seconds` | 单次 HTTP 请求超时时间（秒） | `45` |
| `temperature` | 采样温度参数 | `0.8` |
| `max_output_tokens` | 单次回答最大输出 Token 数 | `800` |
| `style_overrides` | 可选的多行字符串，会直接追加到每次调用的 System Prompt 最末尾 | — |
| `style_profile` | 可选，引用 `style_profiles` 中预定义的共享风格段名称（与 `style_overrides` 拼接生效） | — |
| `stream_enabled` | 是否启用 SSE 流式响应 | `true` |
| `user_agent` | 最高优先级的自定义 `User-Agent` 请求头 | — |
| `extra_body` | 注入到每次请求 JSON Body 中的额外自定义键值对象（模型层覆盖时整块替换） | — |
| `prompt_caching` | 是否启用 Anthropic Prompt Caching 断点打点（**仅 `claude` 协议生效**，需上游或中转站支持 CLI 缓存格式） | `false` |
| `cache_ttl` | Claude Prompt Cache 的生存期：留空 `""` 默认为 5 分钟，填 `"1h"` 使用 1 小时扩展缓存（**仅 `claude` 协议生效**） | `""` |
| `builtin_search` | 是否启用服务商原生联网搜索（**仅 `gemini` 协议生效**）：开启后请求会携带 `google_search` 声明，并在回复末尾自动附上 Grounding 来源链接；同时该渠道会话会自动移除本地 `search_web` 工具并切换提示词引导（其他协议配置此项无效并会记录 warning；检索在 Google 侧执行并计费，不计入本地轮次与 Token 看板）。<br>⚠️ **Gemini 版本兼容性警告**：将 `google_search` 与工具调用（Function Calling）放在同一次请求中混用，**仅 Gemini 3 系列模型支持**！如果你使用的是 Gemini 2.x 模型，必须关闭 `builtin_search` 或关闭全局 `tool_calling_enabled`，否则请求会被 Google API 直接拒绝 | `false` |
| `responses_profile` | **`openai_responses` 协议专属后端能力档位**：<br>• `openai-public`（默认）：对接官方 `/v1/responses` 接口；<br>• `codex-http-relay`：对接 Codex 形态的第三方中转网关（不发送 `service_tier`、容忍 `codex.*` 扩展事件、当终态事件缺省字段时以流式完整收集的 item 作为历史回放基准） | `openai-public` |
| `reasoning_effort` | **思考档位（全协议通用）**：可选 `low` / `medium` / `high` / `xhigh` / `max` / `ultra`，留空 `""` 表示不发送思考参数（使用模型自身默认档）。系统会根据协议和模型家族自动翻译为对应的底层参数并做超档钳制（详见下方映射表）。支持在群内用 `/llm effort <档位>` 按群覆盖（`/llm effort default` 恢复跟随；`/llm status` 可查看“配置档 / 覆盖档 / 实际生效档”三层状态），也可在 Web 后台“群 LLM”页按群设置 | `""` |
| `max_inline_media_bytes` | **单次请求内联图片总解码字节预算**（设为 `0` 表示不限制，详见下方媒体预算说明） | `5242880` (5 MiB) |
| `epoch_*` / 预算键 | 支持同名覆盖 `settings.runtime` 中的 6 个 `epoch_*` 水位键，以及 `request_input_token_budget` 和 `agent_replay_loop_tokens` | `null` (继承全局) |

#### 渠道与模型的 JSON 层级示例

在编辑完整导出 JSON 文件时，连接属性放在渠道顶层，模型专属的温度覆盖放在对应 `models[].parameters` 内：

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

---

#### 思考档位跨协议映射

QuickQuip 内部统一的 6 个思考档位（`low` $\rightarrow$ `ultra`）在发送给不同协议后端时，会自动按以下矩阵翻译并钳制（注：`ultra` 是 Codex 订阅客户端的产品层档位，所有公开 API 的词表最高均止步于 `max`，因此任何渠道选 `ultra` 都会在底层自动降为 `max`）：

| 内部档位 (`reasoning_effort`) | OpenAI Chat<br>（顶层 `reasoning_effort`） | Claude 4.7+<br>（`adaptive` + `output_config.effort`） | Claude 4.6<br>（Opus / Sonnet） | Claude ≤ 4.5<br>（旧式 `budget_tokens`） | Gemini 3.x<br>（`thinkingLevel`） | Gemini 2.5<br>（`thinkingBudget`） |
|---|---|---|---|---|---|---|
| **`low`** | `low` | `low` | `low` | `1024` | `LOW` | `1000` |
| **`medium`** | `medium` | `medium` | `medium` | `2000` | `MEDIUM` | `2000` |
| **`high`** | `high` | `high` | `high` | `8000` | `HIGH` | `8000` |
| **`xhigh`** | `xhigh` | `xhigh` | `high`（自动钳制） | `16000` | `HIGH` | `16000` |
| **`max`** | `max` | `max` | `max` | `32000` | `HIGH` | `32000` |
| **`ultra`** | `max` | `max` | `max` | `32000` | `HIGH` | `32000` |

**各协议与模型家族的特殊钳制规则**：
- **OpenAI Chat 按模型家族二次钳制**：
  - **DeepSeek / GLM-5.3 / Kimi k3（三档系）**：`medium` 与 `xhigh` 自动映射为 `high`，`max`/`ultra` 映射为 `max`（其中 DeepSeek 会同时自动附带 `thinking.type = "enabled"` 开关）；
  - **MiniMax**：支持 `low` 到 `max` 五档全集；
  - **xAI (Grok)**：最高钳制到 `xhigh`；
  - **其余后端**：原样透传上表列出的五档名称。
- **OpenAI Responses 按 `responses_profile` 钳制**：`openai-public` 最高支持并钳制到 `xhigh`；`codex-http-relay` 支持到 `max`（`ultra` 自动降为 `max`，因实测中转网关校验层会拒绝 `ultra`）。
- **Claude 旧式 `budget_tokens` 的下限保护与温度互斥**：
  - Claude ≤ 4.5 的 `budget_tokens` 必须满足 **`≥ 1024` 且 `< max_output_tokens`**。如果该渠道或模型配置的 `max_output_tokens` 太小，导致计算出的思考预算跌破 `1024`，系统会在本次请求中**自动放弃发送思考参数并记录一条 warning 日志**（这是归一化层唯一会自动省略思考参数的场景，其余所有情况一律按表照发）。
  - **Anthropic 温度契约**：当 Claude 思考档位开启生效时，Anthropic API 强制要求只能使用默认温度，因此 QuickQuip 会自动省略非默认的 `temperature` 参数并记录日志。
- **Gemini 2.5 Flash 预算上限**：Gemini 2.5 Flash 系列的 `thinkingBudget` 硬上限为 `24576`（Pro 系列为 `32768`），超出时会自动向下钳制。

---

#### 各协议思考参数支持面（2026-10 调研与排障参考）

如果某个模型后端不支持你设置的思考档位，上游 API 通常会直接返回 HTTP `400` 等 4xx 错误。遇到此类报错时：
1. 先在群内发送 `/llm effort default` 清除本群的会话级档位覆盖；
2. 若仍报错，说明渠道/模型默认配置的 `reasoning_effort` 不受该模型支持，请进入 Web 后台清空该渠道/模型的 `reasoning_effort` 字段（留空），保存草稿并应用，让模型使用自身默认行为。

以下为 2026-10 调研的各后端支持情况，供排障参考：
- **Claude 官方协议**：Extended Thinking 自 **Claude 3.7** 代际引入（3.5 及更早模型无思考能力，若配置了档位下发 budget 会被上游拒绝）；而 **Claude 4.7+ / 5 系**仅接受新版 `adaptive + effort` 格式，若发送旧版 `type: "enabled"` 会直接报 `400`。
- **Claude 兼容第三方端点（Kimi k3 / MiMo m2.5 / GLM Coding Plan 等）**：
  - 这些面向 Claude Code 客户端设计的 Anthropic 兼容端点，对接收 `adaptive + effort` 并映射为自家思考档位有实测旁证，具体支持情况以所用端点为准。但请注意：**一旦在配置中开启了思考档位，QuickQuip 就会遵循 Anthropic 契约不再下发非默认的 `temperature`**（哪怕上游中转站实际上忽略了思考参数，你的自定义温度也不会下发）。
  - **历史对话兼容问题**：某些兼容端点会拒绝历史 thinking 内容。若只在多轮工具对话中出错，请结合 Trace 核对返回的错误和历史内容；Claude 适配器没有自动剥离历史推理后重试的处理。历史保留与降级规则见[开发说明](../dev/llm-module.md#历史回放的协议约束)。
- **Gemini 协议**：`thinkingLevel` 仅适用于 **Gemini 3.x**；**Gemini 2.5** 仅认识 `thinkingBudget`；而 **Gemini 2.0** 系列完全不支持思考参数（配置后会报错），且 `thinkingLevel` 与 `thinkingBudget` 绝不能同时发送。

---

<a id="多模态媒体预算与-gemini--responses-工具回放机制"></a>

#### 图片预算与多轮对话排障

`max_inline_media_bytes` 限制一次请求中全部内联图片解码后的总字节数，默认 5 MiB，`0` 表示不限。用户图片和工具结果共用预算。超限图片会先尝试压缩，仍放不下时跳过它和后续低优先级图片；优先保留当前提问、引用和近期消息里的图片。

如果上游提示请求体过大，可以调小该值。图片经过 Base64 编码后体积约增加三分之一，另外还要计入文本与工具定义。压缩和媒体组装的具体规则见[图片输入实现](../dev/llm-module.md#43-图片输入边界)。

Gemini 和 Responses 需要完整的工具调用与结果配对。工具批次超过轮次上限时会停止本轮，排障时检查 `tool_max_calls_per_round` 和模型返回的工具数。Responses 对符合条件的历史推理错误会去除历史 reasoning 后重试一次；Claude 不采用这条重试路径。完整条件见[历史回放说明](../dev/llm-module.md#历史回放的协议约束)。

---

### `style_profiles` — 共享回复风格段

用于定义可被多个渠道或模型复用的 System Prompt 风格指令段落（多行字符串），渠道或模型通过 `parameters.style_profile` 键名进行引用：

```json
{
  "style_profiles": {
    "my_family": "……共享风格指令条目……\n"
  },
  "providers": [
    {
      "id": "my-provider",
      "parameters": {
        "style_profile": "my_family",
        "style_overrides": "……该渠道专属追加指令……"
      }
    }
  ]
}
```

- **拼接顺序**：`style_profile` 共享段落排在前面，`style_overrides` 专属追加段落排在后面，两者合并后附加到每次调用的 System Prompt 最末尾。
- **空字符串占位**：将某个 `style_profile` 的内容设为空字符串 `""` 是完全合法的（相当于声明一个空占位符，不注入任何额外文本，方便日后统一调校）。
- **引用完整性**：引用不存在的 `style_profile` 名称，或者直接删除仍被渠道/模型引用的 `style_profile`，在保存时都会返回依赖冲突报错。`config/llm.json.example` 随附了按模型谱系命名的四个内置示例家族（`openai_family` / `gemini_family` / `claude_family` / `general`），可直接复用或修改。

---

### `pricing` — 模型定价表（成本统计来源）

采用 **每百万 Token 美元单价（USD / MTok）** 计价，是 Web Admin“用量”页计算美元成本（`cost_usd`）的唯一价格来源：

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

| 键名 | 说明 |
|----|------|
| `provider_id` | 已存在的渠道 ID（必填，非空字符串） |
| `model` | 该渠道实际发出请求时使用的模型 ID（**同名模型在不同渠道下必须分别独立定价**） |
| `input_per_mtok` | 普通输入单价（USD / 百万 Token） |
| `output_per_mtok` | 输出单价（USD / 百万 Token） |
| `cache_read_per_mtok` | 缓存命中读取单价（可选；设为 `null` 或省略时，自动回退按 `input_per_mtok` 普通输入价计算） |
| `cache_write_per_mtok` | 缓存写入单价（可选；无缓存写入溢价的模型可省略，回退按 `input_per_mtok` 计算） |

- **计费匹配规则**：严格按 **`(provider_id, 本次请求发出的 model 名)`** 精确匹配，上游响应中如果改写了模型名称（如去掉前缀或返回日期快照名）不影响匹配。免费模型请显式填 `0`；未配置价格记录的模型会在用量页标记为“未定价”（成本暂计为 0）。
- **JSON 格式版本（`format_version: 2`）**：当前导出 JSON 为版本 `2`。当导入旧版（`format_version: 1`）JSON 时，后端会自动把能明确归属的旧版全局兜底价转换到具体渠道下，并在导入预览报告中逐条列出归属与移除结果（详见 [LLM 配置管理](llm-configuration.md#模型参数与引用)）。

---

### `settings.skills` — Skill 系统

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | Skill 系统全局总开关 | `true` |
| `catalog_dir` | Skill 存放目录；留空 `""` 表示使用项目根目录下的 `skills/`（若填相对路径则按项目根解析） | `""` |
| `catalog_max_bytes` | 系统提示词中注入 Skill 名称与描述清单的最大字节预算（实际生效预算取 `min(模型上下文窗口的 2%, 此值)`） | `8192` |
| `resource_max_bytes` | `read_skill_resource` 工具单次读取文件的最大字节上限 | `65536` |
| `search_max_results` | `search_skill_resources` 工具单次检索返回的最大命中条数 | `50` |
| `search_max_output_bytes` | `search_skill_resources` 工具单次检索输出的最大字节上限 | `32768` |
| `script_timeout_ms` | `run_skill_script` 执行脚本的默认超时毫秒数（单次调用可另行指定，但最高不得超过硬上限 `120000` 毫秒） | `30000` |
| `script_max_output_bytes` | 脚本 `stdout` 与 `stderr` 各自的最大输出字节上限（超限部分自动截断） | `65536` |

> 若 `skills/` 目录为空或不存在，Skill 工具不会注册，系统提示词也保持不变。完整部署与安全说明见 [skills.md](skills.md)。

---

### `settings.mcp` 与 `settings.mcp.servers` — 外部 MCP 工具服务

#### 1. `settings.mcp` — 总开关
| 键名 | 说明 |
|----|------|
| `enabled` | 是否全局启用 MCP 外部工具接入 |

#### 2. `settings.mcp.servers[]` — 单个 MCP Server 定义（支持多个）

| 键名 | 适用 Transport | 说明 | 默认值 |
|----|------|--------|------|
| `id` | 全部 | MCP Server 唯一标识 | — |
| `transport` | 全部 | 传输方式：`stdio` / `docker` / `http` / `sse` | — |
| `enabled` | 全部 | 是否启用该 Server | `true` |
| `timeout_seconds` | 全部 | 连接与工具调用超时秒数 | `30` |
| `tool_prefix` | 全部 | 自定义该 Server 生成的工具名前缀（留空则自动使用 Server `id` 作为前缀） | `""` |
| `include_tools` | 全部 | 允许暴露的工具白名单（支持写 MCP 原始工具名或加上前缀后的 QuickQuip 工具名；留空 `[]` 表示默认接入该 Server 的全部工具） | `[]` |
| `exclude_tools` | 全部 | 要排除的工具黑名单（在 `include_tools` 白名单过滤之后生效） | `[]` |
| `allowed_tools` | 全部 | 旧版兼容白名单字段（新配置请统一使用 `include_tools`） | — |
| `url` | `http` / `sse` | 远端 MCP 服务端点 URL（`http` 与 `sse` 模式下**必填**） | — |
| `headers` | `http` / `sse` | 注入 HTTP 请求的自定义 Header（值支持 `${ENV_VAR}` 或 `${ENV_VAR:-default}`） | — |
| `negotiation` | 仅 `http` | 协议版本协商模式：`legacy`（默认）/ `auto` / `modern` | `legacy` |
| `protocol_version` | 仅 `http` | 当 `negotiation = "legacy"` 时，`initialize` 握手固定使用的协议版本 | `"2025-03-26"` |
| `supported_protocol_versions` | 仅 `http` | 当 `negotiation` 设为 `auto` 或 `modern` 时，客户端声明可接受的协议版本列表（这两种模式下**必填**） | — |
| `command` | `stdio` | 本地子进程启动命令 | — |
| `args` | `stdio` / `docker` | 启动命令参数数组 | `[]` |
| `cwd` | `stdio` | 本地子进程工作目录（留空使用默认目录） | — |
| `env` | `stdio` / `docker` | 注入给子进程或容器的环境变量键值对（支持 `${ENV_VAR}` / `${ENV_VAR:-default}`） | `{}` |
| `image` | `docker` | 要运行的 Docker 镜像名称 | — |
| `mounts` | `docker` | 容器卷挂载列表，格式为 `host:container` 或 `host:container:ro` | `[]` |
| `docker_args` | `docker` | 额外的 `docker run` 参数数组 | `[]` |
| `docker_command` | `docker` | 调用的 Docker 可执行命令名称 | `docker` |
| `pull_policy` | `docker` | 镜像拉取策略：`always` / `missing` / `never` | `missing` |
| `network` | `docker` | 容器网络模式（如 `"host"`；留空使用 Docker 默认网桥） | — |
| `container_workdir` | `docker` | 容器内部工作目录（留空使用镜像默认 WORKDIR） | — |

> **最佳实践建议**：当接入像 GitHub MCP 这样包含数十个工具的大型 Server 时，生产环境强烈建议先用 `include_tools` 将范围收窄到安全的只读类工具，再配合 `settings.tools.discovery_mode` 让模型通过 `tool_search` / `tool_list` 按需加载。

---

### 定时群聊报告（每日播报 / 每日总结 / 群周报 / 群月报）

#### 1. `settings.daily_briefing` — 每日早午晚播报

| 键名 | 说明 |
|----|------|
| `enabled` | 全局总开关（`true` / `false`） |
| `morning_cron` / `noon_cron` / `evening_cron` | 早报、午报、晚报的 5 段式 cron 表达式 |
| `min_messages_for_llm` | 触发 LLM 生成播报所需的最小群消息数 |
| `active_users_limit` / `hot_words_limit` / `sample_messages_limit` | 注入给模型的活跃用户数上限、热词数上限、消息样本数上限 |
| `max_context_chars` / `max_output_chars` | 送给模型的上下文字符上限与最大输出字符数 |
| `routes.daily_briefing` | 每日播报专属的模型级联候选列表（按序尝试，失败自动降级） |

#### 2. `settings.daily_summary` — 每日总结

| 键名 | 说明 |
|----|------|
| `enabled` | 全局总开关（`true` / `false`） |
| `generate_cron` / `publish_cron` | 后台生成总结的 cron 表达式，以及发往群内的发布 cron 表达式 |
| `min_messages` | 当日最小群消息数（不足时自动跳过不生成） |
| `summary_length_hint` | 提示模型生成的目标字数 |
| `routes.daily_summary` | 每日总结专属的有序模型级联候选列表 |

#### 3. `settings.weekly_report` / `settings.monthly_report` — 群周报与群月报

每周一（周报）／每月 1 日（月报）自动基于持久化的聊天记录归档库 `data/chat_archive.db` 生成上一周期的群聊回顾（周报、月报与每日总结三者完全独立，可分别开启；群内管理员可通过 `/summary weekly|monthly on|off|status|now` 按群开关或立即生成；周期标识格式分别为 ISO 周号 `2026-W24` 与年月 `2026-06`）：

- **周报与月报的聊天记录预处理差异**：
  - **群周报**：将整周聊天记录按天分节，自动合并同一分钟内的连续发言、折叠复读机消息并缩短长 URL 后交给模型。
  - **群月报（自然周预算分配算法）**：默认终稿输入预算约为 **24 万字符**。系统会将预算按自然周均分：在每一周内部，**优先完整保留发言较少的“平静日”记录**，然后按消息量从多到少依次处理“高活跃日”——如果剩余额度装得下就完整保留，装不下则进行等距抽样，额度耗尽则跳过剩余日期。

| 键名 | 说明 | 默认值（周报 / 月报） |
|----|------|--------|
| `enabled` | 全局总开关 | `false` |
| `generate_cron` | 报告生成 cron 表达式 | 周报：`0 9 * * 1`（每周一 09:00）<br>月报：`0 9 1 * *`（每月1日 09:00） |
| `publish_cron` | 报告发布 cron 表达式（周报与月报共用，每天检查发布新报告并补发未发布的报告） | `0 10 * * *`（每天 10:00） |
| `min_messages` | 周期内触发生成的最小消息数门槛 | 周报：`100` / 月报：`300` |
| `length_hint` | 目标生成字数提示 | 周报：`2000` / 月报：`2500` |
| `input_char_budget` | **月报专属**：月报终稿聊天记录字符总预算（最小值为 `8000`） | `240000` |
| `routes.weekly_report` / `routes.monthly_report` | 各自独立的有序模型级联候选列表（支持 `"@default"` 动态解析） | — |

> **所有报告级联路由（`routes.*`）的完整性与输出配额要求**：
> - **生成中断后的处理**：级联列表中的候选模型按顺序尝试；如果输出提前截断或以非正常 `finish_reason` 结束，系统丢弃这次正文，继续尝试下一个候选模型。
> - **每跳模型输出上限（`max_output_tokens`）硬门槛**：系统会根据每一跳候选模型自己的 `context_window` 动态推导输入容量与输出上限；其中默认请求的输出上限为：**每日总结 `16384` tokens**，**每日播报与周/月报 `8192` tokens**。如果级联列表里某个模型支持的最大输出配额低于上述数值，轮到该跳时会直接报错——因此请确保放入 `routes.*` 的候选模型都能接受对应的输出 Token 上限（保存配置时会统一校验所有 `routes.*` 引用的渠道与模型是否存在，哪怕该报告功能当前处于关闭状态）。

---

## `config/generation.toml` — 多模态生成、ASR 与 SVG 画图

该文件独立负责**图片生成、语音合成（TTS）、语音识别（ASR）、音乐生成和 SVG 画图**配置（首次从旧版迁移时会自动将旧 TOML 中的内联多模态段落提取生成到此文件；若该文件不存在，上述多模态能力默认全部处于关闭状态）。

> **双重敏感词合规过滤**：
> 图片、语音和音乐各自配置的 `prompt_blocklist` 是生成业务专属的提示词黑名单；此外，只要项目配置了 `config/sensitive_words.toml`，所有的生成 Prompt、歌曲标题、歌词和引用文本在调用前还会统一经过部署级敏感词过滤（仅检查文本，不审核图片像素或音频波形）。

### 1. `[image]` 与 `[[image.providers]]` — 图片生成（`/draw`）

- **`[image]` 全局段**：包含 `enabled`（总开关）、`default_model`（默认模型 ID）、`prompt_blocklist`（提示词黑名单数组）。
- **`[[image.providers]]` 渠道数组**：包含 `id`、`protocol`、`base_url`、`api_key_env`、`timeout_seconds`。
- **`[[image.providers.models]]` 模型数组**：

| 键名 | 说明 |
|----|------|
| `id` | 模型唯一标识（用于 `default_model` 引用以及群内 `/draw <id>` 指定模型） |
| `label` | 可选的展示名称 |
| `model` | 实际传给上游 API 的模型名称 |
| `size` | 图片尺寸（在 `openai_images` / `gemini_imagen` 协议下填如 `1024x1024`；在 `minimax_images` 协议下填宽高比） |
| `quality` | 画质档位（仅 `openai_images` 协议有效，如 `standard` / `hd`） |
| `response_format` | 返回格式（仅 `openai_images` 协议有效：默认 `b64_json` 或 `url`） |

---

### 2. `[audio]` — 语音合成（TTS）

`[audio]`、`[[audio.providers]]` 与 `[[audio.providers.models]]` 的层级结构与图片一致；模型对象额外支持 `voice_id`、`sample_rate`、`bitrate`、`format`、`channel`、`speed`、`vol`、`pitch`、`emotion`、`output_format`、`extra_body` 等语音参数（完整示例见 `config/generation.toml.example`）。

当前支持以下 **4 种 TTS 协议（`protocol`）**：

| `protocol` 取值 | 协议行为与适用服务说明 |
|---|---|
| `minimax_t2a_http` | MiniMax 同步 HTTP TTS（响应体直接包含 hex 编码音频） |
| `minimax_t2a_async` | MiniMax 异步 TTS（创建任务 $\rightarrow$ 轮询状态 $\rightarrow$ 下载音频文件） |
| `openai_tts` | OpenAI TTS 兼容协议（`POST /audio/speech`，响应体为音频二进制流）。广泛兼容 **edge-tts、GPT-SoVITS、piper** 等本地语音服务的 OpenAI 包装层（对接本地无鉴权服务时可省略 `api_key_env`，请求时不附带 Authorization 头） |
| `http_tts` | 通用自定义原始 HTTP POST 协议：请求体 JSON 直接从模型配置的 `extra_body` 模板派生，支持 `{text}` 和 `{voice}` 占位符自动替换，专用于对接非 OpenAI 格式的本地自建 TTS 服务（注：`extra_body` 中以双下划线开头的 `__path` 请求路径与 `__method` HTTP 方法属于内部控制字段，不会发往请求体） |

---

### 3. `[asr]` — 语音消息识别（语音转文字）

用于将群友或私聊发送的 OneBot V11 `record` 语音消息自动转写为文字，并注入 LLM 对话上下文：
- **优先复用协议端转写**：如果 OneBot 协议端已经在语音消息段中直接提供了 `text` / `transcript` / `transcription` 字段，QuickQuip 会直接采用该文本；否则会调用 OneBot `get_record` 接口拉取音频文件，再发给此处配置的 ASR 渠道进行转写（转写出的文本在进入 LLM 前同样会经过统一敏感词过滤）。

| 层级 | 键名 | 说明 |
|---|---|---|
| **`[asr]`** | `enabled` / `default_model` / `max_audio_bytes` | 总开关、默认 ASR 模型 ID、以及单条语音最大字节数上限（超过此大小则自动跳过转写） |
| **`[[asr.providers]]`** | `id` / `protocol` / `base_url` / `api_key_env` / `timeout_seconds` | 当前 `protocol` 固定支持 **`openai_transcriptions`**（即 OpenAI 兼容的 `POST /audio/transcriptions`，采用 `multipart/form-data` 上传音频） |
| **`[[asr.providers.models]]`** | `id` / `label` / `model` / `language` / `prompt` / `response_format` | `language` 为可选语言提示（如 `zh`），`prompt` 为可选上下文提示词，`response_format` 支持 `json` 或 `text` |

---

### 4. `[music]` — 音乐生成

结构与图片、语音一致，模型对象额外支持 `format`、`output_format`、`add_watermark`、`lyrics_optimizer` 等音乐生成专属字段（各渠道的 `api_key_env` 由各自声明，常见变量名如 `MINIMAX_API_KEY`、`VOLCENGINE_API_KEY`、`OPENAI_API_KEY`）。

---

### 5. `[svg]` — SVG 矢量画图（`draw_svg` 内置工具）

启用后，对话模型可以在回答时自主调用 `draw_svg` 工具并直接写出 SVG 源码，由 QuickQuip 本地调用 `resvg` 引擎将其渲染为高清 PNG 图片随消息发出（无需额配画图 Provider，直接由当前对话模型写出 SVG；中文字体复用与词云相同的 `data/fonts/NotoSansSC-Regular.ttf`，部署说明见 [字体准备步骤](deployment.md#42-cjk-字体文件词云与-svg-画图)）。

> **启用 `draw_svg` 需要同时满足两步**：
> 1. 在 `config/generation.toml` 的 `[svg]` 段设置 **`enabled = true`**；
> 2. 在 LLM 配置数据库的 `settings.tools.enabled` 数组中加入 **`"draw_svg"`**。

| 键名 | 默认值 | 说明 |
|----|------|--------|
| `enabled` | `false` | SVG 画图功能总开关 |
| `harden` | `true` | **第一层静态与资源加固（默认开启，强烈建议保持开启）**：<br>• 输入硬约束（SVG 源码 ≤ 64KB、节点嵌套深度 ≤ 2000、viewBox ≤ 2048、滤镜参数上限）；<br>• 静态安全清洗（自动剥离 `<script>`、事件属性与外部网络链接）；<br>• 输出图片尺寸由服务端强制覆盖；<br>• 渲染子进程资源硬限制（Linux 等 POSIX 平台通过 `rlimit` 限制地址空间 ≤ 2GB、CPU 时间 ≤ 5 秒；Windows 平台无 `rlimit`，由 8 秒墙钟超时强制终止兜底）。<br>*(警告：若设为 `false` 关闭，恶意构造的 SVG 炸弹可能耗尽宿主机内存或 CPU！)* |
| `content_judge` | `false` | **第二层文本内容安全裁决（默认关闭）**：在送入渲染器之前，先调用 `settings.quick_judge` 配置的轻量模型对 SVG 内的可见文字做一次合规审查（采用 **Fail-Open** 策略：若判定超时、返回非 JSON 或未配置判定模型，会记录一条 WARN 日志并放行渲染） |

- **进程隔离与限流**：无论 `harden` 是否开启，`resvg` 渲染始终在**独立子进程**中执行（从架构上防止 C/Rust 渲染库段错误拖垮主进程）；内置渲染限流为**全局 10 次/分钟、单用户 2 次/分钟**，单次回复最多外发 3 张 SVG 渲染图。

---

## `config/awakening.toml` — 群聊低频主动唤醒

唤醒模块默认关闭。首次使用请将 `config/awakening.toml.example` 复制为 `config/awakening.toml`，支持配置全局默认值（`[awakening.defaults]`）与按群覆盖（`[[awakening.group_overrides]]`）。

### 1. `[awakening.defaults]` 全局参数表

| 键名 | 说明 | 默认值 |
|----|------|--------|
| `extend_duration` | **显式触发后的连续对话窗口（秒）**：当群友通过前缀或 `@机器人` 显式唤醒 AI 后，在接下来的多少秒内继续回应同一用户的普通发言（设为 `0` 关闭） | `0` |
| `fallback_probability` | **兜底随机冒泡概率**：普通群消息以多低的概率随机触发一次回应（设为 `0` 关闭） | `0` |
| `boredom_silence_seconds` | **无聊唤醒沉寂门槛（秒）**：群聊连续安静多少秒无人说话后，允许触发“无聊主动找话题”唤醒（设为 `0` 关闭） | `0` |
| `boredom_probability` | 当达到沉寂门槛且无聊检查命中时，实际发出冒泡消息的概率 | `0` |
| `boredom_scan_interval` | 后台定时扫描各群是否冷场的周期秒数（未设置时回退使用 `boredom_check_interval`；修改保存后自动热重载，无需重启） | `300` |
| `boredom_check_interval` | 某个群成功触发一次无聊唤醒后的**群级冷却秒数** | `300` |
| `boredom_dnd_start` / `boredom_dnd_end` | 无聊唤醒的免打扰开始与结束时间（格式为 `"HH:MM"`，留空 `""` 表示关闭免打扰） | `""` |
| `interest_topics` | **兴趣话题关键词列表**：群消息命中列表中的词时触发 `awakening_interest` 唤醒 | `[]` |
| `relevance_threshold` | **话题相关性唤醒阈值**：调用 `quick_judge` 判定群聊与机器人的相关性得分门槛（设为 `<= 0` 或 `>= 1` 表示关闭此项 LLM 判定） | `1.0` |
| `qa_threshold` | **答疑唤醒阈值**：调用 `quick_judge` 判定群友是否在提问求助的得分门槛（设为 `<= 0` 或 `>= 1` 表示关闭此项 LLM 判定） | `1.0` |

### 2. 唤醒触发边界与群内管理命令

- **哪些情况不会打开或触发 `extend_duration` 延长窗口？**
  - 只有群友通过**显式入口（命令前缀或 `@`）**触发后才会开启延长窗口；而通过“兴趣、兜底、无聊、相关性、答疑”这五种被动唤醒触发的回复，**不会**开启延长窗口。
  - 在延长窗口期间，如果该用户发的是纯图片、纯 CQ 码、短语气词或过短的无实义文本，也会被自动忽略。
- **无聊唤醒的扫描与状态清理**：
  - Bot 进程刚启动、尚未在该群观察到任何一条新消息前，该群的沉寂状态视为“未知”，不会触发无聊唤醒。
  - 无聊唤醒属于 **Opt-in（需群内显式开启）** 机制：除了规则开关外，还必须在群内执行 `/awakening boredom on` 将本群加入 `data/awakening_boredom_groups.json`；一旦执行 `off` 取消，该群的沉寂计时与冷却状态会立即清除。
- **被动唤醒的图片携带规则**：延长、兴趣、相关性、答疑和无聊唤醒会自动把群内近期的历史图片注入上下文；唯独**兜底唤醒（fallback）**不注入近期图片。
- **按群覆盖与人格扩展写法**：
  - 在 `config/awakening.toml` 中使用 `[[awakening.group_overrides]]`（指定 `group_id = "群号"`）即可按群覆盖上表任意参数。
  - `interest_topics` 除了写在唤醒配置里，还可以写在具体人格文件（`config/personas/*.toml`）的 `[awakening]` 扩展表中，让不同角色拥有各自的兴趣词。
  - 群内发送 `/awakening status` 可查看本群全部 6 类唤醒规则的开关状态与最终生效参数；使用 `/awakening on <rule>` 或 `/awakening off <rule>` 可按群开关指定唤醒规则。

---

## `config/sensitive_words.toml` — 部署级敏感词过滤

当该文件不存在或词表为空时，过滤器默认静默放行。需要启用时，请将 `config/sensitive_words.toml.example` 复制为 `config/sensitive_words.toml`，并按你的合规要求填充两级词表（完整拦截点与运维说明见 [sensitive-filter.md](sensitive-filter.md)）：

| 配置区段 | 命中后的处理行为 |
|------|------|
| **`[block.<category>]`** | **硬拦截级**：命中后直接阻断 LLM 输入、替换脱敏 LLM 输出，或在工具调用链路上拒绝执行 / 替换工具返回结果 |
| **`[soft.<category>]`** | **软观察级**：命中后仅记录审计日志，不阻断正常请求或回复 |

- 每个分类下使用 `words = ["词1", "词2"]` 定义词表；为保护隐私，命中日志中**记录命中的类别名称与词条哈希，不记录命中原文**。

---

## `config/chat_rules.toml` — 正则规则、语境规则与接龙

### 1. `[rate_limit_rules]` — 限流桶定义

在 `[rate_limit_rules]` 下，每个键值对定义一个命名限流桶：

```toml
[rate_limit_rules]
my_rule = { global_limit = 6, user_limit = 3 }
my_global_rule = { global_limit = 3, user_limit = 1, scope = "global" }
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `global_limit` | 滑动窗口内的全局（或单群）最大触发次数 | — |
| `user_limit` | 滑动窗口内的单用户最大触发次数 | — |
| `scope` | 计数的隔离范围：`"group"`（按群独立分桶）或 `"global"`（所有群合并共用一个桶） | `"group"` |
| `window` | 限流滑动时间窗口大小（秒，覆盖代码默认常量 `RATE_LIMIT_WINDOW_SECONDS = 60`） | `60` |
| `probability` | 桶级基础触发概率（范围 `[0, 1]`）：命中规则后先掷骰子，掷中才进入限流桶计数（详见下方[自动回复概率](#自动回复概率)） | `1` |
| `suppress_after_hit` | **防连发压制次数**：同一规则在同一群命中发出后，接下来的 `N` 次命中强制保持沉默（设为 `0` 关闭） | `0` |
| `pity_step` | **保底概率步进系数**：连续未掷中（连哑）次数越多，下一次实际触发概率越高，计算公式为 `p_eff = p × (1 + 连哑次数 × pity_step)`（设为 `0` 关闭） | `0` |

---

### 2. `[[rules]]` 与 `[[rules.reply_templates]]` — 普通正则回复规则

```toml
[[rules]]
name           = 'my_rule'
patterns       = ['正则表达式']
reply_template = '你好，{sender_name}！现在是 {current_time}'
rate_limit_key = 'my_rule'
priority       = 50
```

| 字段 | 说明 |
|------|------|
| `name` | 规则唯一标识名称 |
| `patterns` | 触发正则表达式数组（支持配置多条正则，任一匹配即命中） |
| `reply_template` | 固定回复文本模板（与下方的 `[[rules.reply_templates]]` 加权随机模板互斥） |
| `rate_limit_key` | 引用的限流桶名称 |
| `priority` | 匹配优先级（数字越大越优先判定） |
| `probability` | 规则级触发概率（范围 `[0, 1]`，优先级高于所在限流桶的 `probability`；设为 `0` 等价于全局停用该条规则） |
| `blocked_named_groups` | **命名捕获组黑名单**：当正则命名捕获组的值落在黑名单列表中时，不触发该规则，例如 `{ target = ["bot"] }` |
| `blocked_groups` | **按序号捕获组黑名单**：键为捕获组序号字符串，例如 `{ "1" = ["xxx"] }` |

- **加权随机回复（`[[rules.reply_templates]]`）**：如果需要从多条回复中按权重随机挑选一条，可省略 `reply_template`，改在规则下方挂接多个 `[[rules.reply_templates]]` 子表（分别指定 `template = '回复内容'` 和 `weight = 权重整数`）。
- **回复模板支持的占位符变量**：
  - `{sender_name}`：发送者昵称
  - `{user_id}`：发送者 QQ 号
  - `{current_time}`：当前北京时间（格式 `YYYY-MM-DD HH:MM`）
  - `$1`, `$2`, ...：按序号的正则捕获组
  - `{命名捕获组}`：正则中的命名捕获组（例如正则写 `(?P<target>.+)`，模板中写 `{target}`）

---

### 3. `[[context_rules]]`（语境感知规则）与 `[[chain_games]]`（自定义接龙）

#### 语境感知规则示例（`[[context_rules]]`）
当某句话本身很常见（如“竟然不许！”），只有结合群内前几句话的语境才应该接梗时使用：

```toml
[[context_rules]]
name               = 'caocao_qiushou'
patterns           = ['竟然不许[！!]*']
type               = 'regex_context'
context_window     = 5
context_conditions = ['请假', '调休', '申请', '审批']
reply_template     = '竟然不许！？'
```

| 字段 | 说明 |
|------|------|
| `type` | 语境判定方式：`regex_context`（默认，用正则关键词回溯检查）或 `llm_context`（调用 `quick_judge` 轻量模型判定语境） |
| `context_window` | 向前追溯最近多少条群消息来判定语境 |
| `context_conditions` | 当 `type = "regex_context"` 时：最近 N 条消息中只要有任意一条命中此数组中的任意一个正则，即判定语境成立并放行（若为空数组则永不放行） |
| `llm_judge_prompt` / `llm_timeout` / `llm_cache_ttl` | 当 `type = "llm_context"` 时：发给快速判定模型的 Prompt、超时秒数（默认 `2.0`）以及判定结果缓存秒数（默认 `60`） |
| `probability` | 规则级触发概率（范围 `[0, 1]`，覆盖桶级概率；**掷骰子发生在语境判定之前**，未掷中时直接跳过，不会白白消耗 LLM 判定调用） |

#### 自定义接龙游戏示例（`[[chain_games]]`）
```toml
[[chain_games]]
name            = 'my_game'
trigger_pattern = '^开始(.+?)接龙$'
chain           = ['第一', '第二', '第三']
```
支持在触发与步骤中使用正则捕获组，以及在单个接龙步骤中配置接受多个候选词的匹配方式。

---

### 自动回复概率

为了避免机器人在高活跃群里“逢梗必接”显得过于聒噪，所有限流桶和规则均支持配置 **`probability`**（取值 `[0, 1]`，默认 `1` 表示 100% 触发），并配套提供 **`suppress_after_hit`（防连发）** 与 **`pity_step`（防脸黑保底）** 两个方差驯化开关：

1. **适用范围与先掷骰原则**：
   - 覆盖除斜杠命令（如 `/turmfluch`）之外的**全部自动回复场景**：文字正则规则、语境规则、早安时区回复、被动“xxx了”判定、复读机检测、乖女链、接龙、内置小游戏、低频唤醒，以及显式 LLM 回复（`@` / 前缀 / 私聊）。
   - **先掷骰、后判定/计费**：命中触发条件后第一步先掷骰子——如果没掷中，本次直接保持沉默，**既不消耗限流桶配额，也不会发起后续的 `llm_context` 或被动“xxx了”的 LLM 判定请求**（普通文字规则若未掷中，仅代表该高优先级规则本次沉默，排在后面的低优先级规则依然有机会参与竞争）。
   - **概率取值优先级**：`规则自身的 probability` > `所引用限流桶的 probability` > `默认值 1`。
2. **概率与限流桶的分工，以及防连发 / 保底机制**：
   - **分工**：`probability` 控制长期的平均触发密度（如“十次接五次”），而限流桶（`global_limit` / `user_limit`）负责兜底短时间内的爆发峰值（如“一分钟最多回 3 次”）。
   - **为什么需要方差驯化？** 纯粹独立的随机掷骰（伯努利试验）在数学上必然会出现“连续好几次都接话”或“连续十几次都哑火”的波动。你可以在限流桶上按需开启：
     - `suppress_after_hit = N`（**防连发**）：同一规则在同一群掷中后，接下来连续 `N` 次命中强制沉默，专治“刚回完紧接着又回”（压制期间不消耗随机数，也不计入保底连哑次数；注意不要在 `probability = 1` 时开防连发，否则会变成机械的“一回一哑”交替，建议搭配 `probability < 1` 使用）。
     - `pity_step = X`（**保底步进**）：每次未掷中会使连哑计数加 1，下一次有效概率提升为 `p_eff = probability × (1 + 连哑数 × X)`，为最长沉默次数提供软上限。
   - **状态隔离与容量上限**：防连发与保底的计数状态仅保存在内存中（重启即重置），按 `(规则, 群号)` 独立隔离（私聊按用户隔离），全进程最多维护 `8192` 个组合（超限时整体重置）；且这两个开关始终跟随所在的**限流桶**生效。
3. **调优与覆写系统内置桶的 3 个关键注意事项**：
   - **“命中”的计数时点**：防连发与保底中的“命中”指的是**掷骰子通过的那一刻**——如果掷骰通过后，因为后续语境不匹配或触及每分钟限流而被拦截，这次防连发窗口依然会被消耗掉（语境规则的连哑同样按第一层快筛正则命中时计算）。
   - **切勿给记分游戏桶调低概率**：复读、接龙和内置游戏是**先推进游戏进度与得分，最后才走限流桶决定是否发出回复文本**。如果把这些游戏桶的 `probability` 设低，会出现“后台已经扣分/加分了，但群里没发结果通知”的怪象，因此游戏桶请保持 `probability = 1`。
   - **覆写系统预定义桶（如 `timezone_wake`、`sts_card_le`、`llm_chat`）必须写全字段！**
     由于 TOML 表采用整条替换语义，如果你在 `chat_rules.toml` 中覆写系统内置限流桶，**必须把 `global_limit` 和 `user_limit` 一并写全**！如果只写了一个 `{ probability = 0.5 }` 的残缺条目，配置加载时会打出警告并导致限流器构建失败（**服务启动即崩溃**）。此外，若调低了 `llm_chat` 桶的概率，机器人对群友直接 `@` 提问也会偶发沉默，仅建议在确实需要全局降噪时使用（仓库自带的 `config/chat_rules.toml.example` 已提供完整的内置桶覆写示例与新三国规则分层概率预设）。

---

## 其他独立配置文件与组件说明

### 1. `config/games.toml` 与牛牛文案预设文件
游戏数值参数配置详见 [game-config.md](game-config.md) 与 `config/games.toml.example`。其中可通过 `niuniu_text_path` 和 `niuniu_safe_text_path` 指定自定义的牛牛游戏文案 TOML 路径：

| 文件路径 | Git 追踪状态 | 用途与维护规范 |
|------|-----|------|
| `config/niuniu_text.toml.example`<br>`config/niuniu_text_safe.toml.example` | Git 追踪（模板层） | 标准版与和谐版（中性措辞）的完整文案示例模板（涵盖事件消息、长度评价、运势提示、CD 提示） |
| `config/niuniu_text.toml`<br>`config/niuniu_text_safe.toml` | **Git 追踪（分发层）** | 随代码仓库分发的默认生效文案。**请勿直接在这两个受追踪文件里写入私有敏感内容！** 如需编写私有专属文案，请新建一个不被 Git 追踪的独立 TOML 文件，并在 `games.toml` 中修改 `niuniu_text_path` 指向它 |

- **和谐版（`safe`）增量继承机制**：在编写 `safe` 文案文件时，你只需要填写想要替换改写的条目（事件按 `name` 匹配、长度评价与运势提示按数值区间匹配、消息字典按键名匹配），未填写的条目会自动从 `default` 标准文案中继承。

### 2. `config/admins.toml` — 全局管理员注册表
用于配置跨群拥有最高管理权限的 QQ 号列表（详见 [global-admins.md](global-admins.md) 与 `config/admins.toml.example`）。在 `global_admins` 数组中填写 QQ 号数字字符串即可，支持修改后自动热重载；若文件缺失或列表为空，则全局管理员功能自动关闭。

### 3. `config/personas/*.toml` — 角色人格定义
`config/personas/` 下的每个 `.toml` 文件定义一个独立人格，而 `_shared.toml` 则是会自动注入给所有人格的共享基础行为准则：

```toml
id            = 'my-persona'
display_name  = '我的角色'
system_prompt = '''
你是一个……
'''
style_prompt  = '''
回复风格：……
'''
scope         = ['group']  # 可选限制适用范围：'group' / 'private'，省略则群聊与私聊均可用
```

- **支持 Structured v2 结构化扩展表**：除了上述扁平字段外，人格文件还支持自由扩展表及 `structured v2` 规范（示例见 `config/personas.example/structured.toml`），其中的 `[identity]`、`[biography]`、`[cognition]`、`[instinct]`、`[voice]` 等扩展表会被运行时自动组装渲染进最终的 System Prompt 中。

### 4. SearXNG 容器配置（`docker/searxng/settings.yml`）
项目内置的 `docker-compose.example.yml` 包含开箱即用的 `searxng` 服务，其配置文件位于 `docker/searxng/settings.yml`（默认绑定在 `http://127.0.0.1:8888`，并已开启 `json` 格式输出接口供 Bot 直接调用）：

```yaml
# docker/searxng/settings.yml（核心节选）
search:
  formats:
    - html
    - json
server:
  bind_address: "0.0.0.0"
  secret_key: "change-this-secret"
```
> 若遇到搜索结果为空或相关性较差，请先检查该 SearXNG 实例内部各上游搜索引擎的可用状态、服务器网络出口及语言查询设置，再用相同关键词复测。

### 5. 贴吧登录态文件（`data/tieba/storage_state.json`）
除 `.env` 中的 `TIEBA_*` 变量外，贴吧采集所需的浏览器登录态 Cookie 保存在 `data/tieba/storage_state.json` 中。首次启用贴吧功能前，请按[贴吧登录步骤](deployment.md#41-首次准备贴吧登录态)在本地完成扫码登录导出并同步至服务器。
