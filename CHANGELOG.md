# Changelog

本文件记录主仓库中已提交的可见变更。

## Unreleased

### feat: add /defectify phonetic alias command

Git: `33c9cc4`

- 新增 `/defectify`（别名 `/故障化`）命令，把任意文字、图片或引用消息转写成读音贴近"故障机器人"的五字别名，输出固定格式（五字别名 + 笑点解析）
- `quickquip/llm/defectify.py` 封装约束 prompt 构建逻辑；`LLMService.generate_defectify_reply()` 负责调用，走 `llm_chat` 限流桶
- `LLMRequest` 新增 `thinking_budget` 字段，Gemini provider 对应接入 `thinkingConfig`，供需要控制思考预算的场景使用
- 同步更新群聊与私聊指令文档

### refactor: externalize text reply rules to config/chat_rules.toml

Git: `82d8762`

- 将 `TEXT_REPLY_RULES` 及其专用限流桶从 `quickquip/chat/config.py`（受版本控制）迁移到 `config/chat_rules.toml`（gitignored 部署私有配置）
- `config.py` 保留基础参数（时区、触发词、系统级限流桶），在模块加载时通过 `_load_chat_rules()` 从 TOML 文件追加规则和限流桶
- 新增 `config/chat_rules.toml.example`（入版本控制），包含六条通用示例规则和完整格式注释；`.gitignore` 新增 `config/chat_rules.toml` 排除规则
- 修正 CLAUDE.md / README 对层次结构的描述：明确 `quickquip/adapters/nonebot/` 是 NoneBot2 适配层实现所在，`plugins/` 是 NoneBot2 发现插件的薄层 re-export 入口

### feat: support multi-source tieba pools and source listing

 Git: `e9f54b2`

- 将贴吧搬运从单一固定贴吧升级为多贴吧来源池，支持通过 `TIEBA_FORUM_KEYWORDS` 配置多个来源，并继续兼容旧字段 `TIEBA_FORUM_KEYWORD`
- `/tieba`、`/tieba text`、`/tieba status`、`/tieba refresh` 新增可选贴吧名参数，支持按指定来源抽取、查看状态和定向同步
- 新增 `/tieba source [贴吧名]` 命令，用于查看全部或指定来源的缓存、状态与登录态摘要
- 重构贴吧存储结构，按来源分别维护缓存、同步状态与最近发送记录，同时保留旧版单池缓存文件的加载兼容
- 同步更新 README、群聊命令文档、环境变量示例与贴吧测试覆盖

### feat: add session archive/resume and preset injection for private chat

Git: `48796e9`

- 新增私聊会话存档与恢复机制：`/end_session` 默认自动存档（`--no-save` 跳过），`/start_session --resume [N]` 或 `/resume_session [N]` 恢复指定或最新存档
- 新增 `session_archives` SQLite 表，存储每用户自增编号的存档元数据（人格、附加设定、消息数、时间戳）
- 归档通过改写 `conversation_messages.group_id`（`private:X` → `archive:X:N`）实现零拷贝搬迁
- 新增 `/sessions` 列出存档、`/delete_session <N>` 删除存档
- 新增 `/start_session --preset "..."` 附加设定注入，文本拼接入系统提示词，生命周期为单个会话
- `/llm on --preset/--resume` 与 `/llm off --no-save` 同步支持

### feat: handle recalled and manually deleted messages in LLM context

Git: `48796e9`

- 新增 `GroupRecallNoticeEvent` / `FriendRecallNoticeEvent` 监听，撤回消息自动从 LLM 对话历史和内存缓冲中清除
- `conversation_messages` 表新增 `message_id` 列，入站消息和 bot 回复的平台消息 ID 均被持久化
- LLM 回复路径从 `matcher.finish()` 改为 `matcher.send()` + 回填，捕获 bot 发出消息的 `message_id`
- 新增 `/llm delete_msg` 子命令（admin），支持引用回复或显式消息 ID 手动删除超时无法撤回的消息
- `RecentMessageBuffer` 新增 `message_id` 字段与 `remove_by_message_id()` 方法

### refactor: split personas into per-file directory structure

Git: `48796e9`

- 将 `config/personas.toml` 拆分为 `config/personas/` 目录，每个 `.toml` 文件对应一个人格，支持未来大规模结构化扩充
- 新增 `config/personas/_shared.toml`，提取所有人格共享的通用行为准则和风格规则，加载时自动注入各人格，避免重复维护
- `PersonaConfig` 新增 `extras` 字段，支持在人格文件中自由添加 `source`、`tags` 等自定义键值
- 人格文件采用扁平顶层键格式（`id = "..."`），同时保留 `[[personas]]` 数组格式兼容
- 移除旧的单文件 `personas.toml` sidecar 加载路径
- 新增结构化人格字段：`[identity]`、`[biography]`、`[cognition]`、`[instinct]`、`[voice]`、`[boundaries]`、`[world]` 七个可选 TOML 表，参考 Neural Narratology 的认知分层和 Process Over Label 思路
- `build_system_prompt()` 新增 `_compile_structured_persona()` 编译器，自动将结构化表渲染为自然语言段落并注入 system prompt，与自由文本 `system_prompt` 可共存
- 对 `audrey` 和 `kangel_v` 两个人格进行了结构化试验，其余人格保持传统格式不变
- 新增 `config/personas.example/structured.toml` 结构化格式完整文档和示例
- 新增 `config/personas.example/` 示例目录，替代原 `personas.toml.example`
- 更新 `.gitignore`、README、`llm.toml.example`、CLAUDE.md

### feat: add private session control and stronger identity tracking

Git: `16d66a1`

- 新增私聊会话管理机制，默认不在私聊中自动启用 LLM；通过 `/start_sesssion` 或 `/start_session` 开启当前私聊会话，通过 `/end_session` 结束并清空短期上下文
- 私聊消息入口支持在会话开启后直接处理普通文本、图片与显式回复，并保留部分斜杠命令
- 将私聊短期上下文默认读取上限和保留上限提升到 256 条，适合连续对话
- 修正群聊 LLM 的“认人”链路：短期会话历史改为持久化保存 QQ、当前显示名与标准身份，并在 prompt 中注入认人规则与当前已知参与者摘要，降低多人对话中的张冠李戴
- 补充 README 与测试覆盖，验证多用户轮流发言时的身份区分、私聊会话切换与图片/回复输入解析

### feat: add provider style overrides, forget_all, and per-group context limit

Git: `86311b9`

- 新增 `[[providers]]` 的 `style_overrides` 字段，支持在 `llm.toml` 中为每个 provider 配置针对性的 system prompt 追加段，用于修正特定模型口癖（如 GPT 的句尾反问、DeepSeek 的分点列举等）
- 新增 `/forget_all` 命令（管理员），一次性清空本群全部长期记忆
- 新增 `/llm context_limit <n>` 命令（管理员），支持按群持久化设置 LLM 对话上下文读取上限；`/llm context_limit reset` 重置为全局默认；`/llm reload` 同时清除本群覆盖
- 调整项目内置 `docker/searxng/settings.yml` 的默认引擎集，优先保留在中国大陆网络环境下更易访问的搜索源

### refactor: reorganize runtime into quickquip package

Git: `770858a`

- 新增 `quickquip/` 主包，按 `adapters`、`app`、`llm`、`chat`、`tieba`、`search`、`common` 分层承接运行时实现
- 将群消息管线、NoneBot 适配层、LLM 基础设施、贴吧抓取与共享状态模块迁入新目录
- 将 `plugins/` 收敛为兼容入口层，保留原导入路径与 NoneBot 插件加载面
- 更新 README 项目结构、配置说明与架构设计文档

### feat: add fixed tieba random transport command

Git: `f2b323b`

- 新增固定贴吧随机搬运能力，支持 `/tieba`、`/tieba text`、`/tieba status`、`/tieba refresh` 指令
- 新增贴吧采集与缓存模块，使用 Playwright 合法登录态维护固定贴吧帖子池，并支持缓存避重与质量过滤
- 新增贴吧相关配置项、限流项、规则开关项与独立测试脚本
- 补充 README 中的贴吧功能说明、环境变量示例与测试说明

### feat: add llm tool calling and searxng search backend

Git: `f6cfb6c`

- 新增标准化工具调用链路，补齐工具消息结构、参数校验与 provider 协议映射
- 新增 MCP client 与工具桥接，支持按配置发现和执行外部工具
- 新增身份词表、消息渲染与短期消息检索能力，提升群聊上下文和称呼消歧质量
- 新增可切换联网搜索后端，支持项目内置 SearXNG 与 Tavily 兼容回退
- 新增 SearXNG 容器编排与配置文件，补充联网优先提示词、部署配置与测试覆盖

### feat: add llm, vision, and web search foundation

Git: `c128875`

- 新增 LLM 配置、运行时、持久化与 provider 适配层，支持 OpenAI、Claude、Gemini 三类协议
- 新增群级 LLM 控制命令、手动长期记忆命令与调试命令
- 新增人格注入、词表按需注入、时间元数据注入与严格受限的短期上下文
- 新增图片识别能力与 Tavily 联网搜索命令
- 新增 Docker / 远程部署收尾配置，支持挂载 `config/`、`data/` 与 `dev/llm_about/`
- 新增 LLM 与群内指令相关文档，并补充测试覆盖

### feat: persist stats and rule switch across restarts

Git: `e494665`

- 新增 `plugins/persistence.py`，提供 JSON 原子写入与安全读取
- `GroupStatsTracker` 与 `GroupRuleSwitch` 支持 `save()`/`load()` 序列化
- 启动时从 `data/` 目录加载已有数据，关闭时自动保存
- 每 5 分钟通过 APScheduler 定期自动保存
- `/disable`、`/enable`、`/reset_stats` 命令执行后立即持久化
- `.gitignore` 新增 `data/` 忽略规则

### feat: add random replies, scheduled messages, message stats, and group rule switch

Git: `678b5fe`

- 新增随机回复引擎：规则支持 `reply_templates` 加权随机列表（当前未配置，处于休眠状态）
- 新增定时消息模块 `plugins/scheduler.py`，基于 `nonebot-plugin-apscheduler`（当前未配置，处于休眠状态）
- 新增消息统计模块 `plugins/message_stats.py`，支持 `/stats` 查看群聊统计、`/reset_stats` 重置
- 新增群级规则开关 `plugins/rule_switch.py`，支持 `/disable`、`/enable`、`/rules` 命令（管理员权限）
- `plugins/tz_tracker.py` 集成统计与规则开关，`resolve_reply()` 支持按群跳过被禁用的规则
- `plugins/tz_config.py` 新增 `SCHEDULED_MESSAGES` 空配置
- `requirements.txt` 新增 `nonebot-plugin-apscheduler` 依赖
- 同步更新测试覆盖

## 2026-03-16

### fix: apply code review updates

Git: `bfdfcd0`

- 修正 `plugins/tz_tackcer.py` 文件命名并重命名为 `plugins/tz_tracker.py`
- 新增 `plugins/tz_utils.py`，承载时区计算与地点格式化相关纯函数
- 收窄 `like_reply` 触发范围，并为 `i_do` 增加常见口语过滤
- 为复读检测器与接龙管理器增加按群状态上限，控制长期运行时的内存增长
- 新增 `plugins/__init__.py`
- 同步更新测试、README、`.env.example` 与 `dev/` 忽略规则

### init: scaffold QuickQuip project

Git: `3dc2ab0`

- 初始化 QuickQuip 项目骨架
- 建立 NoneBot2 入口、插件目录与规则驱动回复逻辑
- 添加说明文档、环境示例与基础测试脚本

## 版本号对照表

| 版本 | Git |
|------|-----|
| 0.2.0 | `bfdfcd0` |
| 0.1.0 | `3dc2ab0` |
