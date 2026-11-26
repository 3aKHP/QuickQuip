# Web Admin 会话与执行机制

本文面向维护管理后台鉴权、跨进程任务交接、Trace 存储与环境变量管理接口的开发者。后台访问方式、页面功能与日常运维步骤见[管理员指南](../admin/web-admin.md)。

## 鉴权实现

Web Admin 采用服务端持久化 Session 与 `HttpOnly` Cookie 授权，设计取舍见 [ADR-0009](adr/0009-web-admin-server-sessions.md)。

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
     SQLite 数据库 / 宿主机受管文件与私有守护套接字
```

### 1. 双层门防护与登录防爆破限流

公网环境配合 HTTPS 与 Nginx `auth_basic` 部署时，后台形成双层访问控制：

- **外层门**：由反向代理提供站点级 `auth_basic` 认证。
- **内层门**：FastAPI 应用层独立校验服务端 Session，所有 `/ops/api/*` 业务路由均强制执行该鉴权。
- **登录防爆破限流**：同一客户端 IP 在 60 秒窗口内连续登录失败达到 5 次，会被临时封禁 300 秒（5 分钟）；封禁期间继续提交登录请求直接返回 HTTP `429`。

### 2. 登录与 Session 生命周期机制

1. **前端鉴权与登录流**：浏览器访问 `/ops/`（若配置了外层代理认证则先完成站点认证）加载 Vue SPA 后，前端首先请求 `GET /ops/api/auth/me` 检查会话状态；无有效会话时展示登录页，由管理员提交 `WEB_ADMIN_PASSWORD` 至 `POST /ops/api/auth/login`。后端校验密码通过后创建随机 Session 记录，通过 `Set-Cookie` 下发会话 Cookie；此后所有 `/ops/api/*` 请求凭该 Cookie 鉴权放行，主动退出调用 `POST /ops/api/auth/logout` 销毁服务端记录。
2. **Session 持久化存储（`data/web_admin_sessions.db`）**：
   - 会话独立存放在专用 SQLite 库中。
   - **仅存储哈希摘要**：数据表只保存 `session_id` 的 **SHA-256 哈希值**（明文 Session ID 仅驻留浏览器 Cookie），同时记录创建时间、过期时间、最近活跃时间、客户端 IP 与 User-Agent。
   - **滑动续期与绝对寿命双控**：管理员操作后台期间，会话过期时间按 `WEB_ADMIN_SESSION_TTL_HOURS` 自动滑动顺延；自创建时刻起达到 `WEB_ADMIN_SESSION_MAX_AGE_HOURS` 绝对上限后，会话强制失效并清理，须重新输入密码登录。
3. **Cookie 安全属性与 CSRF 纵深防御**：
   - **`HttpOnly`**：禁止前端脚本读取会话 Cookie，阻断 XSS 窃取令牌。
   - **`SameSite=Strict`**：阻止跨站导航与第三方子请求自动携带 Cookie。
   - **`Path=/ops` 与 `Secure`**：Cookie 作用域收敛在 `/ops` 路径下，`Secure` 属性由 `WEB_ADMIN_COOKIE_SECURE` 控制。
   - **同源校验与安全响应头**：后端对所有状态修改请求额外核验 `Origin` 或 `Referer` 请求头是否与当前 Host 同源，并对全部 HTTP 响应统一下发 `Content-Security-Policy`、`X-Frame-Options`、`X-Content-Type-Options` 与 `Referrer-Policy` 安全响应头。

---

## 跨进程协作与动作队列

`web-admin` 与 `quickquip`（Bot）运行在相互独立的进程或容器中。涉及 OneBot 连接或 Bot 进程内存状态的后台操作，统一由 Web 后端写入共享数据库队列或配置文件，再由 Bot 进程按周期轮询异步执行。

系统按职责划分出 **3 条互不干扰的跨进程通道**：

| 协作通道 | 存储载体 | 轮询周期 | 涵盖操作与容错机制 |
|---|---|---|---|
| **1. 通用动作队列** | `data/web_admin_actions.db`<br>（WAL 模式） | Bot 每 **5 秒**轮询一次<br>（`web_admin_action_queue`） | • **涵盖动作**：诊断页运行时重载、LLM 健康检查、上下文清理、唤醒参数重载；对话页消息删除；群组页立即生成总结／播报／周报／月报；定时消息页任务重注册等。<br>• **查看与清理**：诊断页“最近动作”面板展示排队、执行中、成功或失败记录；“清空历史”仅清理已终结记录，保留排队中与执行中任务。<br>• **防挂起保护**：若 Bot 领取任务进入 `running` 状态后意外退出，后续轮询会将超时的 `running` 记录自动收束为失败，防止队列永久阻塞。 |
| **2. LLM 配置控制任务** | `data/config_runtime.db` | Bot 每 **5 秒**轮询一次 | • **涵盖动作**：承载 LLM 配置快照的在线应用、模型探测、采样请求及运行状态回报。<br>• **状态流转**：任务经历 `queued`、`running`、`succeeded`、`failed`、`cancelled` 五种状态；处于 `queued` 状态的排队任务支持在后台手动取消。 |
| **3. 独立配置文件热同步** | 各领域 JSON / TOML 文件 | Bot 每 **30 秒**检查文件修改时间<br>（`web_admin_state_sync`） | • **涵盖文件**：`data/rule_switch.json`（群规则开关）、`config/awakening.toml`（唤醒配置）、每日总结／播报群组 JSON、无聊唤醒群组 JSON。<br>• **双通道即时触发**：在后台保存 `config/awakening.toml` 时，除等待 30 秒文件巡检外，Web 后端会同步向通用动作队列投递一条 `awakening_reload` 动作，使 Bot 在 5 秒内完成热重载。 |

## Trace 历史清理与索引

- **存量 JSONL 过期清理**：早期版本遗留的 `data/logs/quickquip_trace_YYYY-MM-DD.jsonl` 日志文件无需导入 `data/llm_trace.db`；每当读取 Trace 面板或写入新调用记录时，清理逻辑会按相同的 **14 天保留期**自动删除超期 JSONL 文件。
- **启动组合索引维护**：`data/llm_trace.db` 初始化时会自动检查并建立“状态 + 开始时间”组合索引，用于检索超过 1 小时的挂起记录而无需扫描大体积请求正文。存量数据库在升级后首次启动时读取一次历史行构建索引，后续启动直接复用。

## 环境变量管理能力

Web Admin 通过只写通道与私有守护服务 `env-agent` 协作管理根目录 `.env`（架构依据见 [ADR-0028](adr/0028-write-only-environment-management.md)，部署与运维步骤见[环境变量管理](../admin/environment.md)）。环境变量明文仅经私有套接字快照下发给受管进程，所有公开 HTTP 接口均遵循只写不读回明文的契约。

### 能力查询与写入保护

`GET /ops/api/environment` 在通过管理员会话鉴权后返回能力状态与基础变量清单：

- **能力状态字段**：包含 `enabled`、`restart_required`、`backend_available` 与 `reason`。管理开关 `QUICKQUIP_ENV_MANAGEMENT_ENABLED` 按进程启动时的取值固定：开关关闭时返回 `enabled=false`、`restart_required=true`（提示启用后需重启服务）且 `reason="environment_management_disabled"`；开关已开启但无法连接 `env-agent` 时返回 `backend_available=false`、`reason="environment_backend_unavailable"`（此时启用了环境管理的进程保持启动时凭据，拒绝静默回退）。上述两种不可用状态均返回空的 `variables`、`consumers` 与 `suggestions`，前端据此展示对应引导。
- **变更预览与提交**：管理开关关闭时，`POST /preview`、`POST /changes` 及 `/operations/*` 均直接返回 HTTP `409`（`code="environment_management_disabled"`）。`POST /changes` 要求二次验证管理员密码（复用登录防爆破限流计数）并记录变更变量名审计日志。
- **变量生效模式（`mode`）**：每个变量按当前配置引用归类为四档之一：
  - `hot`：已适配进程内热更新的运行参数，确认快照版本后状态变为 `loaded`。
  - `credential`：LLM 草稿或已发布渠道显式引用的认证凭据变量（仅按配置引用关系判定，变量名后缀不参与归类），确认版本后状态变为 `loaded`。
  - `restart`：已识别的进程启动期或容器编排参数，需要重启或重建服务后生效。
  - `unknown`：尚未匹配任何已知消费关系的自定义变量，同步写入进程环境快照后状态显示为 `synced`。保存新的渠道引用后，再次查询列表或操作状态会按最新引用关系重新计算分类。

### 只读消费目录（`include_directory=true`）

请求 `GET /ops/api/environment?include_directory=true` 时，响应在基础字段之上附加只读消费目录 `taxonomy`、`directory` 与 `directory_errors`（未传该查询参数时不构建目录；管理关闭或后端不可用时三者均为空数组）。`taxonomy` 提供稳定的“领域 → 分组”二级分类树；`directory` 按变量名升序唯一归并根目录 `.env` 已定义项、LLM／多模态配置引用项、内置固定变量目录、`.env.example` 模板项及待删除标记项。配置文件中已引用但根目录 `.env` 尚未定义的变量同样收录进 `directory`（其进程 `states` 为空对象），基础 `variables` 列表则只包含环境存储中实际存在的条目。

每个 `directory` 条目的核心契约字段如下：

| 字段 | 类型与结构 | 契约说明 |
|---|---|---|
| `name` / `assigned` / `mode` / `warning` / `states` | 基础状态字段 | 变量的当前赋值布尔值、生效模式、告警提示，以及 Bot／Web 进程快照或启动值比对状态 |
| `groups` | `string[]` | 归属的 `taxonomy` 分组 ID 列表；无任何已知归属时归入 `unknown.unidentified` |
| `definition` | `{present, value_state, managed_literal, deletion_marker, conflict?}` | 根 `.env` 解析状态：`value_state` 取 `missing`、`bare`、`empty` 或 `nonempty`；当活跃定义与删除标记同时存在时标记 `conflict=true`，写入前须先解决冲突 |
| `allowed_actions` | `string[]` | 按存储存在性计算的允许操作：活跃定义允许 `["replace", "empty", "delete"]`；未定义或带删除标记的可创建项允许 `["create"]`；未定义的内部编排变量为 `[]` |
| `description` / `value_type` / `alias_of?` / `suggest?` / `default_present?` / `default_origin?` | 内置目录元数据 | 命中内置目录时补充用途说明、值类型、规范变量名映射（如 `ONEBOT_V11_*` 别名通过 `alias_of` 指向规范名）及模板默认值存在性布尔标记 |
| `evidence_flags` | `{internal?, example_only?, computed_name?}` | 证据特征标记：`internal` 表示容器／进程内部变量（未定义时不开放根 `.env` 创建）；`example_only` 表示仅见于 `.env.example` 且无实际消费引用（出现真实引用后自动清除）；`computed_name` 表示 `api_key_env` 使用了 `${...}` 插值计算变量名 |
| `relations` | 消费关系对象数组 | 每条记录 `component`、`object_id`、`field_path`、`config_scope`（`draft` / `published` / `file` / `code` / `template`）、声明的 `enabled` 与 `required`（无法静态确定时为 `null`）、`name_kind`、`source_name`、`raw_expression`、目标服务与传递通道、`required_action` 及 `observation="not_observed"` |
| `sources` | 来源证据对象数组 | 记录 `llm_config`、`generation_file`、`code`、`compose`、`compose_interpolation`、`dockerfile` 或 `root_env_file` 的来源类型、上下文、字段路径与解析时机 |

消费关系中的 `required_action` 按目标生效边界精确标注：LLM 未发布草稿引用标为 `publish`；已发布 LLM 凭据及按任务展开的字段标为 `next_task`；需要重新编译并重建连接资源的 MCP 等配置标为 `apply`；`config/generation.toml` 中的进程环境引用标为 `restart_or_recreate`；公开编排模板中的静态覆盖与镜像构建参数分别标为 `edit_compose_then_recreate` 与 `rebuild_image`。

消费目录完全基于静态文件与配置文档投影构建：仅解析原始 LLM 草稿／已发布文档、`config/generation.toml`、内置变量表以及随仓分发的 `prod.example/docker-compose.yml`、`docker-compose.example.yml` 和公开 Dockerfile。解析过程只提取显式声明的凭据变量名与 `${NAME}` 插值规范记号（嵌套请求体或子进程字面量中的同名字符串不视为根环境变量引用），且 `raw_expression`、模板默认值等字段绝不携带默认值原文、完整 Header、URL 或展开后的配置值；真实生产目录 `prod/` 下的私有覆盖与宿主机实时容器环境均保持 `observation="not_observed"`。

若单个配置文件不可读或存在语法错误，其余目录项照常返回，`directory_errors` 仅记录 `{component, code}` 固定错误码而不回传异常堆栈、配置正文或宿主机路径。整个目录响应共享 `env-agent` 私有传输层的 15 秒超时与 2 MiB 载荷上限，超限时直接按后端不可用或响应过大报错，不做静默截断。
