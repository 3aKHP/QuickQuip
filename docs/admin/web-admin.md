# Web Admin 管理后台

本文档记录 QuickQuip Web 管理后台（`/ops/`）的鉴权结构、部署注意事项和功能列表。

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

当前版本采用"双层门"：

- **外层**：nginx `auth_basic`
- **内层**：QuickQuip 自身的应用层 session 登录

这意味着即使 nginx 外层配置出现遗漏，FastAPI 里的管理接口仍然不会直接裸露。

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
- 内容：`session_id`、创建时间、过期时间、最近访问时间、客户端 IP、User-Agent

前端**不会**持久化管理员口令，也不会把长期 token 写进 `localStorage` 或打进 JS bundle。

### 3. cookie 属性

应用层 session cookie 具有以下约束：

- `HttpOnly`
- `SameSite=Strict`
- `Path=/ops`
- `Secure`：由 `WEB_ADMIN_COOKIE_SECURE` 控制

其中 `SameSite=Strict` 用来阻断绝大多数跨站请求自动携带 cookie 的场景；`HttpOnly` 用来避免前端 JS 直接读取会话凭证。

### 4. 路由保护

除以下接口外，所有 `/ops/api/*` 路由都会统一执行 `require_admin_session`：

- `GET /ops/api/auth/me`
- `POST /ops/api/auth/login`
- `POST /ops/api/auth/logout`

业务路由本身不再假设"只要能访问到 FastAPI 就一定已经认证过"。

---

## 为什么不用前端 Bearer Token

当前实现明确没有采用"登录后把长期 token 存进 `localStorage`，再用 `Authorization: Bearer ...` 调接口"的方案，原因是：

- 主密钥会长期暴露给浏览器 JS 运行环境
- 没有真正的服务端会话失效能力
- 退出登录语义较弱，本质上更接近"把主钥匙存到前端"

QuickQuip 当前是一个同源 Vue SPA + FastAPI 后台，做服务端 session 更自然，也更容易和现有部署保持解耦。

---

## 环境变量

Web Admin 使用以下环境变量：

```env
WEB_ADMIN_PASSWORD=change-this-admin-password
WEB_ADMIN_SESSION_TTL_HOURS=168
WEB_ADMIN_COOKIE_SECURE=auto
```

说明：

- `WEB_ADMIN_PASSWORD`
  应用层登录口令，必填
- `WEB_ADMIN_SESSION_TTL_HOURS`
  session 续期窗口，默认 `168`
- `WEB_ADMIN_COOKIE_SECURE`
  `auto | true | false`

`web_api.py` 会在启动时读取项目环境变量文件，并允许运行环境通过同名变量覆盖默认值。

---

## 反向代理注意事项

若使用 HTTPS + 反向代理，推荐让 nginx 传递：

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

这样 `WEB_ADMIN_COOKIE_SECURE=auto` 才能正确判断当前请求应当下发 `Secure` cookie。

如果你的站点已经明确只通过 HTTPS 暴露，但暂时不方便补这些 header，也可以直接设置：

```env
WEB_ADMIN_COOKIE_SECURE=true
```

---

## CSRF 与纵深防御

当前方案主要通过以下方式降低 CSRF 与绕过风险：

- 浏览器会话使用 `SameSite=Strict`
- 写操作会额外检查 `Origin` / `Referer` 是否与当前请求宿主一致
- FastAPI 层自身有登录态校验，不再完全依赖 nginx

外层站点访问控制和应用层 session 共同组成后台的纵深防御边界。

---

## 功能标签页

Web Admin 当前提供 25 个标签页（前端使用 vue-router 4 hash 模式，深链接形如 `/ops/#/stats`）。前端使用响应式设计、亮色/暗色主题切换，以及一套以 QQ 蓝为主色、青/琥珀为辅助色的设计 token 系统：氛围层（侧栏/状态条/抽屉/Toast）采用半透玻璃浮于克制动效的粒子光场之上，内容区（卡片/表格/表单）保持实色以保证可读性；全局缓动为 linear/steps 机械风格，换页时顶部有一道光带横扫。

- **概览** — 汇总运行状态、常用入口和关键指标
- **统计** — 各群消息数、活跃用户排行、规则触发 Top
- **规则** — 按群启用/禁用任意规则，toggle 实时生效
- **群组** — 每日总结 / 每日播报 / 群周报 / 群月报群管理（按群开关、立即生成）
- **群 LLM** — 按群覆盖 provider/model/persona/前缀/历史条数等 runtime 字段；列表会同时显示近期活跃群和数据库里已有覆盖配置的群
- **唤醒** — 按群查看并编辑唤醒参数，切换 `awakening_*` 规则和无聊唤醒 opt-in；兴趣话题由人格配置和规则开关控制
- **限流** — 实时限流观测（按 scope 分全局/按群视图，5s 可选自动刷新）
- **记忆** — 按群浏览与编辑 LLM 长期记忆
- **对话** — 按群浏览 LLM 对话历史（含私聊/归档，支持关键词过滤、游标翻页、按单条删除）
- **人格** — 在线编辑 `config/personas/*.toml`（含新建/删除，`_shared.toml` 保护）
- **资料** — 在线编辑 `llm_about/vocab.yaml`、`llm_about/identities.yaml` 及群级覆盖文件（保存后执行 `/llm reload` 或重启 bot 生效）
- **诊断** — LLM runtime 重载、MCP 重连、上下文清理、样本请求、文本规则回归测试、provider 探活（并发，按需计费）和 LLM 健康状态
- **MCP** — MCP 服务器状态面板（transport、连接状态、工具数量、错误信息，支持 bot 与 web-admin 共享状态文件）
- **总结** — 查阅/删除每日总结、群周报、群月报存档（顶部切换日/周/月）
- **语录** — 语录管理（按群浏览、关键词搜索、删除）
- **贴吧** — 贴吧帖子池浏览（同步状态/关键词搜索/图文详情/立即同步/实时抓取）
- **词云** — 词云生成（today/week/month/year 时间窗、Top 词频排行、图片下载）
- **配置** — `config/llm.toml`、`config/generation.toml`、`config/chat_rules.toml`、`config/games.toml`、`config/awakening.toml`、`config/niuniu_text.toml`、`config/niuniu_text_safe.toml` 多文件 TOML 编辑器
- **实时日志** — 当前运行日志流、连接状态与当前文件下载
- **LLM Trace** — 共享 trace 流、开关控制与最近 trace 条目
- **日志归档** — 历史轮转日志浏览、预览与下载
- **定时任务** — APScheduler 定时任务面板（job ID、trigger、next_run、last_run 时间与状态、错误详情）
- **审计** — Web Admin 变更审计日志（按操作类型、目标类型、操作人、日期范围等条件过滤，分页浏览）
- **金币** — 金币经济面板（各群金币汇总、排行 TOP 20、账户查询、手动余额调整并记录审计日志）
- **牛牛** — 牛牛大作战面板（自然/绝对值/长度/深度四种排行、用户查询含多维度排名、操作记录追溯、文案模式管理）

敏感词过滤器没有独立标签页。后台提供只读接口 `GET /ops/api/sensitive-filter/status`，LLM 健康检查也会汇总过滤器加载状态和词表数量。`config/sensitive_words.toml` 属于高敏部署文件，只在服务器本地维护，Web Admin 不提供内容读取或在线编辑入口。

### Bot 执行动作队列

`web_api.py` 是独立进程，不能直接复用 bot 进程里的 OneBot 连接。诊断页的运行时重载、LLM 健康检查、上下文清理、唤醒参数重载、群组页的“立即生成总结/播报/周报/月报”等需要 bot 进程执行的动作，会先写入 `data/web_admin_actions.db`。bot 端定时任务 `web_admin_action_queue` 每 5 秒领取并执行队列任务，结果回写到同一数据库；诊断页“最近动作”用于查看等待、执行中、成功或失败状态。动作队列数据库启用 WAL；若 bot 在领取任务后退出，后续轮询会将超时的 `running` 动作标记为失败，避免任务永久挂起。

普通配置文件和群级开关仍走文件持久化路径。bot 端 `web_admin_state_sync` 每 30 秒检测 `rule_switch.json`、`config/awakening.toml`、每日总结/播报群组文件、无聊唤醒群组文件的修改并重载。唤醒标签页和配置页保存 `config/awakening.toml` 后也会主动入队一次 `awakening_reload`。

---

## 与项目解耦情况

当前实现保持了较高解耦度：

- 不依赖任何个人网站用户体系
- 不依赖外部 OAuth / SSO
- 不依赖前端构建时注入站点私有 token
- 不依赖额外数据库服务

其他使用者克隆仓库后，只需设置自己的 `WEB_ADMIN_PASSWORD`，构建前端并启动 `python web_api.py`，即可使用同一套机制。
