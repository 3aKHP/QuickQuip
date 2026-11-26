<!-- Generated from docs/glossary.md; do not edit -->

# QuickQuip 项目术语表

本文供用户、管理员和开发者查阅项目核心概念。每个词条给出统一中文名称、常用英文或代码标识及简明定义；具体参数、命令与操作步骤见词条末尾链接的领域文档。术语按部署、配置、会话、历史和扩展能力分组。

## 部署与运行

<a id="deployment-location"></a>
### 部署位置（Deployment location）

按配置或部署命令的操作目标区分“本地”与“云端”：本地直接读写当前机器上的项目目录并管理本机服务，云端通过 SSH 操作远端服务器。见[部署分类与安装入口](admin/installation.md#确定部署方式)。

<a id="runtime-mode"></a>
### 运行方式（Runtime mode）

QuickQuip Bot 与 Web Admin 的进程运行形态，分为主机 Python 进程（文档简称“源码”，包含 Windows 懒人包）与 Docker 容器（包含发行镜像、本地构建镜像及挂载源码的混合编排）。见[部署分类与安装入口](admin/installation.md#确定部署方式)。

<a id="onebot-backend"></a>
### 协议端（OneBot backend）

由部署者独立运行并维护 QQ 登录态的协议服务（如 LLBot、NapCat），通过 OneBot V11 协议为 QuickQuip 提供消息收发与接口调用。接入方法见[协议端说明](admin/onebot-adapters.md)，职责边界见 [ADR-0032](dev/adr/0032-swappable-onebot-backend.md)。

## 配置与生效

<a id="provider"></a>
### 渠道（Provider）

一组可直接调用上游模型接口的连接配置，包含稳定标识（代码中为 `provider_id`）、协议类型、接口地址、认证凭据引用和可用模型清单。同一服务商可按用途、密钥或中转入口配置为多个渠道。见[配置接口](dev/llm-configuration-api.md)。

<a id="protocol"></a>
### 协议（Protocol）

QuickQuip 与上游模型服务通信时使用的请求和响应格式约定，支持 OpenAI Chat Completions、Anthropic Messages、Gemini GenerateContent 和 OpenAI Responses 四类。渠道选定协议后，由对应的协议适配器完成请求组装与响应解析。见[LLM 模块](dev/llm-module.md#请求组装与协议处理)。

<a id="model-id"></a>
### 模型标识（Model ID）

渠道配置中发往上游接口的实际模型名称，接口字段为 `model`。系统内的模型绑定、路由与计费定价均以 `(provider_id, model)` 组合唯一定位。见[配置接口](dev/llm-configuration-api.md#校验导入与历史)。

<a id="model-alias"></a>
### 模型别名（Model alias）

渠道内为较长或带日期后缀的模型标识设置的简短代称。用户在命令或配置中填写别名时，调用前会先解析为对应的模型标识。见[渠道与模型接口](dev/llm-configuration-api.md#修订与读写)。

<a id="config-draft"></a>
### 配置草稿（Configuration draft）

配置数据库中供在线编辑和校验的工作版本。保存操作只会更新草稿，需进一步执行“应用”才会将选定草稿发布给 Bot 加载。见[配置操作](admin/llm-configuration.md#首次启用-llm)。

<a id="config-workspace"></a>
### 配置工作副本（Configuration workspace）

供本地文件编辑使用的配置展开目录（默认位于 `.config-workspace/`）。其中数据库受管配置会展开为带注释的业务 TOML 文件，其余独立配置文件保持原格式，同时保存合并基线与中断恢复信息。见[工作副本操作](admin/config-workspace.md)。

### qqconf

管理本地配置工作副本的命令行工具：`unpack` 从真实配置生成或更新工作副本，`refresh` 只读预览双端差异，`pack` 校验并将修改写回本地配置或生成 `.config-staging/` 暂存候选。见[命令指南](admin/config-workspace.md)。

### qqsync

跨环境同步配置并触发服务生效的命令行工具，按根 `.env` 中的部署位置与运行方式工作：`refresh` 只读预览变更，`push` 推送本地配置或安装暂存候选并按需通知运行中服务生效，`pull` 将线上配置拉回本地。见[命令指南](admin/config-sync.md)。

<a id="config-revision"></a>
### 配置修订（Configuration revision）

配置数据库中用于标记版本与检测并发冲突的递增编号，接口字段为 `revision`。配置内容发生实际变化时递增，重复保存相同内容不会改变编号。见[修订与读写](dev/llm-configuration-api.md#修订与读写)。

<a id="config-snapshot"></a>
### 配置快照（Configuration snapshot）

发起“应用”或“探测”任务时冻结的一份不可变配置副本。快照生成后即使继续修改草稿，已创建的任务仍按启动时的快照执行。见[应用与探测](dev/llm-configuration-api.md#应用探测与运行状态)。

<a id="published-config"></a>
### 已发布配置（Published configuration）

配置数据库中最近一次执行“应用”所指定的目标运行配置。管理员可在后台对照草稿修订号、已发布配置与已加载配置，确认最新修改是否已发布并被 Bot 接纳。见[配置状态](dev/llm-configuration-api.md#应用探测与运行状态)。

<a id="loaded-config"></a>
### 已加载配置（Loaded configuration）

Bot 进程实际完成装载并投入运行的配置版本（状态字段 `loaded_revision`）。执行“应用”后，待 Bot 拉取快照并完成重载，“已加载配置”即更新为刚发布的版本。见[运行状态](dev/llm-configuration-api.md#应用探测与运行状态)。

## 会话与执行

<a id="scope"></a>
### 作用域（Scope）

隔离对话设置、短期上下文与长期记忆的单元，通常对应一个群聊（`group:<群号>`）或一位私聊用户（`private:<QQ号>`）。见[上下文边界](dev/llm-module.md#4-上下文边界)。

<a id="session"></a>
### 业务会话（Session）

一段连续的 LLM 对话周期，具有稳定的 Session 标识及明确的开启、续接、存档与结束边界。日常对话中的多轮工具调用、失败重试、冷场缩窗和进程重启都会沿用当前业务会话身份；定时报告与单发命令则按各自任务独立建立身份（群内小游戏的对局 Session 另见[游戏框架](dev/game-framework.md)）。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="epoch"></a>
### 会话纪元（Session epoch）

同一作用域、渠道与模型组合下，管理对话历史读取起点与已冻结前缀的阶段编号（简称“纪元”或 `epoch`）。遇到清空上下文、切换人格或冷场缩窗等需要重建上下文窗口的情形时，系统推进到新纪元，所属业务会话身份保持延续。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)及[冻结决策](dev/adr/0003-epoch-history-freezing.md)。

<a id="agent-loop"></a>
### 执行回合（Agent Loop）

由一次用户触发或定时任务启动的完整 AI 处理闭环，内部可包含一轮或多轮模型生成、工具调用及消息发送。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="turn"></a>
### 模型轮次（Turn）

单个执行回合内，模型完成一次生成并通过结构校验所产出的一轮响应。发起工具调用的中间响应和给出最终答复的响应各记为一个 Turn。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="chunk"></a>
### 消息片段（Chunk）

将单个模型轮次的可展示正文按分段发送策略切分后得到的文本片段，是向聊天平台逐条发送文字的基本单元。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="delivery"></a>
### 交付条目（Delivery）

计划向聊天平台发出的单条消息项，包括正文片段、工具产出的图片媒体或系统通知，用于关联发送结果、消息引用与撤回操作。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="delivery-attempt"></a>
### 交付尝试（Delivery attempt）

针对某个交付条目发起的一次 OneBot 发送请求，记录成功送达、明确报错或回执超时未知等发送结果。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="http-attempt"></a>
### HTTP 尝试（HTTP attempt）

向模型服务发起的一次底层 HTTP 请求。发生网络重试、备用地址切换或多轮工具结果回传时，单个执行回合会产生多次 HTTP 尝试，完整请求与响应报文记录在 HTTP Trace 中供排障使用。见[LLM 请求追踪](dev/llm-module.md#1-模块定位)。

<a id="generation"></a>
### 写入代次（Generation）

用于防止旧异步任务覆盖最新会话状态的递增序号，代码字段为 `generation`。执行清空上下文、切换模型等重置操作时会推进代次；此前已在运行的旧任务结束时若发现代次过期，将放弃写回结果。见[会话写入边界](dev/llm-module.md#42-llm-短期会话)。

## 历史与上下文

<a id="chat-archive"></a>
### 聊天归档（Chat archive）

持久化保存群内日常聊天消息的统一数据库（`data/chat_archive.db`），供 `/find` 搜索、词云、每日总结、播报、周月报及按需群历史查询读取；与专门记录 AI 多轮问答的“LLM 对话历史”分开存储。见[持久化数据目录](dev/architecture.md#data--运行时持久化数据自用层gitignore)及[统一归档决策](dev/adr/0007-unified-chat-archive.md)。

<a id="conversation-history"></a>
### LLM 对话历史（Conversation history）

为延续多轮 AI 对话而保存的用户输入、模型回复及工具调用记录。每次发起请求时，系统按当前会话纪元窗口、协议兼容规则与 token 预算从中选取记录并组装上下文。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="recent-context"></a>
### 近期上下文（Recent context）

从内存近期消息缓冲中读取的最近若干条群内普通发言，供 AI 在被触发时快速了解当前聊天现场，仅在当轮请求内临时附带。见[临时上下文](dev/llm-module.md#41-临时上下文)。

<a id="long-term-memory"></a>
### 长期记忆（Long-term memory）

跨对话持久保留的群内约定、偏好与事实笔记（支持 Markdown 格式），可通过 `/remember` 等指令、AI 记忆工具或 Web 管理后台维护。群聊记忆由全群共享，私聊记忆按个人独立保存。见[记忆与上下文](dev/llm-module.md#74-记忆与上下文)及[记录身份契约](dev/record-identities.md)。

<a id="turn-envelope"></a>
### 当轮信封（Turn envelope）

组装本轮用户消息时拼在正文前面的动态背景块，包含当前时间、发言人与被艾特成员档案、自动召回的长期记忆及命中设定词条等信息；仅服务于当轮生成，不会原样固化进后续历史。见[当前注入规则](dev/llm-module.md#55-身份映射注入)及[静态前缀决策](dev/adr/0012-static-prefix-turn-envelope.md)。

<a id="scene-patch"></a>
### 现场补丁（Scene patch）

从近期群聊缓冲中提取、并与已有对话历史去重后补充进本轮请求的“现场”消息段，帮助 AI 自然衔接触发前群友正在讨论的话题。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="native-replay"></a>
### 原生回放（Native replay）

在同一协议与兼容模型下续接对话时，直接复用已保存的协议原生消息结构（如 Gemini `parts`、Claude 思维签名块、Responses 输出项）回放历史，保留完整的推理签名与工具交互细节。见[历史投影契约](dev/llm-module.md#42-llm-短期会话)及[原生回放决策](dev/adr/0013-native-replay-compatibility.md)。

<a id="generic-replay"></a>
### 通用回放（Generic replay）

跨协议切换模型、原生块缺失或因临时结果策略省略原生副本时，根据已保存的规范文本、结构化工具执行记录与省略说明重新构造的通用历史消息。见[历史投影契约](dev/llm-module.md#42-llm-短期会话)。

<a id="ephemeral-result"></a>
### 临时检索结果（Ephemeral result）

采用 `ephemeral` 保留策略的工具返回内容（如近期消息搜索、群历史查询与群语录检索结果）。完整检索正文仅供模型在当前执行回合内阅读作答，写入对话记录时只保留调用事实与省略说明，避免大段检索摘录长期占用后续对话窗口。见[工具结果保留决策](dev/adr/0005-tool-result-retention.md#落地核对)。

<a id="group-history-query"></a>
### 群历史查询（Group history query）

供 AI 按需只读检索本群聊天归档的能力，包含关键词搜索（`search_group_history`）、按来源引用展开上下文（`read_group_history`）和委派子代理处理复杂追溯问题（`investigate_group_history`）三个工具。全局默认关闭，支持按群显式开启或关闭（私聊不提供）；检索内容按临时检索结果处理，不自动写入长期记忆。见 [ADR-0027](dev/adr/0027-history-investigation-executor.md)。

<a id="message-ref"></a>
### 来源引用（Message ref）

群历史查询工具为命中消息签发的归档定位标识，格式为 `hr1.<归档UUID前8位>.<行ID>`。模型可凭该标识在本群后续轮次中精确展开对应消息前后的上下文；标识绑定当前归档数据库并在读取时核验所属群号，更换归档库后自动失效（翻页游标则仅在单次请求内有效）。见 [ADR-0027](dev/adr/0027-history-investigation-executor.md)。

## 身份与扩展能力

<a id="persona"></a>
### 人格（Persona）

定义 AI 角色背景、说话风格与互动准则的提示词配置，支持按群聊或私聊独立选择与切换。见[人格与资料](dev/llm-module.md#5-人格注入设计)。

<a id="client-profile"></a>
### 客户端 Profile（Client fingerprint profile）

控制向上游模型服务发请求时采用的客户端标识、HTTP 请求头与请求体结构的模板，由渠道配置中的 `client_fingerprint` 选定。见[请求指纹 Profile](admin/client-fingerprints.md)及[客户端 Profile 决策](dev/adr/0014-client-fingerprint-profiles.md)。

<a id="member-identity"></a>
### 成员身份（Member identity）

以 QQ 号为稳定主键维护的群友身份档案与别名映射，用于识别群友称呼、解析真实艾特，并在长期记忆、语录和离线留言中动态展示最新群名片。见[记录身份契约](dev/record-identities.md)及[正文与成员关联决策](dev/adr/0008-record-content-member-identity.md)。

<a id="tool"></a>
### 工具（Tool）

向模型公开名称、用途说明和参数 Schema，并由运行时校验参数后调度的可调用能力，来源包括内置工具、外部 MCP 服务及已激活的 Skill 脚本。见[工具发现](dev/tool-discovery.md)。

<a id="tool-execution"></a>
### 工具执行（Tool execution）

模型在某一轮次中发起的单次工具调用及其执行记录，保存调用声明、执行状态（成功、失败或结果未知）及受保留策略控制的结果摘要，供后续对话回放与审计使用。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="skill"></a>
### 技能包（Skill）

以 `SKILL.md` 描述、由模型在遇到匹配需求时按需激活的指令与参考资料包；经部署者授权后还可附带受隔离限制的可执行脚本。见[Skill 系统](admin/skills.md)及[渐进加载决策](dev/adr/0015-progressive-skill-loading.md)。

<a id="mcp-server"></a>
### MCP 服务（MCP server）

通过 Model Context Protocol 向 QuickQuip 提供外部工具的独立服务，由 MCP 集成层负责连接维护、工具发现、参数传递与返回结果归一化。见[MCP 集成](dev/mcp-integration.md)及[结果归一化决策](dev/adr/0018-mcp-result-normalization.md)。
