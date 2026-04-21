# ROADMAP

本文件记录 QuickQuip 的演进方向，按版本锁定近期 scope，中远期按优先级分层。

---

## v0.9.x 增量更新 —— 轻量功能扩展

在 v1.0 主轴（前端 TS 迁移）之前插入一轮按"复用现有 infra、低成本高趣味"筛出的增量功能。每条独立可 ship，不互相阻塞。

### @某人捎话（离线留言）

`/tell @某人 <内容>` 把留言存起来，目标用户下次在群内发言时 bot 自动 @ 他并贴出。复用 message pipeline 的现有触发路径 + SQLite 存储，无 LLM 依赖。`/tells` 查看自己待接收的留言、`/untell` 撤回自己刚发的一条。

### 群语料搜索 + 精选回放

- `/find <关键词>` 全文搜本群历史消息，按相关度/时间排序返回
- `/quote` 引用一条消息收藏到群语录库；`/quote random` 随机翻出一条；可选与 LLM 结合做"以 persona 口吻点评"
- `data/wordcloud_msgs/` 和 `data/daily_msgs/` 已经在收全量消息，直接加索引层即可

### 群友人物卡

`/profile @某人` 让 LLM 合成一段"人物志"：消息统计 + 长期记忆 + 最近发言样本 → 当前群绑定的 persona 口吻的短文。复用 `daily_summary` 的采样与 model_cascade；和 v0.9.0 的 `auto_memory` 形成闭环——自动抽取的记忆在此派上用场。

### 轻娱乐命令族

- `/roll [NdM]` 投骰子（默认 1d6）
- `/vote "议题" 选项A 选项B ...` 发起投票，群友用回复参与
- `/fortune` 今日运势（复用时区基础 + 短 LLM prompt）
- `/choose A B C` 从候选里随机选一个

---

## 下一版本（v1.0）—— 类型安全与 LLM 自主性

### 前端完全迁移到 TypeScript（本版本主轴）

- **API 类型**：用 `openapi-typescript` 从 FastAPI 的 `/openapi.json` 自动生成，消除前后端 shape 漂移
- **视图统一**：把剩余的 Options API 视图（Stats / Rules / Groups / Memory / Summary / Config / Login）顺手迁到 `<script setup>`，避免 TS 下 Options API 的 `this` 类型麻烦
- **构建解耦**：`npm run build` 保持 `vite build`（不带 vue-tsc），`npm run type-check` 独立；CI 和 pre-push hook 跑 type-check，`dev/deploy-v4.ps1` 热路径零增量
- **严格模式**：启用 `strict: true`，一次性清掉所有隐性 any
- 暂不引入 zod 等运行时校验层，待真正遇到后端 shape 不匹配的 bug 再考虑

### 自动联网判定

在独立 `[triggers.auto_search]` 开关下，让模型在需要最新信息时自行触发 `search_web`，不再依赖用户显式 `/search`。联网结果继续与长期记忆严格隔离。

顺手做一次搜索工具语义化重排：现在原生 `search_web` 通过 `SEARCH_BACKEND` 环境变量在 SearXNG / Tavily 间二选一，对 LLM 是不透明的 either/or；同时 Tavily MCP sidecar 又把 `tavily_search` / `tavily_crawl` / `tavily_research` 以细粒度工具暴露出来。本版把原生 `search_web` 硬编码走 SearXNG（免费快速元搜索），删掉 `build_search_client()` 的 backend 分发，让 Tavily 能力完全走 MCP 侧的细分工具。工具名就是语义，LLM 直接按场景选，不再依赖 env 切换。

### LLM 诊断工具化

v0.9.0 阶段排 Gemini thought 泄漏和 schema 兼容性 bug 全靠临时写探针脚本 + 手工捕获请求/响应 JSON。把这类工具沉淀成 web admin 的"诊断"标签页：

- 按 provider/model 触发一次样本请求（系统 prompt + 测试 user prompt 可配置），保存原始 JSON 供对着 `_parse_candidate` / `_assemble_stream_response` 逻辑目视
- `LLM_TRACE_FLAG_FILE` 的 on/off 开关 + 最近 N 条 trace 浏览（复用现有 `_trace_log` 机制）
- 按规则/persona 挑几个"典型触发样本"跑回归，直接在浏览器看命中与否

下次类似 bug 出现时不用再现场拼脚本。

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
