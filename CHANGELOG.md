# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [1.3.0] - 2026-05-06

### 新增

- **金币经济系统**：SQLite 持久化金币账户（`data/game_economy.db`），每日签到连击累加、好感度成长、金币排行；`deduct_gold` / `transfer_gold` 原子事务保护，贯穿全部对战游戏
- **21 点（Blackjack）**：`/game start 21点 <赌注>` 发起，bot 坐庄硬 17 停牌，支持 Blackjack 判定和平局退款，最多 8 人同局
- **俄罗斯轮盘**：`/game start 俄罗斯轮盘 <赌注>` 发起，装弹/接受对决/轮流开枪，7 槽弹仓随机排列，存活概率实时更新
- **牛牛大作战**：持久化 RPG 系统（`data/niuniu.db`），注册牛牛随机初始长度、打胶加权事件引擎（5 种事件/6 档评论）、击剑胜率公式、长度/深度排行、CD 系统、操作记录追溯
- **游戏配置文件化**：`config/games.toml` 统一管理全部游戏参数（签到倍率、赌注上下限、CD 时长、衰减率等），`GameConfig` dataclass 层次注入，缺失文件回退默认值
- **`quickquip/games/` 独立子目录**：`registry.py` / `scores.py` / `economy.py` / `config.py` + 4 个游戏实现，与 `llm/`、`generation/`、`tieba/` 同级
- **Web Admin 游戏管理**：金币面板（群金币汇总/排行/账户查询/手动调金审计记录）、牛牛面板（排行/用户详情/长度手动修正）、配置编辑器支持 `games.toml`
- **游戏文档三层体系**：`docs/user/group-games.md`（群友向玩法指南）+ `docs/admin/game-config.md`（部署向配置手册）+ `docs/dev/game-framework.md`（开发向扩展指南）

### 变更

- `BaseGame.start()` 签名新增可选 `start_arg` 参数，`GameRegistry.start_game()` 透传，`/game start` 命令解析附加参数
- `GameScores` / `GameRegistry` / `NumberBombGame` 从 `quickquip/chat/` 迁移至 `quickquip/games/`
- Web Admin 配置白名单新增 `games.toml`，`UiIcon` 组件注册 `Coins` / `Swords` 图标，标签页增至 19 个

## [1.2.1] - 2026-05-05

### 新增

- 前端工程重构：Design Token 体系（暗色/亮色双主题）、响应式布局（768px 断点，侧栏/汉堡菜单自适应）、15 个视图统一卡片化、UI 组件标准化（UiCard/UiButton/UiToggle 等 variant/size 属性）、视图过渡动画
- Web Admin 操作审计：SQLite 审计日志（`data/audit.db`），覆盖规则开关、群组管理、记忆编辑、人格修改、TOML 配置、群 LLM 设置、资料文件共 7 类变更操作；前端审计页支持按操作类型/目标类型/时间范围过滤和分页浏览
- 定时任务看板：聚合 daily_summary、daily_briefing、scheduled_messages 及节日检查的 cron job 状态，展示触发器、下次执行时间、最近执行结果和错误信息，30s 自动刷新
- MCP server 状态看板：展示所有 MCP server 的连接状态（已连接/连接失败/已禁用）、传输方式、工具数量和工具清单；bot 进程通过共享卷 `data/mcp_status.json` 向 web-admin 透传真实连接状态
- MCP server 级工具过滤：`MCPServerConfig` 新增 `include_tools` / `exclude_tools` 字段，支持按白名单/黑名单在注册前过滤工具；兼容旧 `allowed_tools` 字段
- 节日自动化：内置元旦、春节、元宵、端午、中秋、除夕 6 个节日检测（公历+农历，使用 `lunardate` 库），每日凌晨 1 点 cron 触发；命中节日时自动向 LLM 系统提示注入节日人设附录，并向已启用日报的群组发送节日问候
- 数字炸弹游戏：`/game start 数字炸弹` 开始，群友猜 1-1000 间秘密数字，bot 回复"大了/小了"缩小范围，猜中 @ 获胜者；60s 超时自动揭晓，`/game score` 查看排行榜；`BaseGame` + `GameRegistry` 扩展接口预留给后续游戏类型
- 每日总结 Markdown 渲染：详情页使用 `marked` + `DOMPurify` 安全渲染 Markdown 内容（标题、列表、加粗、代码块、引用、链接）

### 变更

- 前端视觉语言完善（Design Token 化、组件标准化），为后续 QQ 原生风格重设计铺平工程基础
- 文档全面脱敏：CHANGELOG、部署指南、架构文档、MCP 集成文档中的私有路径/域名替换为通用描述；ROADMAP 移除已完成 v1.1 条目并标注 v1.2.0 版本号失误

### 修复

- 数字炸弹积分记录从 `user_id`（消息发送者）修正为 `at_user_id`（游戏判定获胜者），确保后续游戏类型的积分正确性
- 定时任务看板中 scheduled_message 任务在 bot 不可用时不误报为"成功"
- 节日 cron 任务补充 `record_job_result` 执行追踪，与其他定时任务在状态看板中一致
- MCP 看板及新标签页缺失图标（Server/Clock/ShieldCheck/ChevronLeft/ChevronRight）已注册
- 未使用 import 清理（`game_registry.py` 的 `field`、`game_scores.py` 的 `Optional`），CI ruff 报错消除

## [1.2.0] - 2026-05-03

### 新增

- LLM 工具发现：新增本地 `tool_search` / `tool_list` 元工具与 `[tools] discovery_mode` 配置。工具数量较多时初始请求只暴露常驻工具，其余内置/MCP 工具按能力描述搜索或按精确名称加载，并在下一轮动态可用，降低大批 MCP 工具对提示词和工具 schema 的占用

> 此版本本应为 v1.1.1（v1.1 的增量补丁），因工程失误标记为 v1.2.0。ROADMAP 原定 v1.2 范围的 6 项功能不受影响，将在后续版本中交付。

## [1.1.0] - 2026-05-01

### 新增

- 自动记忆抽取保守重做：攒批触发（每 10 轮 LLM 对话才触发一次抽取）、多轮对话上下文（最近 10 条消息作为判定背景）、固定置信度 0.5（不再让 LLM 自评）；新增质量门槛——用户消息 ≥ 8 字且助手回复 ≥ 20 字才触发；去重算法改为双向 min 分母 + 0.7 阈值；prompt 强调「宁可不记，不可记错」
- 自动记忆认人：抽取 prompt 现接收 `canonical_name`（来自 identities.yaml 解析），记忆内容强制以群友名开头而非模糊指代
- 自动记忆去重：改为仅查 `scope="user"` 库（不再与全群 group-scope 记忆混排），避免目标用户记忆被其他人高置信度记忆挤出 `LIMIT 50` 候选集
- 图像预处理抽象接口：`ImagePreprocessor` ABC + `NoOpImagePreprocessor` 默认实现，预留 OCR / 多模态模型转述文本的钩子点
- `LLMSceneMessage` 场景块中间表示：支持将 bot 回复间的连续人类发言归入统一场景
- Web 管理后台新增"资料"页：支持在线编辑 `llm_about/vocab.yaml`、`llm_about/identities.yaml` 及群级覆盖文件，并可从示例模板创建群级资料目录
- ASR 语音理解：支持将 OneBot V11 `record` 语音消息转写为文字并注入 LLM 上下文；优先使用协议端自带转写文本，缺失时通过 `get_record` 获取音频并调用 `[asr]` provider；首期支持 OpenAI-compatible `/audio/transcriptions`

### 变更

- LLM 提示词组装重构：从三种不同格式（历史 / 近期缓冲 / 当前消息各用一套语法）统一为单一发言者格式 `身份（QQ 号）：内容`；历史消息按 bot 回复边界分组为 `【上文】` 场景块，当前提问标记为 `【当前提问】`；格式化仅在 `build_messages()` 组装时做一次，不再存入 DB
- LLM 会话落库：新增 `raw_content` 列存储原始轮次文本（含引用/转发上下文），解决多轮追问时历史丢失引用语境的问题；auto-memory 上下文读取优先 `raw_content`
- System prompt 瘦身：移除与 messages 重复的 `当前提问者昵称/身份` 段，替换为消息格式说明；参与者列表简化为纯名称
- `search_memories` 新增 `scope` 参数：支持按 `scope="user"` 限定查询范围
- `/profile @某人` 支持 `short` / `middle` / `long` / `full` 四档人物志长度；默认 `middle` 为约 1600 字长文，`long` 扩大上下文和输出规模，`full` 在约 400k 输入 token 上限内尽量纳入该群已落盘的完整发言记录，并通过合并转发发送完整正文
- `config/generation.toml` 新增 `[asr]` 配置区块，和图片生成、语音生成、音乐生成统一收口；HTTPS 调用优先使用 certifi CA，降低 Windows 环境下证书链缺失导致的请求失败概率

### 修复

- LLM 上下文交替：修正 `build_messages()` 中 pending context flush 与当前场景分别生成连续 `role="user"` 的问题——现合并到同一 user message 用 `【上文】`/`【当前提问】` 在文本内区分，确保三家 provider 的 user/assistant 交替约束
- LLM 图片输入：非视觉模型请求图片时先经图片预处理转述，再移除传给 provider 的图片 URL；配置热重载会同步重建图片预处理器，健康检查展示运行时绑定状态
- `/quote random` 短时间连续触发时优先返回最近未输出过的语录，减少连续重复抽中同一条的情况
- `/profile @某人` 数据收集失败：修正记忆查询调用仍使用旧版位置参数的问题，避免固定落入“收集用户数据时出错”
- `/profile @某人` 无响应：`on_command` 处理后 at 段可能丢失类型信息，现增加 CQ 码文本正则回退解析（`[CQ:at,qq=XXXX]`）
- `/profile` 解除对 `daily_summary.model_cascade` 的依赖：现直接使用当前群的 provider/model，不再因级联配置空缺或引用不存在的 provider 而阻塞
- `/profile` 消息窗口从 30 天缩至 7 天，数据收集增加 try/except 保护
- `/music` 歌词改走合并转发消息（与每日播报相同模式），长歌词按段落边界分块，群聊不再刷屏；私聊回退直发

## [1.0.1] - 2026-04-27

### 新增

- TypeScript 严格模式迁移：前端 33 个文件（API 层、composables、router、views、config）全量转为 `.ts` + `<script setup lang="ts">`，启用 `strict: true`，`vue-tsc --noEmit` 零错误通过；API 类型通过 `openapi-typescript` 从 FastAPI `/openapi.json` 自动生成 `types.d.ts`（2308 行）；构建解耦——`npm run build` 不再捆绑类型检查，`npm run type-check` 独立运行，CI 与 pre-push hook 跑 type-check
- Windows 懒人包 WebView 窗口化：新增 `webview_launcher.py`（基于 pywebview 的原生 WebView2 窗口），`启动.bat` 优先使用 WebView，pywebview 未安装时回落浏览器；pywebview 在 release workflow 中单独安装，不进入 `requirements.txt`
- LLM 健康检查模块（`quickquip/llm/health.py`）：覆盖 LLM 配置、provider/model、persona、数据库、资料库文件、工具、MCP、搜索、生成配置及运行时绑定共 10 个检查项；`verbose` 模式可对当前 provider 发送极短探测请求测量延迟；通过 `/llm health [verbose|detail|full]` 命令或 `get_health_status` LLM 工具调用

### 修复

- DeepSeek thinking mode `reasoning_content` 未传回导致 HTTP 400：`OpenAIProviderClient` 的响应解析（`_parse_response` 非流式 + `_assemble_stream_response` 流式）现提取 `reasoning_content`，存入 `LLMResponse.thinking_blocks`；`_serialize_message` 序列化 assistant 消息时将其输出回请求体，满足 DeepSeek API 对 reasoning 内容 round-trip 的要求
- 私有部署编排中的 `llm_about` volume 挂载目标未随 v1.0.0 的资料目录迁移更新，导致健康检查报告 vocab.yaml / identities.yaml 缺失。现 quickquip 和 web-admin 两服务的挂载目标统一修正为 `/app/llm_about`
- 前端诊断页：样本探测补 `stream: false` 避免流式响应阻塞结果展示；回归测试补空输入保护；API 层增强错误详情格式化（FastAPI 422 数组错误逐条展开）

### 变更

- `frontend/package.json` 移除 `openapi-typescript` devDependency：该工具仅在 API schema 变更时用于重新生成 `types.d.ts`，不参与日常构建链。此项移除消除了 TS6 与 openapi-typescript（要求 TS5）的 peer dependency 冲突，相关 CI / 发布脚本中的 `--legacy-peer-deps` 回退一并摘除
- `.dockerignore`：收紧私有部署材料的构建上下文排除规则
- 全仓文档重构：README 从 644 行精简至 191 行（功能详解与命令表迁入 docs/）；docs/ 建立按读者角色分区的文档体系（`user/` 群友、`admin/` 部署管理、`dev` 开发者），新增 `index.md` 总导航与 8 份专题文档；ROADMAP 移除已完成版本条目并重组未来版本优先级；MCP 集成文档更新为通用 sidecar 部署模式

## [1.0.0] - 2026-04-24

### 新增

- 搜索工具语义化重排：`search_web` 硬编码走 SearXNG，删除 `build_search_client()` 后端分发和 `SEARCH_BACKEND` 环境变量切换；Tavily 能力完全走 MCP 侧 `tavily_search` / `tavily_crawl` / `tavily_research` 细粒度工具
- 自动联网判定：新增 `[triggers.auto_search]` 配置开关（`enabled` + `search_max_calls_per_round`），开启后 LLM 在需要最新信息时主动调用 `search_web`，不再依赖用户显式 `/search`
- LLM 诊断工具：Web admin 新增"诊断"标签页，支持按 provider/model 发送样本请求并查看原始 JSON trace、`LLM_TRACE_FLAG_FILE` 开关与 trace 浏览、文本规则回归测试
- Windows 懒人包：GitHub Actions 自动构建嵌入式 Python 3.11 + 前端 bundle + 项目源码的 zip 包，附 `启动.bat` 一键启动脚本，首次运行自动拷贝 `.example` 模板
- GHCR Docker 镜像：多阶段生产镜像 `ghcr.io/3aKHP/quickquip`，附 `docker-compose.example.yml` 完整部署模板（NapCat + SearXNG + Bot + Web Admin + 可选 MCP sidecar）
- 分群词表与身份覆盖：支持 `llm_about/{群号}/vocab.yaml` 和 `identities.yaml`，与全局文件自动合并，分群条目覆盖全局同名项

### 变更

- 前端全部迁移到 `<script setup>` 语法（10 组件 + 7 视图），不再使用 Options API，为后续 TypeScript 迁移铺平
- `llm_about` 资料目录迁移到仓库根目录，`vocab.yaml.example` 和 `identities.yaml.example` 作为公开模板；`_example/` 子目录提供分群模板

## [0.9.2] - 2026-04-23

### 新增

- `/draw` 配置重构：`[image_generation]` 改为 `[[image_generation.providers]]` + 嵌套 `[[image_generation.providers.models]]`，与 LLM provider 结构对齐；每个 provider 独立配置 `protocol / base_url / api_key_env / timeout_seconds`，同一 provider 下可挂多个模型；`/draw <模型id> <描述>` 按名选模型，省略则用 `default_model`；无参调用时列出全部可用模型
- `/draw` 图生图 / 图文生图：引用消息中的文字前缀合并入 prompt，引用图片 + 自带图片均采集为输入图片；支持纯文字 / 纯图片 / 图文混合 / 合并转发消息的全组合引用场景；`openai_images` 有输入图片时自动切换 `POST /images/edits`（multipart/form-data），`gemini_imagen` 以 `inlineData` 注入
- `/draw` 新增 `--size 宽x高` 和 `--quality 值` 参数，覆盖模型默认值（通过 `dataclasses.replace` 不修改原配置）
- `/draw` 限流桶：在 `[rate_limit_rules]` 中加入 `image_gen` 桶（`scope = "global"`，每分钟全局最多 10 次、单用户最多 2 次）
- `/draw` 提示词预审查：`prompt_blocklist` 大小写不敏感子串匹配，命中则在调 API 前拒绝
- `protocol = "minimax_images"`：支持 MiniMax Image-01（`POST /image_generation`），`size` 字段填宽高比（如 `"1:1"` / `"16:9"`）；有输入图片时以 `subject_reference` 角色参考模式传入；响应取 `data.image_base64[0]`；错误通过 `base_resp.status_code` 检测
- Claude extended thinking：解析 `thinking` / `redacted_thinking` 内容块并存入 `LLMResponse.thinking_blocks`；工具调用轮次回填 assistant 消息时将 thinking blocks 前置，满足 Claude API 对扩展思考场景的 messages 结构要求；支持流式响应中 `thinking_delta` / `signature_delta` 累积

### 修复

- 火山方舟 Seedream `/draw` 404：`volcengine` 的图片端点路径与 chat 端点不同，改为独立 `[[image_generation.providers]]` 配置后路径正确
- `BaseProviderClient._post_json_with_fallback` 遗漏 `OSError` 和 `JSONDecodeError` 处理，与 `image_gen._http_post` 对齐补全

## [0.9.1] - 2026-04-22

### 新增

- 群友人物卡：`/profile @某人` 收集消息统计、长期记忆、近期发言样本，通过 `daily_summary` 的 model_cascade 调用 LLM，以当前群绑定的 persona 口吻合成一段人物志
- 群语料搜索：`/find <关键词>` 全文搜索本群最近 30 天历史消息（复用 `DailyMessageCollector` JSONL 数据），返回最新 5 条匹配结果
- 群语录库：`/quote`（引用消息）收藏到本群语录库（SQLite）；`/quote random` 随机翻出一条；`/quote`（无引用时）等同于 `/quote random`
- 轻娱乐命令族：`/roll [NdM]`（投骰子，默认 1d6，支持最多 10 颗/1000 面）、`/choose A B C`（随机选一个，支持引号含空格选项）、`/fortune`（今日运势，按 user_id + 日期哈希确定，同一天同一用户结果固定）、`/vote "议题" 选项A 选项B`（发起投票面板，最多 9 个选项，带数字 emoji 格式化）
- 离线留言（@某人捎话）：`/tell @某人 <内容>` 将消息存储，目标用户下次在群内发言时 bot 自动 @ 并送达；`/tells` 查看待接收留言；`/untell` 撤回自己最新的未投递留言；无 LLM 依赖，SQLite 持久化（`data/offline_messages.db`）
- 图片生成：新增 `/draw <描述>` 指令，调用图片生成 API 并将结果以 base64 图片发回群聊；通过 `[image_generation]` 配置块启用，复用已有 provider 的鉴权与 base_url
  - `protocol = "openai_images"`：兼容 OpenAI DALL-E / GPT Image 系列及火山方舟 Seedream 系列（ARK API 完全兼容此格式）
  - `protocol = "gemini_imagen"`：Gemini 原生图片生成格式（`generateContent` 端点，`inlineData` 响应解析）
- `ProviderConfig` 新增四个字段，提升 provider 调用层的可配置性：
  - `aliases`：模型别名映射（`{ 短名 = "完整模型ID" }`），`/llm use` 时自动解析，`/llm models` 展示时在方括号内列出；配置加载时校验所有 alias target 必须在 `models` 列表中
  - `user_agent`：注入自定义 `User-Agent` 请求头，适用于校验客户端标识的上游服务；三种协议（OpenAI / Claude / Gemini）均支持
  - `extra_body`：注入到每次请求体的额外字段（TOML inline table），可传递上游厂商私有参数；在工具调用字段之前合并，允许覆盖非核心字段
  - `fallback_urls`：备用 base URL 列表；主地址返回 5xx 或网络错误时自动切换到下一个（路径和 query string 保持不变），所有协议均支持
- `/llm use <provider>` 现可省略模型名，省略时自动使用该 provider 的 `default_model`；切换成功后若输入的是别名，回复中注明解析结果（`← 别名`）
- `/llm providers` 在每个 provider 旁附注别名数和备用地址数

### 变更

- `/llm use` 参数由必须 `<provider> <model>` 改为 `<provider> [model]`（model 可选）

### 修复

- 引用合并转发消息 + @bot 时 bot 看不见被引用内容：`extract_forward_content` 之前只扫当前消息的 segments 找 `forward`，reply 里的 forward segment 被忽略；同时 `render_message_for_llm` 把 `forward` 当未知类型静默丢弃，`quoted_text` 也为空。两处叠加导致"引用一条合并转发消息并 @bot 问问题"时 LLM 既收不到转发内容也收不到引用内容。现 `extract_forward_content` 新增 `reply` 参数，当前消息无 forward 时回退扫 `reply.message`；`render_message_for_llm` 在 `include_image_placeholder=True`（reply 渲染路径）下为 `forward` segment 补 `[合并转发消息]` 占位，避免拉取失败时 LLM 仍然完全不知情

## [0.9.0] - 2026-04-21

### 修复

- Gemini 思维链泄漏到正文：Gemini 流式/非流式响应可能包含 `thought: true` 的原生 thought summary part，与真实回复 part 交替出现；`_parse_candidate` / `_assemble_stream_response` 未过滤，导致内心独白被拼到 `response.text` 开头和真实回复一起发出。现两处入口均跳过 `thought=True` 的 part
- Gemini 工具调用被 400 "Unknown name" 拒绝：Gemini `function_declarations.parameters` 仅接受其 Schema proto 定义的字段集合，部分 MCP server 的 `input_schema` 会吐出超出这个子集的 JSON Schema 关键字（如 `$schema` / `$defs` / `exclusiveMaximum` / `exclusiveMinimum` 等）。新增 `sanitize_gemini_schema()` 按白名单递归裁剪参数 schema，只保留 `type` / `format` / `title` / `description` / `nullable` / `enum` / `default` / `items` / `properties` / `required` / `minItems` / `maxItems` / `minLength` / `maxLength` / `minProperties` / `maxProperties` / `pattern` / `example` / `anyOf` / `propertyOrdering` / `minimum` / `maximum`；`properties` 下的属性名作为用户定义键保持原样透传

### 新增

- 保守版自动记忆抽取：LLM 对话结束后后台异步跑一次独立的短 prompt 判定，提取"关于发言者的稳定长期事实"写入记忆库（source="auto"）。与主对话完全隔离：走 `quick_judge` 单路径（非流式、无工具、`temperature=0.0`），不注入历史记忆、不进入对话历史；异常静默吞掉，只记 `logger.exception`，不影响用户回复。全局开关 `[runtime] auto_memory_enabled`（默认 false）+ `auto_memory_prompt` / `auto_memory_max_tokens`；按群三态覆盖通过 `/llm auto_memory on|off|reset|status` 或 web admin 的"群 LLM"标签页。需要群级 `memory_enabled=true` 且 `auto_memory_enabled=true` 才会触发，关了记忆注入自然也不做抽取
- personas 热重载：新增 `/reload_personas` 管理员命令，调用 `LLMService.reload_personas()` 仅重新读取 `[[personas]]` 段 + `config/personas/*.toml` 目录并就地替换 `self.config.personas`，不触发 provider / MCP / runtime 的任何重载。读取失败或 personas 为空时保留旧状态；若当前 `default_persona` 在新集合中不存在，自动回落到第一个可用人格。`quickquip/llm/config.py` 抽出 `load_personas_only(config_path)` 公开函数，`load_llm_config()` 复用同一实现避免两条代码路径漂移
- chat_rules 热重载：新增 `/reload_rules` 管理员命令，就地重载 `config/chat_rules.toml` 并重建所有派生缓存（`TEXT_REPLY_RULES` / `CONTEXT_REPLY_RULES` / `CHAIN_GAME_CONFIGS` / `RATE_LIMIT_RULES` 四个模块级容器、`_COMPILED_PATTERNS` / `_COMPILED_CONTEXT_PATTERNS` / `_COMPILED_CONTEXT_CONDITIONS` 预编译正则、`SWITCHABLE_RULES` 规则名集合、`ChainGameManager.defs` 与 `KeyedRateLimiter.rule_configs`）；TOML 解析失败时原状态不受影响；接龙中 session 在 defs 替换时自动清空，避免旧 def 的接龙状态被按新 def 错判。`quickquip/app/message_pipeline.py` 导出 `reload_chat_rules_pipeline()` 作为统一入口
- 限流窗口按规则自定义：`[rate_limit_rules]` 每条桶新增可选 `window = N` 字段，不写沿用全局默认 60s；`KeyedRateLimiter` 内部按 `(rule_name, bucket_key)` 存 `SlidingWindowRateLimiter`，每个按规则自身的 `window_seconds` 计窗；`KeyedRateLimiter.reload_rules()` 对 window 或 limits 变化的规则清空其 bucket，完全一致的规则保留状态。`/api/rate-limit` 的 snapshot 返回结构不变（`window_seconds` 字段改为按规则）

### 变更

- `quickquip/llm/store.py` `group_settings` 表新增 `auto_memory_enabled INTEGER` 列（`_ensure_schema` 里的 ALTER 迁移保持旧 db 兼容），`GroupSettingsOverride` / `ResolvedGroupSettings` / `/api/group-settings` PUT body 同步新增字段
- `quickquip/llm/service.py` `quick_judge()` 修正 `self.config.default_provider` 错用（该字段实际在 `runtime` 下），现改为 `self.config.runtime.default_provider`。此前路径因 AttributeError 立即走到 `next(iter(providers))` 兜底，行为没有用户可见差异但代码意图错误
- `quickquip/common/json_utils.py` 新增 `extract_json_object()`，把原 `context_rules._extract_json` 抽为通用工具；`service._extract_auto_memory()` 与 `context_rules` 共享
- 新增仓根 `.gitattributes`：所有跟踪的文本文件强制 `text=auto eol=lf`，`*.ps1` / `*.bat` / `*.cmd` 显式保留 `eol=crlf`，常见图片 / 字体 / sqlite 资源标 `binary`。本次提交时仓内现有文本本就是 LF，没有触发实际 renormalize；规则就位后未来跨平台 commit 不会再写出 CRLF

## [0.8.1] - 2026-04-21

### 测试与 CI

- 测试套件整体重构：旧的 5 个顶层 `test_*.py`（共 2840 行断言式脚本，import 即执行、无 fixture、任一失败屏蔽后续）全部删除，改为 `tests/` 目录下的 pytest 套件（`unit/` + `integration/` + `fixtures/`），共计 193 个可独立运行的用例。新增 `requirements-dev.txt` 固定 `pytest` / `pytest-asyncio` / `pytest-cov` / `pytest-xdist` / `ruff` 版本；`pyproject.toml` 追加 `[tool.pytest.ini_options]`（markers: `playwright`/`slow`/`network`，默认跳过 playwright 与 network）与 `[tool.coverage.*]` 段
- 共享 fixtures 模块化：`tests/fixtures/` 下按职责拆分为 `onebot.py`（OneBot V11 dummy 消息族）、`provider_stubs.py`（4 个 LLM stub client，改为每实例独立状态）、`provider_fakes.py`（3 个 provider fake 子类保留真实序列化）、`mcp_io.py`（stdio 异步 I/O dummy）、`stream_chunks.py`（三家 provider SSE chunk 样本）、`configs.py`（`MIN_LLM_CONFIG_TOML` + `llm_service` pytest fixture）、`chain_game.py`（`make_chain_def` 工厂）
- CI 工作流替换为可复用模板：新 `.github/workflows/_tests.yml` 作为 `workflow_call` 模板，`ci.yml` 与 `release.yml` 双双改为瘦调用；新增 `concurrency` + `timeout-minutes` + `frontend` job（`npm ci && npm run build`）+ coverage.xml artifact 上传；原内嵌 TOML 校验 heredoc 和 CHANGELOG 提取脚本抽离到 `scripts/ci/validate_toml_examples.py` 与 `scripts/ci/extract_release_notes.py`，可本地复跑

### 修复

- `quickquip/chat/context_rules.py` 的 4 个 E402 lint 错误：`_extract_json` 函数定义将 `datetime` / `typing` / `quickquip.chat.config` / `quickquip.chat.text_rules` 的导入推后到了函数体之后，现将其归位到文件顶端

### 变更

- MCP 客户端重构：协议层与传输层解耦。新增 `Transport` 抽象基类 + `JsonRpcSession`（JSON-RPC id/pending-future/消息分发）+ 薄 `MCPClient`（initialize/tools 协议）三层；`StdioTransport` 合并原 stdio + docker 分支，`StreamableHttpTransport` 接管原 `HttpMCPClient`，新增 `SseTransport` 实现经典 MCP HTTP+SSE（GET 事件流 + `endpoint` 事件告知的 POST 地址）。`MCPClientManager` 对外 API 保持不变
- 彻底移除 DooD 支持：`MCPServerConfig.mount_docker_socket` 字段删除，不再自动挂载 `/var/run/docker.sock`；私有部署编排同步摘掉 Docker socket 挂载；`transport = "docker"` 保留但只用于裸机环境执行 `docker run -i --rm ...`。容器化部署请改用 `http` 或 `sse` transport
- `config/llm.toml` / `config/llm.toml.example` 默认 MCP 清单清理：5 个只有 `docker` transport 的社区 server（github/tavily/arxiv/fetch/openweather）全部注释保留（裸机部署可手工启用），默认启用集只剩 `prts_wiki`（`transport = "http"`）
- `config/llm.toml.example` 更新 transport 文档段，列出 4 种传输方式；`README.md` 同步更新 MCP 配置说明

### 新增

- MCP 新增 `sse` transport（经典 MCP HTTP+SSE）：客户端 GET `url` 打开 SSE 长连接，服务端发送 `event: endpoint` 告知 POST 地址；后续请求 POST 到该地址，响应通过 SSE 流以 `event: message` 返回。支持 `headers` 字段传递鉴权头
- MCP sidecar POC：参考 `docker/mcp-example.Dockerfile.example` 用 `mcp-proxy` 包一层把 stdio-only 的上游社区镜像暴露为 SSE 服务，私有部署编排新增对应 sidecar service 跑在同一网络上，bot 通过 `transport = "sse"` 直连。此模式替代原先依赖 DooD 的 `transport = "docker"` 方案；新增 MCP 的模板化流程：写 Dockerfile、加 compose service、追加 `[[mcp.servers]]` 三步即可
- `docker/mcp-example.Dockerfile.example` ENTRYPOINT 模板要求追加 `--pass-environment` 标志。mcp-proxy 默认 `--no-pass-environment`，spawned 子进程拿不到容器 env，表现为 MCP server 侧报"<KEY> environment variable is required"，即便容器里已正确注入。模板注释补充了踩坑说明，下游复用时别漏
- 私有部署脚本在远端对环境变量文件跑 `sed -i 's/\r$//'` 规范化行尾。Windows 编辑器常留下 CRLF，导致 Docker Compose 注入容器的 env 值尾部带 `\r`，表现为 API key 校验失败等奇怪错误；后续清仓排进 ROADMAP
- `MCPClientManager.sync()` 新增启动重试：每个 server 初始化失败时最多重试 3 次、间隔 2s。用于兜底 compose 冷启动时 sidecar 慢 1~3s 导致的"首次握手时 uvicorn 尚未 listening"竞态（典型现象：Python + uv venv 型 MCP 比 Alpine + Node 型慢几百 ms~几秒）

### 修复

- Web 管理后台贴吧标签页图片无法显示：`tiebapic.baidu.com` 对带 `Origin` 头的跨域请求返回 403，新增后端图片代理端点 `GET /ops/api/tieba/imgproxy?url=...`（仅允许 `*.baidu.com` 域名），前端封面图和详情图均改走代理

### 新增

- Web 管理后台贴吧标签页支持手动触发爬取：`GET /ops/api/tieba/sync?forum=...` 以 SSE 流式返回每条帖子的抓取进度；`crawler.collect_threads` 新增 `on_progress` 回调参数，`service.sync_now` 透传；前端页面头部新增"立即同步全部"按钮，每个贴吧条目右侧新增单吧同步按钮，同步过程实时展示日志面板，完成后自动刷新贴吧列表

- LLM 对话支持合并转发消息：用户在群聊/私聊中转发合并消息时，bot 自动通过 `get_forward_msg` API 拉取内容，将每条子消息格式化为编号列表（含发言者名/QQ 号）后注入 LLM 上下文；图片 URL 同步合并到多模态输入；`ExtractedLLMInput` 新增 `forward_text` / `forward_image_urls` 字段，`build_user_message_content` / `generate_reply` / `generate_private_reply` 全链路透传

## [0.8.0] - 2026-04-17

### 新增

- `rate_limit_rules` 支持 `scope = "group" | "global"` 字段：`scope="group"`（默认）按群独立分桶，群 A 的触发不消耗群 B 的预算；`scope="global"` 所有群 + 私聊合并到同一个桶，用于保护跨会话共享资源（LLM、搜索、爬虫）。built-in 规则中 `llm_chat`/`web_search`/`tieba_random_post`/`tavily_search` 标为 `global`，其余 6 条保持 `group`；`chat_rules.toml.example` 的 `[rate_limit_rules]` 文档段补充 `scope` 字段说明
- Web 管理后台新增"词云"标签页：后端 `GET /api/wordcloud/groups` 扫描 `data/wordcloud_msgs/` 列出有消息积累的群（显示天数和磁盘占用），`GET /api/wordcloud/render?group=...&window=today|week|month|year` 复用 `build_word_frequencies` + `render_wordcloud_bytes`，两个 CPU 密集步骤各自走 `asyncio.to_thread` 不阻塞事件循环，成功时返回 base64 PNG + Top50 词频 + 消息/词数统计；低于 50 词阈值返回 422，字体文件缺失返回 500 携带明确提示；前端提供群选择 + 时间窗 4 键切换 + "生成"按钮，左侧显示词云图（自带下载链接），右侧同步展示 Top 词频排行
- Web 管理后台新增"贴吧"标签页：只读视图 `tieba_service.store`，左侧列出所有已缓存贴吧与其同步状态（正常/同步中/错误/需登录），右侧分页展示帖子列表（标题 + 作者 + 封面 + 正文预览 + 图数 + 已发送过标记），支持按标题/正文/作者关键词过滤；点击任意帖子弹出 detail overlay 显示完整正文、所有配图、贴吧原链接；后端 `tieba.py` 路由对 `forum` 和 `tid` 做正则白名单校验（`[^\s/\\:]{1,32}` / `\d{1,20}`）防止路径穿越
- Web 管理后台新增"限流"标签页：`SlidingWindowRateLimiter` / `KeyedRateLimiter` 新增 `snapshot()` 方法在快照前就地 prune 掉过期时间戳并释放空 deque，`GET /api/rate-limit` 把每条限流规则的全局 used/limit、单用户 used/limit、窗口秒数、Top20 活跃用户按 user_id 一次返回；前端每条规则一张卡片，显示全局进度条 + 用户排行 mini bar，支持 5s 自动刷新（手动勾选），进程重启时所有窗口归零（符合内存实现的真实语义）
- Web 管理后台新增"群 LLM"标签页：按群覆盖 `llm.db` → `group_settings` 表中的 9 个字段（enabled / memory_enabled / provider_id / model / persona_id / trigger_prefix / allow_prefix / allow_at / history_limit）；三态语义支持"跟随默认/开/关"，每个文本/数值字段可点"跟随"按钮回落到 llm.toml 里的默认值；右侧表单仅在字段相对加载快照有变化时才 `PUT`（服务端使用 `model_dump(exclude_unset=True)` 仅落表被改的列），避免无谓 row 膨胀；后端路由 `group_settings.py` 额外暴露 `GET /api/group-settings/options`，把 `llm.toml` 里的 provider/persona 清单与当前 runtime/trigger 默认值一次返回给前端做下拉与 placeholder
- Web 管理后台新增"对话"标签页：浏览 `data/llm.db` 的 `conversation_messages` 表，左侧按 `group_id` 列出所有会话（群聊/私聊/归档自动分类），右侧以聊天流式展示消息（role 彩色标记、发送者名、时间、内容全文）；支持关键词过滤与游标翻页（`before_id`），可按单条删除用于回溯和脏数据清理；后端 `conversations.py` 用严格正则校验三种合法的 `group_id` 形态（`\d{5,12}` / `private:\d{5,15}` / `archive:\d{5,15}:\d{1,6}`）防止路径穿越
- "配置"标签页改造为多文件编辑器：新增 `chat_rules.toml` 的在线编辑入口，保留原 `llm.toml`；后端 `GET/PUT /api/config/llm` 泛化为 `GET/PUT /api/config/{key}`，新增 `GET /api/config` 列表端点；白名单机制防止路径穿越；页头补充"保存后需重启 bot 才会生效"提示；切换文件时若有未保存修改会弹确认
- Web 管理后台新增"人格"标签页：列出 `config/personas/*.toml`、读取/编辑单个 TOML、新建与删除；`_shared.toml` 标记为共享且不可删除；后端 `personas.py` 路由按照 `[A-Za-z0-9_][A-Za-z0-9_-]{0,63}` 强校验文件名防止路径穿越，写入前做 `tomllib.loads` 校验，并以 `filelock` 串行化并发写入
- Web 管理后台引入 `vue-router` 4（hash 模式）：`config/nav.js` 扩展 `path` 字段作为路由表唯一来源，`AppNav` 改用 `<router-link>`，支持 URL 深链接（`/ops/#/stats` 等）与浏览器前进后退；抽出 `composables/useAuth.js` 承载全局登录态、`composables/useAsyncData.js` 供后续新视图复用 loading/error/refresh 模板。hash 模式选择原因：nginx 端 `auth_basic` 外门和 FastAPI session cookie 内门的既有分层无需改动，任何深链刷新都只命中 `/ops/` 静态根，不需要额外的 SPA fallback 配置
- 语境感知回复子系统 `context_rules`：在普通 `[[rules]]` 与时区回复之间新增一层判定，`patterns` 首筛命中后再做上下文校验，只有语境合适时才触发；支持两种 `type`：`regex_context`（在最近 N 条消息中搜索 `context_conditions` 正则）和 `llm_context`（用超短 prompt 调用 LLM 返回 `{"trigger": true/false}` JSON）；LLM 判定带 `asyncio.wait_for` 超时（默认 2s）和按 `(rule_name, group_id, text)` 的 TTL 结果缓存（默认 60s，可通过 `llm_cache_ttl` 覆盖），降低常见触发词的调用成本
- `LLMService.quick_judge`：用于 `context_rules` 的极速判定入口，不走群配置 / 不注入记忆 / 不启用工具，单条 system+user prompt，`temperature=0.0`、`stream_enabled=False`
- 《新三国》梗默认入库（`chat_rules.toml.example`）：18 条直接 rules + 7 条 context_rules，共用 `new_three_kingdoms` 限流桶；`chat_rules.toml.example` 新增 `[[context_rules]]` 完整文档段与两条注释化示例

### 变更

- `KeyedRateLimiter` 内部存储从 `{rule_name: Limiter}` 升级为 `{(rule_name, bucket_key): Limiter}`，`allow()` 增加 `group_id` 关键字参数；`scope="group"` 的规则按群创建独立桶，`scope="global"` 的规则和无 `group_id` 的私聊调用都归到空桶；`snapshot()` 响应结构改为按规则列举多个桶，命中时为空的桶会在 snapshot 时 GC 掉；`/api/rate-limit` 响应与"限流"前端页随之更新，显示规则 scope 标签 + 每桶独立进度条
- `group_messages.py` 文本/语境规则的 `rate_limiter.allow()` 调用补传 `group_id=group_id`，其余 5 处调用（`llm_chat`/`web_search`/`tieba_random_post` 都是 global scope，或调用点无 group 上下文）保持原样
- `resolve_reply` / `build_reply` 改为 `async`，新增 `recent_context` 参数透传最近消息列表给 `context_rules`；调用方（NoneBot2 群消息适配层）同步更新

### 修复

- `chat_rules.toml.example` 中 `ntk_longerduo` 的 priority 从 83 抬到 95，避免 `扎聋我自己的耳朵` / `议论孔明先生` 被 `ntk_long` 单字正则（priority 92）提前截胡
- `rule_switch.SWITCHABLE_RULES` 改为在模块加载时动态并入 `TEXT_REPLY_RULES` / `CONTEXT_REPLY_RULES` / `CHAIN_GAME_CONFIGS` 里的规则名，修复 Web 管理后台规则开关页缺失 `kpl_*` 和新三国 `ntk_*` 系列规则开关的问题；系统/模块规则与历史规则名继续保留以兼容已有 `rule_switch.json`

## [0.7.0] - 2026-04-16

### 新增

- Web 管理前台设计升级：引入基于 CSS 变量的统一设计系统（`variables.css`/`transitions.css`），新增 `UiButton`、`UiCard`、`UiTag`、`UiPageHeader`、`UiIcon`、`UiLoading`、`UiEmpty`、`UiToggle` 等通用组件；导航改为配置驱动并预留学生成路由表的扩展接口；按业务域拆分 `api.js` 为模块化 API 层；统计页 Top 列表改为进度条可视化，登录页、规则页、记忆页等全部视图统一升级圆角卡片、阴影层次与响应式布局，并补齐移动端适配
- 每日早中晚播报功能 `daily_briefing`：支持按群开启早报（08:00）、午报（12:00）、晚报（22:00），复用当前群绑定的 LLM provider/model/persona，结合消息数、活跃用户、热词和代表性消息样本生成短播报；消息量不足时自动退回模板播报；`/briefing on|off|status|now [morning|noon|evening]` 命令；`[daily_briefing]` 配置区块支持三段 cron、上下文规模、输出长度和模型级联
- Web 管理后台 `web_api.py` + `quickquip/app/web/`：基于 FastAPI 的独立管理 API 服务，提供消息统计、群级规则开关、每日总结/播报群组管理三个端点；前端为 Vue 3 SPA（`frontend/`），构建产物 serve 在 `/ops/` 路径；通过 `WEB_ADMIN_HOST`/`WEB_ADMIN_PORT` 环境变量控制监听地址（默认 `127.0.0.1:5104`）；新增 `GET /ops/api/groups/known` 返回已知群列表，`GET/PUT /ops/api/config/llm` 支持在线读写 `config/llm.toml`；前端新增配置编辑器标签页（原始文本编辑，保存前校验 TOML 语法），规则开关改为 pill toggle，操作反馈改为 toast，群组页支持从已知群下拉选择
- Web 管理后台鉴权升级：FastAPI 层新增应用内 session 登录（`/ops/api/auth/login|me|logout`），所有管理接口统一要求 `HttpOnly` session cookie；`WEB_ADMIN_PASSWORD` / `WEB_ADMIN_SESSION_TTL_HOURS` / `WEB_ADMIN_COOKIE_SECURE` 等环境变量可直接纳入项目配置与部署流程
- MCP docker transport 支持 `pull_policy` 配置项（`always`/`missing`/`never`，默认 `missing`），设为 `always` 可在每次重载时自动拉取最新镜像，解决镜像更新后工具列表不刷新的问题
- 新增 `/llm mcp reload` 命令（仅管理员）：强制 pull 所有 docker transport MCP 服务器的最新镜像并重连，完成后输出最新状态；非 docker transport 服务器仅重连不 pull
- 词云功能 `/wordcloud`（别名 `/词云`）：管理员可生成本群消息词频可视化图片，支持 `today`/`week`/`month`/`year` 四个时间窗口；独立消息收集层（`data/wordcloud_msgs/`），对所有群始终开启；图片以 base64 内联方式发送；依赖 jieba 分词 + wordcloud + Pillow，需在 `data/fonts/` 放置 NotoSansSC-Regular.ttf 字体文件
- 人格配置支持可选 `scope` 字段，`/llm personas` 会按群聊或私聊上下文只展示当前场景可用的人格
- `bot.py` 新增 loguru 文件日志输出，每日轮转写入 `data/logs/quickquip_YYYY-MM-DD.log`，保留 14 天；通过 nginx `/bot-logs/archive/` 路径（`auth_basic` 鉴权）可直接浏览下载
- 新增 SSE 实时日志服务：监听 `127.0.0.1:5103`，通过 nginx `/bot-logs` 路径（`auth_basic` 鉴权）在浏览器实时查看容器日志，支持关键词过滤和自动滚动
- `docker-compose.yml` 新增 `name: quickquip` 固定 compose project name，避免重复部署时因 project name 不一致导致 napcat 容器名冲突
- `LLM_TRACE_FLAG_FILE` 环境变量：指定一个 flag 文件路径，文件存在时 `provider.py` 以 INFO 级别输出完整的 LLM 请求/响应 JSON；配合 `log_server.py` 的 `/bot-logs/llm-trace` SSE 端点实现浏览器实时查看

### 修复

- Web 管理后台安全加固（审计报告 H2-H6、M2-M4、M7-M10、L1-L2、L5、L9）：
  - 登录接口新增内存速率限制（每 IP 5 次失败/60s，超限封禁 300s）
  - `X-Forwarded-For` 仅在直连 IP 为 loopback/私有地址时才信任，防止 IP 伪造
  - CSRF 检查：Origin 和 Referer 均缺失时拒绝请求（返回 403），而非放行
  - `llm.toml` 写入改用 `filelock` 防止并发覆盖，并用 `try/finally` 确保临时文件不残留
  - `groups.py`、`rules.py` 统一 `group_id` 验证规则（5-12 位数字正则）
  - `memory.py`、`summaries.py` 数据库路径改为基于 `PROJECT_ROOT` 的绝对路径
  - Vite 开发代理路径从 `/api` 修正为 `/ops/api`，与部署路径一致
  - `api.js` 先处理 401 再解析 JSON，避免解析失败吞掉 HTTP 错误信息；401 触发后不再重复 toast
  - `MemoryView.vue`：confidence 空字符串传 `null` 而非 `""`，修复 422 校验错误；错误状态与"暂无条目"不再同时显示
  - `MemoryView.vue`、`SummaryView.vue`：群组列表加载失败时显示错误信息而非静默
  - `RulesView.vue`：checkbox 改用 `@click.prevent` 阻止浏览器默认切换，视觉状态完全由 Vue 控制
  - `App.vue`：`beforeUnmount` 时清理全局 `unauthorizedHandler`，避免 HMR 场景下旧闭包残留
  - 新增 `filelock>=3.12.0` 依赖
- LLM 引用消息认人：`build_user_message_content` 在有引用消息时，在 user message 里同时标注"当前提问者"和"引用发送者"，避免 LLM 跨 system/user 两层拼凑身份时张冠李戴
- LLM 上下文结构：`normalize_history` 统一历史消息格式，无 `user_id` 的旧消息不再裸露内容，改为标注"发言者：未知"；`build_messages` 将 recent_messages 块从序列头部移至紧贴当前提问之前，修正时间顺序（历史对话 → 触发前快照 → 当前提问）
- 每日总结发送：`_send_long_message` 始终通过 `send_group_forward_msg` 发合并转发卡片，不再对单段内容走 `send_group_msg` 直发（规避 NapCat ~667 汉字截断限制）
- 每日总结生成：模型级联现检查 `finish_reason`；Gemini 因 `SAFETY`/`RECITATION`/`MAX_TOKENS` 等非正常原因返回残缺内容时，自动降级至下一个模型，不再将截断文本写入数据库
- Tieba 爬虫 `load_thread_data`：改用 `page.request.get` 直接调 `pb/page_pc` API（共享浏览器上下文 cookie），不再依赖拦截页面 XHR，避免 Playwright 驱动加载时接口不触发的问题；细化登录态错误识别（`error_code` 2/4 或错误信息含"登录"）

## [0.6.0] - 2026-04-09

### 新增

- 每日群聊总结模块 `daily_summary`：凌晨 06:00 自动收集前一日聊天记录（06:00–06:00 窗口）并调用 LLM 生成约 2000 字小作文，中午 12:00 定时发布；以 persona 口吻撰写，注入群成员昵称对照表
- 模型级联策略：生成失败时自动降级到下一个 provider/model，顺序可在 `[daily_summary] model_cascade` 中配置，支持 `"@default"` 占位符指向当前群绑定的默认模型
- `/summary on|off|status|now` 命令：群管理员可开关本群每日总结；`now` 子命令立即生成前一天 06:00 至当前时刻的总结（每分钟限一次）
- `DailyMessageCollector`：逐行写入 `data/daily_msgs/{group_id}/{date}.jsonl`，生成后自动删除原始文件
- `DailySummaryStore`：独立 SQLite 文件 `data/daily_summaries.db` 持久化已生成的摘要
- `DailySummaryEnabledGroups`：群级功能开关（默认关闭，需主动开启），持久化至 `data/daily_summary_groups.json`
- `rule_switch` 新增 `"daily_summary"` 可切换规则，与 `/enable` / `/disable` 命令体系保持一致

## [0.5.0] - 2026-04-09

### 新增

- 通用接龙引擎 `ChainGameManager`，支持可配置步骤、`$N`/`$N[idx]` 捕获组占位符及 `|` OR 候选匹配；`GoodGirlChainManager` 委托其实现，保留全部公开 API
- `config/chat_rules.toml` 新增 `[[chain_games]]` 配置区块，支持自定义接龙游戏
- `/defectify`（别名 `/故障化`）命令，将文字/图片/引用消息转写为五字故障机器人风格别名，含笑点解析
- 私聊会话管理：`/start_session` 开启、`/end_session` 结束并自动存档（`--no-save` 跳过）、`/resume_session [N]` 恢复历史存档
- 私聊会话存档浏览 `/sessions`、删除 `/delete_session <N>` 及 `--preset "..."` 附加设定注入
- 撤回消息自动同步清除 LLM 对话历史；`/llm delete_msg` 支持手动删除超时无法撤回的消息
- 多来源贴吧池：`TIEBA_FORUM_KEYWORDS` 配置多来源；`/tieba source` 查看全部或指定来源状态
- 贴吧随机搬运：`/tieba`、`/tieba text`、`/tieba status`、`/tieba refresh`，基于 Playwright 合法登录态采集与缓存
- LLM 运行时基础设施：多 provider 支持（OpenAI / Claude / Gemini 三类协议）、人格注入、词表按需注入、时间元数据注入及图片识别
- LLM 工具调用链路与 MCP client；身份词表与群聊消息渲染
- 联网搜索后端：内置 SearXNG（含 Docker 容器编排配置）与 Tavily 兼容回退
- 消息统计 `/stats` / `/reset_stats`；群级规则开关 `/disable` / `/enable` / `/rules`
- 统计与规则开关跨重启持久化；APScheduler 定期自动保存
- provider `style_overrides` 字段，为特定模型追加 system prompt 修正段
- `/forget_all`（管理员），清空本群全部长期记忆
- `/llm context_limit <n>`（管理员），按群持久化设置对话上下文读取上限
- 结构化人格字段（`[identity]`/`[biography]`/`[cognition]`/`[instinct]`/`[voice]`/`[boundaries]`/`[world]`），自动编译为自然语言段落注入 system prompt
- `config/personas.example/` 示例目录，含结构化格式完整文档

### 变更

- 文字回复规则外部化到 `config/chat_rules.toml`（gitignored），`config.py` 仅保留基础参数
- 运行时重组为 `quickquip/` 主包，按 `adapters`/`app`/`llm`/`chat`/`tieba`/`search`/`common` 分层；`plugins/` 收窄为薄层 re-export 入口
- 人格配置从单文件 `config/personas.toml` 拆分为 `config/personas/` 目录，每个 `.toml` 对应一个人格；新增 `_shared.toml` 提取共享行为准则
- 私聊短期上下文读取/保留上限提升至 256 条
- 群聊 LLM 认人链路改进：短期历史持久化保存 QQ 号、显示名与标准身份，prompt 中注入参与者摘要
- SearXNG 默认引擎集调整，优先保留在中国大陆网络环境下易访问的搜索源

## [0.2.0] - 2026-03-16

### 新增

- `plugins/tz_utils.py`，承载时区计算与地点格式化纯函数

### 修复

- 修正 `tz_tracker.py` 文件命名拼写错误（原 `tz_tackcer.py`）
- 收窄 `like_reply` 触发范围；`i_do` 规则增加常见口语过滤
- 复读检测器与接龙管理器增加按群状态上限，防止长期运行内存增长

## [0.1.0] - 2026-03-16

### 新增

- 初始化项目骨架：NoneBot2 入口、插件目录与规则驱动回复逻辑
- 时区猜测、复读检测、好姐姐接龙、文字 meme 回复基础功能
- 说明文档、环境变量示例与基础测试脚本

[Unreleased]: https://github.com/3aKHP/QuickQuip/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/3aKHP/QuickQuip/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/3aKHP/QuickQuip/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/3aKHP/QuickQuip/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/3aKHP/QuickQuip/compare/v0.9.2...v1.0.0
[0.9.2]: https://github.com/3aKHP/QuickQuip/compare/v0.9.0...v0.9.2
[0.9.0]: https://github.com/3aKHP/QuickQuip/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/3aKHP/QuickQuip/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/3aKHP/QuickQuip/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/3aKHP/QuickQuip/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/3aKHP/QuickQuip/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/3aKHP/QuickQuip/compare/bfdfcd0...v0.5.0
[0.2.0]: https://github.com/3aKHP/QuickQuip/compare/3dc2ab0...bfdfcd0
[0.1.0]: https://github.com/3aKHP/QuickQuip/commit/3dc2ab0
