# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

> 已完成的版本内容见 [CHANGELOG.md](CHANGELOG.md)。

---

## v1.0.2 — 记忆重做 + Bug 修复

### 自动记忆抽取重做

当前 `quickquip/llm/store.py` 中已有基本的自动记忆抽取实现，但抽取质量过低，实际处于不可用状态。需要对抽取 prompt、触发时机、候选消息筛选（只从 LLM 已触发的对话中抽取）、置信度阈值、冲突合并策略进行全面重做，目标是让抽取结果在群聊中达到"不需要人工 `/remember` 也能自然积累有用记忆"的水平。

### `/profile` 修复

`/profile @某人` 当前被阻塞而实际不可用（疑似消息量或 prompt 构建阶段的 bug）。需要定位根因并修复，确保能稳定产出可用的群友人物志。

### `/music` 合并转发

`/music` 当前先自动生成歌词再谱曲，歌词文本经常刷屏。需要复用每日播报已有的合并转发消息功能，将歌词以合并转发的形式发送（而非直接逐条发送），体验对齐 `/briefing now`。

---

## v1.1 — 多模态理解 + 配置工程化

### 多模态理解升级

当前 LLM 多模态能力仅限于图片理解（单次最多 3 张、5MB 限制）。v1.1 扩展至：
- 语音消息转文字（通过 `/tts` 对应的语音 provider 或独立 ASR API），转录结果注入 LLM 上下文
- 贴吧帖子内容自动摘要（图片 + 文字综合理解，而非当前纯文字截断）
- 考虑接入视频关键帧提取（实验性）

### 配置文件去冗余重构

当前生产环境配置文件（`llm.toml`、`chat_rules.toml`、`generation.toml`）存在大量冗余与重复声明——例如同一 base_url 和 api_key_env 在多个 provider 间反复出现。目标是在保持 TOML 配置兼容性的前提下，引入配置继承、默认值覆盖和模板引用机制，减少复制粘贴维护成本。

### Provider 兼容性回归测试库

`tests/fixtures/stream_chunks.py` 已覆盖 OpenAI/Claude/Gemini 共 3 个 provider 的 8 个场景（text/tool/reasoning/thought_leak）。目标是扩成按 provider + model 分目录的真实 payload 库，每次 `provider.py` 改动跑通全量，把 DeepSeek reasoning_content 这类"上生产才发现"的协议兼容性问题收回到 CI。

---

## v1.2 — 群互动游戏化 + Web Admin 升级

### 互动游戏扩展

`ChainGameManager` 已经是通用引擎，支持捕获组和 OR 候选匹配，`config/chat_rules.toml` 的 `[[chain_games]]` 配置槽位已预留。v1.2 在引擎上配置接歌词、数字炸弹、猜谜等游戏类型，加入 `/game start <类型>` 入口和跨会话持久化的积分/排行榜。当前仅内置 good_girl_chain，示例仍为注释状态。

### 节日自动化

结合 `config/chat_rules.toml` 的定时消息能力与 persona 系统，在指定节日（春节、中秋、元旦等）自动切换 bot 应景言行：节日当天注入对应 system prompt 附录、定时发送 persona 口吻的节日问候。管理员可自定义节日日期和行为。

### 前端美术设计升级

当前 Web Admin 前端处于功能可用但缺少设计感的阶段——纯色面板、无动画过渡、排版密度不均。v1.2 对整体 UI 进行设计升级：统一配色/字体/间距体系、卡片化统计视图、过渡动画、暗色模式支持、移动端响应式适配。

### Web Admin 操作审计

当前所有配置修改（TOML 编辑器、群组管理、记忆编辑、规则开关）均无操作记录。v1.2 新增审计日志模块：记录操作人、时间、操作类型、变更前后内容摘要，Web Admin 新 tab 可浏览和过滤。为后续回滚和排障提供依据。

### 定时任务看板

把 `daily_summary` / `daily_briefing` / 贴吧同步 / `SCHEDULED_MESSAGES` 等定时任务统一到 Web Admin 的一个 tab，列出 cron 下一次执行时间、最近运行结果、失败堆栈。

### MCP server 状态看板

Web Admin 新 tab，列出每个 MCP server 的 ready/disconnected 状态、工具清单、最近调用失败。当前 `/llm mcp` 命令和 `/llm health` 已提供文本查询能力，缺少可视化集中看板。

---

## v1.3+ / 未定版本

### 本地 TTS 服务接入

在 `generation.audio` 下补充对本地 HTTP TTS provider 的支持，让 `/tts` 除远端语音 API 外，也能调用本地语音服务作为 fallback 或独立模型来源。首期只覆盖轻量、短文本、固定音色场景。

### config/llm.toml 热重载

v0.9.0 覆盖了 chat_rules + personas，`/llm reload` 可重读 llm.toml 并重建 MCP 连接，但 provider 客户端不主动重建（惰性创建）。难点在 provider 重建时如何平滑处理 in-flight 请求 + MCP reconnect 顺序 + SQLite store 句柄迁移，需要先设计平滑切换协议再动手。当前重启成本可接受，不排优先级。

### 并发安全加固

已为 3 个模块的关键路径添加锁（`quickquip/llm/service.py:106` MCP 初始化、`quickquip/tieba/service.py:28` 贴吧同步、`quickquip/app/web/auth.py:32` 登录防并发）。ROADMAP 原定目标的 `repeat_detector`、`stats_tracker`、`good_girl_chain` / `chain_game` 四个模块的 `OrderedDict` 状态字典仍无同步原语保护，在 NoneBot 异步并发处理多群消息时存在竞态风险（CPython GIL 在单线程事件循环下提供一定保护，实际触发概率较低）。

### 测试覆盖补充

测试框架现代化已完成 @ v0.8.1（旧的 5 个顶层断言式脚本迁移到 pytest + fixtures + CI reusable workflow）。在此基础上逐步补充并发安全测试、模板渲染负例测试、前端组件测试（TS 严格模式迁移已 @ v1.0.1 完成，引入 Vitest 的前提条件已成熟）和性能基准测试。

### Provider 健康检查与自动故障转移

`quickquip/llm/health.py` 已实现 10 项单次检查 + provider 探活延迟测量。下一步可考虑定时自检 + 多 provider 健康排行 + 故障自动切换，使 `/llm use` 的手动切换升级为半自动降级。

---

## 长期 / 待评估方向

### LLM 主动发言

冷场检测：群内超过 N 小时无消息且处于活跃时段时，bot 主动发一条话题引子（从词云高频词、每日总结或名言录取材）。触发条件和冷却时间需严格配置，避免骚扰。

> 风险较高：误判冷场或话题不合适容易产生骚扰感，短期内不排入版本。

### 群周报 / 月报

从每日总结升级为更丰富的长周期聚合：热词趋势、活跃榜/新人榜、本群大事记。技术可行但群聊消息量大、生成成本高（需处理数万条消息的 LLM 上下文窗口），先留远期评估。

### 平台适配扩展

`adapters/nonebot/` 已将 NoneBot2 依赖隔离，业务逻辑不需改动。接入 Telegram 或 Discord 适配器的成本主要在适配层，适合有跨平台需求时再评估。

### 头像梗图生成

用 QQ 头像合成"摸头"、"拍"等梗图（参考 `nonebot-plugin-petpet` / `meme-generator` 生态）。与项目幽默气质契合，但需引入 Pillow 图像处理依赖，且模板内容高度群体特定，维护成本较高。

---

## 明确不做的事

- 把全天候群消息无差别塞进长期记忆
- 跨群共享人格状态
- 把 `群聊简介和概况.md` 全文直接注入模型
- **链接解析**：各平台 API 变动频繁，维护成本 vs 收益不划算
- **流式输出**：OneBot V11 不支持消息编辑，当前协议下收益不存在；当前实现已在单条消息粒度做到了最大限度
