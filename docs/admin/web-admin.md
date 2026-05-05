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

这比"只有 nginx `auth_basic`，应用层完全无认证"的旧结构更符合纵深防御原则。

---

## 功能标签页

Web Admin 提供以下标签页（前端使用 vue-router 4 hash 模式，深链接形如 `/ops/#/stats`）。前端已升级为响应式设计，支持亮色/暗色主题切换，使用统一的设计 token 体系。当前共 19 个标签页。

- **统计** — 各群消息数、活跃用户排行、规则触发 Top
- **规则** — 按群启用/禁用任意规则，toggle 实时生效
- **群组** — 每日总结 / 每日播报群管理
- **记忆** — 按群浏览与编辑 LLM 长期记忆
- **总结** — 查阅/删除每日总结存档
- **对话** — 按群浏览 LLM 对话历史（含私聊/归档，支持关键词过滤、游标翻页、按单条删除）
- **人格** — 在线编辑 `config/personas/*.toml`（含新建/删除，`_shared.toml` 保护）
- **资料** — 在线编辑 `llm_about/vocab.yaml`、`llm_about/identities.yaml` 及群级覆盖文件（保存后执行 `/llm reload` 或重启 bot 生效）
- **群 LLM** — 按群覆盖 provider/model/persona/前缀/历史条数等 9 个 runtime 字段
- **配置** — `config/llm.toml`、`config/generation.toml`、`config/chat_rules.toml` 多文件 TOML 编辑器
- **限流** — 实时限流观测（按 scope 分全局/按群视图，5s 可选自动刷新）
- **贴吧** — 贴吧帖子池浏览（同步状态/关键词搜索/图文详情）
- **词云** — 词云生成（4 档时间窗、Top 词频排行、图片下载）
- **诊断** — 样本请求与原始 JSON trace、`LLM_TRACE_FLAG_FILE` 开关与 trace 浏览、文本规则回归测试
- **MCP** — MCP 服务器状态面板（各 server 的 transport、连接状态、工具数量、错误信息，支持 bot 与 web-admin 共享状态文件）
- **定时任务** — APScheduler 定时任务面板（job ID、trigger、next_run、last_run 时间与状态、错误详情）
- **审计** — Web Admin 变更审计日志（按操作类型、目标类型、操作人、日期范围等条件过滤，分页浏览）
- **金币** — 金币经济面板（各群金币汇总、排行 TOP 20、账户查询、手动余额调整并记录审计日志）
- **牛牛** — 牛牛大作战面板（长度/深度全局排行、用户查询、操作记录追溯）
- **配置** — 配置文件编辑器中新增加 `config/games.toml`（游戏配置），可在线编辑所有游戏参数

---

## 与项目解耦情况

当前实现保持了较高解耦度：

- 不依赖任何个人网站用户体系
- 不依赖外部 OAuth / SSO
- 不依赖前端构建时注入站点私有 token
- 不依赖额外数据库服务

其他使用者克隆仓库后，只需设置自己的 `WEB_ADMIN_PASSWORD`，构建前端并启动 `python web_api.py`，即可使用同一套机制。
