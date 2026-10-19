# Web Admin 管理后台

本文面向部署者和管理员，说明如何启动 QuickQuip Web 管理后台（`/ops/`）、配置登录与反向代理，并找到各功能入口。

## 第一次打开后台

1. 在根 `.env` 中填写 `WEB_ADMIN_PASSWORD` 作为管理口令。按 [README](../../README.md#安装步骤)启动源码版后台，或按[部署指南](deployment.md)启动容器；Windows 懒人包运行 `start.bat` 会同时启动后台和 Bot。
2. 后台在自己电脑上运行时，浏览器打开 `http://127.0.0.1:5104/ops/`。部署在服务器上时，按[服务器后台访问步骤](deployment.md#7-web-管理后台)建立 SSH 隧道，再打开同一地址。
3. 在登录页输入第 1 步的口令。进入后台概览后，可从侧栏进入“LLM 工坊 → LLM 配置”，按[首次启用 LLM](llm-configuration.md#首次启用-llm)配置一次群聊对话。

浏览器连接失败时检查后台进程或容器是否正在运行；服务器部署同时检查隧道窗口。修改 `.env` 后，源码或懒人包重新启动后台进程，容器按[环境变量更新步骤](deployment.md#日常维护)重建后台，使口令生效。

---

## 鉴权结构

```text
浏览器
  ↓
nginx / auth_basic / HTTPS
  ↓
FastAPI web-admin
  ├─ /ops/            Vue SPA 静态资源
  └─ /ops/api/*       应用层 session 鉴权
       ↓
     SQLite / 文件系统
```

配置 nginx `auth_basic` 的 HTTPS 部署采用“双层门”：

- **外层**：nginx `auth_basic`
- **内层**：QuickQuip 自身的应用层 session 登录

FastAPI 管理接口独立校验应用会话。内层登录带速率限制：同一 IP 在 60 秒内登录失败达到 5 次后被临时封禁 300 秒，封禁期间的登录请求直接返回 429。

---

## 已实现机制

### 1. 登录流程

1. 浏览器访问 `/ops/`
2. 若已通过 nginx `auth_basic`，Vue SPA 会先请求 `GET /ops/api/auth/me`
3. 如果没有有效 session，前端显示登录页
4. 用户输入 `WEB_ADMIN_PASSWORD`
5. 后端校验通过后创建一条随机 session 记录，并通过 `Set-Cookie` 下发会话 cookie
6. 后续所有 `/ops/api/*` 请求都依赖该 cookie 放行

### 2. session 存储

- 存储位置：`data/web_admin_sessions.db`
- 介质：SQLite
- 内容：`session_id` 的 SHA-256 哈希（明文 id 只存在于浏览器 cookie）、创建时间、过期时间、最近访问时间、客户端 IP、User-Agent

管理员登录后，浏览器通过会话 Cookie 访问后台；口令只用于登录校验。会话随活动滑动续期（`WEB_ADMIN_SESSION_TTL_HOURS`），同时受绝对寿命限制（`WEB_ADMIN_SESSION_MAX_AGE_HOURS`）：自创建起超过绝对寿命的会话会被删除并要求重新登录。

### 3. cookie 属性

应用层 session cookie 具有以下约束：

- `HttpOnly`
- `SameSite=Strict`
- `Path=/ops`
- `Secure`：由 `WEB_ADMIN_COOKIE_SECURE` 控制

其中 `SameSite=Strict` 用来阻断绝大多数跨站请求自动携带 cookie 的场景；`HttpOnly` 用来避免前端 JS 直接读取会话凭证。

### 4. 路由保护

所有业务管理接口都校验应用会话；登录状态查询、登录和退出使用以下接口：

- `GET /ops/api/auth/me`
- `POST /ops/api/auth/login`
- `POST /ops/api/auth/logout`

业务接口的读写权限来自应用登录会话。

---

## 环境变量

Web Admin 使用以下环境变量：

```env
WEB_ADMIN_PASSWORD=change-this-admin-password
WEB_ADMIN_SESSION_TTL_HOURS=168
WEB_ADMIN_SESSION_MAX_AGE_HOURS=168
WEB_ADMIN_COOKIE_SECURE=auto
```

说明：

- `WEB_ADMIN_PASSWORD`  应用层登录口令，必填
- `WEB_ADMIN_SESSION_TTL_HOURS`  session 续期窗口，默认 `168`
- `WEB_ADMIN_SESSION_MAX_AGE_HOURS`  session 绝对寿命，默认 `168`，自创建起超过该时长必须重新登录
- `WEB_ADMIN_COOKIE_SECURE`  `auto | true | false`

在根目录 `.env` 设置这些变量后，源码安装重新启动 Web 进程，容器安装重新创建 Web 服务。源码安装先在 `frontend/` 构建前端，再从项目根运行 `python web_api.py`；容器安装与变量更新步骤见[部署指南](deployment.md)。`web_api.py` 启动时读取根 `.env`，已有进程环境变量优先。

---

## 反向代理注意事项

若使用 HTTPS + 反向代理，推荐让 nginx 传递：

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
```

这样 `WEB_ADMIN_COOKIE_SECURE=auto` 才能正确判断当前请求应当下发 `Secure` cookie。

`X-Forwarded-For` 使用 `$remote_addr` 覆盖语义：后端从直连对端为内网地址的请求中取 XFF 最右一个非内网跳作为真实客户端 IP，登录限流按该 IP 计数。`$proxy_add_x_forwarded_for` 会把客户端自带的 XFF 保留在链上，覆盖语义可以让链上只有 nginx 实际看到的对端地址。

外层 `auth_basic` 本身没有速率限制，建议在 nginx 站点中为 `/ops/` 位置补充请求限流，例如：

```nginx
limit_req_zone $binary_remote_addr zone=quickquip_ops:10m rate=10r/m;

location /ops/ {
    limit_req zone=quickquip_ops burst=20 nodelay;
    auth_basic "quickquip";
    ...
}
```

如果你的站点已经明确只通过 HTTPS 暴露，但暂时不方便补这些 header，也可以直接设置：

```env
WEB_ADMIN_COOKIE_SECURE=true
```

---

## CSRF 与纵深防御

当前方案主要通过以下方式降低 CSRF 与绕过风险：

- 浏览器会话使用 `SameSite=Strict`
- 写操作会额外检查 `Origin` / `Referer` 是否与当前请求宿主一致
- FastAPI 独立校验应用登录会话
- 后端对全部响应统一下发安全响应头（CSP、`X-Frame-Options`、`X-Content-Type-Options`、`Referrer-Policy`）

外层站点访问控制和应用层 session 共同组成后台的纵深防御边界。

---

## 功能标签页

后台提供 29 个功能页面，侧栏可直接进入，深链接形如 `/ops/#/stats`。页面支持不同屏幕尺寸及亮色／暗色主题。

- **概览** — 汇总运行状态、常用入口和关键指标
- **统计** — 各群消息数、活跃用户排行、规则触发 Top
- **规则** — 按群启用/禁用任意规则，toggle 实时生效
- **群组** — 每日总结 / 每日播报 / 群周报 / 群月报群管理（按群开关、立即生成）
- **群 LLM** — 按群设置渠道、模型、人格、触发前缀与上下文条数，选择思考档位，并控制过程回复与最终长回复分段；分别对应 `/llm effort`、`/llm delivery` 等命令。列表同时显示近期活跃群和已有配置的会话
- **唤醒** — 按群查看并编辑唤醒参数，切换 `awakening_*` 规则和无聊唤醒 opt-in；兴趣话题由人格配置和规则开关控制
- **限流** — 实时限流观测（按 scope 分全局/按群视图，5s 可选自动刷新）
- **记忆** — 按群浏览与编辑 LLM 长期记忆，支持明确选择、替换和删除成员引用，提供原文查看
- **对话** — 按群浏览 LLM 对话历史（含私聊/归档，支持关键词筛选和翻页）。群聊和私聊的消息删除经任务队列交由 Bot 执行：回复行删除对应 Turn 正文，用户触发行删除关联对话轮；归档会话提供只读浏览。页面在收到确认删除结果后刷新消息及计数，排队期间保留原消息；等待超时可继续查询原任务，服务端任务仍可执行。
- **人格** — 在线编辑 `config/personas/*.toml`（含新建/删除，`_shared.toml` 保护）
- **资料** — 在线编辑 `llm_about/vocab.yaml`、`llm_about/identities.yaml` 及群级覆盖文件（保存后执行 `/llm reload` 或重启 bot 生效）
- **Skill** — 查看技能包状态与诊断、编辑文本资源、同步预置包，并从压缩包、文件夹或 GitHub 导入。安装先检查再确认，覆盖前自动备份；含脚本的包会提示审阅。入口为“LLM 工坊”的 `/ops/#/skills`，操作与约束见[Skill 管理](skills.md)
- **诊断** — 已发布 LLM 配置重载、MCP 手动重连、上下文清理、样本请求、文本规则回归测试、provider 探活（Bot 队列逐目标执行，按需计费）和 LLM 健康状态
- **用量** — LLM 用量/成本看板（渠道／模型／功能／群／人格五维统计与筛选、定价状态展示）
- **纪元** — 查看会话窗口条数、token 及输入构成随时间的变化，按冷场、触顶、行数限制和切换人格事件回看窗口推进。显示轮次上下文构成、实时水位与冷场倒计时，点击时间点可定格查看
- **总结** — 查阅/删除每日总结、群周报、群月报存档（顶部切换日/周/月）；“生成健康度”按链路汇总近 7/30 天日报、简报和周月报的调用次数、接受率、异常构成、成本与均耗时。一次级联可产生多次尝试，成本包含已丢弃正文的调用；旧记录缺少正文接受结果时计入未知。每篇报文详情内的“生成日志”展示为得到该报文经历的级联各跳（时间点、模型、耗时、token、finish_reason、采纳/丢弃结果）；1.15.3 起每次生成携带 run_id 精确归因，历史报文按生成时间窗推算
- **语录** — 语录管理（按群浏览、关键词搜索、删除；发言人优先显示标准身份及 QQ，改名时附收藏时原名片；正文使用当前身份并提供原文查看）
- **贴吧** — 贴吧帖子池浏览（同步状态/关键词搜索/图文详情/立即同步/实时抓取）
- **词云** — 词云生成（today/week/month/year 时间窗、Top 词频排行、图片下载）
- **LLM 配置** — “LLM 工坊”的 `/ops/#/llm-config` 提供六模块工作台，维护渠道、对话、工具、报告、价格与发布历史。支持草稿保存、应用、版本备注、JSON 交换、历史恢复及排队任务取消；MCP 状态在“工具与技能”中查看。旧模块深链与 `/ops/#/mcp-dashboard` 自动定位到对应位置。完整操作与状态说明见[LLM 配置管理](llm-configuration.md)
- **配置** — `config/generation.toml`、`config/chat_rules.toml`、`config/games.toml`、`config/awakening.toml`、`config/niuniu_text.toml`、`config/niuniu_text_safe.toml` 多文件 TOML 编辑器；`awakening`／`chat_rules` 保存后自动重载，其余需重启。
- **实时日志** — 当前运行日志流、连接状态与当前文件下载
- **LLM Trace** — 按 HTTP 调用索引 QuickQuip 与 LLM Provider 之间的完整 JSON 请求/响应文本，支持持久开关、实时状态更新、分页和按需加载正文
- **日志归档** — 历史轮转日志浏览、预览与下载
- **调度器监控** — 查看节日问候、报告、定时消息等任务的计划、下次和上次执行时间、状态及错误。Bot 每 30 秒更新共享状态文件 `data/cron_jobs.json`，重启后恢复上次执行结果。定时消息的编辑入口在“定时消息”页
- **定时消息** — 群聊定时消息管理（新建/编辑/启停/删除，支持固定文案与 LLM 任务两种类型及一次性任务；任务存于 `data/scheduled_messages.json`，保存后经动作队列通知 bot 进程重注册）。表单分简易/高级两种模式：简易模式用频次（每天/每周/每月/仅一次）+ 时间/日期选择器自动组装 cron，群号从已知群列表勾选；高级模式保留手写 5 段 cron。选择"仅一次"即一次性任务（触发后自动删除），其触发日期时间必须在未来——若钉死月/日的 cron 今年对应时刻已过，后端会拒绝创建，避免静默等到来年
- **审计** — Web Admin 变更审计日志（按操作类型、目标类型、操作人、日期范围等条件过滤，分页浏览）
- **金币** — 金币经济面板（各群金币汇总、排行 TOP 20、账户查询、手动余额调整并记录审计日志）
- **牛牛** — 牛牛大作战面板（自然/绝对值/长度/深度四种排行、用户查询含多维度排名、操作记录追溯、文案模式管理）

敏感词过滤器没有独立标签页。后台提供只读接口 `GET /ops/api/sensitive-filter/status`，LLM 健康检查也会汇总过滤器加载状态和词表数量。`config/sensitive_words.toml` 属于高敏部署文件，只在服务器本地维护，Web Admin 不提供内容读取或在线编辑入口。

纪元看板的数据口径：主图每轮对话保留一个采样点，同轮多次模型调用按对话轮去重。锚点推进事件从功能上线后开始记录；窗口构成条展示消息编号、角色和 token 估算，正文在“对话”页浏览。信封构成展示最近一封的缓存分解，定格历史时刻也会标注这是最近一封。实时锚点、窗口行数、token 和生效水位来自 Bot 运行快照；重启后首次请求会重新建立纪元看板数据。

诊断页的“探活 Provider”按钮会对已发布配置中启用的 provider 默认模型分别提交探测任务，每个目标最多发一次 max_tokens=1 的真实请求，可能产生 provider 计费，用于管理员主动巡检。页面展示排队和执行状态，通过 Bot 的最终任务结果确认完成；提交响应丢失时复用任务请求标识查询，未确认结果不自动重发模型请求。样本请求使用同一任务机制，完成后展示模型正文、用量、耗时和 Trace。群内 `/llm reload` 的重载后验证只探活当前会话实际生效的 provider/model。

LLM Trace 以一次 HTTP 尝试为一条调用记录，并把同一轮 Agent Tool Loop 内的调用归入一个明显分组。请求正文是交给 HTTP 客户端的 UTF-8 JSON 序列化文本，详情页可在格式化 JSON 和传输原文之间切换；普通响应保留解析前的服务端 JSON 文本；流式响应完整消费 SSE 后，按 OpenAI、Claude、Gemini 或 OpenAI Responses 协议重建为一份接近非流式结构的完整响应对象。详情页默认展示组合 JSON，也允许管理员切换到 SSE 传输原文。主列表和实时更新只传输调用元数据，选择记录后才读取请求正文、响应正文和 Header。故障切换、重试和 Tool Loop 后续轮次分别保留 HTTP 明细，并通过 Agent Loop ID 与组内序号关联。

该页面面向最高权限管理员，正文和 Header 不做脱敏。页面会明确提示其中可能包含 API 凭证、系统提示和用户内容；当 MCP 工具图片实际发送给 provider 时，原始请求正文还会包含重新编码后的图片 base64，且记录体积会增大。建议只在排障期间开启采集。记录保存在 `data/llm_trace.db`，默认保留 14 天。

从使用 JSONL Trace 的版本升级时，`data/logs/quickquip_trace_YYYY-MM-DD.jsonl` 历史记录不会导入新的调用索引；Web Admin 访问 Trace 存储或产生新调用记录时，运行时按同一 14 天保留期清理这些旧文件。

Trace 存储初始化时自动补建状态与开始时间的组合索引，供超过一小时的待完成记录检查使用。已有数据库首次补建需读取历史记录一次，耗时取决于数据规模；后续启动复用索引，检查可直接从索引取得匹配记录，避免扫描正文。

### Bot 执行动作队列

Web 与 Bot 分别运行；后台把需要连接 QQ 或读取 Bot 运行状态的动作交给机器人执行。诊断页的运行时重载、LLM 健康检查、上下文清理、唤醒参数重载、群组页的“立即生成总结/播报/周报/月报”、定时消息页的任务重注册等需要 bot 进程执行的动作，会先写入 `data/web_admin_actions.db`。bot 端定时任务 `web_admin_action_queue` 每 5 秒领取并执行队列任务，结果回写到同一数据库；诊断页“最近动作”用于查看等待、执行中、成功或失败状态，并可通过“清空历史”按钮清除已结束（成功/失败）的动作记录，排队中与执行中的动作不受影响。动作队列数据库启用 WAL；若 bot 在领取任务后退出，后续轮询会将超时的 `running` 动作标记为失败，避免任务永久挂起。

LLM 配置控制任务存于 `data/llm_config.db`，与通用动作队列独立；任务状态为 queued／running／succeeded／failed／cancelled，只有排队任务可取消。Bot 每 5 秒领取任务并回报实际配置与组件状态。运行状态由 Bot 回报；重启加载已发布配置，草稿通过单独应用生效。

其他配置文件和群级开关继续走各自的文件持久化路径。bot 端 `web_admin_state_sync` 每 30 秒检测 `rule_switch.json`、`config/awakening.toml`、每日总结/播报群组文件、无聊唤醒群组文件的修改并重载。唤醒标签页和配置页保存 `config/awakening.toml` 后也会主动入队一次 `awakening_reload`。

---

记录正文结构升级、历史预览和回填见 [记录身份迁移与验收](record-identities.md)。
