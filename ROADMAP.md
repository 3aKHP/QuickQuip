# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

> 已完成的版本内容见 [CHANGELOG.md](CHANGELOG.md)。

---

## v1.2 — 群互动游戏化 + Web Admin 升级

### 互动游戏扩展

`ChainGameManager` 已经是通用引擎，支持捕获组和 OR 候选匹配，`config/chat_rules.toml` 的 `[[chain_games]]` 配置槽位已预留。v1.2 在引擎上配置接歌词、数字炸弹、猜谜等游戏类型，加入 `/game start <类型>` 入口和跨会话持久化的积分/排行榜。当前仅内置 good_girl_chain，示例仍为注释状态。

### 节日自动化

结合 `config/chat_rules.toml` 的定时消息能力与 persona 系统，在指定节日（春节、中秋、元旦等）自动切换 bot 应景言行：节日当天注入对应 system prompt 附录、定时发送 persona 口吻的节日问候。管理员可自定义节日日期和行为。

### 前端美术设计升级

v1.2 已完成工程基础：Design Token 体系、响应式布局、暗亮切换、UI 组件标准化。视觉风格未发生本质变化，仍偏开发者工具风格。

### Web Admin 操作审计

当前所有配置修改（TOML 编辑器、群组管理、记忆编辑、规则开关）均无操作记录。v1.2 新增审计日志模块：记录操作人、时间、操作类型、变更前后内容摘要，Web Admin 新 tab 可浏览和过滤。为后续回滚和排障提供依据。

### 定时任务看板

把 `daily_summary` / `daily_briefing` / 贴吧同步 / `SCHEDULED_MESSAGES` 等定时任务统一到 Web Admin 的一个 tab，列出 cron 下一次执行时间、最近运行结果、失败堆栈。

### MCP server 状态看板

Web Admin 新 tab，列出每个 MCP server 的 ready/disconnected 状态、工具清单、最近调用失败。当前 `/llm mcp` 命令和 `/llm health` 已提供文本查询能力，缺少可视化集中看板。

---

## v1.2.x — UI 视觉重设计 + 体验优化

当前版本可用，以下改进在日常使用中逐步推进。

### QQ 原生风格 UI 重设计

**现状问题**：v1.2 完成了 Design Token 化、响应式、暗亮切换等工程基础，但视觉语言仍偏 GitHub 式开发者工具风格（深蓝黑底、单一蓝色强调、纯色平面卡片），与 QQ 群聊 bot 管理后台的产品定位不匹配。

**设计方向**：方案 A（QQ 原生风）+ 完整暗色适配。核心变化：

| 维度 | 现状 | 目标 |
|------|------|------|
| 底色 | 纯黑 `#0a0f14` | 亮色 `#F5F6FA`（QQ 灰白）/ 暗色 `#0D1117` |
| 主色 | GitHub 蓝 `#58a6ff` | QQ 蓝 `#12B7F5` |
| 导航 | 左侧固定栏 220px | 顶部水平标签栏（移动端折叠） |
| 卡片 | 纯色平面 | 白底圆角 16px + 微阴影浮起感 |
| 字体 | system-ui | PingFang SC / Microsoft YaHei 优先 |
| 圆角 | 8-16px | 12-20px（更大更圆润） |
| 开关 | CSS 模拟 | iOS 风格 34×20px 椭圆轨道 |
| 空状态 | 灰色文字 | 大图标 + 友好语气文案 |

完整设计方案见 `dev/plans/v1.2-qq-redesign.md`。

### 每日总结 Markdown 渲染

当前每日总结页纯文本展示。许多 LLM 生成的总结内容本身是 Markdown 格式（标题、列表、加粗），应在前端渲染为富文本，提升可读性。引入一个轻量 Markdown 渲染库（如 `marked` + `DOMPurify`），仅做渲染不做编辑。

---

## v1.3+ / 未定版本

### 本地 TTS 服务接入

远程 TTS 已通过 `config/generation.toml` 的 `[audio]` provider 实现。本条目目标为补充本地 HTTP TTS provider 作为 fallback 或独立模型来源，首期只覆盖轻量、短文本、固定音色场景。

### config/llm.toml 热重载

v0.9.0 覆盖了 chat_rules + personas，`/llm reload` 可重读 llm.toml 并重建 MCP 连接，但 provider 客户端不主动重建（惰性创建）。难点在 provider 重建时如何平滑处理 in-flight 请求 + MCP reconnect 顺序 + SQLite store 句柄迁移，需要先设计平滑切换协议再动手。当前重启成本可接受，不排优先级。

### 并发安全加固

已为 3 个模块的关键路径添加锁（`quickquip/llm/service.py:106` MCP 初始化、`quickquip/tieba/service.py:28` 贴吧同步、`quickquip/app/web/auth.py:32` 登录防并发）。ROADMAP 原定目标的 `repeat_detector`、`stats_tracker`、`good_girl_chain` / `chain_game` 四个模块的 `OrderedDict` 状态字典仍无同步原语保护，在 NoneBot 异步并发处理多群消息时存在竞态风险（CPython GIL 在单线程事件循环下提供一定保护，实际触发概率较低）。

### 测试覆盖补充

测试框架现代化已完成 @ v0.8.1（旧的 5 个顶层断言式脚本迁移到 pytest + fixtures + CI reusable workflow）。在此基础上逐步补充：Provider 流式解析回归测试库（`stream_chunks.py` 已覆盖 3 provider × 8 场景，待扩为按 provider/model 分目录的真实 payload 库）、并发安全测试、模板渲染负例测试、前端组件测试（TS 严格模式迁移已 @ v1.0.1 完成，引入 Vitest 的前提条件已成熟）和性能基准测试。

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
