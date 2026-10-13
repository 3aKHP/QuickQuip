<!-- Generated from docs/admin/client-fingerprints.md; do not edit -->

# 请求指纹 Profile

Provider 的固定字段 `client_fingerprint` 选择客户端请求特征。内置 Profile 的支持范围为：

| ID | 支持协议 | 行为 |
|---|---|---|
| `default` | 四种协议 | 保留当前默认请求特征，作为升级后的缺省选择 |
| `quickquip` | 四种协议 | QuickQuip 品牌 UA 与部署、纪元及版本标识，需要显式选择 |
| `opencode2` | OpenAI Chat Completions | OpenCode 2.0.27 native 的 UA、身份头、追踪和 Body 布局，需要显式选择 |
| `codex` | OpenAI Responses | Codex TUI 0.162.1 的静态身份、业务 Session 头与缓存键，需要显式选择 |

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

Anthropic 的 `quickquip` Profile 移除默认 Claude Code 客户端身份头、Stainless 头、浏览器访问标记和 `claude-code` beta 项。其余现有能力声明、URL 与请求 Body 保持原有行为；专门的客户端 Body 对齐将在协议适配中完成。

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

`user_agent` 仅支持 `{client_version}` 版本替换。动态 `bindings` 的来源为 `install_id`、`epoch_id`、`cluster_id`、`client_version`、`stainless_os`、`opencode_session_id`、`project_id`、`b3`、`traceparent`、`business_session_id`。business_session_id 返回业务 Session 的规范 UUID；opencode_session_id 与 project_id 随请求绑定，b3 与 traceparent 在每次实际 HTTP 尝试时绑定；前四个来源归属 `quickquip` Profile。自有 Profile 必须保留四个专有头及其对应绑定。认证与 `content-type` 由协议适配器管理，Profile 文件不接受这些头。

解析器拒绝未知字段、非法动态来源、重复头和不支持的协议。Profile 文件不保存密钥，不执行表达式或脚本。附加认证配置继续使用根目录 `.env` 的变量引用。

源码部署、wheel 和容器均包含内置模板。部署脚本保留当前 release 的本地覆盖文件，新候选中已有的同名文件优先；请同时备份覆盖目录与数据卷。

## OpenCode 2 Profile

选择 `opencode2` 后，默认 UA 为 `opencode/latest/2.0.27/cli`，client 为 cli；四个 OpenCode Session/affinity 头使用同一业务 Session 投影。新建或清空会话改变身份；冷场、历史裁剪和纪元推进保持身份。投影为 `ses_` 加 26 字符，稳定派生自业务 UUID 和创建时间，恢复业务 Session 后获得相同值。没有父子会话关系时省略 parent 头，默认不发送 x-opencode-request。

project 使用部署内稳定的不透明 40 位标识，从 `data/client_identity.json` 的安装身份域分离派生，不包含群号、用户号或本机路径。此 Profile 不发送四个 x-quickquip-* 品牌头。

b3 和 traceparent 共享进程内 trace ID，每次模型调用建立一个逻辑 parent span，每次实际 HTTP 尝试生成新 span。并发、工具续轮、重试和备用地址分别保留其请求上下文；追踪身份不参与 Session 生命周期，不持久化，也不发送遥测到 exporter。进程级 trace 范围是 QuickQuip 的投影规则。OpenCode 原生取证证实过跨 Session 共享 trace，完整生命周期仍取决于其运行入口。

自动绑定的 Session、project 和追踪头禁止在渠道 `headers` 中手工覆盖，大小写变体同样拒绝；UA 继续采用本页的覆盖优先级。Profile 文件本身可以编辑其绑定和策略，修改后重启生效。

通用兼容端点的 Body 使用 max_completion_tokens、store=false、工具 strict=false，省略默认 tool_choice=auto。公开端点的兼容规则来自固定版本源码，保存在 TOML 中，按实际候选 URL 的主机及渠道 ID 匹配；条件分别控制 max token 字段、store、strict、usage 和 tool_stream。代理端点使用自身的匹配结果，模型别名不会自动推断后台供应商。

实际输出预算、temperature、思考档位、人格和工具权限由已有业务配置决定，Profile 不采用捕获样本的工具集合或输出额度。工具返回省略冗余 name，空 assistant 工具正文使用 null；工具顺序、调用 ID、参数、结果、思考和图片继续保留。有工具历史而无当前工具时发送 tools=[]。显式 extra_body 优先于 Profile 缺省；同时配置 max_tokens 和 max_completion_tokens 会报错。手工覆盖可改变最终特征，管理员需要按上游协议填写。

Body 在确定实际候选 URL、流式模式之后投影，以紧凑 UTF-8 JSON 发送。流式请求保留 Accept=*/*，声明 gzip/deflate/br/zstd 并具备对应解压支持。default 与 quickquip 默认继续声明 gzip/deflate。非流式配置及流式失败后的既有降级继续生效，这些兼容路径不代表原生 OpenCode 始终使用非流式请求。

协议表可增加 `body` 策略和 `header_order`；当前 Body 支持 `openai-chat-native`，字段及端点规则示例见随包 `opencode2.toml`。Header 布局在 HTTPX 补齐 Host、Connection、Content-Length 后应用，保留协议鉴权和值，仅按文件声明调整名称大小写及顺序；额外 Header 保留在声明字段之后。HTTP/1.1 实际序列化时，HTTPX 的 h11 传输层将 Host 放在首位，其他字段保持模板顺序和大小写；因此原生捕获中的 Host 位置属于当前传输边界。TLS、HTTP/2 和运行时内部行为另行校准。绑定新增来源为 opencode_session_id、project_id、b3、traceparent。策略和协议不匹配、错误类型、未知策略或未知字段会在加载阶段拒绝。完整模板中记录固定客户端版本和源码基线，升级目标版本时同步维护模板、证据和验证。


## Codex Profile

选择 `codex` 后，默认 UA 为 `codex-tui/0.162.1 (Ubuntu 24.04; x86_64) unknown (codex-tui; 0.162.1)`，originator 为 codex-tui。它是固定的 Linux 环境预设，版本与环境描述均保存在 TOML；需要匹配另一环境时编辑覆盖文件并重启。UA 继续采用本页的覆盖优先级。

session-id、thread-id、x-client-request-id 及 Body 的 prompt_cache_key 使用同一个业务 Session UUID。重试、工具续轮、冷场、历史裁剪及纪元推进保持；新建或清空业务 Session 后改变，恢复存档后沿用原身份。x-client-request-id 使用线程作用域。QuickQuip 当前没有独立子线程身份，三个请求头保持同值，直接使用已有 UUIDv4。

动态身份头拒绝渠道 headers 手工覆盖，包括大小写变体。Body 绑定生效时，渠道及模型的 extra_body 均禁止包含 prompt_cache_key，包括 null；配置校验和运行时会明确报错。需要手工控制缓存键时，从本地 Profile 文件移除该绑定并重启。

可选协议表 body_bindings 当前仅支持 OpenAI Responses 的以下绑定：

```toml
[protocols.openai_responses.body_bindings]
prompt_cache_key = "business_session_id"
```

投影在实际 HTTP 尝试边界读取冻结请求，对载荷副本赋值；未知字段、来源、类型或协议组合会在加载阶段拒绝。格式版本仍为1，无新增身份文件或数据库迁移。

Codex Profile 提供轻量客户端身份及缓存亲和特征。既有 instructions、输出预算、temperature、工具权限、reasoning 档位、原生 items 和 phase 回放继续由 Responses 适配器管理，HTTP／SSE、备用地址与降级路径继续使用原有策略。responses_profile 单独控制后端能力。默认声明 gzip, deflate；此 Profile 不发送自有品牌四头、Codex turn/window 元数据或内部功能标记，不增加 WebSocket 和遥测。
