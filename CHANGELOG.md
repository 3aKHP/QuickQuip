# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

## [1.13.0] - 2026-09-03

### 新增

- LLM provider 支持临时禁用开关（`enabled = false`）：禁用的 provider 不再出现在群聊命令列表、不参与探活与级联回退、切换被拒绝，配置保留、一行恢复。
- gemini provider 可开启内置联网搜索（`builtin_search`）：检索由 provider 侧 grounding 完成，回复自动附带至多 3 条来源；开启后该 provider 的会话不再使用 SearXNG 的 `search_web` 工具。检索成本计入 provider 侧计费。
- 群聊定时消息：管理员可通过 `/schedule` 命令或 Web Admin「定时消息」页面创建定时群消息，支持固定文案与 LLM 动态生成两种类型及一次性任务（触发后自动删除）；群友也可以直接对 bot 说"今晚七点提醒我看 KPL"，由 AI 自行创建提醒任务。LLM 类任务受 `scheduled_message_llm` 规则开关控制，LLM 工具需在 `llm.toml` 的 `[tools]` 中启用 `manage_scheduled_messages`。
- Web Admin「定时消息」页新建/编辑表单改为简易/高级双模式：简易模式用频次（每天/每周/每月/仅一次）加时间、日期选择器自动组装 cron，群号改为从已知群列表勾选；高级模式保留手写 5 段 cron，两种模式可互相切换且内容不丢。「仅一次」任务必须选择未来的触发时间；钉死月/日但今年时刻已过的一次性任务会被后端拒绝，避免静默等到明年才触发（不勾选「一次性任务」则为每年重复的周年提醒）。
- 群语录发言人动态名片解析与按发言人检索：展示语录时结合 QQ 号动态解析最新群名片，对方改名后以"新名片（原：收藏时名片）"形式显示，随机语录、编号查看与搜索结果均已生效；新增 `/quote by 名字或QQ`（别名 `/quote b`）查看某位群友在本群发言的全部语录，支持按最新名片、收藏时名片或 QQ 号检索，最多显示 10 条；Web 管理后台语录列表同步展示发言人的最新名片与 QQ 号。

### 变更

- 「故障化」(/defectify) 归位尖塔公式域（`quickquip.sts`），并改用独立限频桶，不再与 LLM 聊天共享额度——「故障机器人」本是《杀戮尖塔》角色 Defect 的中文名，该命令与 /turmfluch 同属尖塔梗，现同域同构维护。
- 管理控制台视觉翻新：氛围背景升级为全强度粒子光场（品牌色刻度粒子 + 光束 + 圆弧，三层视差纵深，鼠标邻近粒子增亮响应），登录页满强度呈现、控制台内以氛围强度运行；prefers-reduced-motion 渲染静态帧，侧栏提供低动态模式开关。同步松绑设计语言：一次性过渡改用 ease-out 缓动，卡片恢复真实投影与 hover 微浮起，页面标题与节标题拉开字体层级。
- 管理控制台交互反馈增强：标签页切换改为共享组件（选中指示条滑动过渡），按钮图标带 hover 微动效，统计卡数字 count-up 滚动；空态按场景分级，列表与表格加载改用内容形状的 skeleton；功能群组管理四卡合并为单卡 + 标签页；审计/语录/金币/牛牛页面新增头部统计摘要条；确立六域锚点色，页头新增按路由派生的域图标砖，侧栏品牌区升级为 logo + 字标组合；主题切换增加全局颜色过渡，首次访问跟随系统深浅色偏好。修复登录页首次访问误报"登录状态已失效"与本地开发 vite 代理登录 403 的问题。
- LLM 上游自动重试全面覆盖并加入随机抖动：此前仅主聊天链路具备上游 429/5xx 自动退避重试，一次性命令（/defectify 等）、总结、播报、评审、图片预处理等调用遇到上游波动会直接失败；现重试机制内建于 provider 层，所有 LLM 调用路径统一继承，退避延迟加入随机抖动以避免并发请求同步重试。新增 `[runtime] retry_jitter` 配置（默认 0.5，取值 0-1）；原 `retry_max_attempts`（含首次调用）与 `retry_base_delay` 继续有效，热重载即时生效。探活与诊断采样不受重试影响；usage 统计中错误记录按逻辑调用计数（重试吸收的中间失败不再单独计数），单次请求的每次 HTTP 尝试仍可在调用追踪中查看。
- Web Admin「定时任务」页更名为「调度器监控」，副标题注明它是涵盖全部系统任务的只读运行时视图，群聊定时消息请前往「定时消息」页管理，消除两个页面的命名歧义。

### 修复

- Web Admin「定时任务」页在生产部署下始终空白的问题——调度器运行在 bot 进程内，页面现在读取 bot 进程每 30 秒落盘的共享状态文件 `data/cron_jobs.json`。同时修复容器时区：quickquip 与 web-admin 服务新增 `TZ` 环境变量（默认 `Asia/Shanghai`），任务时间与日志时间戳恢复为本地时区。
- 群聊词云与词频统计不再泄露明文 QQ 号：未登记成员的 @ 提及占位符（`@QQ...`）在分词前被清洗；已登记成员的 `@规范名` 提及保留为正常词频信号。
- stdlib logging 未桥接 loguru 的问题：LLM 链路等模块的 INFO 观测日志现在正常进入 stdout 与生产日志文件；httpx/httpcore/uvicorn.access 等逐请求高频日志保持 WARNING 以免刷屏。
- `/llm clear_context` 后模型仍可见最近群聊的问题：此前清空只删除持久会话库，进程内最近消息缓冲（每群最多 20 条、保留 30 分钟）不受影响，构建提示词时仍会拼入上下文。现在清空短期上下文会同时清掉对应会话的内存缓冲，清空立即完全生效；私聊的会话开始、结束（含不存档结束）与恢复存档均走同一条清理路径。清空之后到达的新消息照常进入上下文，旧消息没有任何回填路径。
- 纯图片/引用消息不再从对话历史中丢失：此类消息落库时正文为空、仅带占位符（如"[图片 1 张]"），此前组装上下文时被整体过滤，导致模型看不到"用户发过图"这一事实，且请求中出现连续两条助手消息、破坏消息交替约定。现在占位符消息照常回到上下文，发言者与占位内容均可见。
- 模型状态查询结果补充路由说明：机器人向模型披露自身 provider/model 配置时，附带说明该字段仅表示当前对话的路由；画图、语音、搜索等能力可能由不同模型通道服务，对话人格始终同一，避免模型把不同功能走不同通道误解为对话中"更换过模型"并虚构归因。

## [1.12.2] - 2026-08-28

本版为跨平台发行与部署定型 release（v1.12 系列里程碑版本）：无新功能，主体是 CQ 码注入缺陷类的全面收口、provider 协议健壮性加固与发行/部署链路加固；发布前按里程碑计划在 Windows 懒人包、Windows Docker、Linux Docker、Linux 源码部署四条路径完成全链路验收，并对公开文档逐项校对。维护者可感知收益：协议边界 fail-visible、CQ 注入面清零；部署者可感知收益：四条发行路径均有真实环境证据与已知限制记录。

> **关于版本号**：v1.12.2 向 [Minecraft: Java Edition 1.12.2](https://minecraft.wiki/w/Java_Edition_1.12.2) 致敬。那个 2017 年 9 月发布、只修复了 12 个缺陷的小版本，因足够稳定成了模组社区沿用多年的黄金底座。本版同样不引入新功能、专注于收口与加固——愿它也能被长期安稳地部署下去。

### 🔧 变更 (Changed)

- **发行流水线支持 RC 预发布 tag**：release notes 提取把 `v1.12.2-rc.1` 这类预发布 tag 归一化到基础版本段；Docker 的 `1.12`/`1` 浮动 tag 不再被预发布构建顶掉（与 `latest` 同规则）；`.env.example` 补充本地直跑场景的 `ONEBOT_WS_URLS` 注释示例（#146）。

### 🐛 修复 (Fixed)

- **复读回复保留消息段**：复读指纹与被动规则文本分离，回放复制的 OneBot 消息段而非 CQ 码字符串，规则文本中的 CQ 字面量不再被激活为真实消息段（#138）。
- **CQ 码注入面全面收口**：每日播报与长消息降级改走文本段（array 格式），播报活跃用户昵称在采集侧剔除 `[CQ:...]` 码（#140）；无聊唤醒直发、歌词转发降级（群/私聊）、定时消息与节日问候统一文本段发送，`build_llm_reply_message` 恒返回 Message——#138 同类缺陷的全部 7 处直发点收口完毕（#143）。
- **Gemini 原生工具调用回放**：完整保留并回放 `thoughtSignature`，支持 Bearer 网关鉴权、并行工具批次和工具结果图片的协议安全分离（#136）；修复原生工具请求数组参数缺元素类型被上游拒绝的问题（#137）。
- **provider 协议健壮性三处**：MCP 外部工具声明缺 items 的数组 schema 会被 Gemini 上游 400（#137 只覆盖了内建工具）；Claude 流式路径丢失 redacted_thinking 块导致下一轮回放遭 400；Gemini 工具批次 fail-closed 拒绝时模型的叙述文本会吞掉拒绝提示，现追加提示并记录 warning 日志（#141）。
- **LLM 配置校验可观测性**：显式配置的默认 provider 被剪除后的回退记入 load_error 并显式拒绝服务（fail-visible，与 default_provider 指向不存在 id 的既有语义一致；自动选择的默认值仍静默再回退）；已禁用功能的 model_cascade 不再参与 provider 引用校验，示例 cascade 不再污染新部署的 load_error（#144）。
- **部署与发行加固**：check_bot.sh 移除硬编码 nix store busybox 路径，改容器内 ps → docker top 分级进程探测，探测失效输出 UNKNOWN 而非误报 OFFLINE（消除 llonebot 镜像漂移引起的误报离线告警）；Windows webview 启动器读取 WEB_ADMIN_HOST/WEB_ADMIN_PORT（与 web_api.py 同源默认值，非法端口回退 5104）；懒人包 smoke 增加首启模板清单校验，start.bat 模板缺失输出 WARNING（#145）。
- **RC1 四路径验收修复批**：bot 文件日志不再明文落盘 .env 全部密钥（nonebot 配置 DEBUG dump 被文件日志 INFO 级挡下，#148）；懒人包 ZIP 打包改在冒烟测试之前并对产物做清洁审计，`.env`/`__pycache__`/冒烟残留不再入包，首启门控恢复（#149）；懒人包 Web Admin 经 cmd 重定向启动，不再因 pythonw 无控制台流静默退出，运行日志落 `data\web-admin.log`（#150）；发行镜像随包提供 `/app/plugins`，纯镜像部署（GHCR/compose 自包含模板）首次可正常启动，配套增加 bot 存活 smoke（#151）。
- **验收后收束批**：Web Admin 根路径不再 404——`/` 现重定向到管理台 `/ops/`（Linux Docker 验收发现，#155）；部署脚本增加模板嵌套保护——`cp -r prod.example prod` 误嵌套进已有生产 `prod/` 时中止部署，避免以生产设置运行并外泄运维密钥（源码路径验收发现，#156）。

## [1.12.1] - 2026-08-21

本版为 maintenance / refactor release：一批唤醒与用量修复之外，主体是按 [`docs/dev/style.md`](docs/dev/style.md) 完成的代码规范化拆分——LLM 服务、工具循环、唤醒、总结编排与 Web Admin 前端的模块边界全面收紧，外部行为保持不变。维护者可感知收益：配置/规则/持久化的单一事实来源、跨进程写入一致性、更清晰的模块职责；部署者可感知收益：无迁移负担，配置与数据格式全兼容。

### ✨ 新增 (Added)

- **用量页支持人格维度**：LLM 用量统计新增人格（persona）聚合与筛选，聊天、私聊、日报、播报、周报、月报与自动记忆请求按实际人格归因计量；事件明细显示人格，无可靠来源的调用统一显示后端下发的“(未归因)”标签。

### 🔧 变更 (Changed)

- **MCP era 标签统一由服务端下发**：协议时代标签（modern / auto/legacy）后端单源，聊天状态与 Web Admin 一致渲染；用量归因改经公开 Trace 接口。
- **代码规范化拆分（refactor，无行为变化）**：
  - LLM 服务：quick-judge 通道、一次性生成管线、工具发现与结果后处理、MCP 生命周期各自独立成模块；主回复链路的超长函数拆分为图像预处理/历史加载/持久化三段。
  - 唤醒：无聊巡检发送移至适配层，chat 领域零传输；opt-in 群开关持久化统一单一实现，bot 与 Web Admin 跨进程写入不再丢更新。
  - 总结：每日总结/周期报告生成编排下沉 chat 领域层；`/summary now` 报错类型化（文案不变）。
  - 贴吧：服务不再 import 即读盘，实例由组合根持有，登录 CLI 不再有覆盖空池风险。
  - Web Admin 前端：API 层全面类型化并逐字段对齐后端；诊断页/贴吧页/群设置拆分。

### 🐛 修复 (Fixed)

- **被动唤醒输入去重与语音参与**：当前消息不再同时出现在 prompt 与上下文造成重复；语音转写参与被动唤醒判定；Bot 回复缓存加 30 分钟时效；英文/数字/代码标识符参与相关性快筛。
- **无聊唤醒运行时语义**：扫描周期与冷却分离（新增 `boredom_scan_interval`，保存即生效）；重启后沉寂未知的群不再盲目冒泡；长沉寂门槛不再被状态清理提前满足；取消 opt-in 即时清理状态。
- **quick-judge 失败分类**：技术失败（超时/异常/截断等）与业务 false 区分，技术失败不污染 60 秒判定缓存；诊断日志结构化且脱敏；新增 reasoning 模型预算指引（真实部署验收：完成率 5%→95%+）。
- **用量统计时区统一**：趋势/汇总/明细统一按北京时间（Asia/Shanghai），凌晨记录不再错记前一日；管理端时间不随浏览器时区变化。

## [1.12.0] - 2026-08-18

### ✨ 新增 (Added)

- **SVG 画图（LLM 工具 `draw_svg`）**：启用 LLM 的群里，AI 可以在对话中自主画 SVG 矢量图（梗图、图表、示意图），本地 resvg 渲染成 PNG 直接发到群里，无需任何指令。
  - 启用方式（管理员）：`config/generation.toml` 新增 `[svg]` 段设 `enabled = true`，并在 `config/llm.toml` 的 `[tools] enabled` 中加入 `"draw_svg"`。
  - 渲染在本地完成，不额外消耗图片生成 API；中文字体沿用词云的思源黑体，无需新增部署要求。
  - 两层可选安全防护：默认启用的渲染硬防线（输入约束、清洗、输出尺寸覆盖、子进程资源限制），与默认关闭的 LLM 内容安全裁决（`content_judge`，复用 quick_judge 廉价模型）。
  - 渲染限流：全局每分钟 10 次、单用户每分钟 2 次；单次回复最多发送 3 张图片。
  - 渲染子进程资源硬限制依赖 POSIX `rlimit`，在 Linux 等 POSIX 平台生效；Windows 保留 8 秒墙钟超时兜底。平台与字体说明见 `docs/admin/deployment.md`。

### 🔧 变更 (Changed)

- **`[tools] enabled` 支持 append/replace 两种作用模式**：`enabled` 非空时不再整体替换默认白名单（旧语义会把未列入的 MCP 工具一并过滤掉），默认按 `append` 在默认白名单与 MCP 工具之上追加；需要精确白名单的部署显式设置 `enabled_mode = "replace"`；`enabled = []` 的部署行为完全不变。升级后 `enabled` 非空且未设置 `enabled_mode` 的部署会在启动日志收到语义提醒。升级说明见 `docs/admin/configuration.md`。

### 🐛 修复 (Fixed)

- **用量计量不再阻塞聊天回复**：高并发多群场景下，聊天回复不再等待 LLM 用量计量写库完成，写锁竞争高峰期的回复延迟尖峰消除；进程关停前排空在途计量任务，重启/部署时尾部用量记录不再丢失。
- **成本统计窗口口径对齐**：Web Admin 成本页趋势图与总成本卡片共用同一时间窗下界，趋势合计不再与汇总卡片不一致；计费公式收敛为单一实现。
- **用量错误信息遮蔽请求 URL**：错误信息落库前遮蔽完整请求 URL（可能携带 query 凭据），不再进入数据库与 Web Admin 展示。

## [1.11.1] - 2026-08-12

### 🐛 修复 (Fixed)

- **Modern MCP 服务器信息恢复显示**：按 MCP 2026-07-28 正式字段读取协商版本和服务器身份，同时兼容早期草案服务器，使 `/llm mcp` 能再次显示 PRTS-MCP 等 modern 服务器的名称与版本号。

## [1.11.0] - 2026-08-11

### ✨ 新增 (Added)

- **LLM 用量与成本计量**：每次 LLM 调用常驻捕获 token/成本/耗时/状态，成本引擎按各家缓存约定归一化计算（Claude exclusive→inclusive 还原、inclusive 减法避免缓存按全价计、修复 Claude cache_write 双算），错误/取消/超时同样留痕；价格由 `llm.toml` 的 `[pricing.models]` 配置，未覆盖模型标记“未定价”。
- **用量归因**：所有 LLM 调用入口携带功能与群维度标签（chat / defectify / turmfluch / vision / summary / profile 等 14 类），为成本按维度分解提供归因基础。
- **Web Admin LLM 用量看板**：统一的 token/cost 总览与明细、成功率、缓存命中率、耗时趋势，支持按 provider/功能/模型/群四维分解与筛选，可下钻到请求级明细；旧用量数据库启动时自动迁移并保留历史记录。
- **Provider 级 1h prompt-cache TTL**：provider 可配置 `cache_ttl` 启用 1 小时扩展缓存；群聊两次请求间隔常超 5 分钟默认窗口，1h 缓存可显著提升命中率、降低成本。

### 🔧 变更 (Changed)

- **LLM 定价改为 provider 级覆盖**：`[pricing.models."provider_id/model"]` 支持按 provider 填写实际计费价（如中转价），未命中时回退模型官方价默认值。
- **用量看板 ECharts 视觉改版**：趋势图与维度分布图升级为 ECharts 图表（完整坐标轴、十字线悬浮提示、90 天数据滚轮缩放），点击分布图条形可直接下钻筛选；请求明细补充四桶 token、成本分项、定价置信度等完整计量字段；筛选维度选项在筛选后保持完整，不再塌缩。

### 🐛 修复 (Fixed)

- **cache/thinking token 解析补全**：Claude/OpenAI/Gemini 的 cache 与 thinking token 此前被丢弃，开启 `prompt_caching` 后成本无法正确核算；现已完整解析进 `LLMResponse`。
- **`/llm mcp` 群聊状态信息披露**：strict modern 不再显示重复的 modern/modern 标签；状态输出不再回显 MCP 配置 URL（缺少服务器身份信息时改用中性的 serverInfo 名称）；Web Admin MCP 面板新增协议时代标签与协商版本展示。
- **MCP 聊天输出边界加固**：错误信息只显示故障类别（如连接超时、认证失败），服务器返回的原始文本、名称与协议版本经单行化与 URL/CQ 码清洗后才允许进入群聊；MCP 工具调用的错误文本在进入 LLM 上下文前同样做 URL 遮罩。

## [1.10.2] - 2026-08-09

### 🐛 修复 (Fixed)

- **贴吧采集启动失败**：v1.10.1 的 `collect_threads` 误将 `storage_state` 传给 `launch_persistent_context`（该参数仅 `new_context` 支持），导致 `TypeError`、后台同步任务崩溃、贴吧同步完全失效；改为启动持久 context 后用 `add_cookies` 注入登录态。

## [1.10.1] - 2026-08-09

### 🐛 修复 (Fixed)

- **贴吧爬虫临时 profile I/O 抖动**：`collect_threads` 改用持久 `user_data_dir`（替代每次 `launch` 建删临时 profile），并以跨进程文件锁串行化 bot 与 web-admin 容器对同一 profile 的并发访问，消除曾主导容器累计块写入与内存峰值的 I/O 抖动。

## [1.10.0] - 2026-08-08

### ✨ 新增 (Added)

- **杀戮尖塔“xxx了”公式化回复模块**：基于两代卡牌/遗物名词表，被动捕获群友整句“X了”用 LLM 映射到最近的真名回复，并提供 `/turmfluch` 命令把任意内容提炼成“名了”；独立 `sts` 顶层域，可扩展更多公式。被动路径走 `[triggers.quick_judge]` 专用便宜模型。
- **MCP 工具图片交付**：支持将 MCP 工具返回的图片安全交付给视觉模型，并为非视觉模型提供受控转述或降级提示。
- **MCP 双协议纪元支持**：per-server `negotiation` 配置（legacy/auto/modern），同一进程可同时连接 legacy 和 modern (2026-07-28) MCP Server。

### 🔧 变更 (Changed)

- MCP stale-session 404 现在触发有界重连（只读请求重试 ≤2 次，tools/call 不重放），而非无差别失败。
- MCP `_connect_with_retry` 改为按失败类型分类重试：auth/config/4xx 不重试，timeout/5xx 仍重试。
- MCP `_describe_server` 对 HTTP/SSE URL 脱敏（去除 query string），异常消息经 URL 清洗后才进入 status 和日志。
- MCP alias 冲突改为 fail-closed：冲突的 binding 全部不注册并标记 config 错误，不再静默覆盖。
- MCP status JSON 和 `/llm mcp status` 增加 negotiation、era、failure_kind、negotiated_protocol_version 字段。

### 🐛 修复 (Fixed)

- **LLM 命令输出截断**：`/defectify`、`/turmfluch` 和被动“xxx了”的 `max_output_tokens` 硬上限（512/64）在推理模型上被 `reasoning_content` 耗尽，导致实际输出被截断；现统一使用 provider 自己的 `max_output_tokens`。
- **被动“xxx了”频繁 HTTP Request was cancelled**：应用层 `asyncio.wait_for` 超时（12s）短于 provider HTTP 超时（45s），提前取消了携带 ~1644 token 词表 system prompt 的合法请求；已移除应用层超时，由 provider HTTP 超时做唯一守卫。
- 多模态相关文本链路现已复用部署级敏感词过滤器，覆盖图片、语音和音乐生成提示词、自动歌词、图片转述以及故障化输入输出。
- 加固 MCP 非文本工具结果处理，避免未支持的图片、资源和媒体 payload 进入模型文本。

## [1.9.7] - 2026-08-03

### ✨ 新增 (Added)

- **Web Admin 展示运行版本**：概览页新增 QuickQuip 版本信息，版本号由项目元数据统一提供，便于部署核验与问题排查。

### 🔧 变更 (Changed)

- **重写 Web Admin 的 LLM Trace**：按 Agent Tool Loop 分组并保留每次 HTTP 尝试，可按需查看格式化 JSON、实际传输内容和请求头；流式响应按 Provider 协议重建为完整响应对象，同时保留可选 SSE 原文，并移除旧版独立 Trace 页面。

### 🐛 修复 (Fixed)

- **恢复 Docker 发布镜像的前端构建**：前端构建阶段现在会复制项目版本源文件，既避免发布镜像构建失败，也确保 Web Admin 嵌入正确版本号。
- **完善 LLM Trace 日志维护**：迁移到 SQLite 后，旧版 JSONL 文件继续遵守 14 天保留策略；临时 Trace 存储使用隔离的维护日志，读取路径也会触发每日清理，避免测试或自定义存储误删真实运行数据。
- **增强 LLM Trace 数据库并发初始化**：多个进程或实例同时首次启用 SQLite WAL 时会有界重试瞬时锁冲突，避免迁移阶段偶发 `database is locked`。
- **首次检查即可恢复中断任务**：Web Admin 动作队列在进程启动后的第一次检查中即可回收超时停留在 `running` 状态的任务，不再受进程运行时长影响。

## [1.9.6] - 2026-07-17

### 🐛 修复 (Fixed)

- **LLM 图片理解按主模型能力正确路由**：视觉主模型直接接收原图，不再重复调用前置视觉模型并混入转述文本，消除双重图像解释导致的严重幻觉；非视觉主模型现在会转述被动唤醒携带的近期图片，并为当前、引用、转发和近期图片保留来源编号。前置识别缺失、返回空内容或任一图片失败时会终止本轮，避免主模型在没有图像信息时猜测。
- **前置图片识别增加资源边界**：单轮最多处理 5 张图片，单图转述最多输出 2048 token，注入主模型的转述文本同时受单图和总字符上限保护；健康检查会拒绝把已声明的非视觉模型配置成前置视觉模型。

## [1.9.5] - 2026-07-17

### 🐛 修复 (Fixed)

- **部署脚本失败时如实上报退出码**：`prod.example/deploy-v4.sh` 的步骤执行器此前在任何失败场景都显示 `(exit 0)`（`!` 取反吞掉了真实退出码），现如实显示真实退出码（如 ssh/scp 连接失败为 255），避免掩盖部署故障的真实原因。

## [1.9.4] - 2026-07-14

### ✨ 新增 (Added)

- **跨平台运维工具链**：生产部署/巡检脚本补充 Linux 等价物（`prod.example/deploy-v4.sh`、`check_bot_local.sh`，与既有 Windows `.ps1` 并存）；新增基于 uv 的跨平台 pre-push hook 模板（push 前自动跑 ruff + 前端 type-check + 配置校验 + pytest，本地镜像 CI）。

### 🔧 变更 (Changed)

- **推荐开发环境从 Windows 迁至 Linux（WSL2）**：`CLAUDE.md` / `CONTRIBUTING.md` 的 canonical 版本本地化为 Linux + uv，Windows 降级为本地覆盖（`CLAUDE.local.windows.example`）。Python 环境统一用 uv 管理，日常命令改用 `.venv/bin/python` 直接调用（不再 `uv run`，避免触发 uv 项目模式生成 `uv.lock`，后者已永久 gitignore）。
- **前端构建工具链由 npm 迁移至 pnpm，Node 运行时从已 EOL 的 20 升到 24 LTS**：CI、根 `Dockerfile`、pre-push hook 与部署脚本同步切换；贡献者构建前端改用 pnpm（Node 20 已于 2026-04 EOL）。生产服务器不涉及——前端在开发者本机构建为静态产物上传，服务器只跑纯 Python 镜像 + bind-mount `dist/`，从未跑 Node。

> “变量解析被Powershell咬了一口。”“刚刚这条命令被Powershell绊了一下。”“Powershell的转义有点娇气，我写个ps1脚本。” ——From Codex
>
> 再也不会这样了。让Powershell带着Here-String一起见鬼去吧。

## [1.9.3] - 2026-07-02

### ✨ 新增 (Added)

- **`/llm probe` 命令与 Web Admin provider 探活**：并发探活所有 provider（每个发一条 max_tokens=1 的请求），报告可达性与延迟。按需触发即每次计费，api_key 未设置的 provider 自动跳过——不做静默的后台定时探活（静默扣费是大忌）。Web Admin 诊断页同步加入“探活 Provider”按钮，与命令对等。
- **Web Admin 配置保存按文件返回生效方式**：`awakening`/`chat_rules` 保存即自动重载（`chat_rules` 新接入 `rules_reload`），`llm` 引导手动 reload，`generation`/`games`/`niuniu_text*` 如实提示需重启——不再一律“需重启 bot 才会生效”。

### 🔧 变更 (Changed)

- **`/llm reload` 收紧为仅管理员 + 重载后探活**：原先无权限守卫，现与 `/llm mcp reload` 对齐；并在重载后探活当前会话实际生效的 provider/model、回显结果，补上 reload 后的可达性验证闭环。
- **`llm` 配置保存不再自动触发 reload**：`llm_reload` 会触发 MCP 全量重连且 llm 配置影响面大，改为前端引导用户到诊断页手动 reload（注：`reload_runtime` 本身不探活、不涉及计费）。

## [1.9.2] - 2026-06-30

### 🔧 变更 (Changed)

- **搜索后端配置梳理**：生产运维模板不再内置 SearXNG（改为显式声明外部依赖，匹配真实部署），与终端用户的开箱即用自包含模板职责分离，消除“搜索到底走哪”的长期混乱。

### 🗑️ 移除 (Removed)

- **搜索后端死代码清理**：删除早期遗留的独立 SearXNG 编排文件、Tavily 内嵌空壳（从未接入 `search_web`）以及未被代码读取的后端选择配置——均为 v1.0.0 搜索工具重排后未清干净的残留。

## [1.9.1] - 2026-06-29

### ✨ 新增 (Added)

- **Web Admin 适配群周报与群月报**：群组页新增“群周报”“群月报”卡片，可按群开关并立即生成；总结页加入日/周/月切换，查阅与删除历史报告，与每日总结共享同一套回看交互。
- **主动唤醒携带群内近期图片**：被动/无聊触发主动发言时，现在会注入群内最近发过的少量图片，让主动发言基于更完整的群内现场，而非仅当前触发消息里的图片。
- **牛牛大作战：数值算法抽离 + 离线模拟沙箱**：数值计算抽离为独立纯函数模块，并新增离线模拟沙箱（可复现历史数值场景、扫描参数），为后续数值调整提供可验证的工具。
- **牛牛大作战：与机器人击剑**：新增独立玩法，纯娱乐性质——长期数学期望为 0（胜负各半），运势只影响波动幅度不影响期望。

### 🔧 变更 (Changed)

- **牛牛大作战数值重设计**：
  - 真人击剑改为**严格零和**（赢家所得 = 输家所失），消除原非零和转移凭空创造/销毁数值的通胀/通缩。
  - 打胶凹侧“萎缩”改为 **sublinear 加深**，消除原乘性翻倍导致的指数级数值爆炸。
  - 运势改为**幂压缩**（`luck^0.75`）：中位运势行为不变，仅温和化极端运势的实际影响。
  - 平局改为**两败俱伤**（双方各损少量）：作为有意的非零和破例，略微抵消打胶正期望带来的总量通胀。
  - shrinkage/nightmare 惩罚事件权重调低，减少连续触发。
- **牛牛大作战消息显示**：运势值与时间在消息侧格式化（round 到 2 位 + 本地时区），内部计算仍保留完整精度。

### 🐛 修复 (Fixed)

- **牛牛大作战：运势不再放大固定惩罚**：shrinkage/nightmare 等固定惩罚事件不再受运势影响——“神运”不再加重惩罚力度。
- **LLM 图片下载容错**：请求中单张图片下载失败不再拖垮整次回复（改为跳过该图并继续），避免过期/失效图片链接让整个对话失败。

## [1.9.0] - 2026-06-26

### ✨ 新增 (Added)

- **群周报与群月报**：每周一/每月 1 日自动生成上一周期的群聊回顾，发到群里。与每日日报相互独立，可单独开启。
  - 数据源复用词云采集（`wordcloud_msgs`，always-on 不删除），按天均匀采样后套用每日日报同款 LLM 管线，保证覆盖全周期同时控制成本。
  - 周报覆盖上周（ISO 周号标识，如 `2026-W24`），月报覆盖上月（年月标识，如 `2026-06`），prompt 引导覆盖热词趋势、活跃成员、群内大事记等结构化回顾。
  - 命令 `/summary weekly on|off|status|now` 与 `/summary monthly on|off|status|now`，与现有 `/summary` 日报子命令向后兼容（支持中文别名 `周报`/`月报`）。
  - 配置项 `[weekly_report]` / `[monthly_report]`，含 cron、min_messages、length_hint、sample_per_day、model_cascade。
- **语音合成新增本地 TTS 协议**：`[audio]` 段新增两种 protocol，覆盖各类本地/自建 TTS 服务，`/tts` 命令链路自动接入：
  - `openai_tts`：OpenAI TTS 兼容协议（`POST /audio/speech`），一个 handler 同时适配 edge-tts / GPT-SoVITS / piper 等本地服务的 OpenAI 兼容包装。`api_key_env` 可省略，本地无鉴权时不附加 Authorization 头。
  - `http_tts`：原始 HTTP POST 协议，请求体字段从 model 的 `extra_body` 模板派生，支持 `{text}` / `{voice}` 占位符替换，适配非 OpenAI 格式的本地服务（`__path` / `__method` 为内部控制字段）。
  - 本地协议的音色查询：若 model 在 `extra_body.voices` 配置了静态列表，`/tts voices` 可返回；否则返回空而不报错。
- **Web Admin 视觉语言升级**：引入“QQ 蓝主导 + 青/琥珀辅助色 + 玻璃光场”的设计体系，借鉴 4sljq 主站设计语言并克制适配后台场景：
  - 设计 token 全面扩展：新增青/琥珀辅助色、Inter 字体栈（含 display 标题字）、玻璃层（shell-glass）、光场层（粒子/鼠标辉光）、机械缓动（linear/steps 替代 cubic-bezier）、日志/trace 专用色板等约 40 个 token。
  - 新增氛围层组件：`ParticleBackground`（克制强度的蓝青粒子光场，约为展示站 1/3 强度）、`MouseGlow`（跟随鼠标的蓝青锥形光晕）、`StatusBar`（顶部状态条，显示工作域路径 + CST 时钟 + 在线心跳）。
  - 新增路由切换动效：`page-shell` 三态过渡（前进/后退/切换）+ route trace sweep（换页时顶部一道蓝青光带横扫）。
  - 新增 `useTheme` composable，抽离主题逻辑。
  - 新增 `public/brand.svg`，统一品牌标识引用。

### 🔧 变更 (Changed)

- **Web Admin 外壳玻璃化**：侧栏（domain rail + section panel）、移动端顶栏、抽屉、Toast 化为半透玻璃（`backdrop-filter`）浮于光场之上；内容区（卡片/表格/表单）保持实色以保证长时间阅读可读性。
- **设计基调收敛**：圆角从 6/8/20px 收敛到 4/6/12px；卡片 hover 从浮起投影改为描边式（`0 0 0 1px`）；缓动全局改为 linear/steps 营造机械精确感。
- **品牌标识去重**：`LoginView` / `AppNav` 内联的品牌 SVG（两份共 16 处硬编码渐变 stop-color）抽取为 `public/brand.svg` 单文件 `<img>` 引用。
- **硬编码颜色 token 化**：清理 11 个视图 + 2 个组件中绕过设计系统的约 40 处硬编码颜色，统一到 `--qq-*` token（含日志色板、trace 边框、品牌蓝边框、遮罩、强调态文字色等）。
- `generation/config.py` 四模式（image/audio/music/asr）配置解析去重：`resolve_model` 统一到 `_ResolveModelMixin`，providers/models 解析骨架统一到 `_read_generation_section_data`。对外 import 路径与解析行为不变。
- `command_parts/common.py`（470 行杂物模块）按主题拆分到 `_chat_utils` / `_fortune` / `_content` / `_parsing` / `_formatting` 五个子模块，原路径退化为 re-export shim。同时修复 `is_admin` / `strip_command_name` 的跨层 import 遗留（从 `app.message_pipeline` 改为直接从 `common.event_utils` 导入）。对外 import 路径不变。
- `llm/store.py`（645 行单类）按业务域拆分到 `store_parts/` 子包：基础设施（连接/schema/守卫）→ `_StoreBase`，会话消息/记忆/归档/群设置各自独立为 mixin。对外 import 路径与 SQL 行为不变。
- **群周报/月报发布改为每日轮询**：`publish_cron` 从“每周一/每月 1 日”改为“每天 10:00”，使 generate 成功但 publish 失败的报告能在次日自动补发，不再等到下个周期（原周报延迟一周、月报延迟一个月才补发）。
- **周报/月报命令层错误处理改用自定义异常类**：`/summary weekly|monthly now` 的失败原因（未开启 / 冷却中 / 生成失败）改用专用异常类型向命令层传递，替代原先对 RuntimeError 消息做子串匹配的脆方案，避免无关错误被误判为这三种情况导致提示错乱。

### ⚡ 优化 (Performance)

- Web Admin 启动内存占用优化：10 个 route 文件的 `message_pipeline` 顶层 import 改为 handler 内懒导入，避免启动时实例化 9 个 bot 专属单例（复读检测/接龙/jieba/wordcloud/游戏等），预计 VmHWM 从 ~111MB 降至 ~40MB。

## [1.8.9] - 2026-06-18

> *“为什么版本号是 1.8.9 而不是 1.8.2？”*
> *和当年的 1.7.10 一样，我们在向那个方块游戏致敬。1.8.9 不是一个带来新内容的版本，而是 1.8 系列最坚实、最稳定的收尾——无数服务器和 mod 长期驻留于此。QuickQuip 的 1.8.9 也是如此：不发新功能，而是清偿技术债，引入工程规范，让代码库从“能跑”走向“能维护”。*

### 🔧 变更 (Changed)

- **引入工程规范基准**：新增 `docs/dev/style.md`，作为代码架构硬原则的事实参考（单一职责、400 行预警线、分层纪律、抽取触发条件、反模式清单、重构节奏）。该文档从 GPS-Plane 项目的开发规范本地化而来。
- **LLM 模块大文件拆解（纯内部重构，对外 import 路径不变）**：
  - `llm/provider.py`（1277 行）拆分为 `provider/` 包：`trace.py`（trace 基础设施）、`base.py`（基类 + 数据类 + 共享工具）、`openai.py` / `claude.py` / `gemini.py`（三个协议实现）、`factory.py`。三个 ProviderClient 的 `complete()` 方法逐字节相同，上提至基类。
  - `llm/mcp.py`（1023 行）拆分为 `mcp/` 包：`types.py`（数据类 + 纯函数）、`transport.py`（Transport ABC + Stdio/HTTP/Sse 传输）、`jsonrpc.py`（JSON-RPC 2.0 会话）、`client.py`（客户端 + 多服务器管理器）。依赖方向严格单向。
  - `llm/service.py`（1320 行）降至 1009 行：auto-memory 子域独立为 `AutoMemoryMixin`，群/私聊差异化策略独立为 `ScopeMixin`，工具发现策略下沉至 `ToolMixin`，8 个重复常量统一到 `service_parts/constants.py`。
  - `llm/prompting.py`（803 行）降至 660 行：删除 4 个 deprecated 函数（零生产引用），7 段 persona 渲染收敛为共享辅助函数。
- **跨层违规修复**：`app/message_pipeline.py` 的 4 个纯工具函数（`is_admin` / `is_self_message` / `strip_command_name` / `get_sender_name`）迁至 `common/event_utils.py`，消除适配器层跨层 import app 装配模块的反模式。原路径通过 re-export 保持兼容。

### 🔧 优化 (Performance)

- `_is_tool_discovery_enabled` 在工具发现判定中重复调用 `_get_enabled_tool_names` 达 5 次以上（每次重建列表），该方法位于每条 LLM 回复的热路径。现已缓存为单次调用。

### 🐛 修复 (Fixed)

- `JsonRpcSession.request` 在 task 被取消时泄漏 future（`CancelledError` 跳过超时异常处理，pending future 未清理）。`_reader_loop` 的 `_fail_pending` 此前在 except 和 finally 中双重调用且丢失具体异常信息。

## [1.8.1] - 2026-06-14

### 变更

- LLM provider 网络层从 `urllib` 迁移到 `httpx.AsyncClient`，实现真正的全小写 wire-format header（httpx 保留用户传入的 header 键原样，而 urllib 会在发送时 Title-Case 化）。OpenAI / Claude / Gemini 三个协议统一受益，SSE 流式解析改用原生异步 `aiter_lines`，图片下载、超时与代理行为保持等价。
- Claude 协议指纹基于真实 claude-cli 2.1.150 抓包完整校准：User-Agent 对齐 `claude-cli/2.1.150 (external, cli)`，`anthropic-beta` 集合逐字对齐抓包的 7 个特性标记，补齐 `?beta=true` query param、`accept` 头，`x-stainless-os` 改为按宿主 OS 动态探测（Windows/Linux/macOS）。
- `accept-encoding` 声明为 `gzip, deflate`（真实 CC 声明 `br, zstd` 但 httpx 无 brotli/zstandard 依赖无法解码，声明不支持的编码会导致响应体乱码）。
- 修复 `user_agent` 配置字段与 `headers` 中的 `User-Agent` 同时设置时产生重复 header 键的问题（KHPilot Bot CR 发现）。

## [1.8.0] - 2026-06-09

### 变更

- 代码库迁移至 src layout 并成为可安装包（`pip install`），消除“工作目录恰好可导入”的隐式依赖；生产部署改为镜像内安装 + 源码挂载热更新的混合模式，开发与发布路径更清晰。

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
- 引用身份串台：提示词明确区分“当前提问者”和“引用发送者”
- 引用机器人自身发言：提示词标记“机器人自己”，不再套用普通人物身份
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
- 定时任务看板中 scheduled_message 任务在 bot 不可用时不误报为“成功”
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
- Web 管理后台“资料”页：在线编辑 `vocab.yaml` / `identities.yaml` 及群级覆盖文件
- ASR 语音理解：OneBot V11 `record` 消息转写为文字注入 LLM，支持 OpenAI-compatible transcription

### 变更

- LLM 提示词组装重构：统一为 `身份（QQ 号）：内容` 格式，历史按 bot 回复边界分组为场景块
- LLM 会话落库新增 `raw_content` 列，保留原始轮次文本（含引用/转发上下文）
- System prompt 瘦身：移除重复的“当前提问者”段，参与者列表简化为纯名称
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
- LLM 诊断工具：Web admin “诊断”标签页，样本请求 + JSON trace + 文本规则回归测试
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
- LLM 引用消息认人：user message 同时标注“当前提问者”和“引用发送者”
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

[Unreleased]: https://github.com/3aKHP/QuickQuip/compare/v1.13.0...HEAD
[1.13.0]: https://github.com/3aKHP/QuickQuip/compare/v1.12.2...v1.13.0
[1.12.2]: https://github.com/3aKHP/QuickQuip/compare/v1.12.1...v1.12.2
[1.12.1]: https://github.com/3aKHP/QuickQuip/compare/v1.12.0...v1.12.1
[1.12.0]: https://github.com/3aKHP/QuickQuip/compare/v1.11.1...v1.12.0
[1.11.1]: https://github.com/3aKHP/QuickQuip/compare/v1.11.0...v1.11.1
[1.11.0]: https://github.com/3aKHP/QuickQuip/compare/v1.10.2...v1.11.0
[1.10.2]: https://github.com/3aKHP/QuickQuip/compare/v1.10.1...v1.10.2
[1.10.1]: https://github.com/3aKHP/QuickQuip/compare/v1.10.0...v1.10.1
[1.10.0]: https://github.com/3aKHP/QuickQuip/compare/v1.9.7...v1.10.0
[1.9.7]: https://github.com/3aKHP/QuickQuip/compare/v1.9.6...v1.9.7
[1.9.6]: https://github.com/3aKHP/QuickQuip/compare/v1.9.5...v1.9.6
[1.9.5]: https://github.com/3aKHP/QuickQuip/compare/v1.9.4...v1.9.5
[1.9.4]: https://github.com/3aKHP/QuickQuip/compare/v1.9.3...v1.9.4
[1.9.3]: https://github.com/3aKHP/QuickQuip/compare/v1.9.2...v1.9.3
[1.9.2]: https://github.com/3aKHP/QuickQuip/compare/v1.9.1...v1.9.2
[1.9.1]: https://github.com/3aKHP/QuickQuip/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/3aKHP/QuickQuip/compare/v1.8.9...v1.9.0
[1.8.9]: https://github.com/3aKHP/QuickQuip/compare/v1.8.1...v1.8.9
[1.8.1]: https://github.com/3aKHP/QuickQuip/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/3aKHP/QuickQuip/compare/v1.7.10...v1.8.0
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
[0.9.2]: https://github.com/3aKHP/QuickQuip/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/3aKHP/QuickQuip/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/3aKHP/QuickQuip/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/3aKHP/QuickQuip/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/3aKHP/QuickQuip/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/3aKHP/QuickQuip/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/3aKHP/QuickQuip/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/3aKHP/QuickQuip/compare/9fe89ce...v0.5.0
[0.2.0]: https://github.com/3aKHP/QuickQuip/compare/3dc2ab0...9fe89ce
[0.1.0]: https://github.com/3aKHP/QuickQuip/commit/3dc2ab0
