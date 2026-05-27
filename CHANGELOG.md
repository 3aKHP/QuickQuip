# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.7.10] - 2026-05-28

> *“为什么版本号从 1.7.1 直接跳到了 1.7.10？”*
> *在那个著名的方块游戏里，1.7.10 象征着最坚实的基础设施与最繁荣的 Mod 生态。今天，QuickQuip 也迎来了属于它的 1.7.10。*
> *我们终于彻底清偿了从 0.x 时代积累至今的“开发与生产环境高度耦合”的技术债。它终于成为了一款真正意义上“开箱即用”的机器人框架。*

### 🚀 史诗级基建重构 (Infrastructure)

- 🐳 **Docker 镜像真正可用**：GHCR 分发镜像全面补齐了 Playwright 浏览器内核、Docker CLI、Web Admin 前端构建产物及资料示例目录。公开的 compose 示例已修正为可直接拉取的小写镜像名，并修复了容器内 SearXNG 地址注入的问题。
- 🪟 **Windows 懒人包开箱即用**：启动入口全面升级为 `start.bat`。现已直接打包内置 Playwright Chromium，首次运行会自动生成 `.env`、常用配置、persona 及资料文件，并贴心提示补齐必要配置。告别繁琐的手动初始化！

### 🔧 变更与优化 (Changed)

- **生产环境与配置解耦**：生产运维模板正式迁移至 `prod.example/`，真实生产目录隔离至私有 `prod/`；QuickQuip 应用环境变量现已统一从项目根目录的 `.env` 读取，逻辑更加清晰。
- **贴吧组件入口调整**：贴吧登录态续签入口规范化，改为 `python -m quickquip.tieba.login`。


## [1.7.1] - 2026-05-27

### 修复

- 群聊唤醒延长现在只由显式 LLM 触发打开，并过滤图片-only、CQ-only 与短语气词；兴趣、兜底、相关性、答疑和无聊唤醒不会造成后续普通消息连续响应。
- 唤醒触发会向模型提供内部原因提示，同时避免把触发说明写入 LLM 对话历史。
- 被动唤醒可在延长、兴趣、相关性和答疑场景下携带当前触发消息的少量图片，兜底和无聊唤醒不注入图片。

## [1.7.0] - 2026-05-27

### 新增

- 群聊唤醒模块：新增唤醒延长、兴趣话题、相关性判定、答疑判定、无聊唤醒、兜底概率六类主动响应入口；配置集中在 `config/awakening.toml`，群内通过 `/awakening` 查看状态并管理规则开关。
- Web 管理后台唤醒页支持按群编辑唤醒延长、兜底概率、无聊唤醒、相关性判定和答疑判定参数，保存后通知 bot 重载规则配置。

### 变更

- 推荐 OneBot V11 基座从 NapCat 迁移至 LLBot：更新 compose 示例模板、部署文档、README；新增迁移指南 `docs/admin/migration-napcat-to-llbot.md`。NapCat 近期因 DLL 注入特征遭腾讯高强度风控（频繁 KickedOffLine / 静默掐断），LLBot 使用 PMHQ 外部内存 Hook 规避检测

### 修复

- `/llm reload` 现在会同步刷新敏感词过滤器；`config/sensitive_words.toml` 继续仅通过服务器本地文件或部署流程维护，不在 Web Admin 中回显或编辑。
- Web Admin 唤醒参数保存后会通知 bot 重载 `config/awakening.toml`，并移除 API 响应中的服务端配置路径。
- Web Admin 诊断页健康检查改由 bot 侧动作队列执行；动作队列启用 WAL，并会回收长时间停留在 `running` 的中断任务。

## [1.6.1] - 2026-05-22

### 变更

- Claude 协议线格式对齐：新增 `x-app: cli` 默认头、`auth_method` 配置项（api_key / bearer）、`prompt_caching` 支持（system prompt / 末尾消息块 / 末尾 tool 定义注入 `cache_control` 标记）

## [1.6.0] - 2026-05-22

### 新增

- LLM Provider 代理支持：`ProviderConfig` 新增 `proxy` 字段，可选 HTTP(S) 代理地址

### 变更

- 启动链熔断：单文件配置错误不再导致全集群崩溃。Persona TOML 单文件隔离、chat_rules 原子替换、provider 验证 per-entry 容错、llm.toml 顶层解析兜底、LLMService 懒加载
- 运行时降级：vocab/identity 文件读取容错、7 个 SQLite store 统一加入 `_unavailable` 守卫、分组词表/身份缓存 OrderedDict 驱逐、LLM Trace 按日期轮转
- 语义验证：model_cascade 与 image_preprocessing.provider_id 跨引用校验，缺失时追加到 load_error 而非静默失败
- Web Admin 配置保存后通知 reload（响应注入 reload_required，前端展示操作提示）
- 记忆库脏 tags_json 记录保护、auto_memory turn 计数器 LRU 淘汰

## [1.5.0] - 2026-05-19

### 新增

- LLM 流量敏感词过滤：输入/输出/历史三处接入两级（block/soft）敏感词匹配，基于 Aho-Corasick 自动机。命中日志只记录类别和 SHA-256 前缀哈希，不记录原文。规避 LLM 提供商网关层审核风险（如 DeepSeek `Content Exists Risk`）
- 敏感词过滤器健康检查：`/llm health` 报告新增 `sensitive_filter` 检查项（三态 summary），Web Admin 新增只读端点 `GET /api/sensitive-filter/status`
- 工具调用层敏感词扫描：工具调用前扫描 arguments 拒绝执行，执行后扫描结果进行 scrub/替换。修复群友消息合规但 LLM 自主搜索拉回违规内容的高危路径

## [1.4.5] - 2026-05-18

### 新增

- 牛牛文案模式切换：TOML 驱动多套文案预设（`default`/`safe`），`/牛牛文案 [模式名]` 按群切换
- 牛牛 RPM 限流：`glue_rpm_limit`/`fence_rpm_limit`/`rpm_window_seconds` 按群限制频率
- Web Admin 牛牛面板文案管理：查看可用模式、设置群组模式

### 修复

- 前端移动端适配全面翻新：iOS Safari 输入框缩放修复、表格横向滑动、刘海屏适配、toast 位置调整
- 前端响应式断点统一：消除碎片化断点（720/760/780→767），定义 4 个标准设计令牌
- 配置编辑页布局优化：缩窄面板、编辑器头部压缩为单行
- 总结页行高修复、配置列表 `overflow: hidden` 滚动修复

## [1.4.4] - 2026-05-10

### 新增

- Web 管理后台日志页拆分：`实时日志`、`LLM Trace`、`日志归档` 三个独立标签页
- 诊断页收缩：只保留样本请求与文本规则回归测试，原始 trace 迁入 `LLM Trace`

### 变更

- 牛牛打胶改为 sqrt 尺度：变化量 `∝ √|L|`，系统变为均值回归过程，移除惩罚性回归压力机制
- 打胶基础系数 0.1→0.4，事件数值大幅放宽
- arrested 事件权重 6→2（触发率 7.9%→2.8%），CD 180s→60s
- 击剑数值幅度大幅提升：重写主伤害公式为比值制 balance，`fence_luck` 扩展为全面幅度乘数

## [1.4.3] - 2026-05-09

- 群设置页扩充可见范围：同时展示近期活跃群和已有覆盖配置的群

### 修复

- 引用合并转发识别不稳：递归展开节点和图片，保留发言者身份信息
- 引用身份串台：提示词明确区分”当前提问者”和”引用发送者”
- 引用机器人自身发言：提示词标记”机器人自己”，不再套用普通人物身份
- 每日播报异常截断：提高输出 token 上限，非正常结束时继续尝试级联模型
- 牛牛负数回归过冲：负数长度回归时不再穿过 0 反向冲出

## [1.4.2] - 2026-05-09

- 配置与路径收口：LLM/generation 配置加载共享 helper，`config/*.toml`/`data/*.db`/资料目录路径集中到公共常量
- 跨层路径整理：Web route、消息管线与 LLM 运行时改为从统一路径模块取值
- 引用合并转发回捞失效：修正 `get_forward_msg` 的参数路径

## [1.4.1] - 2026-05-09

- 适配层与 LLM 运行时结构拆分：`commands.py` 收束为聚合注册入口，命令域迁入 `command_parts/`；`LLMService` 拆出 `service_parts/`
- LLM 常量集中管理：`service_parts/` 共享常量收束到单一来源
- 贴吧命令注册整理：`reset_stats` 与 `tieba_peek` 注册和处理逻辑重新靠拢

## [1.4.0] - 2026-05-09

- 共享状态所有权收口：统一 `GameScores` 实例来源，避免多份运行时缓存同时写入
- SQLite 生命周期补齐：`OfflineMessageStore` 与 `GroupQuoteStore` 增加显式关闭路径
- xdist 测试兼容性：持久化 store 改为惰性初始化，减少并行测试下副作用与资源争抢

## [1.3.2] - 2026-05-08

> [!WARNING]
> 此版本彻底移除了对旧版前端 frontend-v1 的支持。如果你在部署脚本或 Docker 编排中引用了 `/ops/v1/` 路径或 `frontend-v1/dist` 卷挂载，请在本版升级前移除相关配置。

### 新增

- 牛牛打胶事件重做：从 5 个扩展至 11 个（新增 lucky_day/mirror/blessing/gambler/zen/frenzy/nightmare），移除急速惩罚陷阱
- 牛牛击剑事件系统：7 种事件（critical/glancing/reversal/slip/draw/dominate/succubus_devour），各独立伤害倍率和文案
- 魅魔吞噬真实窃取对手长度（min(|a|,|b|)×15%），输家损失 ×1.5；牛头人支配从吞噬拆分
- 无牛牛目标击剑加权随机事件（拒绝/强制注册/自伤）
- 机器人击剑：自动生成幻影牛牛，随机长度不持久化，专属文案
- 牛牛数值上下限放宽：衰减率降低（3%→1%），硬下限解除（-100→-1M），growth 基准提升（200→500）
- Web Admin 用户详情页显示击剑运势，前端运势阈值适配新分布（3.0/1.0/0.3）
- 牛牛模块 103 个单元测试覆盖全部子模块

### 变更

- 打胶/击剑全部数值参数化为 `NiuNiuConfig`（29 个 TOML 可调字段）
- 击剑伤害浮点数精度修复：乘法完成后一次性 round
- 长度评论文案扩展：新增 ＜-1000 和 ＞1000 两档极端区间

### 修复

- 审计日志 IP 恒为 `172.20.0.1`：替换为 `X-Forwarded-For` 感知的 `get_client_ip()`
- 击剑 @ 机器人时 @ 提取失败：改为优先从 `event.raw_message` 提取
- 打胶消息 diff 不匹配：运势乘算后数值与实际变化不一致
- 防守方牛头人腰斩/魅魔吞噬未触发：特殊效果现在正确激活
- 注册时全表扫描：改用 `COUNT + OFFSET` 替代全量排序
- 牛牛三种排行体系：新增自然数值排行和绝对值排行，负数用户不再显示排名 -1
- 语录系统升级：per-group 顺序编号、按编号定点查看、关键词搜索、Web 端管理界面；旧数据库自动迁移

### 移除

- frontend-v1 废弃：移除旧版 SPA 前端全部挂载点

## [1.3.1] - 2026-05-07

- 前端品牌设计：v6-fluid 双月牙流体标志，应用于侧边栏、登录页、favicon
- 前端精致度提升：eyebrow 排版优化、多层阴影叠加、导航项 :active 反馈、过渡曲线 cubic-bezier
- Vue 3 Composition API 全面迁移，全局 base.css 抽离，新增 Dashboard 概览页

## [1.3.0] - 2026-05-06

### 新增

- 金币经济系统：SQLite 持久化金币账户，每日签到连击、好感度成长、金币排行，原子事务保护
- 21 点（Blackjack）：bot 坐庄硬 17 停牌，支持 Blackjack 判定和平局退款，最多 8 人
- 俄罗斯轮盘：7 槽弹仓随机排列，存活概率实时更新
- 牛牛大作战：持久化 RPG，注册随机初始长度、打胶加权事件引擎（5 种事件/6 档评论）、击剑胜率公式、排行/CD 系统
- 游戏配置文件化：`config/games.toml` 统一管理全部游戏参数，缺失文件回退默认值
- `quickquip/games/` 独立子目录，与 llm/generation/tieba 同级
- Web Admin 游戏管理：金币面板 + 牛牛面板，配置编辑器支持 `games.toml`
- 游戏文档三层体系：群友向 / 部署向 / 开发向

### 变更

- `BaseGame.start()` 新增可选 `start_arg` 参数
- `GameScores` / `GameRegistry` / `NumberBombGame` 从 `quickquip/chat/` 迁移至 `quickquip/games/`

## [1.2.1] - 2026-05-05

### 新增

- 前端工程重构：Design Token 体系（暗色/亮色双主题）、响应式布局（768px 断点）、15 视图卡片化、UI 组件标准化、视图过渡动画
- Web Admin 操作审计：SQLite 审计日志（`data/audit.db`），覆盖 7 类变更操作，支持按类型/时间过滤和分页浏览
- 定时任务看板：聚合 cron job 状态，展示触发器、下次执行时间、最近结果，30s 自动刷新
- MCP server 状态看板：展示连接状态、传输方式、工具清单；bot 通过共享卷 `data/mcp_status.json` 向 web-admin 透传真实状态
- MCP server 级工具过滤：`include_tools` / `exclude_tools` 字段，兼容旧 `allowed_tools`
- 节日自动化：内置 6 个节日检测（公历+农历，`lunardate`），命中时注入节日人设附录并发送问候
- 数字炸弹游戏：`/game start 数字炸弹`，1-1000 猜数字，60s 超时，`/game score` 排行榜；`BaseGame` + `GameRegistry` 扩展接口
- 每日总结 Markdown 渲染：`marked` + `DOMPurify` 安全渲染

### 变更

- 前端视觉语言完善（Design Token 化、组件标准化）
- 文档全面脱敏：私有路径/域名替换为通用描述

### 修复

- 数字炸弹积分记录从 `user_id` 修正为 `at_user_id`（获胜者）
- 定时任务看板中 scheduled_message 任务在 bot 不可用时不误报为"成功"
- 节日 cron 任务补充 `record_job_result` 执行追踪，与其他定时任务在状态看板中一致
- MCP 看板及新标签页缺失图标（Server/Clock/ShieldCheck/ChevronLeft/ChevronRight）已注册
- 未使用 import 清理（`game_registry.py` 的 `field`、`game_scores.py` 的 `Optional`），CI ruff 报错消除

## [1.2.0] - 2026-05-03

> 此版本本应为 v1.1.1（v1.1 的增量补丁），因工程失误标记为 v1.2.0。ROADMAP 原定 v1.2 范围的 6 项功能不受影响，将在后续版本中交付。

- LLM 工具发现：新增 `tool_search` / `tool_list` 元工具与 `discovery_mode` 配置，初始只暴露常驻工具，其余按需搜索/加载，降低大批 MCP 工具的提示词占用

## [1.1.0] - 2026-05-01

### 新增

- 自动记忆抽取保守重做：攒批触发（每 10 轮）、多轮上下文、固定置信度 0.5、质量门槛（用户 ≥ 8 字且助手 ≥ 20 字）、双向 min 分母去重
- 自动记忆认人：抽取 prompt 接收 `canonical_name`，记忆内容强制以群友名开头
- 自动记忆去重：仅查 `scope=”user”` 库，避免被其他用户记忆挤出候选集
- 图像预处理抽象接口：`ImagePreprocessor` ABC，预留 OCR/多模态转述钩子点
- `LLMSceneMessage` 场景块中间表示：bot 回复间的连续人类发言归入统一场景
- Web 管理后台”资料”页：在线编辑 `vocab.yaml` / `identities.yaml` 及群级覆盖文件
- ASR 语音理解：OneBot V11 `record` 消息转写为文字注入 LLM，支持 OpenAI-compatible transcription

### 变更

- LLM 提示词组装重构：统一为 `身份（QQ 号）：内容` 格式，历史按 bot 回复边界分组为场景块
- LLM 会话落库新增 `raw_content` 列，保留原始轮次文本（含引用/转发上下文）
- System prompt 瘦身：移除重复的”当前提问者”段，参与者列表简化为纯名称
- `/profile @某人` 支持 short/middle/long/full 四档长度
- `config/generation.toml` 新增 `[asr]` 配置区块

### 修复

- LLM 上下文交替：修正 `build_messages()` 中连续 `role=”user”` 问题，合并到同一 user message 用 `【上文】`/`【当前提问】` 区分
- LLM 图片输入：非视觉模型先经图片预处理转述再移除图片 URL
- `/quote random`：优先返回最近未输出过的语录，减少重复
- `/profile` 数据收集修复、at 解析回退、解除对 `daily_summary.model_cascade` 的依赖
- `/music` 歌词改走合并转发消息，群聊不再刷屏

## [1.0.1] - 2026-04-27

### 新增

- TypeScript 严格模式迁移：前端 33 文件全量 TS，`strict: true`，`vue-tsc --noEmit` 零错误
- Windows 懒人包 WebView 窗口化：`pywebview` + WebView2 原生窗口，未安装时回落浏览器
- LLM 健康检查模块：覆盖 10 个检查项，verbose 模式可探测延迟；`/llm health` 命令与 `get_health_status` 工具可调用

### 修复

- DeepSeek thinking mode `reasoning_content` 未传回导致 HTTP 400：响应解析提取 reasoning_content 并 round-trip 回请求体
- 私有部署 `llm_about` volume 挂载目标修正为 `/app/llm_about`
- 前端诊断页：样本探测补 `stream: false`，回归测试补空输入保护，API 增强错误详情格式化

### 变更

- `frontend/package.json` 移除 `openapi-typescript` devDependency，消除 TS6 与 TS5 peer dependency 冲突
- 全仓文档重构：README 从 644 行精简至 191 行，建立按读者角色分区的文档体系（user/admin/dev）

## [1.0.0] - 2026-04-24

### 新增

- 搜索工具语义化重排：`search_web` 硬编码走 SearXNG，Tavily 能力完全走 MCP 侧细粒度工具
- 自动联网判定：`[triggers.auto_search]` 配置开关，LLM 需要时主动调用搜索
- LLM 诊断工具：Web admin "诊断"标签页，样本请求 + JSON trace + 文本规则回归测试
- Windows 懒人包：GitHub Actions 构建嵌入式 Python 3.11 + 一键启动脚本
- GHCR Docker 镜像：多阶段生产镜像 + `docker-compose.example.yml` 完整部署模板
- 分群词表与身份覆盖：`llm_about/{群号}/` 目录自动合并，分群条目覆盖全局同名项

### 变更

- 前端全部迁移到 `<script setup>` 语法
- `llm_about` 资料目录迁移到仓库根目录

## [0.9.2] - 2026-04-23

### 新增

- `/draw` 配置重构：`[[image_generation.providers]]` 嵌套 models 结构，与 LLM provider 对齐；支持按模型 ID 选择
- `/draw` 图生图/图文生图：引用图片 + 自带图片采集为输入，`openai_images` 自动切换 edits 端点，`gemini_imagen` 以 inlineData 注入
- `/draw` 新增 `--size` / `--quality` 参数 + `image_gen` 限流桶 + 提示词 `prompt_blocklist` 预审查
- MiniMax Image-01 支持：`protocol = "minimax_images"`
- Claude extended thinking：解析 thinking/redacted_thinking 内容块，工具调用轮次回填 thinking blocks

### 修复

- 火山方舟 Seedream `/draw` 404：独立 provider 配置后路径正确
- `_post_json_with_fallback` 遗漏 `OSError`/`JSONDecodeError` 处理，已补全

## [0.9.1] - 2026-04-22

### 新增

- `/profile @某人`：群友人物卡，收集消息统计、长期记忆、近期发言，以 persona 口吻合成人物志
- `/find <关键词>`：全文搜索本群最近 30 天历史消息，返回最新 5 条匹配
- `/quote`：群语录库，引用收藏 + 随机翻出（SQLite 持久化）
- 轻娱乐命令族：`/roll`、`/choose`、`/fortune`、`/vote`
- 离线留言 `/tell`：@某人捎话，目标下次发言自动送达；SQLite 持久化
- `/draw` 图片生成：支持 `openai_images`（DALL-E/GPT Image/火山方舟 Seedream）和 `gemini_imagen` 两种协议
- `ProviderConfig` 新增四个字段：`aliases`（模型别名）、`user_agent`（自定义 UA）、`extra_body`（额外请求体字段）、`fallback_urls`（备用地址列表，5xx 自动切换）
- `/llm use <provider>` 可省略模型名，自动使用 `default_model`

### 变更

- `/llm use` 参数改为 `<provider> [model]`（model 可选）

### 修复

- 引用合并转发 + @bot 时 bot 看不见被引用内容：`extract_forward_content` 新增 reply 回退，`render_message_for_llm` 补 forward 占位

## [0.9.0] - 2026-04-21

### 新增

- 保守版自动记忆抽取：LLM 对话结束后后台异步判定并提取长期事实写入记忆库（source="auto"），与主对话完全隔离
- personas 热重载：`/reload_personas` 仅重读 personas 配置，不触发 provider/MCP/runtime 重载
- chat_rules 热重载：`/reload_rules` 就地重载 `chat_rules.toml` 并重建所有派生缓存，解析失败时保留原状态
- 限流窗口按规则自定义：每条限流桶可选 `window = N` 字段

### 修复

- Gemini 思维链泄漏：跳过 `thought=True` 的 part，防止内心独白被拼到回复正文
- Gemini 工具调用 400 错误：新增 `sanitize_gemini_schema()` 按白名单裁剪 MCP 工具参数 schema，过滤 Gemini 不识别的 JSON Schema 关键字

### 变更

- `group_settings` 表新增 `auto_memory_enabled` 列，保持旧 db 兼容
- 修正 `quick_judge()` 中 `default_provider` 的读取路径
- `extract_json_object()` 抽为通用工具，auto_memory 与 context_rules 共享
- 新增 `.gitattributes`：强制 `text=auto eol=lf`，Windows 脚本保留 CRLF

## [0.8.1] - 2026-04-21

### 新增

- MCP `sse` transport：经典 HTTP+SSE 协议，GET 事件流 + POST 请求，支持 headers 鉴权
- MCP sidecar POC：mcp-proxy 封装 stdio-only 镜像暴露为 SSE 服务，替代 DooD docker transport
- MCP 客户端重构：协议层与传输层解耦，新增 Transport 抽象基类 + JsonRpcSession + StdioTransport / StreamableHttpTransport / SseTransport
- `MCPClientManager.sync()` 启动重试：每个 server 最多 3 次、间隔 2s，兜底 compose 冷启动竞态
- Web 管理后台贴吧图片代理：`GET /ops/api/tieba/imgproxy` 绕开百度跨域限制
- Web 管理后台贴吧手动同步：SSE 流式进度 + `on_progress` 回调，实时日志面板
- 合并转发消息 LLM 支持：自动拉取并格式化子消息为编号列表注入上下文

### 测试与 CI

- 测试套件整体重构：193 个独立 pytest 用例替代旧的 2840 行断言式脚本，共享 fixtures 模块化
- CI 工作流替换为可复用 `_tests.yml` 模板，新增 concurrency + timeout + frontend job

### 变更

- 彻底移除 DooD 支持：删除 `mount_docker_socket` 字段与 Docker socket 挂载；`transport = "docker"` 仅用于裸机
- 默认 MCP 清单清理：仅保留 `prts_wiki`（http），其余社区 server 注释保留

### 修复

- `context_rules.py` 的 4 个 E402 lint 错误：import 归位到文件顶端

## [0.8.0] - 2026-04-17

### 新增

- 限流规则 `scope` 字段：`group`（默认，按群独立分桶）与 `global`（跨群共享），LLM/搜索/爬虫标为 global
- Web 管理后台词云标签页：群选择 + 时间窗切换 + 生成，CPU 密集步骤走 `asyncio.to_thread`
- Web 管理后台贴吧标签页：只读浏览缓存帖吧与帖子，关键词过滤与详情 overlay
- Web 管理后台限流标签页：每规则独立卡片，进度条 + 用户排行，5s 自动刷新，快照前自动 prune 过期时间戳
- Web 管理后台群 LLM 标签页：9 字段按群覆盖设置，三态语义（跟随默认/开/关），仅变更字段 PUT
- Web 管理后台对话标签页：浏览 `llm.db` 会话，按群聊/私聊/归档分类，游标翻页与关键词过滤，可逐条删除
- Web 管理后台配置标签页多文件编辑器：`llm.toml` + `chat_rules.toml` 在线编辑，白名单防路径穿越
- Web 管理后台人格标签页：`config/personas/` 文件 CRUD，TOML 校验 + filelock 并发写入保护
- vue-router 4 集成（hash 模式）：深链接与浏览器前进后退支持
- 语境感知回复 `context_rules`：regex 首筛后做 `regex_context` 或 `llm_context` 二次判定，LLM 判定带超时和 TTL 缓存
- `LLMService.quick_judge`：极速 LLM 判定（不走群配置/不注入记忆/不启用工具）
- 合并转发消息 LLM 支持：自动拉取并格式化子消息为编号列表注入上下文
- 《新三国》梗默认入库：18 条直接 rules + 7 条 context_rules

### 变更

- `KeyedRateLimiter` 内部存储升级为 `(rule_name, bucket_key)` 复合键，按 scope 分桶
- `resolve_reply` / `build_reply` 改为 async，新增 `recent_context` 参数透传

### 修复

- `ntk_longerduo` priority 从 83 抬至 95，避免被低优先级规则截胡
- `SWITCHABLE_RULES` 动态并入 text/context/chain 三类规则名，修复规则开关页缺失问题

## [0.7.0] - 2026-04-16

### 新增

- Web 管理前台设计升级：CSS 变量设计系统、通用 UI 组件库、配置驱动导航、模块化 API 层、响应式布局与移动端适配
- 每日早中晚报 `daily_briefing`：按群开启早报(08:00)/午报(12:00)/晚报(22:00)，消息量不足时自动退回模板播报
- Web 管理后台 `web_api.py` + FastAPI + Vue 3 SPA：消息统计、规则开关、群组管理端点，构建产物 serve 在 `/ops/`
- Web 管理后台 session 登录鉴权：HttpOnly cookie，`WEB_ADMIN_PASSWORD` / `WEB_ADMIN_SESSION_TTL_HOURS` 环境变量
- MCP docker transport 支持 `pull_policy` 配置项（always/missing/never）
- `/llm mcp reload` 命令：强制 pull 最新镜像并重连
- 词云功能 `/wordcloud`：支持 today/week/month/year 四个时间窗，jieba 分词 + wordcloud 渲染
- 人格配置支持可选 `scope` 字段，按群聊/私聊上下文筛选可用人格
- `bot.py` 新增 loguru 文件日志（每日轮转，保留 14 天）+ SSE 实时日志服务
- `LLM_TRACE_FLAG_FILE` 环境变量：文件存在时输出完整 LLM 请求/响应 JSON

### 修复

- Web 管理后台安全加固：登录速率限制、`X-Forwarded-For` IP 伪造防护、CSRF 检查、`filelock` 并发写入保护、`group_id` 统一校验规则、前端 401 处理与空状态修复
- LLM 引用消息认人：user message 同时标注"当前提问者"和"引用发送者"
- LLM 上下文结构修正：recent_messages 移至紧贴当前提问之前
- 每日总结发送走合并转发卡片，规避 NapCat ~667 汉字截断
- 每日总结生成检查 `finish_reason`，非正常结束自动降级
- Tieba 爬虫改用 API 直调替代页面 XHR 拦截

## [0.6.0] - 2026-04-09

- 每日群聊总结 `daily_summary`：凌晨 06:00 收集前一日聊天，中午 12:00 定时以 persona 口吻发布约 2000 字小作文
- 模型级联策略：生成失败时自动降级到下一个 provider/model
- `/summary on|off|status|now` 命令：群管理员开关与即时生成
- `DailyMessageCollector`：逐行写入 JSONL，生成后自动清理原始文件
- `DailySummaryStore`：独立 SQLite 持久化已生成摘要

## [0.5.0] - 2026-04-09

### 新增

- 通用接龙引擎 `ChainGameManager`：可配置步骤、捕获组占位符、OR 候选匹配；`config/chat_rules.toml` 新增 `[[chain_games]]` 配置区块
- `/defectify` 命令：文字/图片转写为故障机器人风格
- 私聊会话管理：开启/结束/存档/恢复/浏览/删除，撤回消息自动同步清除 LLM 对话历史
- 多来源贴吧池与随机搬运：Playwright 合法登录态采集与缓存
- LLM 运行时基础设施：多 provider（OpenAI/Claude/Gemini）、人格注入、工具调用链路、MCP client、联网搜索（SearXNG + Tavily）
- 消息统计与群级规则开关，跨重启持久化
- 管理员命令：`/forget_all`（清空群长期记忆）、`/llm context_limit`（设置上下文上限）
- 结构化人格字段（identity/biography/voice 等 7 段），自动编译注入 system prompt

### 变更

- 文字回复规则外部化到 `config/chat_rules.toml`
- 运行时重组为 `quickquip/` 分层架构（adapters/app/llm/chat/tieba/search/common），`plugins/` 收窄为 re-export 入口
- 人格配置拆分为 `config/personas/` 目录，每个 `.toml` 对应一个人格，新增 `_shared.toml` 共享行为准则
- 私聊上下文上限提升至 256 条
- 群聊 LLM 认人链路改进：持久化 QQ 号与身份，prompt 注入参与者摘要
- SearXNG 默认引擎集调整为大陆易访问源

## [0.2.0] - 2026-03-16

- 抽离时区计算与地点格式化纯函数到独立模块
- 修正 `tz_tracker` 文件命名拼写错误
- 收窄 `like_reply` 触发范围，`i_do` 规则增加常见口语过滤
- 复读检测器与接龙管理器增加按群状态上限，防止长期运行内存增长

## [0.1.0] - 2026-03-16

- 初始化项目骨架：NoneBot2 + OneBot V11，规则驱动回复
- 时区猜测、复读检测、好姐姐接龙、文字 meme 回复

[Unreleased]: https://github.com/3aKHP/QuickQuip/compare/v1.7.10...HEAD
[1.7.10]: https://github.com/3aKHP/QuickQuip/compare/v1.7.1...v1.7.10
[1.7.1]: https://github.com/3aKHP/QuickQuip/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/3aKHP/QuickQuip/compare/v1.6.1...v1.7.0
[1.6.1]: https://github.com/3aKHP/QuickQuip/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/3aKHP/QuickQuip/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/3aKHP/QuickQuip/compare/v1.4.5...v1.5.0
[1.4.5]: https://github.com/3aKHP/QuickQuip/compare/v1.4.4...v1.4.5
[1.4.4]: https://github.com/3aKHP/QuickQuip/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/3aKHP/QuickQuip/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/3aKHP/QuickQuip/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/3aKHP/QuickQuip/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/3aKHP/QuickQuip/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/3aKHP/QuickQuip/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/3aKHP/QuickQuip/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/3aKHP/QuickQuip/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/3aKHP/QuickQuip/compare/v1.2.0...v1.2.1
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
