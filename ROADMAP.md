# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

> 已完成的版本内容见 [CHANGELOG.md](CHANGELOG.md)。

---

## v1.4+ 待定

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
