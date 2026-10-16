# QuickQuip LLM 模块说明

本文面向 LLM 运行时维护者，说明消息触发、Session 与上下文、请求组装、人格和工具的契约。配置与部署操作见[管理员文档](../admin/llm-configuration.md)，实现排障见本页第 11 节。

## 1. 模块定位

QuickQuip 的 LLM 模块为规则机器人提供对话扩展。管理员按群或私聊选择渠道、模型和人格，并控制触发、记忆与工具。默认入口为配置前缀、艾特机器人和 `/search`；群聊唤醒按第 3 节的开关与条件启用。

模块支持图片理解、语音转写、项目搜索后端、Gemini 原生搜索和工具调用。MCP 服务作为外部工具来源接入同一注册表，契约见[MCP 集成说明](mcp-integration.md)。

LLM 运行时在 `LLM_TRACE_FLAG_FILE` 指向的开关文件存在时，把每次 HTTP 尝试写入 `data/llm_trace.db`。请求正文取自实际交给 HTTP 客户端的 UTF-8 JSON 序列化文本；普通响应保留 JSON 解析前的服务端文本；流式响应完整消费 SSE 后，由协议客户端重建 OpenAI Chat Completion、Claude Message、Gemini GenerateContent 或 OpenAI Responses 完整响应对象，同时保留 SSE 传输原文供管理员按需核对。索引、正文和单调递增的状态事件分开存储，Web Admin 先读取轻量调用元数据，管理员选择记录后再加载完整 Header 与正文。`run_tool_call_loop` 为一轮完整交互分配 Agent Loop ID，重试、故障切换和工具结果回送产生的 HTTP 调用按组内序号排列。

多模态消息的内联 base64 载荷在落库前按内容寻址去重：`LLM_TRACE_MEDIA_MIN_BYTES` 达到门槛的载荷写入 `data/trace_blobs/`，正文只留 `[qq:blob sha256=<hex> bytes=<n>]` 占位符，同一份载荷在请求、重组响应与原始 SSE 三处共用一个副本。每次截断把 splice 清单与全文哈希记入 `media_truncation` 列；读端默认返回占位符文本，`restore` 参数按清单回拼并逐项校验。每日留存清理之后，按剩余行的引用集合 mark-sweep 未被引用的 blob。截断只发生在落库侧，发往上游的报文不变；未达门槛、畸形或被截断的字符串一律原样存储。配置键与默认值见[管理员配置](../admin/configuration.md)。

### 1.1 执行记录的请求边界

群聊和私聊生成请求创建的执行记录按请求携带的 `trigger_kind` 保存触发类型；未显式指定时，群聊默认为 `group_direct`，私聊默认为 `private_direct`。被动群触发保存为 `group_passive`，供 Loop 详情与历史档案使用。历史记录保留已存分类，缺少原始触发证据时不推断回填。

请求在模型调用、工具执行或分段发送期间被取消时，服务将已创建的 Loop 关闭为 `interrupted`，终止原因为 `request_cancelled`，并继续向调用方传播取消异常。收尾复用存储层的幂等关闭：已完成的 Turn、工具结果和发送回执保留；声明但未启动的工具收束为 `not_executed`，运行中且未记录结果的工具收束为 `indeterminate`，计划交付收束为 `skipped`，发送中且未记录回执的交付收束为 `unknown`。收尾不重试工具或消息发送；存储正常时，同会话后续请求可以创建新的 Loop。

---

### 1.2 请求指纹与身份投影

`client_fingerprints` 模块负责 TOML Profile 解析、启动目录快照、安装身份持久化和请求投影。Provider 固定字段 `client_fingerprint` 选择模板，编译时绑定全局 cluster 和数据目录；模型覆盖保留绑定。四协议在各自认证与 Body 映射边界调用共享 Header/Body 投影接口。OpenCode 2 的 Chat Body 和物理尝试追踪在实际 URL、流式模式确定后进行最终投影；其他 Profile 的早期 Body 接口保留载荷原样。Codex 的可选 body_bindings 在实际 HTTP 尝试边界投影业务 Session，只补充缓存键，保留适配器的其他 Body 字段与序列化策略。模板、字段顺序和端点兼容条件随 TOML 分发。Header 布局作用于 HTTPX 请求对象；HTTP/1.1 的 h11 序列化将 Host 移至首位，真实 socket 验证覆盖该边界和其余字段的排布。

`LLMRequest.session` 是业务 Session，`epoch_id` 是不可变的请求纪元快照。EpochManager 拥有聊天窗口 UUID，TurnRequestAssembler 在历史加载及预算重组后取值；独立任务入口创建临时纪元，工具和识图按调用链传递。底层自有 Profile 请求必须提供 UUIDv4。动态投影头不参与 Responses 内容兼容指纹。管理员配置与文件格式见[请求指纹 Profile](../admin/client-fingerprints.md)。

OpenCode 的 Session ID 是业务 Session 的纯派生，恢复后稳定，纪元推进不旋转。Codex 的 session-id、thread-id、x-client-request-id 和 prompt_cache_key 共用业务 UUID 投影；绑定字段由 Profile 拥有，Provider／Model 手工覆盖在配置及运行时拒绝。请求级 ContextVar 保存冻结请求和逻辑 parent span；HTTP 尝试生成新 span 并在 trace 记录前完成 Header/Body 投影，重试和备用地址各自生成。取消、异常和嵌套调用退出时恢复上下文。HTTP 适配器保留鉴权、代理、超时、SSE 解析和计量职责；Profile 不访问业务存储或替换人格与工具策略。

## 2. 当前代码结构

LLM 维护入口按职责列在下表：

| 文件或目录 | 职责 |
|---|---|
| `src/quickquip/adapters/nonebot/commands.py` | 负责 `/llm`、`/search` 等命令注册；注册逻辑按域拆到 `command_parts/`（llm / memory / sts / media 等） |
| `src/quickquip/adapters/nonebot/group_messages.py` | 负责 NoneBot 群消息入口，并把消息交给应用层管线 |
| `src/quickquip/adapters/nonebot/daily_summary_plugin.py` | 负责每日总结/周期报告的定时任务注册与 `/summary` 命令；生成与发布编排本体在 `src/quickquip/chat/summary_jobs.py`（窗口、min_messages 门槛、persona 兜底、发布状态机） |
| `src/quickquip/llm/service.py` | `LLMService` 门面，装配会话设置、提示、记忆、工具与请求；各域实现见 `service_parts/`。回复入口采用 `ChatTurnRequest` |
| `src/quickquip/llm/reply_chain.py` | 装配首轮与预算降级请求，规范输入、处理输出并构造回复结果 |
| `src/quickquip/llm/quick_judge.py` | 结构化快速判定与诊断结果，服务门面向它委托调用 |
| `src/quickquip/llm/single_shot.py` | 独立生成的共享管线，以 `CommandSingleShotSpec` 表达各命令差异 |
| `src/quickquip/llm/prompting.py` | 组装稳定的 system prompt、当轮上下文信封、场景消息和发言者标签 |
| `src/quickquip/llm/summarize.py` | 生成每日总结与周月报，串联模型候选和压缩输入 |
| `src/quickquip/llm/briefing.py` | 每日播报生成（群人格、模型级联、失败回退；遇到非正常 finish_reason 会继续尝试下一条级联） |
| `src/quickquip/app/message_pipeline.py` | 应用组合根：chat / games / tieba 单例装配、`resolve_reply()` 规则链、`reload_chat_rules_pipeline()`、`save_all()` / `close_persistent_stores()` 与 `_ensure_llm_bindings()` |
| `src/quickquip/llm/config.py` | 保留业务配置对象；数据库应用服务读取已发布快照，`config_document.py` 负责校验、编译与模型参数解析 |
| `src/quickquip/llm/provider/` | 适配四类协议，序列化请求、解析响应、执行重试并记录 HTTP Trace |
| `src/quickquip/llm/tool_loop.py` | 负责工具调用循环编排（Agent Loop trace、会话消息推进） |
| `src/quickquip/llm/thinking.py` | 映射内部六档思考设置到各协议的参数与钳制规则 |
| `src/quickquip/llm/tool_discovery.py` | 负责单次循环内的动态工具加载状态（`loaded_names`）与 `tool_search` / `tool_list` 元工具 handler |
| `src/quickquip/llm/tool_result_pipeline.py` | 负责工具执行前后的强制处理：参数与结果的敏感词扫描、单请求工具图片预算、非视觉模型图片降级 |
| `src/quickquip/llm/tool_registry.py` | 负责工具白名单注册、参数校验和执行调度 |
| `src/quickquip/llm/skills/` | 解析、扫描与执行 Skill 包；模块职责见第 6.3 节 |
| `src/quickquip/llm/store.py` | SQLite 持久化门面，按域组合 `store_parts/` 的会话、记忆、归档与群设置实现 |
| `src/quickquip/llm/vocab.py` | 负责从 `llm_about/vocab.yaml` 读取群别名与黑话词表，并按需注入 |
| `src/quickquip/llm/identity.py` | 复用共享身份模型，归并参与者并收集被艾特成员档案 |
| `src/quickquip/llm/rendering.py` | 负责把消息段标准化为给 LLM 使用的纯文本，并解析艾特 |
| `src/quickquip/llm/message_segments.py` | 负责消息段叶子节点渲染、bot 身份集合归一化等共享小逻辑 |
| `src/quickquip/llm/health.py` | 配置、渠道、数据库、资料、工具与运行时健康检查 |
| `src/quickquip/llm/image_preprocessor.py` | 图像预处理抽象接口（`ImagePreprocessor`），预留 OCR / 多模态模型转述的钩子点 |
| `src/quickquip/adapters/nonebot/voice.py` | 负责 OneBot V11 `record` 语音段提取、转码与 ASR 转写注入 |
| `src/quickquip/generation/asr.py` | 负责 ASR provider 调用，当前支持 OpenAI-compatible `/audio/transcriptions` |
| `src/quickquip/common/recent_message_buffer.py` | 负责“触发前最近群消息”内存缓冲 |
| `src/quickquip/llm/inputs.py` | 负责从消息段中提取文本触发、艾特触发和图片 URL |
| `src/quickquip/search/web_search.py` | 负责项目内 SearXNG 搜索客户端，供 `/search` 与 `search_web` 工具使用 |
| `src/quickquip/llm/provider/gemini.py`、`rendering.py` | 声明 Gemini 内置搜索，解析 `groundingMetadata` 并渲染回复来源 |

### 请求组装与协议处理

服务实现按 scope、MCP 生命周期、内置工具、SVG、定时消息、Skill、独立生成、图像预处理、健康检查、状态、自动记忆和 Agent Loop 拆分，模块清单见 `service_parts/__init__.py`。`reply_chain.py` 中的 `TurnRequestAssembler` 共用首轮与预算降级装配，输入和输出分别由 `normalize_turn_input`、`finalize_reply_text` 处理，`reply_result` 构造返回结果与触发行正文；该模块接收显式参数，与服务门面单向依赖。

报告输入经 `chat/period_serializer.py` 压缩：按日分节、按分钟分块，同身份连续消息用斜杠合并，复读折叠为 ×N，URL 保留域名，机器人标记为 (bot)。日报和周报将整个周期交给序列化器；月报由 `build_monthly_chat_input` 按周分配 `input_char_budget`，保留平静日，高活跃日使用剩余额度并按需等距抽稀，输出包含周节标题。

协议客户端的 `complete()` 对 429、5xx 和网络错误执行指数退避，策略由 `retry.py` 提供；探活和诊断使用 `RetryPolicy.disabled()` 禁用自动重试。基类、四协议实现、工厂、重试和追踪分别由相应子模块维护。

Gemini 在原生工具回合保存并按顺序回放含 `thoughtSignature` 的 parts。Claude 当前工具循环通过通用重建回传签名 thinking 块，已关闭且包含工具的 Loop 在归属匹配和签名有效时跨轮原生回放。Responses 使用 `store:false` 全量回放，当前工具循环回传原生 items，并检查 call_id 记账、冲突和结果配对；已关闭历史经归属校验回放 reasoning 密文，上游返回 HTTP 400 时剥离历史 reasoning 重试一次。当前工具循环内容保留。历史投影规则见第 4.2 节。

Responses 的 `openai-public` 与 `codex-http-relay` Profile 均接受新增的事件类型和附加 JSON 字段。未知事件通过序号与终态顺序校验后跳过，继续等待终态；每条流最多记录八种未知事件，每种记录一次，事件名截取前 128 个字符并转义，原始载荷由 HTTP Trace 开关控制保存。`codex-http-relay` 将 `response.metadata`、`codex.response.metadata` 等已知中转附加事件静默忽略。此策略遵循 OpenAI 将新增流式事件类型视为兼容扩展的[约定](https://developers.openai.com/api/reference/overview#backwards-compatibility)。

Responses 对已消费事件的必要字段、流式正文与工具参数的一致性、终态状态及输出条目类型执行严格校验。不支持的输出条目（含工具条目）或内容类型会使调用失败。

思考设置使用 low、medium、high、xhigh、max、ultra 六档。OpenAI Chat 按模型家族钳制；Claude 按代际选择 adaptive effort 或固定 budget 表；Gemini 按代际选择 thinkingLevel 或 thinkingBudget；Responses 使用自己的 profile 词表。Claude budget 至少为 1024，其余由映射规则照发，上游以 400 报告不支持的参数；钳制与照发决策记录节流日志。

兼容层说明：

- `src/plugins/` 目录是 NoneBot2 插件入口，由 `bot.py` 通过 `nonebot.load_plugins(*plugins.__path__)` 加载已安装包路径
- 新增逻辑优先放在 `src/quickquip/` 下（包路径 `quickquip.*`），`src/plugins/` 只负责 re-export

持久化文件：

- `data/llm.db`
  - 群级 LLM 设置
  - 短期 LLM 会话记录
  - 长期记忆

配置文件：

- `data/llm_config.db`
  - 真实运行配置，本地私有
- `config/llm.json.example`
  - 可导入配置数据库的 JSON 交换模板

群资料文件：

- `llm_about/identities.yaml`
  - 群成员标准身份词表，负责 QQ 号到标准身份的映射
- `llm_about/vocab.yaml`
  - 群成员别名与部分黑话词表
- `llm_about/群聊简介和概况.md`
  - 仅供人工设计人格时参考，不直接整份注入模型

> 注：生产部署中，仓库根目录的 `llm_about/` 通过 docker-compose volume 挂载到容器内的 `/app/llm_about/`。详见 [admin/deployment.md](../admin/deployment.md)。

---

## 3. 触发规则

LLM 默认只在以下场景触发：

- 以配置前缀开头，例如 `/ai`
- `@机器人`
- `/search <query>`

普通群消息可以通过唤醒模块进入 LLM，但所有唤醒入口默认关闭或受阈值控制，且会经过群规则开关与限流器。

当前消息流顺序：

1. 记录普通统计
2. 读取当前群最近消息缓冲
3. 判断是否命中 LLM 显式触发
4. 如果命中 LLM，则优先走 LLM
5. 如果未命中显式触发，则检查唤醒模块：
   - `awakening_extend`
   - `awakening_interest`
   - `awakening_relevance`
   - `awakening_qa`
   - `awakening_fallback`
6. 如果各唤醒条件均未命中，继续规则流：
   - 复读
   - 接龙
   - 彩蛋规则
   - 时区猜测

显式调用优先于唤醒，唤醒优先于规则回复。默认关闭唤醒时，普通群消息进入规则回复流程。

### 3.1 唤醒模块

唤醒模块位于 `src/quickquip/chat/awakening/` 包（config / state / text_signals / judge / triggers / boredom 六个子模块 + facade，依赖单向），命令入口位于 `src/quickquip/adapters/nonebot/awakening_plugin.py`，配置文件为 `config/awakening.toml`。

| 规则名 | 触发方式 |
|------|----------|
| `awakening_extend` | 显式触发后，在 `extend_duration` 秒内继续回应同一用户 |
| `awakening_interest` | 消息命中全局或 persona 里的兴趣话题 |
| `awakening_relevance` | 先做词重叠快筛，再用 `quick_judge` 判断是否延续 bot 近期回复 |
| `awakening_qa` | 先做问句快筛，再用 `quick_judge` 判断是否需要回答 |
| `awakening_boredom` | APScheduler 定时检查沉寂群，并向 opt-in 群发送低频冒泡消息 |
| `awakening_fallback` | 普通消息按配置概率兜底触发 |

相关性与答疑判定会使用 `settings.quick_judge` 指定的小模型配置；阈值 `>= 1.0` 时跳过对应 LLM 判定。

`awakening_extend` 只由显式 LLM 入口打开，例如前缀或艾特触发。兴趣、兜底、无聊、相关性和答疑唤醒都是一次性触发，不会继续刷新延长窗口。延长窗口内会过滤纯图片、纯 CQ 码、短语气词和过短无实义文本。

唤醒触发会给本轮 LLM 请求附加内部触发说明，例如命中的兴趣话题或兜底触发背景，并要求模型不要暴露唤醒机制。内部说明不会作为群友原文写入 LLM 对话历史。

`awakening_extend`、`awakening_interest`、`awakening_relevance`、`awakening_qa` 和 `awakening_boredom` 携带群内近期历史图片；`awakening_fallback` 不注入图片。非视觉模型的图片由 LLM 运行时统一预处理或剥离。

无聊唤醒有两层开关：先在 `config/awakening.toml` 中设置沉寂秒数、概率、检查间隔和免打扰时间，再由群管理员执行 `/awakening boredom on`，写入 `data/awakening_boredom_groups.json`。

---

## 4. 上下文边界

### 4.1 临时上下文

`RecentMessageBuffer` 在内存中保存当前群最近 20 条消息，默认 TTL 为 1800 秒。LLM 触发时按增量补丁规则选取需要补充的现场消息；具体游标、保底时间窗和 token 预算见下一节。缓冲内容用于当轮请求，LLM 对话历史与自动记忆由各自写入流程管理。

### 4.2 LLM 短期会话

**Session 身份与生命周期**：Session 表示业务层持续进行的一段 LLM 交互。群／私聊 scope 承载当前聊天，Session 身份跨轮保持；上下文纪元管理每次发送的历史窗口。内部身份为 UUIDv4，创建时间为 UTC，`SessionIdentity` 是不可变快照，`LLMRequest.session` 显式携带它。

- 群聊首次通过输入与资格检查后懒创建，群内不同发言者共享当前 Session。显式私聊 start 创建新身份；清空结束当前身份，下一轮再创建。查看状态和被过滤的消息不创建聊天身份。
- 工具续轮、重试、流式回退、历史裁剪、冷场、撤回、人格／模型／协议切换、禁用再启用均延续当前身份。活动身份保存于 SQLite，重启后继续使用。
- 私聊保存结束时，将身份与历史归档；恢复保留原身份并替换当前 Session。空私聊结束不建存档；不保存结束、清空和删除存档解除相应绑定。
- 身份、历史迁移与 generation 更新在同一写事务中完成；事务成功后清理派生缓存。每轮冻结身份及 generation，失效后停止工具续轮，并拒绝迟到结果写入或交付。无 Agent 记录路径同样使用事务写入屏障。
- 播报、总结、周月报、人物志、触发判定、后台记忆提取、诊断与独立命令每次操作使用一个短任务身份，级联与操作内重试复用。聊天图片预处理和工具图片转述显式继承聊天身份。

出口投影接口为 `SessionProjector = Callable[[SessionIdentity], str]`。客户端 Profile 接收业务身份，按协议生成请求 Header、Body 或缓存键，具体契约见[请求指纹 Profile](../admin/client-fingerprints.md)。低层 `LLMRequest` 未提供身份时保留 `None`；依赖业务身份的 Profile 会在发送前拒绝缺失身份。

`SessionIdentity` 的可序列化字段保持身份与创建时间；`SessionModelProjection` 承载 Session 的首次使用模型绑定，运行时投影状态不进入身份 JSON。Agent schema 4 的 `session_client_models` 按 Session 与客户端原子保存模型名，持续聊天每次绑定验证当前身份及 generation；存档恢复保留绑定，清空或删除最后一份存档时清理无引用绑定。独立操作在内存中绑定，Gemini CLI 的 default 与显式模板共用同一客户端键，模板版本跟随当前冻结配置。

HTTP 追踪在列表、详情及 SSE 事件中返回可空的 `session_id`。已有追踪记录保持空值。传输层仅在当前 `complete()` 范围内绑定显式快照，退出或取消后恢复；不从外层任务上下文推断业务归属。管理页面继续使用现有展示。

升级前备份会话与追踪 SQLite 库；新增身份列为可空字段，旧消息与存档保留。回退旧代码运行后再次升级，须停服、备份并重置活动与存档绑定，使新版重新分配身份；维护 SQL、数据库路径与执行方式统一见[管理员回退与再次升级流程](../admin/llm-configuration.md#回退旧版本后再次升级)。该维护保留消息、存档、设置和 generation，追踪历史身份继续作为观测记录保存。数据库不可用时，持续聊天停止执行并返回存储错误，不分配临时身份继续回复。

聊天消息与 Agent 执行记录各自遵循保留策略。消息裁剪或删除时，数据库在同一事务中将相关 Turn 的 `message_row_id` 置空；Turn、工具和交付记录按执行记录的保留规则维护。显式撤回继续清理正文及原生证据，清空会话删除整个 Scope 的执行记录。业务库 Agent schema 3 在首次打开时修复已有的悬空消息引用并安装删除保护，保留现存消息、执行记录和 Session 身份。

工具历史投影在请求内按当前敏感词表检查完整 Loop。命中 block 或包含输出过滤替换态时，使用清洗后的文本档案并保留工具终态汇总，省略原生块、工具参数和结果正文；所有预算降级沿用该请求副本，持久化原文保持不变。未命中的 Loop 保留原有协议重放路径；原生回放（Claude 签名块 / Gemini parts / Responses output items）以 owner 五元组精确匹配为前提：渠道 ID、协议、实际请求模型、端点指纹和协议 Profile 指纹全部相同，失配或形状损坏按协议各自降级（档案/通用重建），Responses 侧另有跨 Loop call_id 冲突与配对完整的发送前守门。

LLM 自身的问答往返会写入 SQLite，用于多轮延续。读取窗口由**会话纪元**（session epoch）管理：

- 每个键（`群 × provider × model`）维护一个只追加的读取锚点：每次触发读取 `id >= 锚点` 的全部历史，窗口随对话增长，锚点保持稳定以支持跨轮前缀缓存
- 锚点只在三种时机前移：**冷场**（距该键上次 LLM 请求超过 T 秒且窗口超过 H_cold，缩回 L_cold）、**触顶**（窗口超过 cap，缩回 L_hot）或**容量降级**（请求预算超限时由服务层调用 `force_advance_to_hot` 缩回 L_hot 并重建请求重试一次）；默认 T=300s、L_cold=4k、H_cold=5k、L_hot=32k、cap=64k（token 估算），全部可在 `settings.runtime` 与渠道／模型 `parameters` 的 `epoch_*` 键调整（见[配置参考](../admin/configuration.md)）
- 窗口使用 `token_estimate.py` 估算 token；1024 行硬上限同时控制消息数组长度
- 锚点只落在 user/assistant 对边界，且保留最少 4 行，为超长消息保留基本对话配对
- 存储裁剪以该群所有纪元键的最老锚点为准；锚点缺失（进程重启后）时只按 2048 行硬上限兜底（`MAX_STORED_CONVERSATION_MESSAGES`，群聊/私聊同值），不按窗口重估删行
- 锚点状态保存在进程内存中：进程重启后，首个请求按距最新消息约 8k token 的范围懒初始化锚点
- `/llm context_limit <n>` 将群聊或私聊会话设为保留最新 n 行的滚动窗，上限 1024 行；`/llm context_limit reset` 恢复纪元管理。读取上限由会话覆盖与纪元规则决定；旧 `history_limit` 全局默认和 `history_max_messages_per_group` 保留解析，运行时忽略这两个旧值
- `clear_context` 清理消息与 Agent 执行记录，解除 Session 绑定并推进 generation；提交后清理最近消息缓冲、纪元锚点、信封缓存和 Skill 激活登记。私聊 start/end/resume 使用相应事务与缓存清理流程。
- `/llm use` 换 provider/model 自动开新纪元（键不同）；`/llm persona use` 按冷场水位前移锚点，以适应人格提示变化后的窗口重建
- 历史消息按落库时冻结的 `canonical_name` 渲染；用户改名后，历史前缀保留当时的名称

**近期消息的【现场】补丁**：LLM 请求通过 `recent_message_buffer.py` 的 `list_patch` 取得增量现场消息：

单次请求在首次读取后保存补丁快照，首轮装配与预算缩窗重建共用该快照，并按最新历史去重。缓冲游标仅在自取时推进；私聊未参与补丁与显式空补丁保持独立计量语义。近期图片继续使用独立的全量快照。

- 候选 =（上次服役之后的新消息）∪（`recent_context_floor_seconds`=300s 滑动保底窗内的消息），再按 message_id 剔除 history 已覆盖者与当前触发消息，最后从最新往回截到 `recent_context_token_budget`=800 token（估算，至少保留最新一条；非法取值回退默认并告警）
- 读即服役：取出后 `note_patch_served` 推进按群游标；失败轮丢失超保底窗的旧补丁，由保底窗兜底
- `include_recent_images` 通过 `list_recent` 全量快照取图，使用 TTL 时间窗，与文本补丁游标独立
- 预算只在服役侧执行：buffer 写入侧按 20 条与 TTL 1800 秒控制容量，estimator/budget/floor 全部由 service 按 `settings.runtime` 配置注入（仅全局键，无 provider 覆盖）
- service 在群聊且调用方未显式注入时取得补丁；`recent_messages=[]` 表示显式空输入，供测试或调用方控制现场内容。私聊跳过自取
- `list_recent` 全量快照保留给两个不适用增量语义的消费者：`context_rules` 规则引擎与「读近期消息」模型工具

**场景块消息结构**：当前 messages 数组采用“以 bot 回复为边界的场景块”模式：

- 连续的多人发言归入同一 `role="user"` 场景块（bot 回复打断场景）
- 所有发言者使用统一格式：`身份（QQ 号）：内容`
- 场景以 `【上文】`（历史）或 `【当前提问】`（最后一轮提问）标记；现场补丁独立成 `【现场】` 段（说明这些消息作为聊天氛围使用），消息尾部顺序为 `【轮次上下文】→【上文】→【现场】→【当前提问】`
- 无聊唤醒与定时任务是合成触发源：落库结构化配对行（`【自动唤醒】<诱因>` / `【定时消息】按 <cron> 发送：<摘要>`）消除 history 的 assistant 孤行，但不从合成内容抽取自动记忆（`store_user_message` 与 `trigger_auto_memory` 双开关）；合成 user_id（`boredom_timer`/`scheduled_timer`）既不进信封参与者，渲染时也直接以名字呈现
- 格式化仅在 `build_messages()` 组装时做一次，DB 存储原始文本（`raw_content` 列）
- 引用消息会同时保留“当前提问者”和“引用发送者”，并显式区分机器人自己，避免 A 引用 B 时被误读成 B 在发言
- 合并转发会递归展开多层节点，并保留每层的文字和图片信息；组合文本总长封顶 4000 字符，超出在最外层出口硬切并追加「…（合并转发内容过长，已截断）」
- 非视觉模型的图注以文本身份落库：落库 `raw_content` 追加 `[图片 N 张：…]`（转发图注并入转发文本），落库字节即下一轮 history 的前缀字节，转述内容不随轮丢失、前缀稳定

统一格式使模型可以按发言者理解历史、现场和当前提问；`【当前提问】` 指定需要回答的最后一轮。格式化发生在请求组装阶段，数据库保存原始正文，避免重复包装。

### 4.3 图片输入边界

图片理解遵循显式触发和受限被动唤醒规则：

- 群聊当前图片通过配置前缀或艾特机器人触发；被动唤醒按下述规则补充近期图片
- 单次最多处理 5 张当前、引用图片与近期上下文图片；转发图片以文字或图注形式进入请求
- `awakening_extend`、`awakening_interest`、`awakening_relevance`、`awakening_qa` 和 `awakening_boredom` 携带群内近期历史图片
- 近期历史图片使用当前请求剩余的图片名额，并优先保留最新图片
- 单张图片（解码后）上限 5 MiB；发送前统一过内联媒体收口（`provider/media_guard.py`）：GIF 按魔数嗅探自动取首帧转 PNG、同请求内相同内容去重、MIME 按实际字节归一，并对全部图片施加解码字节总量预算（默认 5 MiB，provider 级 `max_inline_media_bytes` 覆盖，0 = 不限）。超出单图上限或剩余额度的图片先降采样重编码（EXIF 方向校正、透明平铺白底、原始尺寸优先 + 长边 2560→768 阶梯 × JPEG q85/q70 两档，命中即停；结果按「原始字节哈希 + 目标额度」缓存），额度低于 96 KiB 不再压缩。压缩后仍装不下的按候选优先级前缀止停：第一张连同其后全部跳过并记日志，避免丢弃当前大图却保留后续无关小图
- provider 图片下载按客户端实例缓存（TTL 10 分钟、容量 32 张 LRU，仅缓存成功结果）：同一轮内工具循环重建请求与退避重试复用同一 URL 的成功下载结果；GIF 首帧转码结果按内容哈希缓存，逐轮序列化不重复解码
- 请求组装先统一准备用户消息与各批工具结果图片，共享字节预算和内容去重；优先最新用户消息中的当前/引用/近期图片，再按新到旧处理工具结果与历史图片。预算耗尽后停止接纳后续低优先级图片，重试和并发请求各自创建预算。协议序列化保留完整工具结果批次与原消息顺序
- 如果只有图片没有文字提示，会自动补一个默认识图提示
- 视觉主模型直接接收原图；模型条目 `vision = false` 的主模型接收带来源和序号的视觉转述
- 前置视觉识别不可用、返回空内容或任一图片识别失败时，本轮终止并提示用户重试

MCP 工具也可返回经过校验的内联图片。它们不写入对话数据库、普通日志或 MCP 状态；视觉模型在下一轮工具调用消息中接收图片，非视觉模型仅接收经过二次敏感词扫描的转述文本。工具图片的转述不可用或失败时，Agent Loop 继续使用安全工具文本，而不会把原图或编码降级为文本。

模型产出的图片（Responses 内置 image_generation 工具条目——codex 类后端会在服务端注入，请求未声明也会出现；以及 Gemini 响应的 inlineData 图片 parts）由各协议适配器提取为归一的响应侧 `generated_images` 附件，并从原生回放批次剥除，base64 不进入 native_blocks。工具循环在每轮响应到达时把附件收进外发图片通道——与 draw_svg 等工具路径同通道、同上限（`MAX_OUTBOUND_TOOL_IMAGES`）、同「后续调用失败不丢弃已产出图片」语义，送达由适配层拼在正文后发送；收集侧挂与 svg_render 同风格的独立限流（全局 10 次/分钟、单用户 2 次/分钟）。

### 4.4 语音输入边界

语音理解也遵循显式触发原则：

- 群聊中必须和 `/ai` 或 `@机器人` 同时出现
- 私聊会话开启后，普通语音消息可作为 LLM 输入
- 若 OneBot 协议端的 `record` 段已经包含 `text` / `transcript` / `transcription`，直接使用该文本
- 否则通过 OneBot `get_record` 获取音频文件，并调用 `config/generation.toml` 中 `[asr]` 配置的 provider
- 转写结果会作为 `[语音转文字：...]` 拼入当前用户消息，并进入最近消息、日报/播报采集和词云输入
- ASR 失败时不阻塞原消息处理；没有可用转写时按文字和图片输入逻辑继续

### 4.5 长期记忆

长期记忆由人工 `/remember` 和自动事实抽取写入。自动抽取开启时，从已触发的 LLM 会话提取稳定事实；普通群聊归档由聊天记录系统维护。

---

## 5. 人格注入设计

当前人格注入分成多层：

### 5.1 基础人格

由 `config/personas/` 目录下的 TOML 文件定义，每个 `.toml` 一个人格，`_shared.toml` 提取所有人格共享的行为准则。

当前默认人格强调：

- 熟人群语气
- 高语境理解
- 轻松但克制
- 能接梗
- 严肃时收住玩笑
- 不冒充和任何成员有既定私交

### 5.2 群风格约束

人格提示从群资料中选择稳定的交流特征：

- 熟人化
- 深夜活跃
- 游戏 / 创作 / 二次元并重
- 黑话和夸张称呼常见
- 但认真场景要正常说话

### 5.3 词表按需注入

当输入命中 `vocab.yaml` 中的别名或黑话时，运行时在当轮 user 消息头部的【轮次上下文】信封追加对应的消歧说明。例如某个昵称指向群成员或物品时，只注入相关解释。system prompt 保持稳定，词表按实际命中参与当轮理解。

### 5.4 Provider 风格覆盖

渠道的 `providers[].parameters.style_overrides` 支持多行字符串；模型的 `models[].parameters.style_overrides` 可覆盖该值。共享风格段通过同一 `parameters` 对象中的 `style_profile` 引用。

此字段的内容会在每次调用该 provider 时，追加到 persona 的 `style_prompt` 之后，用于修正特定模型的口癖。

典型用途：

- GPT 系：禁止句尾反问句、禁止 emoji
- DeepSeek：禁止分点列举
- Claude / Gemini：禁止旁白括号、禁止过于简略的回复

通过 Web Admin「LLM 配置 → 渠道与模型」保存草稿，再单独应用并确认 Bot 已加载目标版本；在途任务保持原快照，后续请求使用新风格。`/llm reload` 读取已发布配置。完整参数继承与交换流程见[LLM 配置管理](../admin/llm-configuration.md)。

### 5.5 身份映射注入

`identities.yaml` 负责“这个 QQ 号是谁”，用途和 `vocab.yaml` 不同。

标识符分层：**LLM 层认人以标准身份（名字）为主锚**，QQ 号作为名字后的常驻后缀（区分同名无档案成员）；代码层（at 段解析、身份索引配对、存储列、注入管理）一律以 QQ 号为唯一键。`identities.yaml` 是 canonical name 的权威源，`vocab.yaml` 的标准名属称呼提示层，两处命名须保持同名对齐。群级合并仅对纯数字 `group_id` 生效：空串或非数字 scope（如私聊复合 id）不加载群级文件，`group_identities` 直接返回全局索引。

身份解析与消息交付遵循以下规则：

- **统一发言者格式**：历史、现场和当前提问均使用 `身份（QQ 号）：内容`
- 提问者进入 LLM 时，按 QQ 号解析标准身份；认人规则教模型**名字优先**、QQ 号仅作同名区分
- 最近群聊上下文中的发言者也会按 QQ 号显示标准身份
- 消息中的艾特在**入口 ingestion 时**按**群合并身份索引**渲染为 `@标准身份`（引用消息、合并转发子消息同索引）；未登记成员经群成员名片缓存（`get_group_member_info`，按 群×QQ 带 TTL）退化为 `@当前群名片`，查询失败才回退 `@QQ 号` 数字形态——名片预取覆盖消息顶层 @；引用/转发子消息内未登记 @ 不做名片预取，仅有段自带名称或与顶层重叠的预取名片时降级使用，否则回退数字形态
- 未登记发言者降级显示为“当前显示名 + QQ 号 + 未登记”
- **艾特档案注入（信封段）**：被艾特但未在窗口内发言的登记成员，其标准身份＋别名＋备注随当轮【轮次上下文】信封注入（名字在前、QQ 作配对键，上限 5 条）；候选来自入口结构化采集（at 段 QQ）与对窗口文本的 `@QQ 数字` 扫描（覆盖冻结落库的存量形态），已在窗口带发言人标签者跳过
- **出站艾特还原**：模型回复文本中的 `@QQ 号` 数字形态在发送出口（`_llm_reply.py`）切分为真实 at 段（右边界防幻觉长号）；群级开关 `llm_at_mention`（默认开）另启用「@名字」通道——按群合并身份快照的标准身份/别名/观察名片做最长匹配，歧义、艾特 bot 自身或未登记名字一律保留为纯文本（at-all 结构上不可达），群聊 LLM 路径（显式/被动/无聊唤醒/定时任务）共用同一解析出口
- **艾特护栏**：单条回复真实艾特上限 3 个（两通道合计，超出降级为文本）；「@名字」通道对同一（群 × QQ）有 `mention_cooldown_seconds` 冷却（默认 600 秒，0 关闭）——冷却在送达确认（可信 message_id）后记账、解析侧只读，发送失败不消耗名额，窗内重复艾特降级为文本
- **引用锚定**：群级开关 `llm_quote_reply`（默认开）让群聊 LLM 回复以引用段锚定触发它的那条消息；协议端显式拒绝引用段时去段重发正文，超时等传输异常不重试
- **周期报告读时重解析**：日总结/周报/月报/每日播报的序列化输入在读取时按身份索引把登记成员渲染名换成标准身份（归档仅存 user_id，无需回填）；同名不同 QQ 碰撞时给碰撞者附 QQ 后缀（碰撞触发式，控制压缩文本体积）
- **发言者身份**：messages 标记当前提问者与各轮发言者，system prompt 维护稳定的人格与行为要求
- **静态前缀与当轮信封**：时间、星期、节日、参与者、记忆和词表命中在当轮 user 消息头部的【轮次上下文】信封呈现，组装时渲染。同一配置、人格和工具集合下，system 跨轮、跨日字节稳定，支持前缀缓存。`envelope_meter` 将信封 token 记入 `envelope_tokens`；同一个 Agent Loop 的各行记录相同值，看板用 **AVG** 统计每轮成本，求和会重复计数
- **加载可观测**：`identities.yaml` 缺失（INFO）/存在但无有效条目（WARNING）/正常加载条目数（INFO）均有日志；空模板与缺失在索引层面等价

身份索引负责当前成员解析，冻结历史保留记录时名称；消息标签和当轮信封分别承载发言归属与当前资料。

---

## 6. 配置说明

### 6.1 `data/llm_config.db`

配置服务保留草稿、不可变发布快照、修订号、应用任务与 Bot 心跳。Web 和 CLI 共用校验与修订检查，Bot 以租约领取控制任务；保存草稿不会修改运行时，重启加载已发布版本。每个 Agent Loop 和独立报告任务固定配置、价格、工具与资源直到结束。

交换格式的主要字段：

- `providers`：有序渠道、模型与别名；固定认证／地址字段在渠道层，请求参数在渠道或模型的 `parameters`。
- `style_profiles` 与 `pricing`：共享风格及价格，价格以 `(渠道 ID, 配置的模型 ID)` 精确匹配请求模型名，不跨渠道兜底。
- `routes`：四类报告的有序候选，以 `{provider_id, model}` 引用；`@default` 动态选择默认模型。
- `settings.runtime` / `triggers` / `auto_search` / `quick_judge` / `image_preprocessing`：全局运行、触发与专用模型选择。
- `settings.tools` / `skills` / `mcp`：工具绑定、Skill 资源限额与 MCP 配置。
- `settings.daily_summary` / `daily_briefing` / `weekly_report` / `monthly_report`：报告开关、提示与时间配置。

完整字段见 [配置参考](../admin/configuration.md)，状态和操作契约见 [配置 API](llm-configuration-api.md)。`config/personas/` 和 `config/generation.toml` 继续维护独立配置；旧 TOML 仅供迁移与迁移前版本回退。配置修订号覆盖配置库，外部文件和环境变量保持独立生命周期。

### 6.2 工具发现

工具调用开启后，QuickQuip 支持本地 `tool_search` 和 `tool_list` 元工具。该机制用于工具数量较多的场景：初始请求只暴露 `always_loaded` 中的常驻工具，模型需要其它能力时先调用 `tool_search`；搜索不到但工具可能存在时，可用 `tool_list` 查看工具组、工具名或按精确名称加载工具。工具循环会把匹配到或精确加载的真实工具加入下一轮 provider 请求。

默认 `discovery_mode = "auto"`，当可延迟工具数超过 `discovery_min_tools` 后启用；工具较少时继续按原方式全量暴露。该设计不依赖 Claude 原生 tool search，OpenAI / Claude / Gemini / Responses 四类协议适配器共用同一套本地发现逻辑。

Gemini 3 原生工具回合把 `thoughtSignature` 视为不可解释、不可重建的 provider 数据。非流式与 SSE 响应都会保存签名所在的完整有序 part，并在下一轮 model turn 原样回放；并行调用逐 part 保持自己的签名。Gemini 要求上一轮每个 `functionCall` 都有对应 `functionResponse`，因此单轮调用数超过运行时上限时整批拒绝执行。工具返回图片不会与 `functionResponse` 混入同一个 Content，而是在完整响应批次之后作为独立 user turn 发送。

实现细节见 [tool-discovery.md](tool-discovery.md)，MCP 大工具集场景见 [mcp-integration.md](mcp-integration.md)。

窗口的 token 预算和行数上限见第 4.2 节；工具发现的数量约束由 `settings.tools` 与运行时加载规则执行。

### 6.3 Skill 系统

部署者将 Skill 包放入 `skills/`，每个子目录包含一份 `SKILL.md`，并可附带 `references/` 资料和 `scripts/` 脚本。Skill 开关开启且目录存在有效条目时，运行时注册 Skill 工具；工具调用总开关开启后，描述清单进入系统提示。AI 根据请求激活 Skill，再按需读取资料、检索内容或执行脚本。

运行时结构（`llm/skills/` 域包，文件级清单见 §2）：

- `parser`：SKILL.md 校验（name 命名约束与长度、description 长度、包体积上限）
- `catalog`：`skills/` 目录每轮请求扫描，下一轮使用新的目录内容；路径加固把读取与检索限制在 Skill 目录内，内容按 SHA-256 复验，扫描容忍目录被并发修改
- `state`：按会话维护激活状态登记，激活随上下文生命周期保持一致（`/llm clear_context` 等清理同步生效）
- `context`：catalog 块与激活标记的文本渲染（模型可见面的唯一出口，纯函数无状态）
- `preset_drift`：预置 Skill 漂移检测——`skills/` 与 `skills.example/` 同名目录的全文件字节级指纹比对（只读）；分叉名单变化时记 WARNING，`/skill list` 标注分叉条目，结果只进日志与命令回复，不进 catalog 块与系统提示；`skills.example/` 缺失时 fail-open。主机侧同步脚本 `scripts/sync_preset_skills.py` 按文件路径装载同一实现（stdlib，无 venv 依赖）
- `tools/`：四枚工具——`activate_skill`（激活）、`read_skill_resource`（读资料，字节上限）、`search_skill_resources`（内容检索，病态正则拒绝）、`run_skill_script`（脚本执行：隔离最小环境、无 shell、环境变量白名单、工作目录固定、超时与输出上限）
- `service_parts/skills.py`：描述清单注入系统提示（预算 `catalog_max_bytes`，实际取 min(模型上下文窗口 2%, 此值)）与激活接缝；敏感词联动——Skill 描述命中 block 词表时整只剔除该 Skill，激活注入文本预扫命中时本次不登记

配置集中在 `settings.skills`（键与默认值见 [../admin/configuration.md](../admin/configuration.md)）；群友侧用 `/skill list` 查看已安装与已激活项。部署方式与安全模型见 [../admin/skills.md](../admin/skills.md)，编写自己的 Skill 见教程 [skill-tutorial.md](skill-tutorial.md)。

### 6.4 `config/awakening.toml`

唤醒模块配置集中在 `config/awakening.toml`：

- `[awakening.defaults]`
  - `extend_duration`
  - `fallback_probability`
  - `boredom_silence_seconds`
  - `boredom_probability`
  - `boredom_scan_interval`（全局扫描周期；未设置回退 `boredom_check_interval`）
  - `boredom_check_interval`（群级成功唤醒冷却）
  - `boredom_dnd_start`
  - `boredom_dnd_end`
  - `interest_topics`
  - `relevance_threshold`（`<= 0` 或 `>= 1` 均关闭相关性 LLM 判定）
  - `qa_threshold`（`<= 0` 或 `>= 1` 均关闭答疑 LLM 判定）
- `[[awakening.group_overrides]]`
  - `group_id`
  - 任意需要覆盖的默认字段

persona TOML 可通过自由扩展字段追加兴趣话题：

```toml
[awakening]
interest_topics = ["关键词"]
```

### 6.5 `.env`

在根目录 `.env` 配置实际使用的渠道凭据；公开模板中的变量名示例为：

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`

OneBot 连接与 NoneBot 启动按部署模板配置，相关变量包括：

- `QQ_ACCOUNT`
- `ONEBOT_WS_URLS`
- `ONEBOT_ACCESS_TOKEN`
- `DRIVER`
- `HOST`
- `PORT`

### 6.6 `config/generation.toml`

LLM 相关的多模态输入/产出配置在 `generation.toml` 中维护：

- `[image]`：图片生成
- `[audio]`：语音生成（TTS）
- `[asr]`：语音识别，收到 OneBot `record` 语音消息时转写为文字注入 LLM
- `[music]`：歌词与音乐生成
- `[svg]`：SVG 画图（`draw_svg` 工具），模型在工具参数中直接写出 SVG 源码，本地 resvg 渲染成 PNG 后随回复外发

ASR 当前支持 `openai_transcriptions` 协议，即 OpenAI-compatible `POST /audio/transcriptions`。配置示例见 `config/generation.toml.example`。

`draw_svg` 是内置工具但**不在默认启用名单**：需要在 `generation.toml [svg]` 设 `enabled = true`，并在 `settings.tools.enabled` 中加入 `"draw_svg"`。渲染由 `quickquip.generation.svg` 编排——输入硬约束与静态清洗（`svg_sanitize.py`）、输出尺寸服务端覆盖（剥离根节点 width/height 后按 viewBox×2 显式传参）、spawn 子进程沙箱（Linux 带 RLIMIT_AS/RLIMIT_CPU，墙钟超时兜底）。工具结果图片经 `ToolExecutionContext.outbound_images` 外发通道直接发给用户（不回喂模型），单次回复上限 3 张，渲染限流为全局 10 次/分钟、单用户 2 次/分钟。

`harden` 默认启用，控制输入约束、清洗、尺寸覆盖和子进程资源限制。`content_judge` 默认关闭，开启后复用 `settings.quick_judge` 模型检查图片中的可见文本；判定服务失败时继续渲染。完整设置见 `config/generation.toml.example` 的 `[svg]` 注释。

---

## 7. 群内命令

### 7.1 基础状态命令

- `/llm status`
  - 查看当前群 LLM 状态
- `/llm current`
  - 查看当前群实际生效的 provider、model、persona、记忆开关、短期会话条数和长期记忆条数
- `/llm health [verbose|detail|full]`
  - 运行 LLM 健康检查（llm_config、provider、database、knowledge_files、persona、tools、mcp、search、sensitive_filter、generation、image_preprocessing、runtime_bindings、auto_memory 共 13 项）
- `/llm reload`
  - 仅管理员。重载已发布 LLM 配置，并探活当前会话实际生效的 provider/model；草稿通过管理后台或 CLI 单独应用
  - reload 后探活会发一条 max_tokens=1 的真实请求，可能产生 provider 计费；api_key 未设置时自动跳过
- `/llm probe`
  - 仅管理员。并发探活所有 provider（每个发一条 max_tokens=1 的请求），报告可达性与延迟
  - 每次调用可能产生 provider 计费；api_key 未设置的 provider 自动跳过

### 7.2 provider / model / persona

- `/llm providers`
- `/llm models [provider]`
- `/llm use <provider> <model>`
- `/llm personas`
- `/llm persona use <id>`

### 7.3 触发方式

- `/llm trigger prefix <value>`
- `/llm trigger prefix_mode on|off`
- `/llm trigger at on|off`

### 7.4 记忆与上下文

- `/llm memory status`
- `/llm memory on`
- `/llm memory off`
- `/llm auto_memory status|on|off|reset`
- `/llm context_limit <n>` — 把本会话上下文改为固定保留最新 n 行（1-1024），持久化，不受 clear_context 影响；默认由会话纪元自动管理
- `/llm context_limit reset` — 恢复纪元自动管理
- `/llm clear_context`
- `/remember <内容>`
- `/memories [关键词]`
- `/forget <关键词>`
- `/forget_all` — 清空本群全部长期记忆
- `/awakening status`
- `/awakening on <rule>`
- `/awakening off <rule>`
- `/awakening boredom on|off`

### 7.5 联网搜索

- `/search <query>`
- `/search news <query>`
- `/search finance <query>`

当前搜索结果由当前搜索后端返回摘要与来源链接，不自动写入长期记忆。

LLM 侧的联网搜索有两条互斥路径：

- **`search_web` 工具**（默认）：客户端执行，走项目内 SearXNG，受 `auto_search` 提示词引导与每轮调用上限约束。
- **provider 内置搜索**：gemini provider 配置 `builtin_search = true` 后启用。请求在 `tools` 中追加独立的 `{"google_search": {}}` 声明（不依赖 `tool_calling_enabled`），检索由 provider 侧 grounding 完成；响应解析 `groundingMetadata` 提取检索词与来源，回复末尾以「标题 — 域名」形式附至多 3 条来源。该 provider 的会话移除 `search_web` 工具并切换提示词引导，检索成本在 provider 侧计费，本地轮次上限不覆盖。模型约束：`google_search` 与 function calling 在同一请求中组合仅 Gemini 3 系列模型支持；2.x 模型上两者并存的请求会被 API 拒绝，需关闭该 provider 的 `builtin_search` 或全局工具调用。

权限规则：

- 查询型命令多数所有人可用
- 变更型命令默认仅管理员 / 群主可用

---

## 8. 部署注意事项

部署完整指南见 [../admin/deployment.md](../admin/deployment.md)。

部署要点：

- 初始化／迁移准备共享 `data/llm_config.db`，Bot 启动加载已发布快照，草稿通过独立任务应用
- `config/generation.toml` 启用 ASR 时需要配置可用的 `[asr]` provider
- `llm_about` 应在运行环境中提供
  - 包括全局 `vocab.yaml` / `identities.yaml` 与可选群级覆盖目录
- `data/` 需要持久化
- 镜像构建时通过 `COPY src/` + `pip install --no-deps .` 安装项目包
- API key 通过环境变量注入
- 使用 `/search` 或 `search_web` 时需提供可访问的 SearXNG；开启 `builtin_search` 的 gemini provider 不依赖 SearXNG；Tavily 等外部搜索能力通过 MCP 工具接入

根目录 `.dockerignore` 已经做了收紧，避免把以下内容送进 Docker build 上下文：

- 本地 `.env`
- `config/*.toml`
- `data/`
- 临时测试与调试产物
- 其他开发工件

---

## 9. 数据作用域与安全处理

群聊和私聊以各自 scope 管理会话状态与记忆。自动记忆从已触发会话抽取，群资料按人格设计和词表命中使用。工具来源按第 6 节的配置与注册职责接入。

历史消息在读取时按当前敏感词表清洗，持久化原文保持不变；过滤结果变化会改变本轮请求字节，从而影响前缀缓存。完整 Loop 的敏感内容与原生回放规则见第 4.2 节。

总结生成按 `routes.daily_summary` 的候选顺序级联，失败时尝试下一模型；普通聊天由当前会话选择的渠道与模型执行。

## 10. 上线前建议检查项

部署检查以实际启用的能力为对象：

- 在管理后台确认默认渠道、模型、人格与 Bot 加载版本，根目录 `.env` 配置这些渠道需要的凭据。
- 用 `/llm current` 与 `/llm memory status` 查看当前会话设置，验证配置前缀和艾特入口，以及 `/llm clear_context`。
- 按部署所需验证记忆开关、工具、识图或语音入口；记忆关闭时聊天按正常对话流程回复。
- 查看配置、凭据和群资料加载日志。`identities.yaml` 缺失或为空时按默认身份解析；需要标准身份时配置资料，并确认“已加载 N 条身份”日志。

## 11. 请求结构排障

排查请求失败、设置生效或跨轮连续性时，先确认任务使用的配置，再核对最终发送载荷。配置保存、应用和 Bot 实际加载状态见 [LLM 配置管理](../admin/llm-configuration.md)；参数继承与整体覆盖见该文档的“模型参数与引用”；请求特征及受管字段见 [请求指纹 Profile](../admin/client-fingerprints.md)。

### 生命周期与生效边界

- **静态前缀与当轮信封**：system 包含人格、风格和工具说明；时间、节日、参与者、记忆和词表命中进入当轮信封。同一配置、人格和工具曝光面下保持前缀稳定。配置、人格、Skill 目录或工具曝光面变化时，按对应变更解释前缀差异。实现与计量见 §5.5 的前缀缓存契约。
- **配置与群覆盖**：LLM 任务持有开始时的配置和资源快照；已经进入生成的任务继续使用捕获的群设置，群覆盖修改后的新请求读取新设置。群覆盖、人格文件与 Skill 内容分别管理，配置修订号只覆盖配置库。检查群设置时同时核对实际请求的渠道、模型和人格。
- **Session、纪元与追踪**：业务 Session 表示持续互动，纪元表示当前上下文窗口；重试和工具续轮沿用所属业务身份。请求追踪按逻辑调用和实际 HTTP 尝试分别建立标识。各 Profile 的字段与生命周期见本页“请求指纹与身份投影”和 Profile 文档。
- **当前工具回合与已关闭历史**：当前回合的原生块、签名、调用 ID 和结果配对须完整。已关闭历史按 owner、完整性及预算决定原生回放或通用投影。Responses 收到上游 HTTP 400 且存在可剥离的历史 reasoning 时重试一次，保留当前回合内容；网络、鉴权、非 400 和协议终态错误使用各自错误处理路径。

### 核对顺序与证据

1. 记录代码 SHA、安装版本、配置修订与 Bot 实际加载状态，注明操作发生在旧任务开始前还是开始后。分别确认全局默认、群覆盖、模型参数和实际选中的人格。
2. 记录协议、Provider、请求模型、`client_fingerprint` 与 `responses_profile`。渠道上的 `extra_body`、Profile 的策略和受管字段按各适配器契约共同形成最终载荷；检查实际请求，确认覆盖字段的位置、类型和效果。
3. 在 Web Admin 的 LLM Trace 中核对该 Loop 的实际 Header、请求正文、HTTP 状态或流终态，区分首轮、工具续轮、重试和备用地址。Trace 采集须在复现前开启；未采集的历史请求无法补回。HTTP Trace 与模型执行记录的原生内容分别服务传输取证和历史回放。
4. 对跨轮问题记录 owner 校验、预算投影和降级原因，同时核对工具声明、结果与签名。切换模型后出现历史投影变化时，将其与当前回合的协议错误分别定位。
5. 对照 Trace 和用量记录核实实际 HTTP 次数。Responses 的历史降级重试会形成失败与重试各自的用量记录；基座内部重试沿用其既有计量口径。配置任务提交成功、Bot 加载成功与模型请求成功分别由对应结果确认。

公开复现使用脱敏样本，保留定位所需的字段结构、顺序、错误和生命周期信息；真实凭据、账号、用户正文及签名或密文仅在受保护的排障环境中核对。真实渠道结论注明具体模型、端点、Profile、代码基线和验证日期。本地替身测试记录具体覆盖的客户端契约。

## 12. 推荐维护方式

按问题归属选择修改入口：

| 问题 | 维护入口 |
|---|---|
| 人格与交流风格 | `config/personas/` 和渠道／模型风格参数 |
| 成员身份解析 | `llm_about/identities.yaml` |
| 昵称与黑话理解 | `llm_about/vocab.yaml` |
| 工具可见范围与执行契约 | `settings.tools` 和工具注册表 |
| 记忆事实提取 | 自动抽取提示与实现 |

数据库设置通过草稿保存和独立应用生效；人格与资料文件按各自重载方式加载。先核对设置、输入和实际请求，再修改相应领域实现。
