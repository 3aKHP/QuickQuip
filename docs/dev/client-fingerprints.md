# 请求指纹与协议转换实现

本文供维护协议适配器、Profile 解析器和请求身份逻辑的开发者查阅。部署者选择模板、处理字段冲突和维护身份文件时，请先看[管理员操作指南](../admin/client-fingerprints.md)。

Profile 控制请求的客户端特征；业务配置继续决定人格、模型、预算和工具权限。维护时应分别核对模板定义、实际请求与会话身份，避免调整客户端特征时改变业务行为。设计背景见 [ADR-0014](adr/0014-client-fingerprint-profiles.md)。

实现入口位于 `src/quickquip/llm/client_fingerprints/`，随包模板位于其中的 `defaults/`。模板语法与可编辑字段见[自定义 Profile](../admin/client-fingerprints.md#编辑-profile-文件)；以下记录各协议的具体转换规则。

## 安装身份与纪元复用

### 3. 安装身份维护、纪元复用与 Anthropic 清洗规则
- **克隆部署时的身份重置**：`data/client_identity.json` 会随 `data/` 数据卷一起被备份和恢复。如果你通过直接复制 `data/` 目录来搭建第二个独立的机器人实例，请在停止新实例服务并备份原文件后，**移走新实例的 `data/client_identity.json`**，让它在首次启动时生成全新的独立安装身份（若身份文件格式损坏，系统会明确报错，需由管理员检查并从备份恢复）。
- **业务 Session 与纪元（Epoch）的区别**：
  - **业务 Session** 标识一段持续的群聊/私聊对话；而**纪元（Epoch）** 标识当前的上下文滑动窗口（冷场缩窗、预算裁剪等窗口推进操作会改变纪元 UUID，但保留原有的业务 Session）。
  - 单次请求一旦冻结了纪元，后续的报错重试、备用地址（Fallback URL）切换和工具调用循环（Tool Loop）均复用同一个纪元值；辅助识图请求也会继承调用方的纪元。定时总结等独立后台任务则在每次操作开始时生成一个临时纪元，并在该次操作的级联和重试内部复用。
- **Anthropic 协议下的 `quickquip` 行为**：在 Anthropic 协议下选择 `quickquip` Profile 时，系统会移除默认的 Claude Code 客户端身份头、`X-Stainless-*` 头、浏览器访问标记以及 `claude-code` beta 声明；其余现有的能力声明、请求 URL 与请求 Body 则保持原有行为不变。

## 四大内置协议 Profile 深度解析

以下分别说明 `opencode2`、`claude-code`、`codex`、`gemini-cli` 四个核心客户端模板的请求头、身份生命周期与 Body 转换规则：

---

## OpenCode 2 Profile（`opencode2` — OpenAI Chat 默认）

### 1. 请求头、Session 投影与分布式追踪
- **默认特征**：默认 UA 为 `opencode/latest/2.0.27/cli`，`client` 标识为 `cli`（不发送四个 `x-quickquip-*` 品牌头）。
- **Session 与 Project 身份派生**：
  - 四个 OpenCode Session / Affinity 相关请求头共用同一个业务 Session 投影——格式为 **`ses_` + 26 位字符**，由当前业务 Session 的 UUID 和创建时间稳定派生而来（冷场缩窗、历史裁剪和纪元推进时保持不变；从历史存档恢复会话后也能得到完全相同的 `ses_...` 值；只有新建或清空会话时才会改变。当前无父子会话关系时自动省略 `parent` 头，且默认不发送 `x-opencode-request`）。
  - `project` 头使用一个在当前部署内固定不变的 **40 位不透明标识**（由 `data/client_identity.json` 的安装身份通过域分离算法派生，**绝不包含**任何 QQ 群号、用户 QQ 号或宿主机本地路径）。
- **`b3` 与 `traceparent` 追踪头**：
  用于在单进程内关联单次模型调用及其底层每一次 HTTP 尝试（同进程共享追踪根标识，每次模型调用建立父级 Span，每次网络重试或切换备用地址生成子级 Span；并发请求与工具续轮各自保持独立上下文）。
- **禁止手工覆盖保护**：上述自动绑定的 Session 头、`project` 头和追踪头（含大小写变体）**严禁**在渠道的自定义 `headers` 中手工覆盖。

### 2. Body 策略（`openai-chat-native`）与端点兼容规则
- **通用兼容端点默认 Body**：默认使用 `max_completion_tokens`、设置 `store=false`、工具声明 `strict=false`，并省略默认的 `tool_choice=auto`。
- **按候选 URL 主机名与渠道 ID 自动适配公开端点**：
  `opencode2.toml` 内置了提取自 OpenCode 2.0.27 源码的公开端点兼容规则表，会在确定了本次实际请求的候选 URL（含 Fallback URL）后，按主机名（Host）和渠道 ID 自动匹配，动态控制：输出 Token 字段名（`max_tokens` vs `max_completion_tokens`）、是否发送 `store`、`strict`、`stream_options.include_usage` 以及 `tool_stream`（注：使用第三方中转代理地址时按代理自身的 URL 匹配，不会根据模型别名去猜测背后厂商）。
- **工具历史与覆盖规则**：
  - 工具返回消息自动省略冗余的 `name` 字段；空的 `assistant` 工具调用消息正文统一设为 `null`；工具顺序、调用 ID、参数、结果、推理内容（Thinking）和图片原样保留。如果历史上下文中包含工具调用记录、但当前轮次未启用任何工具，会自动发送 `tools=[]` 以满足协议要求。
  - 渠道或模型显式配置的 `extra_body` 优先级高于 Profile 默认值；但**如果同时出现了 `max_tokens` 和 `max_completion_tokens` 会直接报错拦截**。

### 3. 编码压缩与 HTTP/1.1 Header 排序细节
- **JSON 与流式压缩**：Body 在确定最终候选 URL 和流式模式后进行投影，序列化为紧凑的 UTF-8 JSON。流式请求保留 `Accept: */*`，并声明 `Accept-Encoding: gzip, deflate, br, zstd`（内置完整解压支持；`default` 下的 Chat 同样采用此压缩策略，而 `quickquip` Profile 默认声明 `gzip, deflate`）。
- **Header 顺序（`header_order`）保真**：
  在底层 HTTPX 补齐了 `Host`、`Connection`、`Content-Length` 等基础头之后，系统会严格按照 Profile 文件声明的 `header_order` 重新排列请求头顺序并修正名称大小写（渠道额外自定义的 Header 会排在模板声明字段之后）。在 HTTP/1.1 实际网络传输时，底层 `h11` 库会将 `Host` 固定放在第一行，其余所有 Header 均严格保持模板定义的顺序与大小写（LLM Trace 中记录的是应用层构造的请求头与值）。

---

## Claude Code Profile（`claude-code` — Anthropic 默认）

### 1. 客户端基线与网络头
- **基线版本**：Anthropic 的 `default` 与 `claude-code` 采用固定基线：**Claude Code 2.1.296 Linux x64 CLI**、Anthropic TS SDK `0.128.0`、Runtime `v26.3.0`、API Key 鉴权模式、且关闭 attribution。
- **Accept 与超时/重试头**：
  - 流式与非流式请求默认均发送 `Accept: application/json`（由 `claude-code.toml` 中的 `stream_accept = "preserve"` 控制；自定义 Profile 也可设为 `"event-stream"` 让流式请求发送 `text/event-stream`），压缩声明支持 `gzip, deflate, br, zstd`。
  - `X-Stainless-Timeout` 自动跟随渠道配置的 `timeout_seconds`。
  - `X-Stainless-Retry-Count` 从 `0` 开始，随渠道重试策略递增（切换到备用 Fallback URL 时保持当前重试轮次；发起新调用或流式失败降级为非流式时重置为 `0`）。

### 2. 双块 `system` 结构、Session 与设备身份（`device_id`）
- **双块 `system` 布局**：请求体中的 `system` 数组由两个 `text` 块组成——第一块为可编辑的 CLI 身份声明文本，第二块为 QuickQuip 原有的业务系统提示词（包含人格、群成员认人、消息引用、艾特规则与工具权限声明；该新增身份文本与结构开销会一并计入首轮和工具循环的 Token 预算）。
- **Session 与 `metadata.user_id` 绑定**：
  - 请求头 `X-Claude-Code-Session-Id` 与请求体 `metadata.user_id` 中的 `session_id` 共用同一个业务 Session UUID（跨冷场、裁剪、纪元推进、重启及存档恢复保持不变；新建或清空会话时改变）。
  - `metadata.user_id` 序列化为紧凑的 JSON 字符串，固定键顺序为 `{"device_id":"...","account_uuid":"","session_id":"..."}`（API Key 基线下 `account_uuid` 为空字符串，且不发送 Agent / parent-agent ID 或 billing 连续性字段）。
- **全局设备身份（`settings.runtime.claude_code_device_id`）**：
  - **自动生成（默认）**：当全局设置留空时，首次使用会自动生成 32 字节随机值（转为 **64 位小写十六进制字符串**），持久化保存在 `data/client_identity.json` 的 `claude_code_device_id` 字段中，跨重启与迁移稳定保持。
  - **手动指定**：你也可以在 Web Admin 全局设置中填入一个现成的 64 位 hex 字符串（例如复用你本机真实 Claude Code 的 `userID`，所有使用 CC 策略的渠道共用；若填入现成身份，建议同步调整本地模板中的 OS / arch 以匹配来源环境）。手动设置不会覆盖文件里的自动生成值，清空设置即可随时切回自动身份。

### 3. 动态 `anthropic-beta`、四断点缓存与受管字段保护
- **条件派生 `anthropic-beta`**：
  系统会根据本次请求最终生效的 `tools`、`thinking`、`effort` 以及是否使用 JSON Schema 输出，自动组合生成 `anthropic-beta` 请求头（如果渠道 `headers` 中显式手写了 `anthropic-beta`，则以手写覆盖为准）。
  - **`context-1m` 自动判定**：当已知模型的上下文窗口大于模板阈值（默认 `200000`，可在 TOML 中调整）时自动附加 `context-1m` beta；模型窗口未知时省略。
  - 系统不会自动声明 `advanced-tool-use`、DTU 或 AFK。
- **Thinking 上下文管理与 Prompt Caching 四断点打点**：
  - 当 `thinking` 有效开启时，默认注入 `context_management` 以保留所有历史 `thinking` 块（若 `extra_body.context_management` 有显式配置则优先使用显式值）。
  - 当渠道开启 `prompt_caching` 时，系统会在**两个 `system` 块**以及**最后一条消息的最后一个可缓存块**上自动打上缓存断点（`tools` 列表与 `thinking` 块不直接打点，全请求最多 4 个缓存断点；缓存 TTL 沿用渠道 `cache_ttl` 设置）。当关闭 `prompt_caching` 时，会自动清除协议位置上的缓存标记。
- **受管字段覆盖保护（`claude-code-messages` 策略）**：
  - 严禁在渠道或模型的 `extra_body` 中传入 **`system`、`messages`、`tools`**；当开启自动 `user_id` 时，也严禁传入 **`metadata.user_id`**（含 `null`；但 `metadata` 对象下的其他自定义键允许保留）。动态 Session Header 同样禁止手工覆盖。
  - **如何解除限制？** 如果你需要手工控制 `metadata.user_id`，可在本地 `claude-code.toml` 中将 `metadata_user_id` 设为 `false` 并移除对应的 Session Header 绑定；如果需要完全自定义整份 Body，请直接将渠道 Profile 切换为 **`legacy-claude`**。

---

## Codex Profile（`codex` — OpenAI Responses 默认）

### 1. 客户端基线与三合一 Session 头
- **默认特征**：选择 `codex`（或 Responses 协议使用 `default`）时，默认 UA 为 `codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)`，`originator` 头为 `codex-tui`，压缩声明为 `gzip, deflate`（如需伪装成其他操作系统环境，可复制修改本地 `codex.toml` 并重启）。
- **请求头与缓存键四处同源绑定**：
  请求头中的 **`session-id`**、**`thread-id`**、**`x-client-request-id`**（线程作用域），以及请求体 Body 中的 **`prompt_cache_key`**，四者全部绑定为**同一个业务 Session UUIDv4**（在重试、工具续轮、冷场、历史裁剪、纪元推进及存档恢复时均保持不变；仅在新建或清空会话后改变）。

### 2. `body_bindings` 与 `prompt_cache_key` 覆盖保护
`codex.toml` 使用了目前仅对 `openai_responses` 协议开放的 `body_bindings` 语法：

```toml
[protocols.openai_responses.body_bindings]
prompt_cache_key = "business_session_id"
```

- **覆盖保护规则**：当 Profile 声明了上述动态绑定（包括 `default` 下的 Responses 和显式 `codex`）时，除了禁止手工覆盖动态身份 Header 外，**渠道和模型的 `extra_body` 中也严禁包含 `prompt_cache_key`（哪怕设为 `null` 也会在保存校验和运行时报错）**。
- **如何改为手动控制缓存键？** 如果你需要手动在 `extra_body` 中指定 `prompt_cache_key`，请复制本地 `codex.toml`、删掉 `[protocols.openai_responses.body_bindings]` 段并重启服务（未声明该动态绑定的自定义 Profile 允许在 `extra_body` 中自由填写 `prompt_cache_key`）。

---

## Gemini CLI Profile（`gemini-cli` — Gemini 默认）

### 1. 客户端基线与 `{session_model}` 模型名锚点机制
- **基线版本**：Gemini 的 `default` 与 `gemini-cli` 采用 **Gemini CLI 0.64.0**、Google GenAI JS SDK `1.30.0`、Node `24.18.0`、Linux x64 terminal TUI 的 HTTP/1.1 基线（`Accept: */*`，压缩声明 `br, gzip, deflate`）。
- **UA 中的 `{session_model}` 冻结锚点**：
  - 模板使用协议局部 `user_agent_template`，默认格式为：`GeminiCLI-tui/0.64.0/{session_model} (linux; x64; terminal)`。
  - **什么是模型名锚点？** 当一个业务 Session **第一次**使用该模板发起请求时，会将当时实际请求的模型名称“冻结”保存进会话数据中作为 `{session_model}` 锚点。此后在该会话生命周期内——**哪怕你中途切换了模型或渠道**、或者发生了工具续轮、重试、纪元推进、进程重启、存档恢复，UA 里的 `{session_model}` 都会一直沿用最初绑定的那个模型名！只有当你清空或新开 Session 后才会重新绑定（临时总结、诊断等一次性操作的锚点仅保存在内存中；辅助识图则直接继承调用方 Session 的锚点）。

### 2. 安装身份（`gemini_cli_install_id`）与 API Key Header 传输
- **特权用户安装头（`x-gemini-api-privileged-user-id`）**：
  - 该请求头的值来自全局设置 `settings.runtime.gemini_cli_install_id`（可选填写小写 UUIDv4）。
  - 留空时，系统在首次发送请求时会自动生成一个独立的随机 UUIDv4，持久化保存在 `data/client_identity.json` 的 `gemini_cli_install_id` 字段中（渠道 `headers` 严禁手工覆盖此头；如需彻底省略不发，可在本地 `gemini-cli.toml` 中移除该绑定）。
- **API Key 传输方式升级（`api_key_transport`）**：
  - `gemini-cli` 模板将协议局部配置 `api_key_transport` 设为了 **`"header"`**——由底层适配器自动注入 `x-goog-api-key` 请求头，**不再将 API Key 拼在 URL 查询参数（`?key=`）中**，从而避免密钥泄漏到反代或网关的访问日志里（若渠道显式配置了 `auth_method = "bearer"`，则继续使用 `Authorization: Bearer`）。
  - 而 `legacy-gemini`（以及未声明 `api_key_transport` 的自定义 Profile）则继续保留传统的 URL 查询参数（`query`）传输方式。

### 3. Body 布局策略（`gemini-cli-generate-content`）与受管字段
- **结构转换规则**：
  - 将当前人格与业务系统指令合并发送为单个 `text` 块的 `systemInstruction`，并按 CLI 规范显式设置 `role = "user"`。
  - 工具声明统一使用 **`parametersJsonSchema`** 字段，完整保留原始 JSON Schema、工具定义与权限；输出预算、采样参数、`thinking`、多模态媒体、工具调用 ID 与原生思维签名（`thoughtSignature`）均使用实际业务数据。发送时序列化为紧凑 UTF-8 JSON（无末尾换行）。
- **受管字段覆盖保护**：
  - 在 `gemini-cli` 策略下，**`contents`、`systemInstruction`、`tools`** 三个顶级字段由策略全权管理，严禁在渠道或模型的 `extra_body` 中手工覆盖（保存与发送阶段均会拦截）。
  - 如果你对接的上游中转站不支持 `parametersJsonSchema` 或需要手工覆盖上述三个字段，请将该渠道的 Profile 切换为 **`legacy-gemini`**。
