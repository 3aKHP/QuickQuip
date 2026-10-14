# 请求指纹 Profile

Provider 的固定字段 `client_fingerprint` 选择客户端请求特征。内置 Profile 的支持范围为：

| ID | 支持协议 | 行为 |
|---|---|---|
| `default` | 四种协议 | Chat 使用 OpenCode 2，Responses 使用 Codex，Anthropic 使用 Claude Code；Gemini 使用 Gemini CLI |
| `quickquip` | 四种协议 | QuickQuip 品牌 UA 与部署、纪元及版本标识，需要显式选择 |
| `opencode2` | OpenAI Chat Completions | OpenCode 2.0.27 native 的 UA、身份头、追踪和 Body 布局；Chat 默认采用 |
| `codex` | OpenAI Responses | Codex TUI 0.162.1 的静态身份、业务 Session 头与缓存键；Responses 默认采用 |
| `claude-code` | Anthropic Messages | Claude Code 2.1.296 Linux CLI 的 Header、身份、system、缓存与 Body 布局 |
| `gemini-cli` | Gemini GenerateContent | Gemini CLI 0.64.0 TUI 的 Header、安装 UUID、Session 模型锚点和 Body 布局 |
| `legacy-gemini` | Gemini GenerateContent | 保留通用 Gemini 请求与 API Key 查询参数鉴权，供兼容回退使用 |
| `legacy-claude` | Anthropic Messages | 保留 2.1.150 的既有 Header 与 Body 行为，供兼容回退使用 |

渠道字段缺省或显式选择 default 时采用协议默认策略。已有 default.toml 本地覆盖继续整份生效，需核对其中的协议配置；启用默认策略前检查动态 Header 与 Body 绑定的手工覆盖。需要通用请求形态时，可按下方最小示例定义自有 Profile；Anthropic 提供 legacy-claude，Gemini 提供 legacy-gemini 回退。

在 Web Admin「LLM 配置 → 渠道」选择 Profile，保存草稿后应用。JSON 的 `client_fingerprint` 放在渠道对象内；模型参数覆盖不接受该字段。它与 OpenAI Responses 的 `responses_profile` 能力设置分别配置。

## 自有品牌请求头

默认 UA 为 `QuickQuip/<实际安装包版本>`，例如 `QuickQuip/1.16.2.dev1`。版本来自 `importlib.metadata`，缺少包元数据时使用 `unknown` 并记录诊断。Provider 参数 `user_agent` 优先于附加请求头中的 UA，附加 UA 优先于 Profile 默认 UA；请求头名称按大小写无关处理。

| 请求头 | 来源及生命周期 |
|---|---|
| `x-quickquip-install` | 首次使用时计算随机 UUID 字符串的 SHA-256，保存到 `data/client_identity.json`；跨重启稳定 |
| `x-quickquip-session` | 当前请求冻结的纪元 UUIDv4；纪元实际推进时改变，重启建立新纪元 |
| `x-quickquip-cluster` | 全局 `settings.runtime.client_cluster`；空字符串时省略 |
| `x-quickquip-client` | 实际安装包版本，与默认 UA 的版本来源相同 |

四个专有头仅在 `quickquip` Profile 下发送。Provider 的 `headers` 不接受这四个名称，包括不同大小写拼写；配置校验与运行时均拒绝手工覆盖。

cluster 在 Web 的全局设置中填写，部署内所有渠道共用，只使用可打印 ASCII。安装标识随数据卷备份恢复；复制数据卷会保留相同安装身份。创建独立部署时，在停止服务并保留原文件备份后，移走新部署的 `data/client_identity.json`，首次使用会生成新身份。损坏的身份文件会明确报错，需要管理员检查和恢复。

业务 Session 与纪元分别管理。业务 Session 标识持续对话，纪元标识当前上下文窗口；冷场、预算裁剪等窗口推进可以改变纪元并保留业务 Session。请求冻结纪元后，重试、备用地址和工具循环复用该值；辅助识图继承调用时的纪元。独立任务在每次操作开始时生成临时纪元，操作内部级联和重试复用。

Anthropic 的 `quickquip` Profile 移除默认 Claude Code 客户端身份头、Stainless 头、浏览器访问标记和 `claude-code` beta 项。其余现有能力声明、URL 与请求 Body 保持原有行为；Claude Code Body 对齐由对应客户端策略负责。

## 编辑 Profile 文件

内置 TOML 随包分发，源码位置为 `src/quickquip/llm/client_fingerprints/defaults/`。将需要调整的文件复制到 `config/client_profiles/`，保留文件名与 `id`，编辑后重启 Bot 和 Web。相同 ID 使用本地文件整份覆盖；新增 ID 可定义独立 Profile。文件修改不会随配置「应用」自动重新加载，正在执行的操作继续使用其配置快照。

Profile 的最小文件示例：

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

文件名为 `custom.toml`。`protocols` 声明支持的协议，协议表可包含 `headers` 和 `bindings`。根表中的请求头用于全部已声明协议；协议表补充本协议的请求头，同一名称不能重复声明。

`user_agent` 仅支持 `{client_version}` 版本替换。动态 `bindings` 的来源为 `install_id`、`epoch_id`、`cluster_id`、`client_version`、`stainless_os`、`opencode_session_id`、`project_id`、`b3`、`traceparent`、`business_session_id`、`timeout_seconds`、`retry_count`、`gemini_cli_install_id`。business_session_id 返回业务 Session 的规范 UUID；opencode_session_id 与 project_id 随请求绑定，b3 与 traceparent 在每次实际 HTTP 尝试时绑定；timeout_seconds 为渠道超时秒数，retry_count 为当前重试策略轮次；gemini_cli_install_id 为 Gemini CLI 安装 UUID，仅支持 Gemini 协议。前四个来源归属 `quickquip` Profile。自有 Profile 必须保留四个专有头及其对应绑定。认证与 `content-type` 由协议适配器管理，Profile 文件不接受这些头。

协议表可使用 `protocol_ref = "claude-code"` 引用另一 Profile 的同协议配置。引用表只包含此字段，目标使用协议局部配置，顶层 UA、Header 和 bindings 为空；禁止链式及循环引用。内置 default 的 Chat、Responses、Anthropic 和 Gemini 分别引用 opencode2、codex、claude-code 和 gemini-cli。客户端模板的 UA 与其他特征定义在协议表中；已有 opencode2／codex 本地副本需将顶层 user_agent 移入对应 protocols.<协议>.headers 的 user-agent 字段，满足引用目标的协议局部约束；修改对应本地模板后重启，default 与显式客户端选择共用同一策略快照。

解析器拒绝未知字段、非法动态来源、重复头和不支持的协议。Profile 文件不保存密钥，不执行表达式或脚本。附加认证配置继续使用根目录 `.env` 的变量引用。

源码部署、wheel 和容器均包含内置模板。部署脚本保留当前 release 的本地覆盖文件，新候选中已有的同名文件优先；请同时备份覆盖目录与数据卷。

## OpenCode 2 Profile

选择 `opencode2` 后，默认 UA 为 `opencode/latest/2.0.27/cli`，client 为 cli；四个 OpenCode Session/affinity 头使用同一业务 Session 投影。新建或清空会话改变身份；冷场、历史裁剪和纪元推进保持身份。投影为 `ses_` 加 26 字符，稳定派生自业务 UUID 和创建时间，恢复业务 Session 后获得相同值。没有父子会话关系时省略 parent 头，默认不发送 x-opencode-request。

project 使用部署内稳定的不透明 40 位标识，从 `data/client_identity.json` 的安装身份域分离派生，不包含群号、用户号或本机路径。此 Profile 不发送四个 x-quickquip-* 品牌头。

b3 和 traceparent 共享进程内 trace ID，每次模型调用建立一个逻辑 parent span，每次实际 HTTP 尝试生成新 span。并发、工具续轮、重试和备用地址分别保留其请求上下文；追踪身份不参与 Session 生命周期，不持久化，也不发送遥测到 exporter。进程级 trace 范围是 QuickQuip 的投影规则。OpenCode 原生取证证实过跨 Session 共享 trace，完整生命周期仍取决于其运行入口。

自动绑定的 Session、project 和追踪头禁止在渠道 `headers` 中手工覆盖，大小写变体同样拒绝；UA 继续采用本页的覆盖优先级。Profile 文件本身可以编辑其绑定和策略，修改后重启生效。

通用兼容端点的 Body 使用 max_completion_tokens、store=false、工具 strict=false，省略默认 tool_choice=auto。公开端点的兼容规则来自固定版本源码，保存在 TOML 中，按实际候选 URL 的主机及渠道 ID 匹配；条件分别控制 max token 字段、store、strict、usage 和 tool_stream。代理端点使用自身的匹配结果，模型别名不会自动推断后台供应商。

实际输出预算、temperature、思考档位、人格和工具权限由已有业务配置决定，Profile 不采用捕获样本的工具集合或输出额度。工具返回省略冗余 name，空 assistant 工具正文使用 null；工具顺序、调用 ID、参数、结果、思考和图片继续保留。有工具历史而无当前工具时发送 tools=[]。显式 extra_body 优先于 Profile 缺省；同时配置 max_tokens 和 max_completion_tokens 会报错。手工覆盖可改变最终特征，管理员需要按上游协议填写。

Body 在确定实际候选 URL、流式模式之后投影，以紧凑 UTF-8 JSON 发送。流式请求保留 Accept=*/*，声明 gzip/deflate/br/zstd 并具备对应解压支持。quickquip 默认声明 gzip/deflate；default 的 Chat 使用同一 OpenCode 压缩策略。非流式配置及流式失败后的既有降级继续生效，这些兼容路径不代表原生 OpenCode 始终使用非流式请求。

协议表可增加 `body` 策略和 `header_order`；Chat Body 支持 `openai-chat-native`，字段及端点规则示例见随包 `opencode2.toml`。Header 布局在 HTTPX 补齐 Host、Connection、Content-Length 后应用，保留协议鉴权和值，仅按文件声明调整名称大小写及顺序；额外 Header 保留在声明字段之后。HTTP/1.1 实际序列化时，HTTPX 的 h11 传输层将 Host 放在首位，其他字段保持模板顺序和大小写；因此原生捕获中的 Host 位置属于当前传输边界。TLS、HTTP/2 和运行时内部行为另行校准。绑定新增来源为 opencode_session_id、project_id、b3、traceparent。策略和协议不匹配、错误类型、未知策略或未知字段会在加载阶段拒绝。完整模板中记录固定客户端版本和源码基线，升级目标版本时同步维护模板、证据和验证。


## Claude Code Profile

Anthropic 的内置 default 和 claude-code 使用固定 2.1.296 Linux x64 CLI、SDK 0.128.0、runtime v26.3.0、API Key、attribution 关闭的基线。流式与非流式均发送 Accept=application/json，支持 gzip/deflate/br/zstd。X-Stainless-Timeout 跟随渠道 timeout_seconds；Retry-Count 从 0 开始，按现有重试策略递增，备用地址保持当前轮次，新调用与流式降级从 0 开始。实际网络超时和流式读超时继续使用渠道策略。

system 为可编辑 CLI 身份文字和原有 QuickQuip 业务指令两个 text 块。人格、认人、引用、艾特和工具权限由业务 system 保持。模型、输出预算、thinking、工具集合、历史签名和媒体使用实际业务数据；转换只操作发送副本。

X-Claude-Code-Session-Id 与 metadata.user_id.session_id 共用业务 Session UUID；冷场、裁剪、纪元推进、重启及恢复保持，新建或清空改变。user_id 是紧凑 JSON 字符串，键序为 device_id、account_uuid、session_id。API Key 基线的 account_uuid 为空，当前不发送 Agent／parent-agent ID 或 billing 连续性字段。

全局 settings.runtime.claude_code_device_id 可在 Web Admin 设置，所有使用 CC 策略的渠道共用。非空值须为 64 位十六进制，保存时规范为小写；可填写已有 CC 的 userID。使用现成身份时，同步调整模板 OS／arch 以对应其来源环境。该字段作为配置文档和发布快照保存，配置数据库继续使用 schema 2。

留空时首次使用生成随机 32 字节，并将 64hex 自动身份保存到 data/client_identity.json 的 claude_code_device_id 字段。文件升级保留 install_id，通过跨进程锁和原子写入保存；损坏时明确报错。手工设置不覆盖自动值，清空设置恢复自动身份。备份恢复和部署迁移保留身份；复制数据卷建立独立部署时，可填写独立值，或停止服务、备份后移除新副本的自动 CC 字段再启动。该标识表达安装级身份，不采集硬件指纹，不作为鉴权凭据，也不证明上游认可客户端。

有效 thinking 开启时，缺省 context_management 保留所有 thinking 块；显式 extra_body.context_management 优先。beta 根据最终 tools、thinking、effort 和 JSON schema 输出派生；context-1m 使用已知模型窗口大于模板阈值的工程判据，窗口未知时省略。阈值默认 200000，可在 TOML 调整；它是兼容策略，不能据此推断模型实际具备 1M 上下文。显式 anthropic-beta Header 覆盖继续优先。不自动声明 advanced-tool-use、DTU 或 AFK。

缓存开启时在两个 system 块及末消息最后可缓存块打点，tools 不打点；TTL 沿用渠道设置。缓存关闭时清除协议位置的标记。thinking 块不直接打点，最终最多四个断点；工具参数、结果正文和 schema 保持不变。新增身份文字及结构开销计入首轮和工具循环预算，预算中的模型与输出预留采用最终覆盖值。

CC Body 策略拒绝渠道和模型 extra_body 中的 system、messages、tools；自动 user_id 开启时拒绝 metadata.user_id，包括 null。metadata 需为对象，其他键保留。动态 Session Header 禁止手工覆盖；UA 继续使用原有优先级。需要手工 user_id 时，在本地 Profile 将 metadata_user_id 设为 false，并移除对应 Session Header binding；需要完整手工 Body 时使用 legacy-claude 或不声明自动 Body 策略的自定义 Profile。

claude-code.toml 包含 claude-code-messages 策略、条件 beta 和 stream_accept="preserve"。协议表可设置 stream_accept 为 preserve 或 event-stream，分别保留已有 Accept 或为流式请求设 text/event-stream。Body 以紧凑 UTF-8 JSON 发送。原有 default.toml 本地覆盖继续整份生效；内置默认升级后出现受管字段冲突时，在应用前调整渠道配置或选择 legacy-claude。完整原生编程提示词、权限分类器、OAuth、count_tokens、TLS 和 HTTP/2 对齐另行评估。

## Codex Profile

选择 `codex` 后，默认 UA 为 `codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)`，originator 为 codex-tui。它是固定的 Linux 环境预设，版本与环境描述均保存在 TOML；需要匹配另一环境时编辑覆盖文件并重启。UA 继续采用本页的覆盖优先级。

session-id、thread-id、x-client-request-id 及 Body 的 prompt_cache_key 使用同一个业务 Session UUID。重试、工具续轮、冷场、历史裁剪及纪元推进保持；新建或清空业务 Session 后改变，恢复存档后沿用原身份。x-client-request-id 使用线程作用域。QuickQuip 当前没有独立子线程身份，三个请求头保持同值，直接使用已有 UUIDv4。

动态身份头拒绝渠道 headers 手工覆盖，包括大小写变体。Body 绑定生效时，渠道及模型的 extra_body 均禁止包含 prompt_cache_key，包括 null；配置校验和运行时会明确报错。需要手工控制缓存键时，从本地 Profile 文件移除该绑定并重启。标准渠道／模型 extra_body 中的 prompt_cache_key 属于缓存亲和数据，未声明动态绑定的 Profile 允许手工填写；default 的 Responses 和 codex 共同适用上述覆盖保护。其他位置和认证字段继续执行原有凭证校验。

可选协议表 body_bindings 当前仅支持 OpenAI Responses 的以下绑定：

```toml
[protocols.openai_responses.body_bindings]
prompt_cache_key = "business_session_id"
```

投影在实际 HTTP 尝试边界读取冻结请求，对载荷副本赋值；未知字段、来源、类型或协议组合会在加载阶段拒绝。格式版本仍为1，无新增身份文件或数据库迁移。

Codex Profile 提供轻量客户端身份及缓存亲和特征。既有 instructions、输出预算、temperature、工具权限、reasoning 档位、原生 items 和 phase 回放继续由 Responses 适配器管理，HTTP／SSE、备用地址与降级路径继续使用原有策略。responses_profile 单独控制后端能力。默认声明 gzip, deflate；此 Profile 不发送自有品牌四头、Codex turn/window 元数据或内部功能标记，不增加 WebSocket 和遥测。

## Gemini CLI Profile

Gemini 的内置 default 与 gemini-cli 采用 Gemini CLI 0.64.0、JavaScript SDK 1.30.0、Node 24.18.0、Linux x64 terminal TUI 的 HTTP/1.1 基线。版本、环境、静态头、Header 次序和 Body 布局保存在 gemini-cli.toml，支持现有本地覆盖。Accept 为 */*，流式请求保持此值；压缩声明 br, gzip, deflate，使用发行物已有 Brotli 解码依赖。

协议局部 user_agent_template 支持 {session_model}，默认 UA 为 GeminiCLI-tui/0.64.0/{session_model} (linux; x64; terminal)。业务 Session 首次使用该模板时，冻结实际请求的模型名；之后切换模型或渠道、工具续轮、重试及纪元推进沿用原锚点。default 与显式 gemini-cli 共用锚点。重启、聊天存档与恢复保留；清空或新开 Session 后重新绑定。模板版本和环境仍跟随当前配置快照，显式 UA 覆盖优先级沿用本页约定。

持续聊天的模型锚点由业务存储原子维护，Agent schema 4 为现有 Session 增加首次使用绑定，不猜测历史模型。临时总结、诊断等操作的锚点仅在该 Session 内存中保持；辅助识图继承传入 Session。该方案采用 QuickQuip 业务 Session 作用域；参考客户端在请求客户端创建时冻结 UA 模型，普通切换模型时也保持。当前 API Key 路径没有专有业务 Session Header。

全局 settings.runtime.gemini_cli_install_id 可在 Web 设置，为可选 UUIDv4，保存时规范为小写。留空时首次发送安装绑定生成独立随机 UUIDv4，保存在 data/client_identity.json 的 gemini_cli_install_id 字段，跨进程与重启稳定。手工设置不修改自动值，清空设置恢复自动值；损坏的已存身份会报错。x-gemini-api-privileged-user-id 使用此值，仅在声明绑定的 Profile 下发送，渠道 headers 禁止覆盖；需要省略时，从本地模板移除该绑定。它表达安装维度身份，随数据卷备份恢复，独立部署应使用独立身份。配置数据库保持 schema 2。

协议局部 api_key_transport 支持 query 或 header。新模板选择 header，由适配器注入 x-goog-api-key，不将凭据放入 URL；显式 auth_method=bearer 保持 Authorization: Bearer。认证字段不接受 Profile 静态配置。legacy-gemini 和未声明该设置的自定义 Profile 使用既有查询参数传输。

Body 的 gemini-cli-generate-content 策略保留业务 system 正文，以单个 text 的 systemInstruction 表示，并补充 role=user；不添加原生编程提示词。工具声明使用 parametersJsonSchema，保留实际 JSON Schema、工具及权限。输出预算、采样、thinking、媒体、工具 ID 与原生 thoughtSignature 使用业务数据。结构重排作用于发送副本，数组顺序和任意工具参数内容保留，JSON 为紧凑 UTF-8 且无末尾换行。

contents、systemInstruction、tools 为策略管理字段，渠道及模型 extra_body 中包含这些字段时，在保存和发送阶段拒绝；其余覆盖保持现有语义。启用新默认前核对受管字段与供应商 JSON Schema 支持，必要时选择 legacy-gemini。已有本地 default.toml 继续整份覆盖生效。

此 Profile 对齐应用层特征和现有 HTTP/1.1 布局。HTTPX 连接生命周期、TLS、Node 运行时行为及任意 JSON 数值的逐字节编码另行校准；请求重试和工具调度继续由现有业务策略管理。
