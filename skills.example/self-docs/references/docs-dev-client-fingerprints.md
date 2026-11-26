<!-- Generated from docs/dev/client-fingerprints.md; do not edit -->

# 请求指纹与协议转换实现

本文面向维护协议适配器、Profile 解析器与会话身份投影的开发者，说明安装身份持久化、业务 Session 与纪元复用边界，以及四大内置客户端 Profile 的请求头与请求体转换契约。部署选型、冲突排查与本地模板编辑步骤见[管理员操作指南](../admin/client-fingerprints.md)，架构决策背景见 [ADR-0014](adr/0014-client-fingerprint-profiles.md)。

Profile 仅负责塑造出站 HTTP 请求的客户端特征；人格、模型选择、上下文预算与工具调用权限仍由业务配置独立控制。实现代码位于 `src/quickquip/llm/client_fingerprints/`，随包默认模板存放在其中的 `defaults/` 子目录，可编辑 TOML 语法见[自定义 Profile](../admin/client-fingerprints.md#编辑-profile-文件)。

## 安装身份与纪元复用

- **部署级安装身份（`data/client_identity.json`）**：文件首次缺失时由运行时原子创建并持久化随机安装身份，供 OpenCode 项目标识、Claude Code 默认设备身份与 Gemini CLI 默认安装标识做域分离派生；若文件存在但 JSON 结构或字段格式损坏，解析器直接抛出明确错误以防静默轮换线上身份。通过复制 `data/` 目录克隆第二个机器人实例时的身份重置流程见[管理员操作指南](../admin/client-fingerprints.md)。
- **业务 Session 与上下文纪元（Epoch）的职责分工**：
  - **业务 Session** 标识一段持续的群聊或私聊对话；冷场缩窗、触顶裁剪、切换模型或人格等窗口演进操作会生成新的**纪元（Epoch）** UUID，而业务 Session UUID 全程保持不变。
  - 单次对话请求在组装完成时冻结当轮纪元快照，随后的报错退避重试、备用地址（Fallback URL）切换、多轮工具调用循环（Tool Loop）及前置辅助识图均复用同一个纪元值。每日总结、播报、人物志等独立后台任务在每次操作启动时生成临时纪元，并在该次操作的模型级联与内部重试中复用。
- **Anthropic 协议下的自有 `quickquip` Profile**：在 `claude` 协议渠道显式选用 `quickquip` Profile 时，适配器仅发送基础认证头、标准能力声明、目标 URL 与业务请求体，不注入 Claude Code 客户端身份头、`X-Stainless-*` SDK 头、浏览器访问标记及 `claude-code` beta 声明。

## 四大内置协议 Profile 深度解析

以下按协议说明 `opencode2`、`claude-code`、`codex` 与 `gemini-cli` 四个默认客户端模板的请求头排布、身份派生与 Body 转换规则。

---

## OpenCode 2 Profile（`opencode2` — OpenAI Chat 默认）

### 1. 请求头、Session 投影与分布式追踪

- **默认客户端标识**：User-Agent 固定为 `opencode/latest/2.0.27/cli`，`client` 请求头设为 `cli`，不下发四个 `x-quickquip-*` 自有品牌头。
- **Session 与 Project 身份派生**：
  - 四个 OpenCode 会话亲和性请求头共用同一个业务 Session 派生值，格式为 **`ses_` + 26 位字符**，由当前业务 Session 的 UUID 与创建时间纯函数计算得出。冷场缩窗、历史裁剪、纪元推进以及从私聊存档恢复会话均保持完全相同的 `ses_...` 值，仅在新建或清空会话时改变；无父子会话关系时自动省略 `parent` 头，默认也不发送 `x-opencode-request`。
  - `project` 请求头为当前部署内恒定不变的 **40 位不透明标识**，由 `data/client_identity.json` 中的安装身份经域分离哈希派生，不包含任何群号、用户 QQ 号或宿主机文件系统路径。
- **`b3` 与 `traceparent` 追踪头**：在单进程内关联同一次逻辑模型调用及其底层多次 HTTP 尝试——同进程共享追踪根标识，每次 `complete()` 建立父级 Span，每次退避重试或切换备用地址派生独立子 Span，并发请求与工具续轮各自隔离。
- **受管请求头保护**：上述自动派生的会话头、`project` 头与追踪头（含任意大小写变体）均由 Profile 独占管理，禁止在渠道自定义 `headers` 中手工覆盖。

### 2. Body 策略（`openai-chat-native`）与端点兼容规则

- **通用端点默认字段**：默认输出上限字段使用 `max_completion_tokens`，显式设置 `store=false`、工具定义 `strict=false`，并省略默认的 `tool_choice="auto"`。
- **按候选 URL 主机名与渠道 ID 匹配公开端点**：`opencode2.toml` 内置提取自 OpenCode 2.0.27 的公开端点兼容表。每次尝试确定实际候选 URL（含 Fallback URL）后，策略按目标主机名（Host）与渠道 ID 动态调整输出上限字段名（`max_tokens` 或 `max_completion_tokens`）以及是否下发 `store`、`strict`、`stream_options.include_usage` 和 `tool_stream`。对接第三方中转地址时严格按中转自身的 URL 主机名匹配，不根据模型名称猜测上游厂商。
- **工具历史规整与 `extra_body` 合并**：
  - `tool` 角色返回消息自动省略冗余的 `name` 字段；无文本正文的 `assistant` 工具调用消息统一设 `content: null`；工具调用顺序、`call_id`、参数、结果、推理文本与内联图片均原样保留。若历史上下文中存在工具调用记录而当轮请求未启用任何工具，自动下发空数组 `tools=[]` 以满足严格端点的协议校验。
  - 渠道或模型显式配置的 `extra_body` 优先级高于 Profile 默认字段；若合并后请求体同时出现 `max_tokens` 与 `max_completion_tokens`，校验器直接报错拦截。

### 3. 编码压缩与 HTTP/1.1 Header 排序细节

- **序列化与流式压缩**：请求体在确定最终候选 URL 与流式标志后完成投影，序列化为紧凑无多余空白的 UTF-8 JSON。流式请求发送 `Accept: */*` 并声明 `Accept-Encoding: gzip, deflate, br, zstd`（传输层内置四类算法完整解压支持；`quickquip` 自有 Profile 则默认声明 `gzip, deflate`）。
- **请求头顺序保真（`header_order`）**：在 HTTPX 补齐 `Host`、`Connection`、`Content-Length` 等底层标准头之后，投影层严格按模板声明的 `header_order` 重排字段顺序并归一大小写，渠道自定义额外 Header 排在模板声明字段末尾。通过 HTTP/1.1 实际发包时，底层 `h11` 库固定将 `Host` 置于首行，其余所有请求头均维持模板定义的精确顺序与大小写；LLM Trace 记录应用层完成排序后的请求头快照。

---

## Claude Code Profile（`claude-code` — Anthropic 默认）

### 1. 客户端基线与网络头

- **固定版本基线**：`claude` 协议下的 `default` 与显式 `claude-code` 采用 **Claude Code 2.1.296 Linux x64 CLI**、Anthropic TS SDK `0.128.0`、Runtime `v26.3.0` 与 API Key 鉴权基线，默认关闭 attribution 标记。
- **`Accept`、超时与重试计数头**：
  - 流式与非流式请求默认均发送 `Accept: application/json`（由 `claude-code.toml` 中的 `stream_accept = "preserve"` 控制；本地自定义模板可改为 `"event-stream"` 使流式请求发送 `text/event-stream`），压缩编码声明为 `gzip, deflate, br, zstd`。
  - `X-Stainless-Timeout` 自动同步当前渠道生效的 `timeout_seconds`。
  - `X-Stainless-Retry-Count` 从 `0` 起算，随退避重试递增；同一调用内切换备用 Fallback URL 时延续当前重试计数，发起新模型调用或流式降级重发非流式请求时重置为 `0`。

### 2. 双块 `system` 结构、Session 与设备身份（`device_id`）

- **双块 `system` 布局**：请求体 `system` 数组固定由两个 `text` 块组成——第一块为模板可编辑的 CLI 身份声明文本，第二块为业务系统提示词（承载人格、群成员认人、引用与艾特规则及工具使用规范）；两块文本及其结构开销共同计入首轮与工具续轮的输入 Token 预算。
- **Session 与 `metadata.user_id` 同源绑定**：
  - 请求头 `X-Claude-Code-Session-Id` 与请求体 `metadata.user_id` 内的 `session_id` 共用同一个业务 Session UUID，跨冷场缩窗、历史裁剪、纪元推进、进程重启及私聊存档恢复保持恒定，仅在新建或清空会话时轮换。
  - `metadata.user_id` 序列化为键序固定的紧凑 JSON 字符串 `{"device_id":"...","account_uuid":"","session_id":"..."}`；API Key 模式下 `account_uuid` 固定为空串，且不附带子代理标识或计费连续性字段。
- **全局设备身份（`settings.runtime.claude_code_device_id`）**：
  - **默认自动生成**：全局设置留空时，首次调用自动生成 32 字节随机数（编码为 **64 位小写十六进制字符串**）并写入 `data/client_identity.json` 的 `claude_code_device_id` 字段，跨重启持久复用。
  - **显式手动指定**：管理员也可在全局运行设置中填入指定的 64 位十六进制字符串，供所有启用 Claude Code 策略的渠道共享（复用本机真实客户端身份时，建议同步调整本地模板中的操作系统与架构字段）；手动覆盖值保存在配置库中，清空该设置即可切回 `client_identity.json` 中的自动身份。

### 3. 动态 `anthropic-beta`、四断点缓存与受管字段保护

- **条件组合 `anthropic-beta`**：适配器根据当次请求实际启用的 `tools`、`thinking`、`effort` 及 JSON Schema 结构化输出自动拼接 `anthropic-beta` 请求头（若渠道 `headers` 显式配置了 `anthropic-beta` 则以渠道显式值为准，且系统不会自动声明 `advanced-tool-use`、DTU 或 AFK）。当已知模型的上下文窗口大于模板阈值（默认 `200000`，可在本地 TOML 调整）时自动追加 `context-1m` beta 标识；模型窗口未知时省略。
- **Thinking 上下文管理与四断点缓存**：
  - 当 `thinking` 有效开启时，默认注入 `context_management` 以保留多轮历史 `thinking` 块；若 `extra_body.context_management` 已显式指定则采用显式配置。
  - 渠道开启 `prompt_caching` 时，系统自动在**两个 `system` 文本块**及**最后一条消息的末尾可缓存块**打上缓存断点（`tools` 数组与 `thinking` 块不直接打点，整次请求最多 4 个断点，TTL 跟随渠道 `cache_ttl`）；关闭 `prompt_caching` 时自动清理上述协议位置的缓存标记。
- **受管字段覆盖保护（`claude-code-messages` 策略）**：
  - 渠道或模型的 `extra_body` 严禁传入 `system`、`messages`、`tools`，开启自动 `user_id` 时严禁传入 `metadata.user_id`（含 `null`；`metadata` 下的其他自定义键允许并存），动态 Session 请求头同样禁止手工覆盖。
  - 若需手工接管 `metadata.user_id`，可在本地 `claude-code.toml` 中将 `metadata_user_id` 设为 `false` 并移除对应的 Session Header 绑定；若需完全自定义整份请求体结构，可将渠道 Profile 切换为 **`legacy-claude`**。

---

## Codex Profile（`codex` — OpenAI Responses 默认）

### 1. 客户端基线与四处同源 Session 绑定

- **默认客户端标识**：`openai_responses` 协议使用 `default` 或显式选择 `codex` 时，User-Agent 默认为 `codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)`，`originator` 头为 `codex-tui`，压缩声明为 `gzip, deflate`（需要调整操作系统标识时可复制编辑本地 `codex.toml` 后重启服务）。
- **请求头与缓存键四处同源绑定**：请求头中的 **`session-id`**、**`thread-id`**、**`x-client-request-id`** 以及请求体中的 **`prompt_cache_key`** 全部绑定为同一个业务 Session UUIDv4；在退避重试、工具续轮、冷场缩窗、历史裁剪、纪元推进与存档恢复期间均保持不变，仅在新建或清空会话时轮换。

### 2. `body_bindings` 与 `prompt_cache_key` 覆盖保护

`codex.toml` 使用专供 `openai_responses` 协议的 `body_bindings` 声明：

```toml
[protocols.openai_responses.body_bindings]
prompt_cache_key = "business_session_id"
```

- **覆盖保护规则**：只要所选 Profile 声明了该动态绑定（含 Responses 下的 `default` 与显式 `codex`），配置校验与运行时发送都会拦截渠道或模型 `extra_body` 中手工传入的 `prompt_cache_key`（即使设为 `null` 同样拒绝），并禁止手工覆盖受管动态身份请求头。
- **手工接管方式**：若业务需要在 `extra_body` 中自行指定 `prompt_cache_key`，可复制本地 `codex.toml`，删除 `[protocols.openai_responses.body_bindings]` 段后重启加载；未声明该动态绑定的自定义 Profile 允许自由传入 `prompt_cache_key`。

---

## Gemini CLI Profile（`gemini-cli` — Gemini 默认）

### 1. 客户端基线与 `{session_model}` 模型名锚点机制

- **固定版本基线**：`gemini` 协议下的 `default` 与显式 `gemini-cli` 采用 **Gemini CLI 0.64.0**、Google GenAI JS SDK `1.30.0`、Node `24.18.0`、Linux x64 终端 TUI 的 HTTP/1.1 基线（`Accept: */*`，压缩编码声明 `br, gzip, deflate`）。
- **User-Agent 中的 `{session_model}` 首次模型锚点**：模板通过协议局部字段 `user_agent_template` 定义格式 `GeminiCLI-tui/0.64.0/{session_model} (linux; x64; terminal)`。当某个业务 Session 首次通过该模板发起请求时，运行时将当次实际请求的 wire 模型名原子写入会话绑定表作为 `{session_model}` 锚点。在该业务 Session 存续期间，即便后续中途切换了模型或渠道，或经历了工具续轮、报错重试、纪元推进、进程重启与私聊存档恢复，User-Agent 中的 `{session_model}` 始终保持最初绑定的模型名，直至清空上下文或开启新会话才重新绑定。后台定时报告与诊断探活在内存中维护当次操作的临时锚点，聊天前置识图直接继承所属对话 Session 的锚点。

### 2. 安装身份（`gemini_cli_install_id`）与 API Key 传输位置

- **特权用户安装头（`x-gemini-api-privileged-user-id`）**：优先读取全局设置 `settings.runtime.gemini_cli_install_id`（支持填写小写 UUIDv4）；留空时首次调用自动生成独立随机 UUIDv4 并持久化至 `data/client_identity.json` 的 `gemini_cli_install_id` 字段。渠道 `headers` 禁止手工覆盖该请求头；如需彻底省略该头，可在本地 `gemini-cli.toml` 中移除对应绑定。
- **API Key 传输位置（`api_key_transport`）**：`gemini-cli` 模板将协议局部字段 `api_key_transport` 设为 `"header"`，由适配器自动注入 `x-goog-api-key` 请求头，避免密钥出现在反向代理或网关的 URL 查询串访问日志中（渠道显式设置 `auth_method = "bearer"` 时发送 `Authorization: Bearer`）。`legacy-gemini` 及未声明 `api_key_transport` 的自定义 Profile 则采用 URL 查询参数（`?key=`，`query` 模式）传输密钥。

### 3. Body 布局策略（`gemini-cli-generate-content`）与受管字段

- **结构转换规则**：适配器将当前人格与业务系统提示词合并为单个 `text` 块的 `systemInstruction`，并按 Gemini CLI 规范显式填入 `role = "user"`；工具函数声明统一输出为 `parametersJsonSchema` 字段以保留完整原始 JSON Schema；输出上限、采样温度、`thinking` 参数、内联多模态媒体、工具调用 ID 与原生 `thoughtSignature` 均按实际业务请求序列化为无尾随换行的紧凑 UTF-8 JSON。
- **受管字段覆盖保护**：`gemini-cli` 策略独占管理顶层 `contents`、`systemInstruction` 与 `tools` 三个字段，配置保存校验与运行时发送阶段均禁止在 `extra_body` 中覆盖它们。若所接第三方中转端点尚未支持 `parametersJsonSchema` 或需要手工改写上述顶层字段，请将该渠道的 `client_fingerprint` 切换为 **`legacy-gemini`**。
