# QuickQuip LLM 模块说明

本文面向 LLM 运行时维护者，说明消息触发、Session 与上下文窗口、请求组装、人格编译、工具调用及协议适配契约。日常配置与运维操作见[管理员文档](../admin/llm-configuration.md)，请求结构排障见本页[第 11 节](#11-请求结构排障)。

核心概念定义见[项目术语表](../glossary.md#session)，会话身份、纪元冻结、历史调查与引用显示投影等架构取舍见[架构决策索引](adr/README.md)。

## 1. 模块定位

QuickQuip 的 LLM 模块在规则机器人之上提供多轮对话、知识检索与周期内容生成能力。管理员可按群聊或私聊作用域配置渠道、模型与人格，并独立控制触发条件、长期记忆、群历史查询和工具调用。默认显式入口包括配置前缀、艾特机器人和 `/search`；群聊被动唤醒受第 3 节的开关、阈值与限流器约束。

模块支持图片理解与生成、语音转写、项目内 SearXNG 搜索、Gemini／Claude／Responses 原生联网搜索以及本地函数与外部 MCP 工具调用。MCP 服务通过统一注册表接入工具循环，协议与安全边界见 [MCP 集成说明](mcp-integration.md)。

当环境变量 `LLM_TRACE_FLAG_FILE` 指向的开关文件存在时，LLM 运行时将每次底层 HTTP 尝试写入 `data/llm_trace.db`：请求正文直接取自提交给 HTTP 客户端的 UTF-8 JSON 文本；非流式响应保存 JSON 解析前的服务端原始文本；流式响应在完整消费 SSE 后，由各协议客户端重组为对应的 OpenAI Chat Completion、Claude Message、Gemini GenerateContent 或 OpenAI Responses 响应对象，同时并列保存原始 SSE 帧供排障核对。数据库将轻量调用索引、大体积报文正文与单调递增的状态事件分表存储，Web Admin 列表先读取元数据，点击单条记录后再按需加载完整 Header 与正文。`run_tool_call_loop` 为每轮完整工具交互分配统一的 Agent Loop ID，循环内的重试、备用地址切换与工具结果续轮按组内序号依次排列。

配置 `LLM_TRACE_MEDIA_MIN_BYTES` 后，Trace 入库前会自动剥离达到字节门槛的内联 base64 媒体载荷。扫描范围覆盖完整 JSON 报文、单行 JSON 格式的 SSE `data:` 记录以及其中最多四层嵌套的 JSON 字符串：带 `data:` URI 前缀的内容须通过严格 base64 校验；裸 base64 文本还须位于明确声明媒体的字段（如 `b64_json`、`partial_image_b64`、伴随 MIME 声明的 `data` 或生图结果字段）。普通文本、低于门槛的短载荷及无法解析的编码形态保持原样入库。

被剥离的媒体原文按 SHA-256 摘要写入 `data/trace_blobs/`，报文内原位置替换为占位符 `[qq:blob sha256=<hex> bytes=<n>]`（`data:` URI 前缀一并计入哈希，跨请求、重组响应与原始 SSE 共享同一份物理文件）。每条记录的 `media_truncation` 清单保存各处替换偏移与哈希，原始字节统计维持剥离前体积，实际发往上游的网络请求仍使用完整载荷。

每个 `trace_blobs/` 目录归属对应的 Trace 数据库管辖。Bot 与 Web Admin 通过该库的 `BEGIN IMMEDIATE` 写事务协调文件创建、哈希复用、引用落库及垃圾回收：每日过期清理后，仅删除无任何记录引用且文件年龄超过一天的孤立文件（留出一天的写入恢复窗口）；遇到损坏清单时跳过当轮文件清理。管理员手动清空 Trace 时同步删除无引用载荷文件。详情接口默认返回带占位符的报文，传入 `restore=true` 时按清单回填并校验全文与分片哈希，文件缺失或摘要不符返回 HTTP `409`；单文件下载接口继承后台会话鉴权，固定以 `application/octet-stream` 附件及 `nosniff`、严格 CSP 响应头下发。即使后续关闭媒体剥离，已剥离的历史记录仍可正常还原。相关环境变量与备份说明见[管理员配置](../admin/configuration.md#trace-媒体存储)。

### 1.1 执行记录的请求边界

群聊与私聊生成请求在创建 Agent 执行记录时，按请求显式携带的 `trigger_kind` 记录触发来源；调用方未指定时，群聊记为 `group_direct`，私聊记为 `private_direct`，群聊唤醒触发记为 `group_passive`，供 Loop 详情面板与归档查询区分触发路径。存量记录保留写入时的分类，缺失原始触发上下文的旧数据不做事后推断回填。

若请求在等待模型响应、执行工具或分段发送消息期间被取消，服务会将当前已开启的 Loop 幂等收束为 `interrupted`（终止原因 `request_cancelled`），随后向上层继续传播取消异常：已完成的 Turn、已落库的工具结果与已确认的发送回执原样保留；已声明但尚未启动的工具标记为 `not_executed`，执行中途中断且无结果的工具标记为 `indeterminate`，尚未发出的分段交付标记为 `skipped`，已发出但未收到协议端回执的交付标记为 `unknown`。取消收尾阶段不再补发消息或重试工具；底层存储健康时，同一会话的后续请求可正常开启新 Loop。

---

### 1.2 请求指纹与身份投影

`quickquip.llm.client_fingerprints` 模块负责解析客户端指纹 Profile 模板、构建启动期目录快照、维护 `data/client_identity.json` 安装身份，并在协议适配边界执行请求头与请求体投影。渠道固定字段 `client_fingerprint` 指定所用模板，配置编译阶段绑定全局 `client_cluster` 与数据目录，模型级参数覆盖沿用同一渠道身份绑定。四类协议客户端在完成鉴权头组装与业务 Body 序列化后调用统一的投影接口：OpenCode 2 在最终请求 URL 与流式标志确定后执行 Chat Body 兼容适配及分布式追踪头注入；Codex 通过可选的 `body_bindings` 在单次 HTTP 尝试边界注入业务会话缓存键，其余适配器字段保持不变。HTTP 请求头按模板声明的 `header_order` 排布在 HTTPX 请求对象上；HTTP/1.1 传输层由 `h11` 将 `Host` 置顶，其余字段严格维持模板顺序与大小写。

身份传递链路上，`LLMRequest.session` 携带不可变的业务会话快照 `SessionIdentity`，`epoch_id` 携带当前上下文纪元 UUID。常规对话由 `EpochManager` 维护纪元窗口 UUID，经 `TurnRequestAssembler` 在加载历史与预算裁剪后注入请求；定时报告、人物志等独立后台任务在操作开始时生成单次临时纪元，前置识图与工具子调用沿调用链继承父级会话与纪元身份。自有 `quickquip` Profile 要求底层请求提供合法 UUIDv4。动态投影生成的身份请求头不参与 Responses 历史原生回放的归属指纹计算。模板语法与运维说明见[请求指纹 Profile](../admin/client-fingerprints.md)，四大内置模板的协议细节见[请求指纹与协议转换实现](client-fingerprints.md)。

各模板的会话派生规则相互独立：OpenCode 的 `ses_...` 标识由业务 Session 纯函数派生，跨纪元推进与存档恢复保持恒定；Codex 的 `session-id`、`thread-id`、`x-client-request-id` 与 `prompt_cache_key` 同源绑定业务 Session UUID，受 Profile 独占保护，禁止在渠道或模型的 `headers`／`extra_body` 中手工覆盖。请求级 `ContextVar` 保存当前冻结请求与父级追踪 Span，每次底层 HTTP 尝试（含退避重试与备用 URL 切换）在写入 Trace 前派生独立子 Span，并在结束、异常或取消时自动还原外层上下文。网络鉴权、代理、超时控制、SSE 流解析与用量记账仍由 `llm/provider/` 承担，Profile 层不读写业务数据库，也不介入人格与工具权限判定。

## 2. 当前代码结构

LLM 相关核心模块与职责如下：

| 文件或目录 | 职责 |
|---|---|
| `src/quickquip/adapters/nonebot/commands.py` | 注册 `/llm`、`/search` 等命令入口；具体处理器按域拆分在 `command_parts/`（`llm` / `memory` / `sts` / `skills` / `media` 等） |
| `src/quickquip/adapters/nonebot/group_messages.py`、`private_messages.py` | NoneBot 群聊与私聊消息入口，负责媒体与转发提取并转交应用层管线 |
| `src/quickquip/adapters/nonebot/daily_summary_plugin.py` | 每日总结与周期报告的定时任务注册及 `/summary` 命令；生成与发布状态机位于 `src/quickquip/chat/summary_jobs.py` |
| `src/quickquip/app/message_pipeline.py` | 应用组合根：装配 `chat` / `games` / `tieba` / `llm` 单例、组织 `resolve_reply()` 规则链、管理配置热重载与持久化优雅关闭 |
| `src/quickquip/llm/service.py` | `LLMService` 门面，按 `ChatTurnRequest` 编排会话设置、提示词、记忆、工具与模型调用；子域实现拆分至 `service_parts/` |
| `src/quickquip/llm/reply_chain.py` | `TurnRequestAssembler` 首轮与预算降级装配，统一处理输入规范化、纯文字引用／纯图默认提示补齐、输出清洗与回复构造 |
| `src/quickquip/llm/epoch.py`、`epoch_history.py` | 会话纪元锚点推进、同纪元动态工具粘性保留（`loaded_tool_names`）、历史表达冻结与行指纹差异诊断 |
| `src/quickquip/llm/prompting.py` | 组装静态 `system_prompt`、当轮 `【轮次上下文】` 信封、场景块消息与发言者标签 |
| `src/quickquip/llm/persona_compiler.py` | Persona v3 三段式系统提示词编译、少样本对话示例（`dialogue_examples`）装配与 `[[lore]]` 角色百科触发匹配 |
| `src/quickquip/llm/config.py`、`config_document.py` | 运行时业务配置对象、配置文档 schema 校验、版本迁移、依赖检查与渠道／模型有效参数解析 |
| `src/quickquip/llm/provider/` | 四类模型协议客户端、HTTP 重试、内联媒体预算收口与 HTTP Trace 采集 |
| `src/quickquip/llm/provider/gemini_compat.py`、`gemini_recovery.py` | Gemini 空文本块过滤、无签名 `functionCall` 哨兵补齐、HTTP 400 签名拒绝单次降级重试，以及 `MAX_TOKENS` 空回复续接补正 |
| `src/quickquip/llm/provider/claude_web_search.py`、`openai_responses/web_search.py` | Anthropic `web_search_20250305` 与 OpenAI Responses 托管 `web_search` 的工具声明构造、流式事件采集与来源报告提取 |
| `src/quickquip/llm/search_policy.py` | 按渠道协议、Responses Profile 与工具总开关统一裁决模型联网搜索路由模式 |
| `src/quickquip/llm/standalone_search.py`、`src/quickquip/search/responses_web.py` | Responses `web.run` 独立搜索执行器、`/alpha/search` 预算分配、命令 schema 校验与结果解析 |
| `src/quickquip/search/web_search.py` | 项目内 SearXNG 客户端，服务 `/search` 命令与本地 `search_web` 工具 |
| `src/quickquip/llm/thinking.py` | 将内部六档思考设置映射为四类协议的请求参数与模型代际钳制规则 |
| `src/quickquip/llm/tool_loop.py` | 工具调用多轮循环编排、Agent Loop 记录写入与分段消息交付推进 |
| `src/quickquip/llm/tool_registry.py` | 工具白名单注册、参数 JSON Schema 校验、调度执行，以及结果保留策略（`ephemeral`）与落库参数脱敏器声明 |
| `src/quickquip/llm/tool_discovery.py` | 单次工具循环内的动态已加载集合（`loaded_names`）维护与 `select:`／裸名显式点名解析；`tool_search` / `tool_list` 元工具 handler 位于 `service_parts/tools.py` |
| `src/quickquip/llm/tool_result_pipeline.py` | 工具执行前后的统一安全管线：参数与结果敏感词扫描、单请求工具图片字节预算、非视觉模型图片转述与降级 |
| `src/quickquip/llm/history_tools.py`、`history_investigation.py` | 群历史查询工具（`search_group_history` / `read_group_history`）与独立上下文受限历史调查子代理（`investigate_group_history`，见 [ADR-0027](adr/0027-history-investigation-executor.md)） |
| `src/quickquip/chat/history_query.py` | `chat_archive.db` 之上的同群只读查询层：SQL 过滤、keyset 游标分页、来源引用标记与已撤回消息屏蔽 |
| `src/quickquip/llm/quote_tools.py`、`service_parts/quote_tools.py` | 同群只读语录查询工具 `query_group_quotes` 的 schema、成员消歧、单次与循环级 token 预算控制及落库参数脱敏 |
| `src/quickquip/llm/skills/` | Skill 包解析、每轮目录扫描、漂移检测与四枚 Skill 工具执行器（详见第 6.3 节） |
| `src/quickquip/llm/store.py` | `data/llm.db` 持久化门面，组合 `store_parts/` 下的会话、长期记忆、私聊存档、Agent 记录与群历史开关实现 |
| `src/quickquip/llm/quick_judge.py`、`single_shot.py` | 唤醒轻量判定管线与 `/defectify`、`/turmfluch` 等单轮命令共享生成骨架 |
| `src/quickquip/llm/summarize.py`、`briefing.py` | 每日总结、周报、月报与每日播报的模型级联生成编排 |
| `src/quickquip/llm/vocab.py`、`identity.py` | `llm_about/vocab.yaml` 词表按需匹配，以及基于共享身份模型的参与者归并与被艾特成员档案采集 |
| `src/quickquip/llm/inputs.py`、`rendering.py`、`message_segments.py` | OneBot 消息段触发提取、纯文本标准化渲染、艾特解析与保存侧来源尾块拼装 |
| `src/quickquip/llm/reply_presentation.py`、`citation_display.py` | 构建独立的聊天交付显示投影，隐藏已确认引用 URL 与自动来源尾块并保留原文坐标映射 |
| `src/quickquip/llm/image_preprocessor.py` | 非视觉主模型的前置图像转述抽象接口与多模态实现 |
| `src/quickquip/adapters/nonebot/voice.py`、`src/quickquip/generation/audio_transcode.py`、`asr.py` | OneBot `record` 语音段提取、基于字节魔数的受限子进程 SILK／AMR 转码以及 OpenAI 兼容 `/audio/transcriptions` 转写调用 |
| `src/quickquip/common/recent_message_buffer.py` | 触发前群内近期消息内存环形缓冲与增量现场补丁游标 |
| `src/quickquip/llm/health.py`、`provider_health.py` | 12 项运行时健康自检与渠道真实请求探活 |

### 请求组装与协议处理

`LLMService` 的内部实现按职责拆分为 `service_parts/` 下的多个 Mixin，分别管理作用域解析、MCP 生命周期、内置工具与工具发现、群语录工具、SVG 绘图、定时消息工具、Skill 注入、单发命令生成、图像预处理、健康检查、运行状态、记忆工具和 Agent Loop 执行，完整导出清单见 `service_parts/__init__.py`。回复主链路中，`reply_chain.py` 的 `TurnRequestAssembler` 统一承接首轮请求与输入超限时的降级重装，配合 `normalize_turn_input`、`finalize_reply` 与 `reply_result` 完成输入规整、输出过滤和返回字典构造；该模块只接收显式参数，保持从 `service.py` 到 `reply_chain.py` 的单向依赖。

周期报告输入先经 `chat/period_serializer.py` 压缩：按自然日分节、按分钟聚合时间块，同一成员的连续发言用斜杠合并，重复刷屏折叠为 `×N`，长链接仅保留域名，机器人自身消息标注 `(bot)`。日报与周报直接序列化完整时间窗；月报先由 `build_monthly_chat_input` 按自然周切分 `input_char_budget`，完整保留低消息量的平静日，再将剩余字符预算分配给高活跃日并按需等距抽稀，最终输出带周次小节标题的压缩文本。

协议客户端的 `complete()` 对 HTTP `429`、`5xx` 与瞬态网络异常执行指数退避重试（策略见 `provider/retry.py`）；渠道探活与后台诊断调用统一传入 `RetryPolicy.disabled()` 禁用自动重试。

Gemini GenerateContent 适配器包含空回复续接补正与严格签名兼容两套协议保障：

- **空回复补正**（默认关闭，配置见[管理员参考](../admin/configuration.md#gemini-空回复补正)）：当非 `single_dispatch` 请求返回单候选 `MAX_TOKENS`、未产出可见正文及客户端函数调用或多模态图片（包含仅返回服务端 `google_search` 的 `toolCall`／`toolResponse` 中间块而尚未生成正文的情形），且响应携带 `continuationToken` 时，客户端在刚成功的实际端点自动发起一次续接请求。续接请求保留完整原始消息、工具声明与思考配置，将输出额度翻倍（不超过配置的补正额度上限）并适用独立总超时；续接失败直接转为不可重试的协议错误。对上层而言一次 `complete()` 仍返回单个 `LLMResponse`：两段 `parts` 按序拼接并保留各自签名块边界与 `groundingMetadata`，Token 用量累加记账，HTTP Trace 则如实保留两次底层请求；若续接中途失败或取消，已产生的两段用量仍合并落库。
- **空块过滤、签名回放与 HTTP 400 单次降级重试**：序列化模型侧 `parts` 时自动剔除无载荷的空文本或空 `thought` 块；若同一 model turn 含并行无签名 `functionCall`（例如跨模型历史投影），仅为首个 `functionCall` 填入官方哨兵 `"skip_thought_signature_validator"`。流式 SSE 重组时，任何携带 `thoughtSignature` 的分片均保持独立条目，禁止与相邻文本分片合并。非 `single_dispatch` 调用若收到上游 HTTP `400` 明确拒绝 `thoughtSignature`，客户端会在请求副本中将历史客户端 `functionCall` 签名替换为跳过哨兵、整组移除历史服务端 `toolCall`／`toolResponse` 块并剥离其余签名（若剥离后整个 model turn 为空，则填入单空格文本块维持 `user`／`model` 角色交替），随后原地重试一次；HTTP Trace 分别记录初次 `400` 与降级重试两次尝试。

Claude 与 OpenAI Responses 同样按各自协议边界维护工具循环与历史回放：Claude 在当前工具循环中回传带签名的 `thinking` 块，已关闭且含工具调用的历史 Loop 在归属（owner）匹配且签名完整时跨轮原生回放；Responses 固定发送 `store: false` 由客户端全量回放上下文，当前工具循环按原始顺序回传 output items 并严格核对 `call_id` 配对与冲突，已关闭历史经归属校验后回放加密 `reasoning` 条目，若上游返回 HTTP `400` 则剥离已关闭历史的 `reasoning` 重试一次（当前工具回合的原生内容始终保留）。完整跨轮投影规则见[第 4.2 节](#42-llm-短期会话)与[第 11 节](#历史回放的协议约束)。

Responses 适配器支持五档 `responses_profile`（`openai-public`、`responses-plaintext-reasoning`、`codex-http-relay`、`codex-relay-hosted-tools`、`codex-relay-standalone-search`），均对未知流式事件类型与新增 JSON 扩展字段保持前向兼容（遵循 OpenAI 将新增流式事件视为非破坏性扩展的[兼容约定](https://developers.openai.com/api/reference/overview#backwards-compatibility)）：未知事件在通过序号与终态顺序校验后跳过，每条流最多记录 8 种未知事件名（截断至 128 字符并转义）；中转档位对 `response.metadata`、`codex.response.metadata` 等已知附加事件静默忽略。`responses-plaintext-reasoning` 不下发 `service_tier`，接受合法的明文 `reasoning.content`（`type="reasoning_text"`）及 `response.reasoning_text.{delta,done}`、`response.reasoning.{delta,done}` 流式事件，不带 `encrypted_content` 的明文推理在跨轮历史中自动转为通用文本投影；其余四档拒绝非空明文 `reasoning.content`。对于已消费的标准事件，客户端严格校验必填字段、流式增量与终态正文／工具参数的一致性及输出条目类型，遇到未声明的工具条目或非法内容块立即报错终止。`codex-relay-hosted-tools` 与 `codex-relay-standalone-search` 两档除提供对话内生图声明外，分别接入托管搜索与独立搜索管线，完整契约见[第 6.7 节](#67-联网搜索路由契约)。

思考强度统一使用 `low`、`medium`、`high`、`xhigh`、`max`、`ultra` 六档词表：OpenAI Chat 按模型家族钳制可用档位；Claude 按模型代际映射为自适应 `effort` 或固定 `budget_tokens`（最低 `1024`）；Gemini 按代际映射为 `thinkingLevel` 或 `thinkingBudget`；Responses 按所选 `responses_profile` 的支持集合下发。发生自动钳制或原样透传未知模型档位时均输出节流日志，上游不支持的参数由服务端返回 HTTP `400` 暴露。

插件入口与持久化目录约定：

- **NoneBot 插件薄层**：`src/plugins/` 仅通过 re-export 向 `bot.py` 的 `nonebot.load_plugins(*plugins.__path__)` 暴露插件入口，新增业务逻辑一律放入 `src/quickquip/`。
- **运行数据库（`data/llm.db`）**：保存私聊会话开关、群历史查询覆盖开关、短期会话消息、Agent Loop 记录与长期记忆。
- **受管配置（`config/managed/config.db`）**：保存真实 LLM 配置草稿、修订与历史；`config/llm.json.example` 为可导入的配置交换示例。
- **群资料目录（`llm_about/`）**：`identities.yaml` 定义 QQ 号到标准身份的映射，`vocab.yaml` 定义群友别名与黑话词表，`群聊简介和概况.md` 供维护者编写人格时参考（不整份注入模型）。容器部署通过卷挂载将宿主机 `llm_about/` 映射到容器内 `/app/llm_about/`，详见[部署指南](../admin/deployment.md)。

---

## 3. 触发规则

LLM 对话默认仅在三类显式入口触发：

- 消息以配置的触发前缀开头（默认 `/ai`）
- 消息真实 `@机器人`
- 发送 `/search <query>`

普通群聊消息只有在命中群聊唤醒模块时才会进入 LLM；所有唤醒规则默认关闭或受严格阈值、群级规则开关与限流器约束。单条群消息的处理顺序为：

1. 写入群消息统计与聊天归档
2. 更新并读取当前群最近消息缓冲
3. 检查是否命中显式 LLM 触发；命中则直接进入 LLM 回复主链
4. 未命中显式触发时，依次评估群聊唤醒规则：`awakening_extend` → `awakening_interest` → `awakening_relevance` → `awakening_qa` → `awakening_fallback`
5. 所有唤醒规则均未命中时，回落至常规规则链（复读、接龙、会话游戏、正则彩蛋、语境规则、时区猜测、尖塔 `card_le` 公式）

### 3.1 唤醒模块

唤醒实现在 `src/quickquip/chat/awakening/`（拆分为 `config`、`state`、`text_signals`、`judge`、`triggers`、`boredom` 六个单向依赖子模块与门面），命令注册位于 `src/quickquip/adapters/nonebot/awakening_plugin.py`，参数由 `config/awakening.toml` 维护。

| 规则名 | 触发机制 |
|---|---|
| `awakening_extend` | 显式触发 LLM 后，在 `extend_duration` 秒窗口内继续回应同一发言者 |
| `awakening_interest` | 消息命中全局或当前人格定义的 `interest_topics` 兴趣关键词 |
| `awakening_relevance` | 先做词重叠快筛，通过后再调用 `quick_judge` 小模型判断是否在延续机器人近期发言 |
| `awakening_qa` | 先做问句特征快筛，通过后再调用 `quick_judge` 判断是否值得插话解答 |
| `awakening_boredom` | APScheduler 定时扫描已开启无聊唤醒的沉寂群，按概率主动发送低频冒泡消息 |
| `awakening_fallback` | 普通群消息按配置的极低概率随机兜底触发 |

相关性与答疑判定复用 `settings.quick_judge` 指定的小模型；对应阈值配置为 `<= 0` 或 `>= 1.0` 时直接关闭该项模型判定。

`awakening_extend` 仅由前缀或艾特等显式入口开启，且在窗口内自动过滤纯图片、纯 CQ 码、单字语气词和过短碎片消息；其余五类被动唤醒均为单次触发，不会刷新延长窗口。唤醒命中后，运行时仅在当轮请求中附带内部触发背景提示（要求模型自然接话且不暴露唤醒机制），该提示不写入持久化对话历史。除 `awakening_fallback` 外，其余五类唤醒均允许附带群内近期历史图片。无聊唤醒采用双层门控：需同时在 `config/awakening.toml` 配置参数，并由群管理员执行 `/awakening boredom on`（状态持久化于 `data/awakening_boredom_groups.json`）。

---

## 4. 上下文边界

### 4.1 临时上下文

`RecentMessageBuffer` 在进程内存中维护各群最近 20 条消息（默认存活时间 1800 秒）。群聊触发 LLM 时，运行时按游标与保底时间窗从中提取尚未进入对话历史的群内近期发言，组装为当轮请求的 `【现场】` 段落；具体提取算法与预算上限见下一节。内存缓冲仅服务当轮临时语境，持久化短期对话与长期记忆由各自存储流程独立维护。

### 4.2 LLM 短期会话

**Session 身份与生命周期**：业务 Session 标识一段连续的群聊或私聊对话交互，内部使用不可变的 `SessionIdentity`（UUIDv4 + UTC 创建时间）表示，并通过 `LLMRequest.session` 显式传递；上下文窗口的滑动裁剪则由下文的**会话纪元**（Session Epoch）独立管理。

- **创建与共享**：群聊在首次通过输入与触发检查时懒创建 Session，全群成员共享该群当前活动 Session；私聊在显式开启会话时创建新身份；执行清空上下文会终结当前身份，待下次实际对话时再创建新身份。仅查询状态或被前置规则拦截的消息不会创建 Session。
- **跨轮保持**：工具循环续轮、报错重试、流式降级、纪元缩窗、冷场、消息撤回、切换模型／渠道／人格以及开关重开均延续同一个业务 Session 身份；活动身份持久化在 `data/llm.db` 中，跨进程重启继续生效。
- **私聊存档与恢复**：私聊保存并结束会话时，原 Session 身份随消息历史一同归档（空会话结束不生成存档）；从存档恢复时直接还原原身份并替换当前活动 Session；不保存结束、清空上下文或删除最后一份关联存档时同步解除对应绑定。
- **并发与代际屏障**：身份变更、历史迁移与作用域 `generation` 递增在同一个 SQLite 写事务内原子提交，提交后立即失效内存派生缓存。每轮请求在入口处冻结当前 Session 身份与 `generation`；一旦中途检测到代际变化，立即中止工具续轮并拒绝迟到的结果落库或消息发送。
- **后台独立任务**：每日播报、总结、周月报、人物志、唤醒判定、诊断探活与单发玩梗命令在每次操作开始时分配独立的短生命周期任务身份，供同次操作内的模型级联与重试复用；聊天前置识图与工具图片转述则显式继承所属对话的 Session 身份。

客户端指纹层通过 `SessionProjector = Callable[[SessionIdentity], str]` 将业务身份映射为各协议所需的请求头、请求体字段或缓存键（如 Gemini CLI 按 `{session_id, client_key}` 在 `session_client_models` 表原子绑定首次使用的模型名作为 `{session_model}` 锚点）。底层直接构造的裸 `LLMRequest` 允许省略 `session`（置为 `None`），但声明了会话身份绑定的 Profile 会在发送前拦截缺失身份的请求。HTTP Trace 在列表、详情与流式事件中记录可空的 `session_id`（仅在当前 `complete()` 生命周期内显式绑定，退出或取消时还原，不从异步外层任务隐式猜测归属）。

数据库升级与回退维护：会话表与追踪表的身份字段均为可空列，升级前须先备份 SQLite 数据库。若曾回退到早期版本运行后再次升级，须停服备份并执行身份绑定重置以重新分配干净的会话身份，具体步骤与维护 SQL 统一见[管理员回退与再次升级流程](../admin/llm-configuration.md#回退旧版本后再次升级)。若运行期 `data/llm.db` 不可读写，持续对话直接中止并返回存储故障提示，拒绝在内存中临时伪造会话身份继续回复。

对话消息表与 Agent 执行记录表按各自的保留周期独立裁剪：当旧对话消息因容量裁剪或单条删除被移除时，数据库在同一写事务中将关联 Turn 的 `message_row_id` 外键置空，完整保留 Turn、工具调用及交付记录；用户撤回消息时同步抹除正文、显示投影载荷与协议原生状态；执行 `clear_context` 则一并清空该作用域的全部对话消息与 Agent 执行记录。

工具执行许可遵循最小暴露原则：本地函数工具仅当其名称出现在当轮请求实际下发的 `LLMRequest.tools` 列表中时才允许执行（动态发现的工具须先装入下一轮请求方可调用）；若模型幻觉调用未装载工具，循环直接返回错误提示并将该调用记为 `not_executed`，绝不派发给底层 handler。服务端托管工具（如原生搜索、对话内生图）的许可按渠道协议配置独立判定。

### 来源引用与显示投影

为兼顾归档可追溯性与群聊阅读体验，保存正文与聊天可见文本采用双层投影（设计依据见 [ADR-0030](adr/0030-citation-display-projection.md)）：数据库保存的正文保留完整规范化引用与自动生成的来源尾块，协议原生块原样留存；发往 QQ 的聊天显示层统一隐藏已确认检索来源的裸 URL、引用角标包装及末尾自动来源块，仅保留自然语言事实陈述与有实际语义的链接标题。当响应不含协议级引用注解时，清洗逻辑仅剥离明确匹配的编号引用、括号域名引用与标准来源尾块，保留常规操作链接、下载地址与代码块内容。

`reply_presentation.py` 在完整 Turn 文本上计算显示投影：分段切分与发送长度预算均以实际可见的 `display_text` 为准，每段交付记录通过 `source_start`／`source_end` 精确映射回保存正文的字符区间（段间被隐藏的引用归入前一段，首尾隐藏内容分别归入首段和末段）。分段发送、后台预览与发送回执缓存均消费冻结后的 `display_text`；跨轮历史协议回放与纪元前缀计算则读取保存正文，不混入显示层字段或来源元数据。PUA 私有区引用符号替换产出的来源标题使用独立的不透明引用跨度标记，在显示层一并隐藏。

持久化结构上，含 Loop 的回复将展示元数据与来源详情存入 `agent_turns.presentation_json`、将实际发送切片存入 `agent_deliveries.display_text`，无 Loop 的合成触发回复存入 `conversation_messages.presentation_json`（历史存量记录若显示字段为空，读取时自动回退为保存正文切片）。来源元数据完整记录原始 grounding 结构、检索查询动作、引用坐标、URL 与正文指纹，与主记录在同一事务内落库并计入存储体积预算；命中敏感词拦截替换的回复以及标记为 `ephemeral` 的临时子循环不保存来源副本。

跨轮回放包含工具调用的历史 Loop 前，运行时会用当前生效的敏感词表重新扫描整轮 Loop：一旦任一环节命中拦截规则或曾发生输出替换，该 Loop 在当次请求及其后续预算降级中统一退回清洗后的纯文本摘要（仅保留工具终态计数，剥离全部原生块、工具入参与结果正文），数据库中的原始记录保持不变。通过安全检查的已关闭 Loop 在满足归属五元组（渠道 ID、协议类型、实际请求模型、端点指纹、协议 Profile 指纹）完全一致且结构完整时走协议原生回放，失配时自动降级为通用文本／摘要重建。

**会话纪元（Session Epoch）窗口管理**：LLM 问答往返持久化在 `data/llm.db` 中，每次组装请求时由 `EpochManager` 按键 `scope × provider × model` 维护读取窗口：

- **固定锚点与冻结历史**：每个纪元键在进程内存中持有起点行号 `anchor_id`、纪元 UUID、历史表达快照 `FrozenHistory` 以及同纪元动态加载工具列表 `loaded_tool_names`。历史行首次进入窗口时选定文本或协议原生表达并冻结，同一纪元后续轮次直接在尾部追加新片段，维持前缀字节稳定以命中上游缓存；单次发送前的临时降级在请求副本上进行，不污染已冻结快照。
- **同纪元工具列表粘性**：同一会话纪元内通过 `tool_search` 或 `tool_list` 动态加载的工具按加载顺序保存在 `EpochState.loaded_tool_names` 中，跨后续对话轮次自动保留在 `LLMRequest.tools` 内，同时从当轮信封的延迟工具按名公告中扣除（静态 `system_prompt` 仍只渲染 `always_loaded` 常驻工具，确保系统提示前缀不变）。当发生纪元推进或重建、`/llm persona use` 切换人格、`clear_context` 清空上下文或进程重启时，粘性工具列表立即清空（且切换人格即使未移动锚点也会轮换纪元 UUID，拦截在途旧请求回写）。
- **冷场与触顶自动缩窗**：空闲时长按该纪元键最近一次模型调用开始或结束时刻计算（工具续轮、失败和取消同样刷新活跃时间）。当空闲超过 `T` 秒且窗口估算体积超过 `H_cold` 时，触发**冷场缩窗**前移锚点至 `L_cold`；当窗口体积超过上限 `cap` 时，触发**触顶缩窗**前移锚点至热水位 `L_hot`。默认参数为 `T=300s`、`L_cold=4000`、`H_cold=5000`、`L_hot=32000`、`cap=64000`（估算 token，可在渠道或模型的 `parameters` 中覆盖）。
- **对齐边界与行数硬顶**：窗口单次最多读取 1024 行，裁剪边界严格对齐完整 Agent Loop（无 Loop 旧消息按 `user`／`assistant` 成对对齐），并在满足总预算的前提下尽量保留最近两个完整对话单元；若最新单个 Loop 自身超过 1024 行则整轮保留，交由回放预算与总输入预算控制体积。
- **历史工具回放预算**：窗口内的历史工具投影额外受独立回放预算约束。追加新轮次后若超出回放预算，系统开启新纪元并按 `L_hot / cap` 比例截取最新完整后缀；若最新单个巨型 Loop 单独超限，则按确定性精简阶梯压缩并冻结。整次请求总输入超限时，优先将纪元窗口缩至热水位 `L_hot`；若锚点已无法前移，则收紧回放预算或裁剪普通历史后重装重试一次。
- **失效检测与假阳性防护**：消息撤回、单条删除、敏感词策略变更或 Loop 修订号推进会触发 `history` 重建；协议归属或预算上限变化分别触发 `profile` 或 `budget` 重建（可保留原锚点并更新纪元 UUID）。计算历史行内容指纹时，系统显式排除异步回填且不参与提示词渲染的 `assistant.message_id` 列，避免协议端发送回执晚到引发假阳性 `history` 重建；真实触发 `history` 重建时，日志会输出首处失配行号或变更字段摘要供排障核查。
- **存储回收水位与冷启动**：底层消息表裁剪以该会话所有活跃纪元键中的最小 `anchor_id` 为安全下界（无活跃纪元时兜底保留最新 2048 行）；Agent 执行记录触及条数或字节上限时，先以 `retention` 原因推进受影响纪元再物理删除旧 Loop。切换模型时自动释放同会话非当前模型的冻结大对象以节约内存；进程重启后首次请求按距最新消息约 `8000` token（`context_tokens`）的范围懒初始化锚点。
- **手动窗口与会话指令**：`/llm context_limit <n>` 将会话切换为保留最新 `n` 行（`1–1024`，按完整 Loop 对齐）的滚动窗口并记录 `context_limit` 事件，`reset` 恢复纪元自动管理。`/llm use` 切换渠道或模型因纪元键不同自然启用新纪元；`/llm persona use` 切换人格时因系统提示词改变，直接按冷场水位前移锚点并重置空闲计时。`clear_context` 在同一事务中清空消息与执行记录、解绑 Session 并递增 `generation`，随后清理近期消息缓冲、纪元状态、信封缓存与已激活 Skill 登记。历史消息统一按落库时冻结的 `canonical_name` 渲染，成员后续改名不影响既有历史前缀。

**近期消息的【现场】增量补丁**：群聊触发 LLM 且调用方未显式传入 `recent_messages` 时（显式传入 `recent_messages=[]` 表示强制空现场，私聊则固定跳过自取），服务通过 `recent_message_buffer.py` 的 `list_patch` 提取群内环境消息并缓存为单次请求快照，供首轮组装与预算缩窗重装复用：

- **候选集合与预算截断**：取“上次服役游标之后的新消息”与“`recent_context_floor_seconds`（默认 300 秒）滑动保底窗内消息”的并集，按 `message_id` 剔除已在短期对话历史中出现的消息及当前触发消息，再从最新一条往回累计至 `recent_context_token_budget`（默认 800 估算 token，至少保底保留最新一条；参数统一由全局 `settings.runtime` 控制）。
- **读即服役游标**：自取补丁后立即调用 `note_patch_served` 推进该群游标；若当轮模型请求最终失败，超出 300 秒保底窗的更早现场消息不再重发，近期消息仍由滑动保底窗兜底。
- **全量快照隔离**：被动唤醒附带的近期图片以及 `context_rules` 语境规则、`search_recent_messages`（读近期消息）内置工具均直接调用 `list_recent` 读取 20 条／1800 秒 TTL 的全量缓冲快照，与文本增量补丁游标互不干扰。

**场景块消息结构**：发往模型的 `messages` 数组采用“以机器人回复为分界的多人场景块”格式：

- 机器人两次回复之间的连续多人发言合并为同一个 `role="user"` 场景块，每行统一渲染为 `身份（QQ 号）：内容`；历史场景冠以 `【上文】`，当轮末尾提问冠以 `【当前提问】`，增量环境消息独立为 `【现场】` 段，尾部固定按 `【轮次上下文】→【上文】→【现场】→【当前提问】` 排列。
- 无聊唤醒与定时消息在落库时生成结构化配对触发行（`【自动唤醒】<诱因>` 或 `【定时消息】按 <cron> 发送：<摘要>`），消除孤立的 `assistant` 行；合成发送者标识（`boredom_timer`／`scheduled_timer`）直接显示名称且不计入信封参与者列表。
- 引用回复同时标明当前发言者与被引用发送者（显式区分引用机器人自身发言），防止模型混淆说话主体。
- 合并转发消息按树状结构递归展开文字与图片占位，整份渲染文本硬上限为 4000 字符：每层优先保障本层正文，再向嵌套子转发分配剩余额度，使用成对边界与局部／整体截断标记；缺少真实 QQ 号的伪造或匿名节点统一标注账号未知，不采信显示名认人。
- 数据库 `raw_content` 列仅保存未加场景标签的原始触发正文；非视觉主模型的前置识图图注在落库前拼入 `raw_content`（单条截断 200 字、整批截断 800 字，格式 `[图片 N 张：…]`，转发内图注直接并入转发文本），使下一轮历史回放直接复用同一文本前缀。

### 4.3 图片输入边界

多模态图片输入覆盖用户侧传入、工具返回与模型原生生图三条路径：

- **候选来源与数量上限**：群聊图片须通过前缀／艾特显式触发或允许带图的五类唤醒进入。单条用户请求最多附带 5 张输入图片，严格按“当前消息 → 引用消息 → 合并转发 → 近期历史消息”的优先级去重选取；合并转发内超额未附带的图片在展开文本中保留占位并在当轮上下文注明省略张数，近期历史图片仅消费剩余名额且优先保留最新图片。
- **空文本默认提示补齐**：当输入仅包含图片而无文字正文时，自动补入默认识图提示；当用户仅引用一条纯文字消息触发机器人且未附加任何正文或图片时，自动补入默认引用回应提示。
- **解码校验与自适应重编码（`provider/media_guard.py`）**：单张图片解码后上限为 5 MiB，整次请求全部内联图片默认共享 5 MiB 解码字节总预算（可通过渠道／模型参数 `max_inline_media_bytes` 覆盖，`0` 表示不限）。发送前统一按字节魔数归一真实 MIME、将 GIF 抽取首帧转为 PNG 并在同请求内按内容哈希去重。单图超限或超出剩余预算时，先执行方向校正、透明背景铺白及多档降采样重编码（原始尺寸优先，随后沿长边 `2560 → 768` 阶梯配合 JPEG `q85`／`q70` 尝试，结果按“原始哈希 + 目标额度”缓存；剩余额度低于 96 KiB 时停止压缩）。若重编码后仍无法装入预算，则按候选顺序执行前缀止停——从首张装不下的图片起连同其后候选一并跳过并记录日志，避免丢弃当前核心大图却保留排在后面的次要小图。
- **跨轮下载缓存与全局预算分配**：协议客户端实例内置图片下载 LRU 缓存（容量 32 张、TTL 10 分钟，仅缓存成功结果）与 GIF 首帧转码缓存，同轮工具续轮与网络重试无需重复拉取解码。组装多轮请求时，最新用户消息中的图片（当前 → 引用 → 转发 → 近期）享有最高预算优先级，其次按由新到旧顺序接纳工具结果图片与历史图片；协议序列化阶段保持工具结果批次完整性与消息原序。
- **非视觉主模型转述**：若当前模型的 `vision = false`，运行时调用 `settings.image_preprocessing` 配置的视觉模型将候选图片转为带来源与序号的文字描述；未配置预处理器、返回空文本或任一图片转述失败时，当轮对话直接中止并提示用户稍后重试。
- **工具返回内联图片**：MCP 工具与独立搜索工具可返回经格式与尺寸校验的内联图片（驻留当前工具循环内存，不写入对话库或普通日志）。视觉主模型在下一轮工具结果消息中直接接收图片；非视觉主模型接收经二次敏感词扫描的转述文本，若转述不可用则仅保留工具安全文本并注明省略图片。
- **模型原生生图外发**：Responses 内置 `image_generation` 条目（由中转服务端注入，或由 `codex-relay-hosted-tools`、`codex-relay-standalone-search` Profile 在请求侧显式声明）以及 Gemini 响应中的 `inlineData` 图片块，由协议适配器提取为统一的响应侧 `generated_images` 附件并从 `native_blocks` 中剥离，防止巨型 base64 进入历史回放。工具循环将每轮产出的图片收进与 `draw_svg` 共用的外发图片通道（共享单次回复上限 `MAX_OUTBOUND_TOOL_IMAGES` 及“后续轮次失败仍保留已生成图片”语义），由适配层附在回复末尾发出，并受全局 10 次／分钟、单用户 2 次／分钟的独立限流保护。

### 4.4 语音输入边界

语音消息同样遵循显式触发边界：群聊须与配置前缀或 `@机器人` 同条发送，私聊在会话开启期间可直接发送语音。若 OneBot 协议端上报的 `record` 段已自带非空转写字段（`text`、`transcript` 或 `transcription`），运行时直接采用；否则拉取语音文件交由 `generation/audio_transcode.py` 按字节魔数识别处理——标准与腾讯前缀 SILK 音频在受限独立子进程（`audio_worker.py`）中解码为 16 kHz 单声道 WAV，AMR／AMR-WB 在宿主机装有 `ffmpeg` 时转码为 WAV，常规音频格式在通过双层体积上限校验后透传，非音频或超限分段直接跳过——最终送入 `config/generation.toml` `[asr]` 配置的 OpenAI 兼容 `/audio/transcriptions` 端点。转写文本以 `[语音转文字：...]` 形式并入当前用户消息，同步参与近期消息缓冲、日报／播报采集与词云统计；转写失败时不阻塞同条消息中的文字与图片处理。

### 4.5 长期记忆

长期记忆按群聊或私聊作用域隔离存储于 `data/llm.db`，由主对话模型的四枚常驻记忆工具（`list_memories`、`read_memory`、`write_memory`、`delete_memory`）、群内管理指令和 Web Admin 共同维护（管理说明见[记忆管理](../admin/memory.md)，架构依据见 [ADR-0026](adr/0026-conversation-owned-memory.md)）。每条记忆采用 Markdown 正文，记录标题、简述、乐观锁版本号、结构化成员引用及来源消息元数据；写入时校验来源消息 ID 必须属于当轮可见的真实消息，操作者角色由运行时按真实权限填入。

检索与自动注入共用本地 BM25 索引（覆盖标题、简述、正文与成员身份关联，中文按连续双字切分）：

- **模型工具查询**：`list_memories` 传入 `keyword` 时按相关性排序分页（每页最多 20 条，返回会话总条数 `total`、匹配数 `matched_count`、续页偏移 `next_offset` 及每条最多 128 估算 token 的命中摘录 `excerpt`），留空时按编号倒序浏览目录；需要完整内容时再调用 `read_memory` 读取正文与版本号。
- **请求前自动召回**：每轮组装当轮信封时自动检索并注入记忆目录与相关正文，总预算约 2048 估算 token（其中目录上限 512 token，完整正文最多 5 条）。当整次请求输入超限时，降级链路优先卸除自动注入的记忆材料，再执行少样本示例卸除与纪元历史缩窗。同一 Agent Loop 内固定首轮记忆快照，循环中途新增或修改的记忆通过工具返回结果对模型可见。

---

## 5. 人格注入设计

系统提示词编译器按人格文件中的 `schema_version` 兼容两代结构：

### 5.1 基础人格与三段式架构（Persona v3）

人格文件存放在 `config/personas/` 目录下（每个 `.toml` 对应一个人格），`_shared.toml` 承载跨人格共享准则并支持通过 `shared_group_*` 与 `shared_private_*` 区分群聊与私聊作用域。

- **Persona v1 / v2（`schema_version < 3`）**：按固定顺序拼接结构化字段、`system_prompt`、`style_prompt`、`style_overrides` 与宿主协议规则，维持存量人格文件的静态前缀字节稳定。
- **Persona v3（`schema_version = 3`，编译入口 `quickquip/llm/persona_compiler.py`）**：将 `system_prompt` 组织为首尾锚定的三段式结构，兼顾模型首尾注意力分布与静态前缀缓存：
  1. **首部 `<persona_core>`**：渲染 `[identity]`、精简常驻外貌锚点 `[portrait]`（`appearance` + `attire`）、内在动机 `[mind]` 与关系拓扑 `[topology]`；完整设定表 `[appearance]` 与维护备注 `[audit]` 仅保存在源文件中供人工查阅，不随请求常驻下发。
  2. **中部 `<host_contract>`**：声明聊天运行环境及“工具／检索客观执行与角色声腔分离”原则，汇入 `_shared.toml` 公共规则、私聊 `session_preset`，以及认人准则、引用判定、场景块消息格式、搜索路由引导与工具使用规范。
  3. **尾部 `<voice_anchor>`**：紧贴对话历史之前放置 `[voice]`（核心声腔、句式节奏、情境语气切换、低频口癖词库、表达禁区）、共享 `style_profile` 文本与渠道／模型 `style_overrides`，强化回复语感与格式禁令遵从度。Skill 目录块 `<skill_catalog>` 固定追加在系统提示词最末尾。
- **少样本语感示例（`[[dialogue_examples]]`）**：最多选取 4 组不含真实或虚构 QQ 号的中性 `user`／`assistant` 示范对话，插入在 `messages` 数组的 `history` 之前（静态前缀固定，可参与上下文缓存）。注入行为受渠道／模型参数 `persona_few_shot`（`auto | on | off`，默认 `auto`）控制：`auto` 在 `gemini` 协议下默认关闭，在其余三类协议下默认开启；当请求输入预算超限时，继卸除自动召回记忆之后可继续卸除少样本示例以保障主对话发出。
- **非对话任务复用**：每日播报、日报、周报、月报与群友人物志统一调用 `render_persona_for_task()` 提取完整人格核心与声腔锚点。

默认人格围绕熟人群聊语境设计：保持高语境理解、轻松克制、自然接梗，遇到正经技术或严肃求助话题时自动收起玩笑，且不捏造与任何群成员的线下私交记忆。

### 5.2 群风格约束

人格设计通常贴合目标群的稳定交流习惯（例如熟人化互动、夜间活跃、游戏／创作／ACGN 混合讨论、常见群内黑话与夸张称呼，以及在严肃场景恢复平实表达）。

### 5.3 词表与角色百科按需注入

为保持 `system_prompt` 跨轮静态稳定，话题相关的背景知识统一按需注入当轮 `user` 消息头部的 `【轮次上下文】` 信封：

- **群词表消歧（`vocab`）**：当输入文本命中 `llm_about/vocab.yaml` 中的成员别名或群内黑话时，向信封追加对应的词条释义。
- **角色百科（Persona v3 `lore`）**：使用 v3 人格时，系统扫描当前消息、被引用消息正文及最近 2 条现场消息；命中 `[[lore]]` 条目的 `triggers` 关键词后，按优先级与命中频次选取最多 3 条、总长不超过 800 字符的设定注入信封 `lore` 段（排在 `vocab` 与延迟工具公告之间），并通过 `envelope_cache.SEGMENT_KEYS` 同步呈现在 Web Admin 纪元监控看板中。

### 5.4 Provider 风格覆盖

渠道与模型的 `parameters` 支持配置共享风格引用 `style_profile`、多行补充指令 `style_overrides` 及少样本开关 `persona_few_shot`。有效风格文本由所选 `style_profile` 正文与有效 `style_overrides` 拼接而成，在 v1／v2 人格中置于 `style_prompt` 之后，在 v3 人格中置于 `<voice_anchor>` 末尾，常用于针对特定模型家族补充文风约束（例如抑制 GPT 系句尾反问与列表模板、抑制 DeepSeek 机械分点、抑制 Claude／Gemini 括号神态旁白）。在 Web Admin“LLM 配置 → 渠道与模型”修改后，保存草稿并执行应用即可对后续新任务生效（详见[LLM 配置管理](../admin/llm-configuration.md)）。

### 5.5 身份映射注入

`llm_about/identities.yaml` 定义 QQ 号到群成员标准身份的权威映射，与提供称呼提示的 `vocab.yaml` 分工明确（两处出现的同一成员标准名应保持一致）：模型阅读的文本层以**标准身份名称**为主锚、QQ 号作括号后缀（用于区分同名未登记成员），而程序内部（艾特段解析、索引关联、数据库外键与冷却记账）一律以 **QQ 号**为唯一主键。群级身份文件合并仅对纯数字群号生效；私聊等非数字作用域直接读取全局身份索引。

身份解析、信封注入与出站还原遵循以下规则：

- **统一发言者标签**：历史、现场和当前提问统一渲染为 `身份（QQ 号）：内容`；未在 `identities.yaml` 登记的发言者渲染为“当前显示名 + QQ 号 + 未登记”，认人提示引导模型优先称呼名字、仅在重名消歧时参考 QQ 号。
- **入站艾特解析**：消息进入管线时，顶层、引用及合并转发内的艾特段按群合并身份索引渲染为 `@标准身份`。遇到未登记 QQ 时，消息顶层艾特通过带 TTL 的 `get_group_member_info` 群名片缓存降级为 `@当前群名片`（查询失败再回退为 `@QQ号`）；引用与转发子消息内的未登记艾特不额外发起远程名片预取，仅在消息段自带昵称或命中顶层已缓存名片时使用名字，否则直接保留 `@QQ号`。
- **被艾特成员档案注入**：当本轮输入或窗口文本（含结构化艾特段与历史文本中的 `@QQ号`）提及了某位已登记群成员，且该成员尚未在当前可见窗口内发言时，系统将其“标准身份 + 别名 + 档案备注”注入当轮信封的艾特档案段（最多 5 条），避免模型对被提及但未出场的老群友一无所知。
- **出站艾特还原与冷却护栏**：回复发送前（`_llm_reply.py`），文本中的 `@QQ号`（带右边界校验防止误切长数字）会还原为真实 OneBot `at` 段；开启群级开关 `llm_at_mention`（默认开启）时，同时启用“@名字”还原通道——按群身份快照中的标准身份、别名和已观察群名片做最长匹配，存在重名歧义、指向机器人自身或未登记的名字一律保留为纯文本（且结构上禁止生成 `@全体成员`）。两条通道合计每条回复最多发出 **3 个**真实艾特，超出部分保留为纯文本；“@名字”通道额外对同一“群 × 目标 QQ”施加 `mention_cooldown_seconds` 冷却（默认 600 秒，`0` 关闭），仅在拿到可信发送回执 `message_id` 后记账，发送失败不扣减名额。
- **触发消息引用锚定**：群级开关 `llm_quote_reply`（默认开启）使群聊 LLM 回复自动挂载引用段指向触发消息；若协议端明确拒绝引用段则自动剥离引用重发纯正文，网络超时等未决传输异常不重发。
- **周期报告读时解析**：日报、周报、月报与每日播报在序列化归档消息时实时查询最新身份索引替换标准名，仅当不同 QQ 发生同名碰撞时才为碰撞者附加 QQ 号后缀以节省输入体积。
- **静态前缀与当轮信封边界**：当前时间、星期、节日、窗口内发言参与者、被艾特成员档案、自动召回记忆、命中词表、Persona v3 命中角色百科（`lore`）以及工具发现开启时的延迟工具按名公告，全部汇总在当轮 `user` 消息头部的 `【轮次上下文】` 信封中动态渲染。只要配置、人格、常驻工具与已安装 Skill 清单未变，`system_prompt` 跨轮跨日保持字节级恒定。`envelope_meter` 将当轮信封体积记入用量表的 `envelope_tokens`（同一 Agent Loop 内多次模型调用记录同一信封值，统计单轮平均开销时应取 **AVG**）。`identities.yaml` 缺失、为空或成功加载条目数均在启动和重载时输出明确日志。

---

## 6. 配置说明

### 6.1 `config/managed/config.db`

LLM 核心配置采用“草稿编辑 → 独立应用／离线发布 → 运行库任务交接”模型：`config/managed/config.db` 维护可编辑草稿、修订号与历史快照，`data/config_runtime.db` 维护绑定任务的不可变执行快照、发布指针与 Bot 心跳（存储边界见[配置与运行存储](configuration-storage.md)）。每个已启动的 Agent Loop 与独立报告任务在生命周期内固定使用开始时捕获的配置快照、价格表、工具集与 MCP 资源。

配置交换 JSON（`format_version = 2`）的顶层与 `settings` 子域包括：

- `providers`：有序渠道列表、模型清单与模型别名；连接与鉴权字段位于渠道顶层，可继承的请求策略位于渠道或模型的 `parameters`。
- `style_profiles` 与 `pricing`：共享风格字典，以及按 `(provider_id, model)` 精确匹配的模型单价表。
- `routes`：`daily_summary`、`daily_briefing`、`weekly_report`、`monthly_report` 四类周期任务的有序模型级联列表（支持 `{provider_id, model}` 与 `"@default"`）。
- `settings.runtime` / `triggers` / `auto_search` / `quick_judge` / `image_preprocessing`：全局聊天开关、上下文纪元与预算默认值、触发前缀、自动搜索引导、轻量判定模型与前置识图模型。
- `settings.tools` / `group_history` / `skills` / `mcp`：工具白名单与工具发现策略、群聊历史查询默认开关与历史调查执行器参数、Skill 资源限额以及外部 MCP 服务定义。
- `settings.daily_summary` / `daily_briefing` / `weekly_report` / `monthly_report`：四类报告的定时 Cron、最少消息门槛与篇幅提示。

完整字段定义与默认值见[管理员配置参考](../admin/configuration.md)，管理端 HTTP 契约见 [LLM 配置后端接口](llm-configuration-api.md)。人格 TOML（`config/personas/`）与多模态生成配置（`config/generation.toml`）独立于 `config.db` 按各自文件生命周期管理。

### 6.2 内置工具与工具发现

开启全局工具总开关 `settings.runtime.tool_calling_enabled`（默认关闭）后，运行时按作用域与功能门控组装当前会话的已启用工具集合：

- **内置只读与管理能力**：包含身份查询 `get_identity`、长期记忆四工具、群统计 `get_group_stats`、规则开关查询 `get_rule_status`、近期缓冲检索 `search_recent_messages`、运行时状态与自检工具，以及按需显式加入白名单的 `draw_svg` 和定时消息管理工具 `manage_scheduled_messages`。
- **同群只读语录工具（`query_group_quotes`）**：群聊默认启用并归入可延迟加载池，私聊自动屏蔽。支持按本群语录编号 `seq` 精确读取，或按正文／提及关键词 `keyword` 与发言人 `speaker`（支持 QQ 号、群名片、标准身份与别名，重名歧义时返回候选提示）分页检索，不传筛选条件时按最新收藏倒序浏览。工具受单次返回 `1200` 估算 token、单次工具循环累计 `3600` 估算 token 双重上限约束；注册为 `ephemeral` 临时结果保留策略，且通过 `redact_quote_arguments` 脱敏落库参数（仅记录查询模式与分页整数，不把搜索词或成员名写入执行记录表）。
- **群聊历史查询三工具**：当群聊有效开启历史查询（群级 `/llm history on|off|reset` 三态设置优先覆盖全局 `settings.group_history.enabled`，私聊恒关闭）时，额外开放 `search_group_history`、`read_group_history` 与专用子代理工具 `investigate_group_history`，三者同样采用 `ephemeral` 结果保留与参数脱敏策略。

当接入较多内置扩展工具或外部 MCP 工具时，本地工具发现机制（实现细节见[`tool-discovery.md`](tool-discovery.md)）避免在首轮全量下发大体积 JSON Schema，且四类协议适配器共用同一套服务层发现状态：

- **启用条件**：默认 `discovery_mode = "auto"` 统计不在 `always_loaded` 常驻列表中的可延迟工具；当可延迟工具数量超过 `discovery_min_tools`（默认 `6`），**或**可延迟工具的协议中立 Schema 估算体积总和超过 `discovery_min_schema_tokens`（默认 `2000`，设为 `0` 关闭体积触发线）时自动启用发现模式。未达阈值时直接下发全部已启用工具。
- **按名公告、批量加载与同纪元粘性**：发现模式启用后，静态系统提示词仅渲染常驻工具以保持前缀稳定，首轮 `LLMRequest.tools` 包含常驻工具与当前会话纪元已粘性加载的工具，同时在当轮信封末尾附一行可延迟工具按名公告（仅含名称，扣除常驻工具、当前纪元已加载工具与发现元工具）。模型可直接调用 `tool_search(query="select:工具A,工具B")` 一次精确批量加载多个工具，也可按关键词搜索或用 `tool_list` 分组浏览兜底。新装载的工具在紧随其后的循环轮次立即可用，并在同一会话纪元内跨轮粘性保留（总装载数受 `discovery_max_loaded_tools` 封顶）。

### 6.3 Skill 系统

部署者可将领域知识包放入 `skills/` 目录（每个子目录含一份带 YAML frontmatter 的 `SKILL.md`，可选配 `references/` 文本资料、`assets/` 资产与 `scripts/` 脚本）。当 `settings.skills.enabled` 与工具调用总开关同时开启且目录内存在合法 Skill 时，系统提示词尾部注入 `<skill_catalog>` 路由清单并注册四枚 Skill 工具：模型根据用户提问自主调用 `activate_skill` 加载指令正文，随后按指引调用 `read_skill_resource`、`search_skill_resources` 或 `run_skill_script`。

`llm/skills/` 子包按职责拆分为：

- `parser.py`：校验 `SKILL.md` 体积上限、UTF-8 编码、常规文件形态及 `name`／`description` 约束。
- `catalog.py`：每轮请求实时扫描 `skills/` 目录，限制读取与检索路径不得越出包根目录，记录脚本 SHA-256 快照并容忍并发目录修改。
- `state.py` 与 `context.py`：按会话维护内存激活登记（随 `clear_context` 同步清空），通过纯函数渲染 `<skill_catalog>` 清单与激活注入块。
- `preset_drift.py`：只读比对 `skills/` 已安装同名包与仓库 `skills.example/` 预置模板的全文件字节指纹；出现分叉时记录告警并在 `/skill list` 中提示管理员运行 `scripts/maintenance/sync_preset_skills.py` 同步（比对结果不进入模型提示词）。
- `tools/`：实现四枚工具——含按行段读取的 `read_skill_resource`、内置静态防灾难性回溯正则检查的 `search_skill_resources`，以及无 Shell 直启、环境变量白名单（仅透传 `PATH`/`LANG`/`TZ`）、固定工作目录、执行前哈希复验与超时／输出截断保护的 `run_skill_script`。
- `service_parts/skills.py`：负责目录体积预算裁剪（`min(模型上下文窗口 2%, catalog_max_bytes)`）及双层敏感词联动——描述命中拦截词时直接从目录剔除该 Skill，激活正文命中拦截词时整段替换且不留激活登记。

配置参数见[配置参考](../admin/configuration.md)，安全边界与部署说明见[Skill 管理](../admin/skills.md)，手把手编写指南见[`skill-tutorial.md`](skill-tutorial.md)。

### 6.4 `config/awakening.toml`

唤醒模块参数由 `config/awakening.toml` 独立维护：

- `[awakening.defaults]`：配置全局默认项，包括延长窗口秒数 `extend_duration`、随机兜底概率 `fallback_probability`、无聊唤醒沉寂门槛 `boredom_silence_seconds`、触发概率 `boredom_probability`、全局扫描间隔 `boredom_scan_interval`（缺省回退 `boredom_check_interval`）、单群唤醒冷却 `boredom_check_interval`、免打扰时段 `boredom_dnd_start`／`boredom_dnd_end`、全局兴趣词 `interest_topics`，以及小模型判定阈值 `relevance_threshold` 与 `qa_threshold`（设为 `<= 0` 或 `>= 1` 关闭对应模型判定）。
- `[[awakening.group_overrides]]`：按 `group_id` 覆盖指定群的上述任意字段。
- 人格扩展：单个 persona TOML 可通过 `[awakening]` 段的 `interest_topics = ["关键词"]` 为该角色追加专属兴趣词。

### 6.5 `.env`

应用层所有涉密凭据与基础连接参数统一存放在仓库根目录 `.env`（管理后台启用 `env-agent` 后可通过只写面板维护，见[环境变量管理](../admin/environment.md)），常见变量包括：

- 模型与多模态渠道密钥：如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GEMINI_API_KEY` 等（配置文件中仅填写变量名或 `${VAR}` 引用）。
- OneBot 与 NoneBot 基础连接：`QQ_ACCOUNT`、`ONEBOT_WS_URLS`、`ONEBOT_ACCESS_TOKEN`、`DRIVER`、`HOST`、`PORT`。

### 6.6 `config/generation.toml`

多模态输入转写与内容生成配置集中在 `config/generation.toml`（模板见 `config/generation.toml.example`）：

- `[image]` / `[audio]` / `[music]`：外部图片生成、TTS 语音合成与音乐生成渠道配置。
- `[asr]`：语音识别渠道配置（当前支持 `openai_transcriptions` 协议，即 `POST /audio/transcriptions`），供 4.4 节语音消息转写调用。
- `[svg]`：本地 `draw_svg` 矢量图渲染配置。`draw_svg` 默认不在常驻启用名单中，需同时在 `generation.toml` 的 `[svg]` 段设置 `enabled = true`，并在 LLM 配置 `settings.tools.enabled` 中加入 `"draw_svg"`。渲染管线（`quickquip.generation.svg`）默认开启 `harden` 加固：先经 `svg_sanitize.py` 执行输入约束与危险标签／外部引用静态清洗，剥离根节点宽高后按 `viewBox × 2` 强制指定输出像素尺寸，再派生受限 `spawn` 子进程调用 `resvg` 渲染 PNG（Linux 下施加 `RLIMIT_AS` 与 `RLIMIT_CPU` 并配墙钟超时兜底）。可选开关 `content_judge` 开启后会复用 `settings.quick_judge` 检查 SVG 可见文本（判定异常时不阻断渲染）。生成的 PNG 经 `ToolExecutionContext.outbound_images` 直接发给用户而不回传给模型，单次回复最多 3 张，受全局 10 次／分钟、单用户 2 次／分钟限流保护。

### 6.7 联网搜索路由契约

对话与工具循环中的模型联网检索由 `search_policy.resolve_search_mode` 统一裁决为以下互斥模式；任一原生或独立搜索模式激活时，运行时都会自动从当前会话的工具列表及发现目录中移除本地 `search_web`，并切换对应的系统提示词检索引导：

1. **本地 `search_web` 工具（`local`）**：默认客户端检索路径，需同时开启 `tool_calling_enabled` 与 `auto_search.enabled`，底层请求项目内 SearXNG，受 `auto_search` 每轮调用次数上限约束。
2. **Gemini 原生 Grounding（`gemini_grounding`）**：`gemini` 协议渠道设置 `builtin_search = true` 时激活，独立于 `tool_calling_enabled`。请求在 `tools` 数组中追加 `{"google_search": {}}`；若同次请求同时携带客户端 `functionDeclarations`，自动合并注入 `toolConfig.includeServerSideToolInvocations = true`（保留 `extra_body.toolConfig` 中的其他自定义键值；注意 `google_search` 与客户端函数工具同请求并存仅受 Gemini 3 系列模型支持，Gemini 2.x 需二选一）。服务端产出的 `toolCall`／`toolResponse` 搜索块在当前工具循环及同 owner 跨轮原生回放中按序保留（预算首档剥离 `thought` 块时仍保留服务端搜索块，`thoughtSignature` 体积估算按单块上限封顶；遇到跨上游 HTTP `400` 验签失败降级重试时则整组剥离历史服务端工具块）。响应解析 `groundingMetadata` 提取检索词与来源，在保存正文末尾生成至多 3 条“标题 — 域名”来源记录并将完整结构存入元数据。
3. **Claude 原生搜索（`claude_web_search`）**：`claude` 协议渠道设置 `builtin_search = true` 时激活，独立于 `tool_calling_enabled` 且可与客户端函数工具共存。请求在 `tools` 数组中追加 `{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}`；非流式与流式 SSE 响应统一由 `claude_web_search.py` 从 `server_tool_use`、`web_search_tool_result` 及文本块 `citations`／`citations_delta` 中提取 `LLMWebSearchReport`（被引用的来源排在前面，开启 `link_urls=True`，元数据中主动剔除大体积不透明 `encrypted_content`）。为防止搜索结果撑爆后续轮次上下文，`native_blocks` 不持久化服务端搜索块，完整原始流仍可从 HTTP Trace 查阅。
4. **Responses 托管搜索（`responses_hosted`）**：`openai_responses` 渠道选择 `responses_profile = "codex-relay-hosted-tools"` 且当次请求允许工具调用（`allow_tool_calls = true`）时激活。请求显式声明 `{"type": "web_search"}`（即使当轮无本地函数工具也正常下发）与 `include: ["web_search_call.action.sources"]`，同时一并声明 `image_generation`。响应保留 `web_search_call` 原生条目供同 owner 跨轮回放，并提取规范化来源引用（保存正文最多附 3 条链接）；若后续某次请求禁用了工具调用，则同步关闭搜索声明与 `include`，并将含托管搜索的历史 Loop 自动降级为通用文本与工具事实投影（不回放关联原生推理块）。
5. **Responses 独立搜索（`responses_standalone`）**：`openai_responses` 渠道选择 `responses_profile = "codex-relay-standalone-search"` 且 `allow_tool_calls = true` 时激活（工具调用关闭时路由为 `none`），要求上游同时支持 namespace 工具与 `/alpha/search` 端点（架构依据见 [ADR-0031](adr/0031-standalone-search-evidence.md)）。运行时注册常驻原生工具 `web_run`（保留 `image_generation`，不声明托管 `web_search`），支持网页搜索、引用阅读、页内查找、链接打开、图片检索、PDF 截图与体育／金融／天气／时间查询。固定命令 Schema 生成自上游 Codex 提交 `77873dd0d284aeba7ce849b995b28ee8f4498d73`（Apache-2.0 许可证随包附于 `src/quickquip/search/`，维护脚本为 `scripts/maintenance/generate_responses_web_schema.py`，未开放实验性文献检索）。执行器保持 `store: false`，按 `session × owner × epoch` 哈希隔离搜索会话 ID（后端引用过期时不自动重连重搜）；单轮最多 3 次工具调用、单次回复累计最多 64 个子命令操作，返回明文经 24 KiB 本地截断与剩余上下文 token 预算裁剪后作为标准函数结果落库冻结，前 5 条白名单来源写入结果元数据 `search`（`version: 1`）；截图命令若未拿到可读图片则明确标记工具失败，搜索图片共享工具内联图片预算且不直接外发到群。

**跨轮网页正文恢复边界**：在 `store: false` 无状态全量回放契约下，三类服务端托管搜索（`gemini_grounding`、`claude_web_search`、`responses_hosted`）在跨轮历史中仅保留搜索动作或来源 URL 元数据，首轮回复未引述的原始网页正文不会留在后续轮次上下文中，群友追问细节时由模型重新发起检索；若业务场景需要跨轮直接阅读已检索到的网页正文片段，且 Responses 渠道支持 `/alpha/search`，可选用将明文摘要落库冻结的 `codex-relay-standalone-search`。所有原生与独立搜索的检索费用均由对应上游端点计费，聊天交付层统一隐藏自动来源尾块。

---

## 7. 群内命令

查询类命令默认对群成员开放；修改配置、清空上下文、探活与增删记忆等写操作默认仅限群主、群管理员或全局管理员执行。完整用户侧说明见[群内指令速查](../user/group-commands.md)。

### 7.1 基础状态与运维命令

- `/llm status`：查看当前会话的 LLM 开关、触发方式与基本状态。
- `/llm current`：查看当前会话实际生效的渠道、模型、人格、记忆开关、历史查询开关、短期会话条数与长期记忆条数。
- `/llm health [verbose|detail|full]`：执行涵盖 `llm_config`、`provider`、`database`、`knowledge_files`、`persona`、`tools`、`mcp`、`search`、`sensitive_filter`、`generation`、`image_preprocessing`、`runtime_bindings` 的 12 项内部健康检查。
- `/llm reload`（管理员）：重新加载已发布的 LLM 配置快照并重置当前会话手动行数上限，随后向当前生效的渠道／模型发送一条 `max_tokens=16` 的真实探活请求（可能产生微量模型费用；密钥未配置时自动跳过）。
- `/llm probe`（管理员）：向所有已启用渠道并发发送 `max_tokens=16` 的真实探活请求，汇总可达性与响应耗时（密钥未配置的渠道自动跳过）。
- `/llm mcp status` / `/llm mcp reload`：查看 MCP 服务装载状态，或由管理员强制拉取最新镜像并重连全部 MCP 服务。

### 7.2 渠道、模型、人格与输出控制

- `/llm on` / `/llm off`：在群聊中开关本群 LLM 响应；在私聊中开启（支持 `--resume` 恢复存档与附加设定）或结束私聊会话（支持 `--no-save`）。
- `/llm providers` / `/llm models [provider]` / `/llm use <provider> [model]`：查看可用渠道与模型，或切换当前会话使用的渠道与模型。
- `/llm personas` / `/llm persona use <id>`：列出当前作用域可用人格并切换人格。
- `/llm effort [status|<档位>|default|clear]`：查看或覆盖当前会话的思考档位。
- `/llm delivery [status | intermediate|final|all <on|off|reset>]`：查看或按“中间轮发送／最终轮分段”控制分段交付策略。

### 7.3 触发方式

- `/llm trigger prefix <value>`
- `/llm trigger prefix_mode on|off`
- `/llm trigger at on|off`（仅群聊）

### 7.4 记忆与上下文

- `/llm memory status` / `/llm memory on` / `/llm memory off`：查看或切换当前会话的长期记忆注入开关。
- `/llm history status` / `/llm history on|off|reset`：查看或设置本群归档历史只读查询开关（仅群聊；`on`／`off` 显式覆盖全局 `settings.group_history.enabled`，`reset` 恢复跟随全局默认）。
- `/llm context_limit <n>` / `/llm context_limit reset`：将当前会话改为保留最新 `n` 行（`1–1024`）的固定滚动窗口，或恢复会话纪元自动管理。
- `/llm clear_context` / `/llm delete_msg [消息ID]`：清空当前会话全部短期上下文，或通过引用／指定消息 ID 从短期上下文中移除单条消息。
- `/remember [--id <编号>] <内容>`：新增一条长期记忆，或指定 `--id` 覆写已有条目正文（正文以 `--` 开头时可用 `/remember -- <正文>` 转义）。
- `/memories [--page <页码>] [关键词]` / `/memories --id <编号>`：分页浏览或按关键词检索记忆目录，或按编号读取单条记忆完整正文。
- `/forget <关键词|#编号>` / `/forget_all`：按关键词／成员关联批量删除匹配记忆、按 `#编号` 精确删除单条记忆，或清空当前会话全部长期记忆。
- `/awakening status` / `/awakening on|off <rule>` / `/awakening boredom on|off`：查看或管理本群被动唤醒与无聊唤醒开关。

### 7.5 联网搜索

- `/search <query>`
- `/search news <query>`
- `/search finance <query>`

`/search` 是独立的显式命令，直接调用项目内 SearXNG 客户端执行检索并格式化返回前 5 条摘要与链接，受 `web_search` 限流桶保护，检索结果不写入长期记忆。对话过程中由模型自主触发的五种联网搜索路由契约见[第 6.7 节](#67-联网搜索路由契约)。

---

## 8. 部署注意事项

生产与本地部署的完整步骤见[部署指南](../admin/deployment.md)，核心运行前提如下：

- 共享持久化目录 `config/managed/` 与 `data/` 须正确挂载并具备读写权限；Bot 启动时从运行库指针加载已发布配置快照。
- 根目录 `.env` 提供所有渠道 API Key 与 OneBot 连接参数（可选启用 `env-agent` 守护服务支持后台只写维护）。
- 宿主机 `llm_about/` 挂载至容器 `/app/llm_about/`，提供全局 `identities.yaml`、`vocab.yaml` 及可选按群子目录。
- 启用语音转写时须在 `config/generation.toml` 配置可用 `[asr]` 渠道；使用 `/search` 命令或默认 `search_web` 工具时须提供可达的 SearXNG 实例（已开启原生搜索或独立搜索的渠道在模型对话中不依赖 SearXNG）。
- 根目录 `.dockerignore` 已排除本地 `.env`、`config/*.toml`、`data/` 及开发临时产物，防止私有配置打入镜像层。

---

## 9. 数据作用域与安全处理

群聊（`<group_id>`）与私聊（`private:<user_id>`）在数据库与内存缓存中严格按 `scope_key` 隔离短期上下文、会话纪元、长期记忆与执行记录；群历史查询工具与群语录工具进一步在入口与查询层双重绑定当前群号，杜绝跨群读取。

历史对话消息与历史工具 Loop 在每轮读取组装时均按当前最新敏感词表执行动态复检（底层数据库保留原始记录供审计）：普通消息清洗变化或工具 Loop 退回安全文本摘要都会改变历史前缀字节，属于预期内的安全优先行为。周期报告沿 `routes.*` 候选列表顺序依次回退，常规聊天固定使用当前会话解析出的单一渠道与模型。

## 10. 上线前建议检查项

按目标环境实际开启的功能逐项核验：

- 在 Web Admin“LLM 配置”确认默认渠道、默认模型、默认人格及 Bot 实际加载修订号，核对密钥状态显示为已配置。
- 在测试群执行 `/llm current`、`/llm health` 与前缀／艾特对话，确认回复正常送达后再测试 `/llm clear_context`。
- 按需抽测长期记忆读写、群历史查询（`/llm history status`）、图片输入、语音转写与 MCP 状态（`/llm mcp status`）。
- 检查启动日志中的 `identities.yaml` 与 `vocab.yaml` 加载条数，确认成员标准身份解析符合预期。

## 11. 请求结构排障

排查模型报错、参数未生效或多轮上下文异常时，应按“配置快照 → 会话与纪元状态 → 最终协议载荷”的顺序定位。草稿保存与发布流程见[LLM 配置管理](../admin/llm-configuration.md)，客户端指纹受管字段见[请求指纹 Profile](../admin/client-fingerprints.md)。

### 生命周期与生效边界

- **静态前缀与当轮信封**：`system_prompt` 仅承载人格、共享与覆盖风格、宿主规则、常驻工具说明及 `<skill_catalog>` 清单；时间、星期、节日、窗口参与者、被艾特成员档案、自动召回记忆、命中词表、Persona v3 角色百科（`lore`）和延迟工具按名公告全部位于当轮 `user` 消息头部的 `【轮次上下文】` 信封。只有配置、人格、常驻工具集合或已安装 Skill 清单变化时，系统提示词前缀才会改变。
- **任务级配置快照隔离**：正在运行的 Agent Loop 与周期报告任务全程持有启动时刻捕获的配置、价格与 MCP 连接租约；修改群级覆盖或发布新配置草稿只作用于随后新进入的请求。
- **Session、纪元与追踪 Span**：业务 Session 跨缩窗与切换模型保持不变，纪元 UUID 随每次缩窗或历史重建轮换，底层 HTTP Trace Span 按单次网络尝试独立派生。
- **当前工具回合与已关闭历史**：当前正在进行的工具循环回合必须保持协议原生块、思维签名、工具调用 ID 与返回结果的一一配对；已关闭的历史 Loop 则根据归属匹配、敏感词复检与回放预算决定采用原生回放还是通用文本投影。

### 历史回放的协议约束

已关闭的含工具历史 Loop 仅在归属五元组（渠道 ID、协议、实际模型名、端点指纹、协议 Profile 指纹）完全匹配时启用原生回放；思考档位（`effort`）不纳入归属比较，切换档位后仍可原生回放既有推理块（体积估算按各轮生成时记录的档位计算）。归属变化、签名缺失、命中敏感词清洗或触及预算压缩时自动转为通用文本／摘要表达；无工具调用的常规问答轮始终使用场景块文本历史。各协议的特殊约束如下：

- **Claude（Anthropic Messages）**：无有效签名的历史 `thinking` 块自动降级为普通文本；适配器不在收到上游错误后做二次剥离重试。
- **Gemini（GenerateContent）**：`thoughtSignature` 作为不可篡改的不透明令牌随完整有序 `parts` 保存并原样回放；同一回合的每个 `functionCall` 都必须有配对的 `functionResponse`（单轮调用数超出运行时上限时整批拒绝执行，防止留下半截工具历史），工具返回的内联图片独立放在整批 `functionResponse` 之后的下一个 `user` 回合发送。面对严格上游兼容问题，`gemini_compat.py` 在序列化时过滤空文本块、为无签名并行 `functionCall` 首项补入 `"skip_thought_signature_validator"`、在 SSE 重组时禁止合并带 `thoughtSignature` 的分片，并在非 `single_dispatch` 请求遭遇 HTTP `400` 明确拒绝签名时自动降级历史签名原地重试一次。
- **OpenAI Responses**：固定使用 `store: false` 全量客户端回放，并在发送前执行跨 Loop `call_id` 冲突与配对守门校验。若非探活请求收到上游 HTTP `400` 且请求中包含已关闭历史的加密 `reasoning` 条目，适配器自动剥离历史 `reasoning` 原地重试一次（当前工具回合内的原生条目始终完整保留）；网络异常、鉴权失败与非 `400` 状态码直接走常规错误处理。更多多轮排障指引见[配置参考](../admin/configuration.md#图片预算与多轮对话排障)。

### 预算参数与历史收缩

单次请求的输入总预算按“渠道／模型显式覆盖 → 已知模型上下文窗口减去输出预留推导 → 全局运行默认值”三级回退确定。首轮组装超限时，依次卸除自动召回记忆、卸除 Persona v3 少样本对话示例、将纪元窗口强制推进至热水位 `L_hot`；若锚点已无法继续前移，则收紧历史工具回放预算或缩短普通历史后重装一次，仍超限则拒绝发起请求并提示用户清空上下文。工具循环中途续轮超限时直接终止当轮循环。

历史工具回放预算从总输入预算中扣除纪元可见文本窗口、`system_prompt` 与工具 Schema 预留以及当前活跃 Loop 预留后得出（受 `agent_replay_loop_tokens` 推导下限保护，也可由渠道／模型参数显式指定）。当窗口内历史工具投影超出该预算时，系统按 `epoch_hot_target_tokens / epoch_cap_tokens` 比例截取最新完整 Loop 后缀；若最新单个 Loop 自身即超出上限，则按确定性精简阶梯逐级剥离大载荷并冻结结果。

### 核对顺序与证据

1. **确认运行基线**：记录代码提交 SHA、应用版本、草稿与已发布修订号及 Bot 心跳回报的 `loaded_revision`，确认操作发生在目标请求启动之前，并核对全局配置、群级覆盖与生效人格。
2. **确认渠道与指纹策略**：核对渠道协议、实际请求模型、`client_fingerprint`、`responses_profile` 及 `extra_body`，检查最终载荷中受管字段与自定义字段的合成结果。
3. **检查 LLM Trace 原始报文**：在复现前开启 Trace 采集，在后台按 Agent Loop ID 对照首轮、工具续轮、退避重试、备用地址切换以及 Responses／Gemini 历史签名 400 降级重试的每次 HTTP 请求头、请求体与原始响应（注意降级重试与 Gemini 空回复补正都会在 Trace 与用量表中各自产生两次底层 HTTP 记录）。
4. **核对跨轮投影与纪元事件**：查看后台“会话纪元”面板与日志中的纪元推进原因（`cold` / `hot` / `rows` / `persona` / `history` / `profile` / `budget`）及 `history` 重建差异摘要，将跨模型切换导致的预期历史降级与当前回合的协议报错区分定位。

对外提交 Issue 或复现材料时一律使用脱敏样本，保留报文结构、字段顺序、状态码与纪元事件序列，隐去真实 API Key、QQ 号、群聊原文及不透明签名／加密推理密文。真实上游兼容性结论须注明模型名、端点类型、指纹 Profile、代码 SHA 与实测日期。

## 12. 推荐维护方式

日常迭代时按职责边界定位修改入口：

| 调整目标 | 维护位置 |
|---|---|
| 角色设定、三段式声腔与角色百科 | `config/personas/*.toml`、`persona_compiler.py` 及渠道／模型风格参数 |
| 群成员认人与出站艾特还原 | `llm_about/identities.yaml`、`llm/identity.py` 与 `_llm_reply.py` |
| 昵称别名与群内黑话释义 | `llm_about/vocab.yaml` 与 `llm/vocab.py` |
| 工具可见范围、按需发现与同纪元粘性 | `settings.tools`、`service_parts/tools.py`、`tool_discovery.py` 与 `epoch.py` |
| 长期记忆、群历史与群语录检索 | `service_parts/memory_tools.py`、`history_tools.py`、`quote_tools.py` 及对应存储层 |

受管数据库配置经草稿保存与独立应用任务生效，人格与 `llm_about/` 资料可通过 `/llm reload` 或后台动作重载。动手改动前先对照 Trace 与生效参数定位问题所在层，保持协议适配、上下文编排与业务存储之间的单向边界。
