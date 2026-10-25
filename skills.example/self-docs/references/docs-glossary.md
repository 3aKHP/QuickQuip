<!-- Generated from docs/glossary.md; do not edit -->

# QuickQuip 项目术语表

本文供用户、管理员和开发者查阅项目概念。条目给出统一名称、常用英文或代码映射及简短定义；字段约束和操作步骤由链接的领域文档维护。术语按配置、会话、历史和扩展能力分组。

## 配置与生效

<a id="provider"></a>
### 渠道（Provider）

一组提供模型调用能力的连接配置，包含稳定 ID、协议、地址、认证引用和模型清单。服务商品牌相同的连接可以配置为多个渠道。代码中的 `provider_id` 指向渠道 ID。见[配置接口](dev/llm-configuration-api.md)。

<a id="protocol"></a>
### 协议（Protocol）

QuickQuip 与模型服务交换请求和响应的格式约定，例如 OpenAI Chat Completions、Anthropic Messages、Gemini GenerateContent 和 OpenAI Responses。渠道选择协议，协议适配器负责相应序列化和解析。见[LLM 模块](dev/llm-module.md#请求组装与协议处理)。

<a id="model-id"></a>
### 模型标识（Model ID）

渠道配置中用于请求模型的名称，接口字段为 `model`。引用与定价使用渠道 ID 和模型标识组成的 `(provider_id, model)`；上游响应回报的模型名用于观测。见[配置接口](dev/llm-configuration-api.md#校验导入与历史)。

<a id="model-alias"></a>
### 模型别名（Model alias）

渠道内便于选择模型的名称映射。调用时先解析别名，模型请求使用解析后的名称；别名清单由渠道配置维护。见[渠道与模型接口](dev/llm-configuration-api.md#修订与读写)。

<a id="config-draft"></a>
### 配置草稿（Configuration draft）

配置数据库中供编辑和校验的当前文档。保存草稿后，通过独立的应用操作把选定内容交给 Bot。见[配置操作](admin/llm-configuration.md#首次启用-llm)。

<a id="config-workspace"></a>
### 配置工作副本（Configuration workspace）

由本地真实配置生成的可编辑目录：数据库内容展开为业务 TOML，其余文件保留原格式。默认位于 `.config-workspace/`，保存注释、共同基线和恢复资料。见[工作副本操作](admin/config-workspace.md)。

### qqconf

本地配置工作副本 CLI。`unpack` 接收真实配置，`refresh` 只读预览，`pack` 校验并写回真实配置或 `.config-staging/` 候选。配置生效由应用和部署流程负责。见[命令指南](admin/config-workspace.md)。

<a id="config-revision"></a>
### 配置修订（Configuration revision）

识别配置内容及并发修改的递增编号，接口字段为 `revision`。有效内容变更增加修订号，相同内容保存保持编号。项目发行版本、数据库 schema 和会话历史修订分别使用各自的标识。见[修订与读写](dev/llm-configuration-api.md#修订与读写)。

<a id="config-snapshot"></a>
### 配置快照（Configuration snapshot）

应用或探测任务绑定的不可变配置输入。建立快照后继续修改草稿，该任务仍使用原目标；历史中包含应用和探测的快照，发布结果需结合任务状态判断。见[应用与探测](dev/llm-configuration-api.md#应用探测与运行状态)。

<a id="published-config"></a>
### 已发布配置（Published configuration）

配置数据库记录的当前发布版本。它与草稿、Bot 回报的加载版本分别展示，帮助管理员判断编辑和生效进度。见[配置状态](dev/llm-configuration-api.md#应用探测与运行状态)。

<a id="loaded-config"></a>
### 已加载配置（Loaded configuration）

Bot 最近回报已接纳的运行配置版本，通过 `loaded_revision` 等状态字段观察。MCP 连接、工具发现等组件的就绪状态另外回报。见[运行状态](dev/llm-configuration-api.md#应用探测与运行状态)。

## 会话与执行

<a id="scope"></a>
### 作用域（Scope）

会话设置、历史和相关业务状态的隔离范围，例如一个群聊或一位用户的私聊入口。同一作用域可以先后绑定不同的业务 Session。见[上下文边界](dev/llm-module.md#4-上下文边界)。

<a id="session"></a>
### 业务会话（Session）

应用维护的一段持续 LLM 交互，具有稳定身份和明确的续接、归档与结束边界。聊天中的工具续轮、重试、冷场缩窗和服务重启沿用所属身份；独立任务按业务操作建立身份。本条适用于 LLM，游戏的 Session 模式见[游戏框架](dev/game-framework.md)。详细生命周期见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="epoch"></a>
### 会话纪元（Session epoch）

某个作用域、渠道和模型下，管理历史读取窗口与冻结表达的阶段，常简称“纪元”或 `epoch`。窗口或表达需要重建时推进纪元，业务 Session 可以继续保持。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)及[冻结决策](dev/adr/0003-epoch-history-freezing.md)。

<a id="agent-loop"></a>
### 执行回合（Agent Loop）

一次外部触发启动的完整生成、工具执行和交付过程，可包含多个模型轮次。业务执行记录中的 Loop 与 HTTP Trace 的调用分组各自维护关联标识。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="turn"></a>
### 模型轮次（Turn）

一个完整接收并通过结构校验的模型响应。工具调用轮和最终回复轮都可以形成 Turn；其中可显示的正文按交付策略生成消息片段。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="chunk"></a>
### 消息片段（Chunk）

同一个 Turn 正文中供发送的一段源文本范围。正文拆分参数影响片段划分，模型轮次与工具事实保留各自的边界。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="delivery"></a>
### 交付条目（Delivery）

计划向聊天平台发送的一个内容条目，包括文字片段、工具媒体或主机通知。交付记录关联发送尝试及其结果，供引用、撤回和故障判断使用。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="delivery-attempt"></a>
### 交付尝试（Delivery attempt）

针对交付条目发起的一次 OneBot 调用。回执用于确认送达、失败或结果未知；发送尝试与模型生成轮次分别记录。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="http-attempt"></a>
### HTTP 尝试（HTTP attempt）

向模型服务发起的一次实际 HTTP 请求。重试、备用地址或工具结果回送可以产生新的 HTTP 尝试，其追踪记录用于诊断。见[LLM 请求追踪](dev/llm-module.md#1-模块定位)。

<a id="generation"></a>
### 写入代次（Generation）

作用域的执行有效性标识，代码字段为 `generation`。清空、切换等失效操作推进代次，后续写入校验据此阻止旧执行把迟到结果写回当前状态。它与 Session ID、配置修订、历史修订分别管理。见[会话写入边界](dev/llm-module.md#42-llm-短期会话)。

## 历史与上下文

<a id="chat-archive"></a>
### 聊天归档（Chat archive）

统一保存群聊消息的记录源，供群聊搜索、日报、词云和周期报告等功能使用。它与用于延续 LLM 对话的历史分别维护。见[持久化数据目录](dev/architecture.md#data--运行时持久化数据自用层gitignore)及[统一归档决策](dev/adr/0007-unified-chat-archive.md)。

<a id="conversation-history"></a>
### LLM 对话历史（Conversation history）

为多轮对话延续保存的用户输入、模型回复及关联执行事实。每次请求按当前窗口、协议兼容性和预算选取并投影相应内容。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="recent-context"></a>
### 近期上下文（Recent context）

从最近消息缓冲中取得、供当前回复理解现场的消息。缓冲的时间和数量边界由对应实现管理，选入请求的内容按本轮生命周期使用。见[临时上下文](dev/llm-module.md#41-临时上下文)。

<a id="long-term-memory"></a>
### 长期记忆（Long-term memory）

由人工记录或符合资格的自动提取形成的持久事实，用于后续检索与个性化回答。记忆具有自己的归属、检索和删除规则。见[记忆与上下文](dev/llm-module.md#74-记忆与上下文)及[记录身份契约](dev/record-identities.md)。

<a id="turn-envelope"></a>
### 当轮信封（Turn envelope）

请求组装时放入用户消息头部的“轮次上下文”，承载当前时间、参与者、记忆或词表命中等动态信息。其生命周期属于当前交互，历史使用允许保留的规范表达重建。见[当前注入规则](dev/llm-module.md#55-身份映射注入)及[静态前缀决策](dev/adr/0012-static-prefix-turn-envelope.md)。

<a id="scene-patch"></a>
### 现场补丁（Scene patch）

从近期群聊中选取、为本轮请求补充现场信息的内容，以“现场”段呈现。选择结果在本次请求装配和预算重组之间复用，并与已有历史去重。见[LLM 短期会话](dev/llm-module.md#42-llm-短期会话)。

<a id="native-replay"></a>
### 原生回放（Native replay）

在协议归属和结构检查通过后，把保存的协议原生条目用于历史请求，例如 Gemini parts、Claude 签名块或 Responses output items。具体兼容与降级规则由协议适配器维护。见[历史投影契约](dev/llm-module.md#42-llm-短期会话)及[原生回放决策](dev/adr/0013-native-replay-compatibility.md)。

<a id="generic-replay"></a>
### 通用回放（Generic replay）

从规范正文、结构化工具事实及省略说明生成可供目标模型理解的历史表达。原生状态缺失或不兼容时，投影按协议规则采用通用表达或档案。见[历史投影契约](dev/llm-module.md#42-llm-短期会话)。

<a id="ephemeral-result"></a>
### 临时检索结果（Ephemeral result）

按已接受的工具结果政策，仅供当前回合使用、业务记录保留执行事实和省略说明的查询结果正文，保留策略名为 `ephemeral`。存储支持与工具入口接入情况见[工具结果保留决策](dev/adr/0005-tool-result-retention.md#落地核对)；HTTP Trace 按独立诊断职责管理。

## 身份与扩展能力

<a id="persona"></a>
### 人格（Persona）

组织机器人角色、语气和业务行为提示的配置。群聊或私聊可以选择人格，来源文件与合并规则由 LLM 配置和人格加载流程维护。见[人格与资料](dev/llm-module.md#5-人格注入设计)。

<a id="client-profile"></a>
### 客户端 Profile（Client fingerprint profile）

定义请求发给上游时采用的客户端特征、请求头与请求体投影策略的模板，由渠道的 `client_fingerprint` 选择。Profile 接收业务 Session 等输入，具体协议模板见[请求指纹 Profile](admin/client-fingerprints.md)，选择依据见[客户端 Profile 决策](dev/adr/0014-client-fingerprint-profiles.md)。

<a id="member-identity"></a>
### 成员身份（Member identity）

以 QQ 为稳定关联键的成员资料及名称解析结果，用于展示、提及和记录关联。群级覆盖、同名歧义和历史名称快照由[记录身份契约](dev/record-identities.md)维护，选择依据见[正文与成员关联决策](dev/adr/0008-record-content-member-identity.md)。

<a id="tool"></a>
### 工具（Tool）

向模型公开名称、说明和参数 schema，并由运行时校验和调度的可调用能力。工具可来自内置实现、MCP 或 Skill 脚本，具体注册与发现规则见[工具发现](dev/tool-discovery.md)。

<a id="tool-execution"></a>
### 工具执行（Tool execution）

某个 Turn 声明的一次工具调用及其执行事实。声明、启动、成功、失败或结果不确定分别记录；历史回放引用这些事实。见[执行与交付决策](dev/adr/0004-agent-execution-replay-delivery.md)。

<a id="skill"></a>
### 技能包（Skill）

由 `SKILL.md` 描述、按需激活的指令与资源包，可按部署权限提供脚本能力。包的安装、可见性、激活和执行边界见[Skill 系统](admin/skills.md)，按需取得正文的选择依据见[渐进加载决策](dev/adr/0015-progressive-skill-loading.md)。

<a id="mcp-server"></a>
### MCP 服务（MCP server）

通过 Model Context Protocol 向 QuickQuip 提供工具或资源的外部服务。连接、能力发现、参数适配和结果校验由 MCP 集成层负责。见[MCP 集成](dev/mcp-integration.md)及[结果归一化决策](dev/adr/0018-mcp-result-normalization.md)。
