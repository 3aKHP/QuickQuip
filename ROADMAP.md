# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

---

## 下一版本（v0.9.0）—— 让修改立即生效

**主题**：消除"保存后需重启 bot"债务，让 web admin 真正闭环。

### 配置热重载（chat_rules + personas 两档）

目前编辑 `config/chat_rules.toml` 和 `config/personas/*.toml` 都需要重启 bot 才能生效。本档先覆盖这两个改动最频繁的文件：观察 mtime 或显式 `/reload` 命令触发重新 parse，替换模块级缓存。`config/llm.toml` 因为涉及 provider/MCP 初始化副作用，继续要求重启，放到后续版本单独规划。

### 保守版自动记忆抽取

仅从已经触发的 LLM 对话结束后跑一次"抽取 pass"：用短 prompt 问"这轮对话里有没有值得记住的事实"，命中后写入长期记忆。独立开关、独立 prompt、与主对话隔离。不扫全天候群消息，不做无差别持久化。

### 限流窗口按规则自定义

`rate_limit_rules` 增加 `window = N` 字段，向后兼容（未指定时沿用全局默认 60s）。`SlidingWindowRateLimiter` 本身已经接受 `window_seconds`，只需把配置层打通。

---

## v0.10.0 —— 类型安全与 LLM 自主性

### 前端完全迁移到 TypeScript（本版本主轴）

- **API 类型**：用 `openapi-typescript` 从 FastAPI 的 `/openapi.json` 自动生成，消除前后端 shape 漂移
- **视图统一**：把剩余的 Options API 视图（Stats / Rules / Groups / Memory / Summary / Config / Login）顺手迁到 `<script setup>`，避免 TS 下 Options API 的 `this` 类型麻烦
- **构建解耦**：`npm run build` 保持 `vite build`（不带 vue-tsc），`npm run type-check` 独立；CI 和 pre-push hook 跑 type-check，`dev/deploy-v4.ps1` 热路径零增量
- **严格模式**：启用 `strict: true`，一次性清掉所有隐性 any
- 暂不引入 zod 等运行时校验层，待真正遇到后端 shape 不匹配的 bug 再考虑

### 自动联网判定

在独立 `[triggers.auto_search]` 开关下，让模型在需要最新信息时自行触发 `search_web`，不再依赖用户显式 `/search`。联网结果继续与长期记忆严格隔离。

---

## v0.11+ / 未定版本

### MCP 工具接口专项升级

摆脱当前 `transport = "docker"` + `mount_docker_socket = true` 的 DooD 方案。候选方向：优先使用原生 stdio（对只发 docker 镜像的上游 server 用轻量封装代替），评估 HTTP/SSE transport 的可用性，必要时自建常驻 RPC 代理。目标是权限收敛 + 配置简化 + 启停更清晰。

### 定时任务看板

把 `SCHEDULED_MESSAGES` / `daily_summary` / `daily_briefing` / 贴吧同步等定时任务统一到 web admin 的一个 tab，列出 cron 下一次执行时间、最近运行结果、失败堆栈。

### MCP server 状态看板

Web admin 新 tab，列出每个 MCP server 的 ready/disconnected 状态、工具清单、最近调用失败。与 MCP 接口升级互补。

### 群内名言录

引用一条消息后发送 `/quote` 收藏，存入本群名言库；`/quote random` 随机翻出一条。纯规则驱动，可选与 LLM 结合做"以 persona 口吻点评"。

### 互动游戏扩展

`ChainGameManager` 已经是通用引擎，支持捕获组和 OR 候选匹配。可以通过 `chat_rules.toml` 的 `[[chain_games]]` 配置更多游戏类型（接歌词、接成语、数字接龙），并考虑加入跨会话持久化的积分/排行榜。

### 并发安全加固

为 `repeat_detector`、`stats_tracker`、`good_girl_chain` 等单例的关键路径添加 `asyncio.Lock`，消除高并发场景下的竞态风险。详见 `dev/docs/OPTIMIZATION_BACKLOG.md`。

### 测试覆盖补充

逐步补充并发安全测试、模板渲染负例测试、前端组件测试（TS 迁移完成后引入 Vitest）和性能基准测试。

---

## 长期 / 待评估方向

### LLM 主动发言

冷场检测：群内超过 N 小时无消息且处于活跃时段时，bot 主动发一条话题引子（从词云高频词、每日总结或名言录取材）。触发条件和冷却时间需严格配置，避免骚扰。

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
