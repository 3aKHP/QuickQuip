<!-- Generated from docs/dev/web-admin.md; do not edit -->

# Web Admin 会话与执行机制

本文供维护后台鉴权、任务交接与存储逻辑的开发者查阅。后台访问、页面用途和运维步骤见[管理员指南](../admin/web-admin.md)。

## 鉴权实现

关于 Web Admin 采用服务端 Session 与 Cookie 授权的设计依据，详见 [ADR-0009](adr/0009-web-admin-server-sessions.md)。

```text
浏览器 (Browser)
  │
  ▼
[外层门] Nginx / auth_basic / HTTPS (可选反向代理层)
  │
  ▼
[内层门] FastAPI web-admin
  ├─ /ops/            Vue SPA 前端静态资源
  └─ /ops/api/*       应用层 Session 鉴权 + 暴力破解限流
       │
       ▼
     SQLite 数据库 / 宿主机文件系统
```

### 1. 双层门防护与登录防爆破限流
当你在公网使用 HTTPS + Nginx `auth_basic` 部署时，后台具备“双层门”保护：
- **外层门**：Nginx `auth_basic` 站点级访问控制。
- **内层门**：QuickQuip 自身的应用层 Session 登录（FastAPI 的所有业务管理接口均独立校验应用层 Session）。
- **防爆破速率限制**：内层登录自带防暴力破解保护——**同一客户端 IP 在 60 秒内连续登录失败达到 5 次，会被临时封禁 300 秒（5 分钟）**，封禁期间的任何登录请求直接返回 HTTP `429`。

### 2. 登录与 Session 生命周期机制

1. **前端鉴权与登录流**：
   浏览器访问 `/ops/`（若配有外层 Nginx `auth_basic` 则先通过外层认证）$\rightarrow$ Vue SPA 首先请求 `GET /ops/api/auth/me` 检查登录态 $\rightarrow$ 若无有效 Session 则展示登录页 $\rightarrow$ 管理员输入 `WEB_ADMIN_PASSWORD` 提交至 `POST /ops/api/auth/login` $\rightarrow$ 后端校验通过后生成一条随机 Session 记录，并通过 `Set-Cookie` 下发会话 Cookie $\rightarrow$ 后续所有 `/ops/api/*` 业务请求均凭该 Cookie 放行（退出登录调用 `POST /ops/api/auth/logout`）。
2. **Session 持久化存储（`data/web_admin_sessions.db`）**：
   - 使用独立的 SQLite 数据库存储。
   - **数据库不存明文 Token**：表中仅保存 `session_id` 的 **SHA-256 哈希值**（明文 Session ID 仅存在于浏览器 Cookie 中），同时记录创建时间、过期时间、最近访问时间、客户端 IP 与 User-Agent。
   - **滑动续期 + 绝对寿命双控**：管理员操作后台时，会话会随活动自动滑动续期（由 `WEB_ADMIN_SESSION_TTL_HOURS` 控制）；但自创建起一旦超过绝对最大寿命（由 `WEB_ADMIN_SESSION_MAX_AGE_HOURS` 控制），该会话会被强制删除并要求重新输入密码登录。
3. **Cookie 安全属性与 CSRF 纵深防御**：
   - **`HttpOnly`**：禁止前端 JavaScript 读取 Cookie，防止 XSS 窃取会话。
   - **`SameSite=Strict`**：阻断绝大多数跨站请求自动携带 Cookie。
   - **`Path=/ops`** 与 **`Secure`**（由 `WEB_ADMIN_COOKIE_SECURE` 控制）。
   - **Origin / Referer 校验与安全响应头**：除 `SameSite=Strict` 外，后端对所有写操作还会额外校验请求头中的 `Origin` / `Referer` 是否与当前请求 Host 一致；并且对全部 HTTP 响应统一下发安全响应头（`CSP`、`X-Frame-Options`、`X-Content-Type-Options`、`Referrer-Policy`）。

---


## Bot 执行动作队列（Web 与 Bot 是如何跨进程协作的？）

由于 `web-admin` 与 `quickquip`（Bot）是两个相互独立的进程/容器，当你在后台点击那些**需要操作 QQ 连接或改变 Bot 内存运行态**的按钮时，Web 后端并不会自己直接执行，而是通过数据库队列交由 Bot 进程异步完成。

系统按职责将跨进程任务拆分为 **3 条互不干扰的通道**：

| 协作通道 | 存储位置 / 载体 | 轮询频率 | 涵盖的后台操作与容错机制 |
|---|---|---|---|
| **1. 通用动作队列** | `data/web_admin_actions.db`<br>（启用 WAL 模式） | Bot 每 **5 秒**轮询一次<br>（`web_admin_action_queue`） | • **涵盖动作**：诊断页的运行时重载、LLM 健康检查、上下文清理、唤醒参数重载；对话页的消息删除；群组页的“立即生成总结/播报/周报/月报”；定时消息页的任务重注册等。<br>• **查看与清理**：可在诊断页“最近动作”面板查看等待、执行中、成功或失败状态；点击“清空历史”可清除已结束（成功/失败）的记录，不影响排队或执行中的任务。<br>• **防挂起保护**：若 Bot 在领取任务（`running`）后意外崩溃退出，后续轮询会自动将超时的 `running` 动作标记为失败，防止任务永久卡死。 |
| **2. LLM 配置控制任务** | `data/config_runtime.db` | Bot 每 **5 秒**轮询一次 | • **涵盖动作**：专门处理 LLM 配置的发布应用与状态回报（与通用动作队列完全独立）。<br>• **状态流转**：状态分为 `queued` / `running` / `succeeded` / `failed` / `cancelled`，其中处于 **`queued`（排队中）** 的任务支持在页面上手动取消。 |
| **3. 独立配置文件定时热同步** | 各自对应的 JSON / TOML 文件 | Bot 每 **30 秒**检查一次文件修改时间<br>（`web_admin_state_sync`） | • **涵盖文件**：`data/rule_switch.json`（群规则开关）、`config/awakening.toml`（唤醒配置）、每日总结/播报群组 JSON、无聊唤醒群组 JSON。<br>• **双保险即时触发**：当你在后台“唤醒”页或“配置”页保存 `config/awakening.toml` 时，除了等待 30 秒自动检测外，后台还会主动向通用动作队列塞入一条 `awakening_reload` 任务，让 Bot 在 5 秒内立即重载生效。 |


## Trace 历史清理与索引

- **旧版 JSONL 清理与启动索引补建**：
  - 从旧版 JSONL Trace 升级上来时，旧的 `data/logs/quickquip_trace_YYYY-MM-DD.jsonl` 文件不会导入新数据库，但当访问 Trace 或产生新记录时，系统会按同样的 **14 天保留期**自动清理这些过期旧文件。
  - Trace 数据库初始化时会自动检查并补建“状态 + 开始时间”的组合索引（用于快速检索超过 1 小时的挂起记录，避免全表扫描大体积正文）。已有存量数据的老库在首次升级启动时需要读取一次历史记录来建索引，耗时取决于库大小；后续启动直接复用索引。
