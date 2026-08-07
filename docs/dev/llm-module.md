# QuickQuip LLM 模块说明

## 1. 模块定位

QuickQuip 的 LLM 模块是建立在原有规则机器人之上的**显式触发扩展层**。

它在保留原有规则回复体系的前提下，提供一套受开关、触发条件和上下文边界约束的 LLM 能力：

- 可按群开关
- 可按群切换 provider / model / persona
- 仅在指令或艾特时触发
- 带有限定人格注入
- 带有严格边界的短期上下文与长期记忆

的 LLM 能力。

当前模块还额外覆盖两类能力：

- 显式触发下的图片理解
- 显式触发下的语音消息转写
- 基于项目内搜索后端的联网搜索
- 标准化工具调用（身份查询、记忆查询、联网搜索）

如果后续需要把外部工具后端扩展为 MCP，单独查看 [mcp-integration.md](mcp-integration.md)。当前文档只描述已经落在项目内的 LLM 与工具调用实现。

LLM 运行时在 `LLM_TRACE_FLAG_FILE` 指向的开关文件存在时，把每次 HTTP 尝试写入 `data/llm_trace.db`。请求正文取自实际交给 HTTP 客户端的 UTF-8 JSON 序列化文本；普通响应保留 JSON 解析前的服务端文本；流式响应完整消费 SSE 后，由协议客户端重建 OpenAI Chat Completion、Claude Message 或 Gemini GenerateContent 完整响应对象，同时保留 SSE 传输原文供管理员按需核对。索引、正文和单调递增的状态事件分开存储，Web Admin 先读取轻量调用元数据，管理员选择记录后再加载完整 Header 与正文。`run_tool_call_loop` 为一轮完整交互分配 Agent Loop ID，重试、故障切换和工具结果回送产生的 HTTP 调用按组内序号排列。

---

## 2. 当前代码结构

LLM 相关核心文件如下：

- `src/quickquip/adapters/nonebot/commands.py`
  - 负责 `/llm`、`/search` 等命令注册
- `src/quickquip/adapters/nonebot/group_messages.py`
  - 负责 NoneBot 群消息入口，并把消息交给应用层管线
- `src/quickquip/adapters/nonebot/daily_summary_plugin.py`
  - 负责每日总结的定时任务注册与 `/summary` 命令
- `src/quickquip/llm/service.py`
  - 框架无关的 LLM 服务核心（`LLMService`），NoneBot2 插件从此处 re-export
- `src/quickquip/llm/prompting.py`
  - 负责 system prompt 组装、场景块构建、统一发言者格式渲染与 messages 数组拼装
- `src/quickquip/llm/summarize.py`
  - 每日总结生成逻辑（模型级联、prompt 构建）
- `src/quickquip/llm/briefing.py`
  - 每日播报生成（群人格、模型级联、失败回退；遇到非正常 finish_reason 会继续尝试下一条级联）
- `src/quickquip/llm/defectify.py`
  - `/defectify` 故障机器人转写逻辑
- `src/quickquip/app/message_pipeline.py`
  - 负责群级配置解析、人格注入、身份注入、词表注入、记忆检索、工具调用循环与请求拼装
- `src/quickquip/llm/config.py`
  - 负责读取 `config/llm.toml`
- `src/quickquip/llm/provider/`（包）
  - 负责 OpenAI / Claude / Gemini 三类协议适配，并处理工具调用协议映射；v1.8.9 从单文件 `provider.py` 拆为子包（`base.py` 基类 + `openai.py` / `claude.py` / `gemini.py` 协议实现 + `factory.py` + `trace.py`）
- `src/quickquip/llm/tool_loop.py`
  - 负责统一工具声明、工具调用循环、工具结果和会话消息结构
- `src/quickquip/llm/tool_registry.py`
  - 负责工具白名单注册、参数校验和执行调度
- `src/quickquip/llm/store.py`
  - 负责 SQLite 持久化（会话/记忆/归档/群设置）；v1.8.9 后按域拆为 `store_parts/` 子包的 mixin 组合
- `src/quickquip/llm/vocab.py`
  - 负责从 `llm_about/vocab.yaml` 读取群别名与黑话词表，并按需注入
- `src/quickquip/llm/identity.py`
  - 负责从 `llm_about/identities.yaml` 读取 QQ 号到标准身份的映射
- `src/quickquip/llm/rendering.py`
  - 负责把消息段标准化为给 LLM 使用的纯文本，并解析艾特
- `src/quickquip/llm/message_segments.py`
  - 负责消息段叶子节点渲染、bot 身份集合归一化等共享小逻辑
- `src/quickquip/llm/health.py`
  - LLM 健康检查模块（配置、provider 探活、知识文件、工具、MCP 等 10 项检查）
- `src/quickquip/llm/image_preprocessor.py`
  - 图像预处理抽象接口（`ImagePreprocessor`），预留 OCR / 多模态模型转述的钩子点
- `src/quickquip/adapters/nonebot/voice.py`
  - 负责 OneBot V11 `record` 语音段提取、转码与 ASR 转写注入
- `src/quickquip/generation/asr.py`
  - 负责 ASR provider 调用，当前支持 OpenAI-compatible `/audio/transcriptions`
- `src/quickquip/common/recent_message_buffer.py`
  - 负责"触发前最近群消息"内存缓冲
- `src/quickquip/llm/inputs.py`
  - 负责从消息段中提取文本触发、艾特触发和图片 URL
- `src/quickquip/search/web_search.py`
  - 负责项目内 SearXNG 搜索客户端，供 `/search` 与 `search_web` 工具使用

兼容层说明：

- `src/plugins/` 目录是 NoneBot2 插件入口，由 `bot.py` 通过 `nonebot.load_plugins(*plugins.__path__)` 加载已安装包路径
- 新增逻辑优先放在 `src/quickquip/` 下（包路径 `quickquip.*`），`src/plugins/` 只负责 re-export

持久化文件：

- `data/llm.db`
  - 群级 LLM 设置
  - 短期 LLM 会话记录
  - 长期记忆

配置文件：

- `config/llm.toml`
  - 真实运行配置，本地私有
- `config/llm.toml.example`
  - 原始通用示例，保留为参考模板

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
6. 如果仍未命中，则继续原有规则流：
   - 复读
   - 接龙
   - 彩蛋规则
   - 时区猜测

这意味着：

- 默认配置下 LLM 不会吞掉普通消息
- 规则系统依然是默认主流程
- 显式调用优先级高于唤醒模块，唤醒模块优先级高于普通规则回复

### 3.1 唤醒模块

唤醒模块位于 `src/quickquip/chat/awakening.py`，命令入口位于 `src/quickquip/adapters/nonebot/awakening_plugin.py`，配置文件为 `config/awakening.toml`。

| 规则名 | 触发方式 |
|------|----------|
| `awakening_extend` | 显式触发后，在 `extend_duration` 秒内继续回应同一用户 |
| `awakening_interest` | 消息命中全局或 persona 里的兴趣话题 |
| `awakening_relevance` | 先做词重叠快筛，再用 `quick_judge` 判断是否延续 bot 近期回复 |
| `awakening_qa` | 先做问句快筛，再用 `quick_judge` 判断是否需要回答 |
| `awakening_boredom` | APScheduler 定时检查沉寂群，并向 opt-in 群发送低频冒泡消息 |
| `awakening_fallback` | 普通消息按配置概率兜底触发 |

相关性与答疑判定会使用 `[triggers.quick_judge]` 指定的小模型配置；阈值 `>= 1.0` 时跳过对应 LLM 判定。

`awakening_extend` 只由显式 LLM 入口打开，例如前缀或艾特触发。兴趣、兜底、无聊、相关性和答疑唤醒都是一次性触发，不会继续刷新延长窗口。延长窗口内仍会过滤图片-only、CQ-only、短语气词和过短无实义文本。

唤醒触发会给本轮 LLM 请求附加内部触发说明，例如命中的兴趣话题或兜底触发背景，并要求模型不要暴露唤醒机制。内部说明不会作为群友原文写入 LLM 对话历史。

被动唤醒会携带群内近期历史图片（不再只注入当前触发消息里的图片）。`awakening_extend`、`awakening_interest`、`awakening_relevance`、`awakening_qa` 和 `awakening_boredom` 携带群内近期历史图片；`awakening_fallback` 不注入图片。非视觉模型仍由 LLM 运行时的图片预处理与剥离逻辑统一处理。

无聊唤醒有两层开关：先在 `config/awakening.toml` 中设置沉寂秒数、概率、检查间隔和免打扰时间，再由群管理员执行 `/awakening boredom on`，写入 `data/awakening_boredom_groups.json`。

---

## 4. 上下文边界

### 4.1 临时上下文

为避免长期运行后将 24 小时持续监听数据混入模型，当前实现明确限定：

- 仅在一次 LLM 触发发生时，读取**该群向前最多 20 条消息**
- 这 20 条消息来自 `RecentMessageBuffer`
- 这部分数据**仅保存在内存中**
- 不写入 `data/llm.db`
- 不作为长期记忆保存

这是当前最重要的设计边界之一。

### 4.2 LLM 短期会话

LLM 自身的问答往返会写入 SQLite，用于多轮延续，但有硬限制：

- 单群最多保留 20 条（存储上限，不受配置影响）
- 每次触发时实际读取的条数由以下优先级决定：
  1. 本群通过 `/llm context_limit <n>` 设置的覆盖值（若有）
  2. `llm.toml` 的 `[runtime] history_limit`（全局默认，当前为 10）
  3. 代码存储上限（`MAX_STORED_CONVERSATION_MESSAGES`，当前为 20，为最终截断）
- 群级覆盖写入 `data/llm.db`，重启或 `clear_context` 不会清除
- 执行 `/llm reload` 或 `/llm context_limit reset` 可重置为全局默认
- `clear_context` 只清空已存的会话消息，不改变上限设置

**场景块消息结构**：当前 messages 数组采用"以 bot 回复为边界的场景块"模式：

- 连续的多人发言归入同一 `role="user"` 场景块（bot 回复打断场景）
- 所有发言者使用统一格式：`身份（QQ 号）：内容`
- 场景以 `【上文】`（历史/缓冲）或 `【当前提问】`（最后一轮提问）标记
- 格式化仅在 `build_messages()` 组装时做一次，DB 存储原始文本（`raw_content` 列）
- 引用消息会同时保留“当前提问者”和“引用发送者”，并显式区分机器人自己，避免 A 引用 B 时被误读成 B 在发言
- 合并转发会递归展开多层节点，并保留每层的文字和图片信息，不再只剩一个占位外壳

这样做的好处：
- 模型只看到一种"某人说了某话"的语法，消除历史/缓冲/当前三种格式的解析负担
- `【当前提问】` 明确标记最后一轮——模型无需自己推断该回答谁
- 不存在 DB 存取嵌套包装（旧实现将已格式化的文本再次包入历史消息外层）

### 4.3 图片输入边界

图片理解遵循显式触发和受限被动唤醒规则：

- 必须和 `/ai` 或 `@机器人` 同时出现
- 单次最多处理 5 张当前、引用或转发图片
- 被动唤醒在 `awakening_extend`、`awakening_interest`、`awakening_relevance` 和 `awakening_qa` 中携带群内近期历史图片
- 近期历史图片使用当前请求剩余的图片名额，并优先保留最新图片
- 当前单张图片大小限制为 5MB
- 如果只有图片没有文字提示，会自动补一个默认识图提示
- 视觉主模型直接接收原图；列入 `non_vision_models` 的主模型接收带来源和序号的视觉转述
- 前置视觉识别不可用、返回空内容或任一图片识别失败时，本轮终止并提示用户重试

MCP 工具也可返回经过校验的内联图片。它们不写入对话数据库、普通日志或 MCP 状态；视觉模型在下一轮工具调用消息中接收图片，非视觉模型仅接收经过二次敏感词扫描的转述文本。工具图片的转述不可用或失败时，Agent Loop 继续使用安全工具文本，而不会把原图或编码降级为文本。

### 4.4 语音输入边界

语音理解也遵循显式触发原则：

- 群聊中必须和 `/ai` 或 `@机器人` 同时出现
- 私聊会话开启后，普通语音消息可作为 LLM 输入
- 若 OneBot 协议端的 `record` 段已经包含 `text` / `transcript` / `transcription`，直接使用该文本
- 否则通过 OneBot `get_record` 获取音频文件，并调用 `config/generation.toml` 中 `[asr]` 配置的 provider
- 转写结果会作为 `[语音转文字：...]` 拼入当前用户消息，并进入最近消息、日报/播报采集和词云输入
- ASR 失败时不阻塞原消息处理；没有可用转写时按原有文字/图片输入逻辑继续

### 4.5 长期记忆

长期记忆当前来源非常保守：

- 人工 `/remember`
- 自动记忆抽取开启时，仅从 LLM 已触发会话内提取稳定事实

明确不允许：

- 直接把 24 小时全群监听内容塞进记忆
- 把所有群聊消息无差别持久化给 LLM 模块

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

这部分不靠整份群资料硬灌，而是抽取稳定特征：

- 熟人化
- 深夜活跃
- 游戏 / 创作 / 二次元并重
- 黑话和夸张称呼常见
- 但认真场景要正常说话

### 5.3 词表按需注入

`vocab.yaml` 不会整份注入模型。

当前做法是：

- 只有当 prompt 命中某个别名或黑话
- 才在本轮 system prompt 里追加一小段消歧说明

例如：

- `哈基镜` 通常指镜子
- 注意不要和王者荣耀的镜混淆

这样做的好处：

- 模型更会"听懂"
- 不会变成背词表机器
- 不容易把群资料污染成固定口癖

### 5.4 Provider 风格覆盖

每个 `[[providers]]` 条目支持可选字段 `style_overrides`（多行字符串）。

此字段的内容会在每次调用该 provider 时，追加到 persona 的 `style_prompt` 之后，用于修正特定模型的口癖。

典型用途：

- GPT 系：禁止句尾反问句、禁止 emoji
- DeepSeek：禁止分点列举
- Claude / Gemini：禁止旁白括号、禁止过于简略的回复

修改后需 `/llm reload` 生效。

### 5.5 身份映射注入

`identities.yaml` 负责"这个 QQ 号是谁"，用途和 `vocab.yaml` 不同。

当前做法是：

- **统一发言者格式**：所有进入 LLM 的消息（历史、缓冲、当前提问）均使用同一格式 `身份（QQ 号）：内容`，不再区分三种不同的包装语法
- 提问者进入 LLM 时，优先按 QQ 号解析标准身份
- 最近群聊上下文中的发言者也会按 QQ 号显示标准身份
- 消息中的艾特会优先渲染为 `@标准身份`
- 未登记成员会降级显示为"当前显示名 + QQ 号 + 未登记"
- **身份信息只在 messages 中呈现**：system prompt 不再重复声明"当前提问者是谁"——消除双信息源冲突

这样可以减少群友频繁改名带来的身份漂移，并且让模型在单一信息源中自然识别发言者归属。

---

## 6. 配置说明

### 6.1 `config/llm.toml`

主要区块：

- `[runtime]`
  - `enabled`
  - `memory_enabled`
  - `default_provider`
  - `default_persona`
  - `history_limit`
  - `history_max_messages_per_group`
  - `memory_limit`
  - `memory_max_items_per_group`
  - `max_prompt_chars`
  - `tool_calling_enabled`
  - `tool_max_rounds`
  - `tool_max_calls_per_round`
  - `auto_memory_enabled`
  - `auto_memory_prompt`
  - `auto_memory_max_tokens`
- `[triggers]`
  - `default_prefix`
  - `allow_prefix`
  - `allow_at`
  - `empty_prompt_reply`
  - `[triggers.quick_judge]`：唤醒模块和语境规则使用的快速判定模型
- `[tools]`
  - `enabled`
  - `discovery_mode`
  - `discovery_min_tools`
  - `discovery_search_limit`
  - `discovery_max_loaded_tools`
  - `always_loaded`
- `[[providers]]`
  - `id`
  - `protocol`
  - `base_url`
  - `api_key_env`
  - `default_model`
  - `models`
  - `timeout_seconds`
  - `temperature`
  - `max_output_tokens`
  - `style_overrides`（可选，追加到每次调用的 system prompt 末尾）
  - `auth_method`（可选，`api_key` / `bearer`，默认 `api_key`，控制认证头格式）
  - `prompt_caching`（可选，`claude` 协议专用，启用 Anthropic Prompt Caching）
- `[daily_briefing]`
  - 每日早/午/晚播报全局开关、三段 cron、最小消息数、活跃用户/热词/样本上限、上下文规模、输出长度、模型级联列表
- `[daily_summary]`
  - 每日总结全局开关、生成/发布 cron、最小消息数、字数目标、模型级联列表

Persona 定义已从 `llm.toml` 移出，改为 `config/personas/` 目录下每个 `.toml` 一个人格文件，`_shared.toml` 存储共享行为准则与风格规则。

### 6.2 工具发现

工具调用开启后，QuickQuip 支持本地 `tool_search` 和 `tool_list` 元工具。该机制用于工具数量较多的场景：初始请求只暴露 `always_loaded` 中的常驻工具，模型需要其它能力时先调用 `tool_search`；搜索不到但工具可能存在时，可用 `tool_list` 查看工具组、工具名或按精确名称加载工具。工具循环会把匹配到或精确加载的真实工具加入下一轮 provider 请求。

默认 `discovery_mode = "auto"`，当可延迟工具数超过 `discovery_min_tools` 后启用；工具较少时继续按原方式全量暴露。该设计不依赖 Claude 原生 tool search，OpenAI / Claude / Gemini 协议适配器共用同一套本地发现逻辑。

实现细节见 [tool-discovery.md](tool-discovery.md)，MCP 大工具集场景见 [mcp-integration.md](mcp-integration.md)。

注意：

- 这里的配置是"逻辑配置"
- 真正的硬上限仍然在代码里存在
- 即使把 `history_max_messages_per_group` 写大，实际仍会被代码上限截断

### 6.3 `config/awakening.toml`

唤醒模块配置集中在 `config/awakening.toml`：

- `[awakening.defaults]`
  - `extend_duration`
  - `fallback_probability`
  - `boredom_silence_seconds`
  - `boredom_probability`
  - `boredom_check_interval`
  - `boredom_dnd_start`
  - `boredom_dnd_end`
  - `interest_topics`
  - `relevance_threshold`
  - `qa_threshold`
- `[[awakening.group_overrides]]`
  - `group_id`
  - 任意需要覆盖的默认字段

persona TOML 可通过自由扩展字段追加兴趣话题：

```toml
[awakening]
interest_topics = ["关键词"]
```

### 6.4 `.env`

本地开发与容器运行都需要：

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`

此外容器部署还会用到：

- `QQ_ACCOUNT`
- `ONEBOT_WS_URLS`
- `ONEBOT_ACCESS_TOKEN`
- `DRIVER`
- `HOST`
- `PORT`

### 6.5 `config/generation.toml`

LLM 相关的多模态输入/产出配置在 `generation.toml` 中维护：

- `[image]`：图片生成
- `[audio]`：语音生成（TTS）
- `[asr]`：语音识别，收到 OneBot `record` 语音消息时转写为文字注入 LLM
- `[music]`：歌词与音乐生成

ASR 当前支持 `openai_transcriptions` 协议，即 OpenAI-compatible `POST /audio/transcriptions`。配置示例见 `config/generation.toml.example`。

---

## 7. 群内命令

### 7.1 基础状态命令

- `/llm status`
  - 查看当前群 LLM 状态
- `/llm current`
  - 查看当前群实际生效的 provider、model、persona、记忆开关、短期会话条数和长期记忆条数
- `/llm health [verbose|detail|full]`
  - 运行 LLM 健康检查（配置、provider 探活、知识文件、工具、MCP 等 10 项）
- `/llm reload`
  - 仅管理员。重载 LLM 配置，并探活当前会话实际生效的 provider/model
  - reload 后探活会发一条 max_tokens=1 的真实请求，可能产生 provider 计费；api_key 未设置时自动跳过
- `/llm probe`
  - 仅管理员。并发探活所有 provider（每个发一条 max_tokens=1 的请求），报告可达性与延迟
  - 每次调用都可能产生 provider 计费——按需触发，不静默扣费；api_key 未设置的 provider 自动跳过

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
- `/llm context_limit <n>` — 设置本群上下文读取上限（1-20），持久化，不受 clear_context 影响
- `/llm context_limit reset` — 重置为全局默认
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

权限规则：

- 查询型命令多数所有人可用
- 变更型命令默认仅管理员 / 群主可用

---

## 8. 部署注意事项

部署完整指南见 [../admin/deployment.md](../admin/deployment.md)。

部署要点：

- `config/llm.toml` 应在运行环境中提供
- `config/generation.toml` 启用 ASR 时需要配置可用的 `[asr]` provider
- `llm_about` 应在运行环境中提供
  - 包括全局 `vocab.yaml` / `identities.yaml` 与可选群级覆盖目录
- `data/` 需要持久化
- 镜像构建时通过 `COPY src/` + `pip install --no-deps .` 安装项目包
- API key 通过环境变量注入
- 使用 `/search` 或 `search_web` 时需提供可访问的 SearXNG；Tavily 等外部搜索能力通过 MCP 工具接入

根目录 `.dockerignore` 已经做了收紧，避免把以下内容送进 Docker build 上下文：

- 本地 `.env`
- `config/*.toml`
- `data/`
- 临时测试与调试产物
- 其他开发工件

---

## 9. 现阶段已知边界

当前模块定位为刻意收边的群聊 LLM，边界如下：

- 不自动扫全群消息做长期记忆
- 不自动做复杂摘要归档
- 不做跨群共享人格状态
- 不把 `群聊简介和概况.md` 全文直接注入模型
- 不默认把所有外部工具都改成 MCP

注：每日总结（`daily_summary`）模块已实现模型级联策略，生成失败时自动降级到下一个 provider/model，顺序在 `[daily_summary] model_cascade` 中配置。这是总结生成专用的级联，不影响普通 LLM 对话的 provider 选择。

---

## 10. 上线前建议检查项

如果准备正式上线，建议确认：

- `config/llm.toml` 中默认 provider、model、persona 正确
- `.env` 中 Gemini / OpenAI / Claude key 正确
- `/llm current` 输出正常
- `/llm memory status` 输出正常
- `/llm clear_context` 可用
- `@机器人` 和 `/ai` 触发都可用
- 关闭记忆注入后，模型仍能正常回复
- Docker 容器内日志没有出现：
  - 配置文件缺失
  - API key 缺失
  - `vocab.yaml` 缺失
  - `identities.yaml` 缺失

---

## 11. 推荐维护方式

后续如果继续演进，建议遵守下面的顺序：

1. 先改 `config/llm.toml` 和 persona 文案
2. 再改 `identities.yaml`
3. 再改 `vocab.yaml`
4. 最后才考虑扩大自动记忆能力

原因很简单：

- 人格问题，优先改 prompt
- 认人问题，优先改身份词表
- 称呼理解问题，再改话题词表
- 工具边界问题，优先改 `[tools]` 配置和注册表
- 记忆问题，最后改自动抽取逻辑

不要反过来。
