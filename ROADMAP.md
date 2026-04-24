# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

---

## 下一版本（v1.0.1）—— TypeScript 全面迁移

### 前端 TypeScript 化（本版本主轴）

- **API 类型**：用 `openapi-typescript` 从 FastAPI 的 `/openapi.json` 自动生成，消除前后端 shape 漂移
- **构建解耦**：`npm run build` 保持 `vite build`（不带 vue-tsc），`npm run type-check` 独立；CI 和 pre-push hook 跑 type-check，`dev/deploy-v4.ps1` 热路径零增量
- **严格模式**：启用 `strict: true`，一次性清掉所有隐性 any
- 暂不引入 zod 等运行时校验层，待真正遇到后端 shape 不匹配的 bug 再考虑

---

## v1.0.0（已完成）—— 类型安全与 LLM 自主性（第一阶段）

### 前端 Options API 迁移

- 10 组件 + 7 视图全部迁移到 `<script setup>`，为 TS 化铺平
- 零 Options API 残留

### 自动联网判定

- 新增 `[triggers.auto_search]` 配置开关（`enabled` + `search_max_calls_per_round`）
- 开启后 LLM 自行判断联网时机，不再依赖用户显式 `/search`

### 搜索工具语义化重排

- `search_web` 硬编码走 SearXNG，删除 `build_search_client()` 后端分发和 `SEARCH_BACKEND` 环境变量切换
- Tavily 能力完全走 MCP 侧 `tavily_search` / `tavily_crawl` / `tavily_research`

### LLM 诊断工具化

- Web admin 新增"诊断"标签页：样本请求 + 原始 JSON trace、`LLM_TRACE_FLAG_FILE` 开关与 trace 浏览、文本规则回归测试

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

> 已在 v0.9.x 增量更新里排期（与 `/find` 一起），该条保留作为交叉引用。

### Provider 兼容性回归测试库

把当前散落在 `tests/fixtures/stream_chunks.py` 的 SSE 样本扩成一套按 provider + model 分目录的真实 payload 库，每次 `quickquip/llm/provider.py` 改动必须跑通。目标是把 Gemini thought 泄漏、tool schema 字段兼容性这类"上生产才发现"的问题收回到 CI。驱动力不足前留这里，等下次类似 bug 触发再排期。

### 本地 TTS 服务接入

在 `generation.audio` 下补充对本地 HTTP TTS provider 的支持，让 `/tts` 除远端语音 API 外，也能调用本地语音服务作为 fallback 或独立模型来源。首期只覆盖轻量、短文本、固定音色场景。

### config/llm.toml 热重载

v0.9.0 覆盖了 chat_rules + personas，`llm.toml` 仍然要求重启 bot。难点在 provider 重建时如何平滑处理 in-flight 请求 + MCP reconnect 顺序 + SQLite store 句柄迁移，需要先设计平滑切换协议再动手。当前重启成本可接受，不排优先级。

### 互动游戏扩展

`ChainGameManager` 已经是通用引擎，支持捕获组和 OR 候选匹配。可以通过 `chat_rules.toml` 的 `[[chain_games]]` 配置更多游戏类型（接歌词、接成语、数字接龙），并考虑加入跨会话持久化的积分/排行榜。

### 并发安全加固

为 `repeat_detector`、`stats_tracker`、`good_girl_chain` 等单例的关键路径添加 `asyncio.Lock`，消除高并发场景下的竞态风险。详见 `dev/docs/OPTIMIZATION_BACKLOG.md`。

### 测试覆盖补充

测试框架现代化已完成 @ v0.8.1（旧的 5 个顶层断言式脚本迁移到 pytest + fixtures + CI reusable workflow）。在此基础上逐步补充并发安全测试、模板渲染负例测试、前端组件测试（TS 迁移完成后引入 Vitest）和性能基准测试。

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
