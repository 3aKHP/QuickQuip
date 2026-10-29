<!-- Generated from docs/admin/client-fingerprints.md; do not edit -->

# 请求指纹 Profile

本文面向需要选择或自定义上游请求模板（Client Fingerprint Profile）的部署者。

**什么是请求指纹 Profile？**
Profile 定义了 QuickQuip 向模型上游 API 发送请求时的**客户端名称（User-Agent）、HTTP 请求头（Headers）排列顺序以及请求体（Body）结构布局**。

你可以在 Web Admin 的 **“LLM 配置 → 渠道与模型”** 页面中，为每个渠道单独选择 `client_fingerprint`，点击“保存草稿”并“应用到 Bot”后生效（关于模板、业务身份与协议能力分工的设计依据，详见 [ADR-0014](../dev/adr/0014-client-fingerprint-profiles.md)）。

---

## 如何选择模板？

第一次配置渠道时，先使用 `default`。如果上游返回受管字段冲突或请求结构不兼容，再按本文的协议排障说明调整。已有本地模板覆盖的部署，升级时要一并核对覆盖文件。

## 内置 Profile 模板总览

| Profile ID | 支持的协议 | 行为与伪装基线说明 |
|---|---|---|
| **`default`**（默认） | 全部四种协议 | 自动按协议选用主流 CLI 模板：<br>• OpenAI Chat 使用 `opencode2`<br>• OpenAI Responses 使用 `codex`<br>• Anthropic 使用 `claude-code`<br>• Gemini 使用 `gemini-cli` |
| **`quickquip`** | 全部四种协议 | 使用 QuickQuip 自有品牌 UA，并附带部署群、会话纪元及安装包版本标识（需显式选择） |
| **`opencode2`** | OpenAI Chat Completions | 采用 **OpenCode 2.0.27 native** 的 UA、身份头、追踪头和 Body 布局（Chat 协议默认采用） |
| **`codex`** | OpenAI Responses | 采用 **Codex TUI 0.162.1** 的静态身份、业务 Session 头与缓存键绑定（Responses 协议默认采用） |
| **`claude-code`** | Anthropic Messages | 采用 **Claude Code 2.1.296 Linux CLI** 的 Header、设备身份、双块 `system`、断点缓存与 Body 布局（Anthropic 协议默认采用） |
| **`gemini-cli`** | Gemini GenerateContent | 采用 **Gemini CLI 0.64.0 TUI** 的 Header、安装 UUID、Session 模型锚点和 Body 布局（Gemini 协议默认采用） |
| **`legacy-gemini`** | Gemini GenerateContent | 保留传统的通用 Gemini 请求结构与 URL 查询参数（`?key=`）鉴权，供不兼容 CLI 形态的中转站回退使用 |
| **`legacy-claude`** | Anthropic Messages | 保留早期 2.1.150 的既有 Header 与通用 Body 行为，供兼容回退使用 |

### 选择与配置基本规则

- **缺省行为与本地覆盖**：渠道未配置或选择 `default` 时，自动采用上表对应的协议默认模板。如果你在本地 `config/client_profiles/default.toml` 放置了自定义覆盖文件，整份模板以本地文件为准（升级版本前请核对本地文件中的协议配置及手工 Header／Body 字段）。若需要传统通用请求形态，可直接切换为 `legacy-claude`、`legacy-gemini`，或按后文示例编写自定义模板。
- **配置层级与职责边界**：
  - 在导出 JSON 中，`client_fingerprint` 位于**渠道（Provider）对象层级**；模型级的 `parameters` 覆盖**不接受**该字段。
  - 它与 OpenAI Responses 协议的后端能力开关 `responses_profile`（`openai-public` / `codex-http-relay`）相互独立、分别配置。
- **首次从旧版 `llm.toml` 迁移时的冲突处理**：
  如果旧 TOML 中手写了被新版默认 Profile 接管的 Body 或 Header 字段，首次运行 `init` 初始化会先报错拦截。请先按[首次迁移的 Profile 字段冲突](llm-configuration.md#首次迁移的-profile-字段冲突)清理迁移输入完成入库，再进入 Web 后台切换兼容 Profile（数据库就绪后，切换 Profile 与调整手工字段可在同一个草稿中一并保存并应用）。

---

## 自有品牌请求头

当渠道显式选择 **`quickquip`** Profile 时，系统会使用自有品牌特征并附带 4 个专有请求头：

### 1. User-Agent 覆盖优先级
- **默认 UA 格式**：`QuickQuip/<实际安装包版本>`（例如 `QuickQuip/1.16.2.dev1`；版本号读取自已安装 Python 包的元数据，若缺失则回退为 `unknown` 并记录诊断日志）。
- **UA 优先级（从高到低，所有 Profile 通用）**：
  ```text
  1. 渠道/模型 parameters 中的 user_agent 字段 (最高优先级)
  2. 渠道额外 headers 中手写的 User-Agent (大小写无关)
  3. 当前 Profile 模板定义的默认 User-Agent
  ```

### 2. 四个 `x-quickquip-*` 专有请求头

**注意**：以下四个请求头**仅在 `quickquip` Profile 下发送**。为保证标识可信度，渠道的自定义 `headers` **严禁手工填写这四个名称（含任何大小写变体）**，配置保存校验与运行时均会直接拒绝。

| 专有请求头名称 | 值来源与生命周期说明 |
|---|---|
| `x-quickquip-install` | **持久化安装身份**：首次使用时生成随机 UUID 字符串并取其 SHA-256 哈希，持久化保存在 `data/client_identity.json` 中，跨重启保持不变。 |
| `x-quickquip-session` | **当前上下文纪元（Epoch）标识**：取当前请求冻结的纪元 UUIDv4；仅当上下文窗口发生实际纪元推进或进程重启时才会改变。 |
| `x-quickquip-cluster` | **部署集群标识**：读取全局设置 `settings.runtime.client_cluster`（在 Web 全局设置中填写，部署内所有渠道共用，仅允许可打印 ASCII 字符；为空字符串时自动省略不发）。 |
| `x-quickquip-client` | **客户端版本号**：读取实际安装的 Python 包版本（与默认 UA 的版本来源相同）。 |

### 3. 备份与复制安装身份

`data/client_identity.json` 随数据目录备份、恢复。复制数据目录建立独立机器人时，在停止新实例并保留备份后移走新实例的这个文件，首次使用会生成新的自动身份。若全局配置填写了手动身份，也应为新实例调整相应值。

业务 Session 表示持续对话，纪元表示当前上下文窗口。冷场缩窗会改变纪元，业务 Session 可以继续保留；不同 Profile 使用的身份类型见下文。身份派生和请求重试中的复用规则见[实现说明](../dev/client-fingerprints.md#安装身份与纪元复用)。

---

## 编辑 Profile 文件

所有内置 Profile 的 TOML 模板随安装包一起分发，源码位于 `src/quickquip/llm/client_fingerprints/defaults/`。

### 1. 如何自定义或新增 Profile？
1. 将你需要修改的内置 `.toml` 文件复制到项目的 **`config/client_profiles/`** 目录下（或者在该目录下新建一个 `.toml` 文件）。
2. **修改现有 Profile**：保持文件名与文件内的 `id` 不变，本地文件会**整份覆盖**同 ID 的内置模板。
3. **新增独立 Profile**：使用新的文件名和新的 `id`，即可在后台下拉框中看到新增的 Profile 选项。
4. **重启生效**：编辑或放置好 `.toml` 文件后，**必须重启 Bot 和 Web 服务才会加载生效**（修改本地 Profile 文件不会随 Web 后台点击“应用配置”而自动热重载；正在执行中的请求会继续使用它启动时的配置快照）。
5. **部署与备份**：源码部署、Python wheel 和 Docker 镜像均内置了默认模板。自动部署脚本会保留服务器当前 release 的本地覆盖文件（若新候选版本中已有同名本地文件则优先保留）；日常备份时请将 `config/client_profiles/` 覆盖目录与 `data/` 数据卷一并备份。

### 2. Profile TOML 最小结构示例

以新建 `config/client_profiles/custom.toml` 为例：

```toml
format_version = 1
id = "custom"
label = "Custom Client"
user_agent = "CustomClient/{client_version}"

[headers]
accept = "application/json"

[protocols.openai]
[protocols.openai_responses]
```

- **结构说明**：
  - `[protocols.<协议名>]`：声明该 Profile 支持哪些协议（未声明的协议不可使用该 Profile）。每个协议表内部可以定义该协议专属的 `headers` 和动态绑定 `bindings`。
  - **顶层 `[headers]` vs 协议层 `headers`**：顶层 `[headers]` 会应用到该 Profile 声明的所有协议上；协议表内的 `headers` 则作为该协议的补充（**注意：同一个请求头名称不能在顶层和协议层重复声明**）。
  - `user_agent` 支持使用 `{client_version}` 占位符自动替换为当前 QuickQuip 版本号。

### 3. 可用的动态绑定变量（`bindings`）

在 `[protocols.<协议>.bindings]` 中，可以将请求头动态绑定到以下运行时数据源：

| 动态绑定数据源名称 | 含义与适用范围 |
|---|---|
| `install_id`、`epoch_id`、`cluster_id`、`client_version` | QuickQuip 自有品牌头的安装 ID、纪元 ID、集群名与版本号（专属于 `quickquip` Profile，自定义 `quickquip.toml` 时必须完整保留这四个专有头及绑定） |
| `stainless_os` | 当前运行宿主机的操作系统标识（如 Linux） |
| `business_session_id` | 当前业务会话（Session）的规范 UUIDv4 |
| `opencode_session_id`、`project_id` | OpenCode 格式的派生会话 ID 与部署项目标识 |
| `b3`、`traceparent` | 每次实际 HTTP 尝试生成的分布式追踪头 |
| `timeout_seconds`、`retry_count` | 当前渠道配置的超时秒数与当前重试轮次（从 0 开始） |
| `gemini_cli_install_id` | Gemini CLI 安装 UUIDv4（适用于 Gemini 协议） |

### 4. 引用其他 Profile（`protocol_ref`）与安全校验约束

- **跨模板协议引用（`protocol_ref`）**：
  协议表可以使用 `protocol_ref = "claude-code"` 直接复用另一个 Profile 的同协议配置（内置的 `default.toml` 正是通过这种方式，将四种协议分别指向 `opencode2`、`codex`、`claude-code` 和 `gemini-cli`）。
  - **引用约束**：包含 `protocol_ref` 的协议表内**只能有这一个字段**；且**被引用的目标 Profile** 必须将所有特征（包括 `user_agent`、`headers`、`bindings`）全部写在它自己的 `[protocols.<协议>]` 局部表内，其顶层 UA、Header 和 `bindings` 必须为空；严禁链式引用或循环引用。
  - **升级本地旧副本提示**：如果你之前在本地自定义过 `opencode2.toml` 或 `codex.toml`，升级后请将它们顶层的 `user_agent` 移入各自 `protocols.<协议>.headers` 下的 `user-agent` 字段中，以满足作为 `default` 引用目标的局部约束（修改重启后，`default` 与显式选择该客户端将共享同一份策略快照）。
- **解析器安全与禁填字段**：
  - **`authorization`、`x-api-key`、`x-goog-api-key`、`content-type`** 这四个头由底层协议适配器全权管理，严禁在 Profile 的静态 `headers` 或动态 `bindings` 中声明，否则加载校验会直接失败。
  - 解析器会严格拒绝未知字段、非法绑定源、重复头名称与不支持的协议。Profile 文件仅作为纯静态结构声明，不存储任何密钥（渠道认证继续使用根 `.env` 变量引用），也不执行任何动态表达式或脚本。

---

## 各协议的调整与排障

默认模板已经包含对应协议的客户端特征。需要改动时，先确认上游报错涉及哪个字段，再在本地模板或渠道配置中调整。下列说明保留常用选择；完整 Header、身份派生和 Body 转换细节见[开发参考](../dev/client-fingerprints.md)。

<a id="opencode-2-profile"></a>
<a id="opencode-2-profileopencode2--openai-chat-默认"></a>

### OpenCode 2：请求字段不兼容时怎么查？

`opencode2` 是 Chat 协议的默认模板，UA 为 `opencode/latest/2.0.27/cli`。它按本次请求实际使用的 URL 主机及渠道 ID 选择兼容规则；中转地址按中转自身匹配，模型别名不会让系统自动采用另一家服务的规则。

在 Trace 中查看最终请求字段，重点核对上游要求的输出 token 字段、`store` 和工具声明。渠道或模型的 `extra_body` 可覆盖模板默认值，但同时出现 `max_tokens` 与 `max_completion_tokens` 会报错。自动绑定的 Session、project 和追踪头禁止在渠道 `headers` 中覆盖；需要调整这些绑定时编辑本地 Profile 并重启。

<a id="claude-code-profile"></a>
<a id="claude-code-profileclaude-code--anthropic-默认"></a>

### Claude Code：设备身份、缓存与手工字段

Anthropic 默认使用 `claude-code`。全局设置 `settings.runtime.claude_code_device_id` 留空时，首次使用会生成并保存自动身份；手工设置需为 64 位十六进制字符串，保存后规范为小写。手动值随配置保存和发布，清空后恢复使用文件里的自动值。若复用已有客户端的身份，请同时核对本地模板中的 OS、arch 与其来源环境。

开启渠道的 `prompt_caching` 后，模板在 system 与消息中的适当位置设置缓存断点，TTL 使用 `cache_ttl`。实际命中情况在“用量”页查看；模板的打点位置与 beta 推导规则见[Claude Code 实现](../dev/client-fingerprints.md#claude-code-profileclaude-code--anthropic-默认)。

`system`、`messages`、`tools` 由模板管理，放入 `extra_body` 会被拒绝；自动 user_id 开启时，`metadata.user_id` 也受此限制，包括 `null`。需要手工 user_id 时，在本地模板关闭 `metadata_user_id` 并移除相应 Session Header 绑定；需要完整手工 Body 时可选择 `legacy-claude`，或使用不声明自动 Body 策略的自定义模板。

<a id="codex-profile"></a>
<a id="codex-profilecodex--openai-responses-默认"></a>

### Codex：会话身份与缓存键

Responses 默认使用 `codex`，其 UA 与环境描述来自模板中的固定 Linux 预设。需要匹配其他环境时编辑本地模板并重启；渠道或模型设置的 `user_agent` 仍具有更高优先级。

Session 请求头和 `prompt_cache_key` 共用业务 Session UUID。切换模型思考档位、冷场或恢复存档会保留这个身份，新建或清空会话会改变它。

当模板声明 `prompt_cache_key` 动态绑定时，渠道或模型 `extra_body` 不能同时填写该字段，包括 `null`。需要手工控制缓存键，可从本地 `codex.toml` 移除 `[protocols.openai_responses.body_bindings]` 段后重启，再配置自己的值。

<a id="gemini-cli-profile"></a>
<a id="gemini-cli-profilegemini-cli--gemini-默认"></a>

### Gemini CLI：安装身份与模型名显示

Gemini 默认使用 `gemini-cli`。全局 `settings.runtime.gemini_cli_install_id` 可以填写 UUIDv4；留空时使用保存在 `data/client_identity.json` 中的自动身份。手动值不会覆盖文件中的自动值，清空配置即可切回自动值。备份时保留身份文件，独立部署使用独立身份。

UA 中的 `{session_model}` 在业务 Session 首次使用该模板时固定。后续切换模型后，UA 仍可能显示最初的模型名；这不改变请求实际使用的模型。新建或清空 Session 后会重新绑定。

默认模板通过 `x-goog-api-key` Header 发送 API Key，`legacy-gemini` 使用 URL 查询参数。显式 `auth_method = "bearer"` 使用 Bearer 认证。`contents`、`systemInstruction`、`tools` 由模板管理；上游不支持 `parametersJsonSchema` 或需要手工覆盖这些字段时，可以选择 `legacy-gemini`。
