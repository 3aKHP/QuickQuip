# LLM 配置后端接口

本文供配置 API 调用方与后端维护者查阅。受管配置正文及本机修订历史存储在 `config/managed/config.db`，控制任务绑定的不可变输入快照、发布版本指针与 Bot 运行状态存储在 `data/config_runtime.db`。Web Admin、CLI 与 Bot 通过 `ConfigService` 协作，存储归属与跨进程事务边界见[配置与运行存储](configuration-storage.md)。

接口统一挂载在 `/ops/api/llm-configuration` 前缀下，所有请求均须携带有效管理员会话 Cookie `quickquip_admin_session`，写操作还须通过同源 `Origin` 或 `Referer` 校验。请求体大小上限为 1 MiB（含分块传输）。完整机器可读契约见随仓维护的 [OpenAPI JSON](llm-configuration.openapi.json)（修改字段约束或路由后须运行 `python scripts/ci/export_llm_configuration_openapi.py` 同步更新；线上管理进程不暴露 `/docs`、`/redoc` 或 `/openapi.json`）。

前端表单语义、参数继承交互与验收清单见[前端交付契约](llm-configuration-frontend.md)；核心概念定义见[项目术语表](../glossary.md#config-draft)，在线与离线发布机制的依据见 [ADR-0023](adr/0023-online-and-offline-configuration-publication.md)。

配置交换 JSON 当前 `format_version` 为 `2`，顶层固定包含 `providers`、`style_profiles`、`pricing`、`routes` 与 `settings`。渠道以公开 `id` 为稳定身份，模型以发往上游的 wire 名称为身份，跨处引用统一使用 `{provider_id, model}` 对象（兼容含 `/` 的模型名）。涉密认证字段只允许保存 `.env` 变量名或 `${VARIABLE}` 引用；导出文件、错误详情与审计日志均保留符号引用，绝不回传展开后的密钥明文。

读取历史快照、导入配置或编译旧版 `format_version = 1` 文档时，后端按确定性规则将旧价格升级为 `format_version = 2`（要求每条价格明确绑定已存在的 `provider_id`）：形如 `渠道ID/模型` 的兜底条目归入对应渠道（若该渠道已存在同模型定价则丢弃兜底项）；不含渠道前缀的纯模型名仅在全局恰好只有一个尚未定价的渠道配置了该模型时自动归入该渠道，其余存在歧义或指向不存在渠道的旧条目一律移除。底层不可变历史快照保持原始字节不变，读取接口返回升级后的规范化结构。

## 修订与读写

| 请求 | 响应与行为 |
|---|---|
| `GET /metadata` | 返回请求参数与 `settings` 字段的类型、数值范围、枚举值、默认值、继承规则及可用 `client_fingerprints` |
| `GET` 根路径（`?source=draft`） | 返回 `{revision, document}`；省略 `source` 默认读取 `draft`，也支持传 `published` 或具体快照修订号（根路径无末尾斜杠） |
| `PUT` 根路径 | 请求体 `{expected_draft_revision, document, note?}`，完整替换当前草稿并返回 `{revision, document}` |
| `GET /providers` | 返回 `{revision, version, providers}` 渠道摘要列表 |
| `GET /providers/{id}` | 聚合返回 `{revision, provider, pricing, effective_parameters}`，其中 `pricing` 仅含该渠道价格，`effective_parameters` 按模型 wire 名索引 |
| `PUT /providers/{id}` | 请求体 `{expected_draft_revision, value: provider}`，新增或完整替换指定渠道 |
| `PATCH /providers/{id}` | 请求体 `{expected_draft_revision, fields}`，局部更新渠道字段（未传字段保持原值，渠道 `id` 不可修改） |
| `DELETE /providers/{id}?expected_draft_revision=N` | 删除无外部引用的渠道；存在引用依赖时返回冲突及依赖路径列表 |
| `PUT /providers/{id}/models` | 请求体 `{expected_draft_revision, value: models}`，完整替换该渠道的有序模型列表 |
| `PUT /providers/{id}/aliases` | 请求体 `{expected_draft_revision, value: aliases}`，完整替换该渠道的有序模型别名列表 |
| `GET /providers/{id}/effective?model=wire` | 返回 `{revision, parameters}`，逐字段给出 `{configured, value, source}` |
| `GET /sections/{section}` | 返回 `{revision, value}`，`section` 支持 `style_profiles`、`pricing`、`routes`、`settings` |
| `PUT /sections/{section}` | 请求体 `{expected_draft_revision, value}`，完整替换对应顶层配置域 |
| `PUT /settings/{name}` | 请求体 `{expected_draft_revision, value}`，完整替换 `settings` 下的单个子域 |
| `POST /batch` | 请求体 `{expected_draft_revision, changes: [{section, value}]}`，在单次事务中原子替换多个配置域 |

`qqsync` 执行配置同步维护期间，所有草稿修改、在线应用及作用域覆盖写请求均返回 HTTP `409`（`code="configuration_busy"`），调用方需等待同步提交或恢复完成后重试。

每次实际改变草稿正文的写操作都会递增 `revision`；提交内容与当前草稿完全一致时保持原修订号不变。乐观锁校验失配时返回 `409 revision_conflict`，由调用方重新拉取最新草稿合并修改后再提交。渠道与模型 `parameters` 中显式写入 `null` 表示向上层继承；`false`、合法 `0`、空字符串 `""` 与空对象 `{}` 均表示显式覆盖值（其中 `extra_body` 每次按整块对象替换）。`/effective` 返回的每个字段通常以 `{provider, model}` 记录 `configured`，唯独模型专有的 `context_window` 直接以整数或 `null` 作为 `configured`；有效值仅反映静态配置层级解析结果，不包含单次调用参数或群聊／私聊会话覆盖。

草稿与离线部署快照共用同一个单调递增的整数编号池。由于离线部署可在不覆盖后台独立编辑草稿的前提下直接发布新快照，`draft_revision` 可能小于 `published_revision`；下一次保存草稿时会自动跳到全局已分配最大编号之后分配新修订号。

思考档位快捷接口 `/ops/api/llm-effort` 同样读写当前草稿：`PUT /llm-effort/{id}` 接收 `{expected_draft_revision, effort}`，保存成功后返回 `effect: "saved_draft"`。早期已废弃的 `/ops/api/config/llm` 路由固定返回 HTTP `410`（`code="llm_configuration_migrated"`）。

## 校验、导入与历史

| 请求 | 响应与行为 |
|---|---|
| `POST /validate` | 请求体 `{document?}`（省略时校验当前草稿）；合法时返回 `{valid: true, warnings, dependencies}`，存在结构或引用错误时直接返回标准错误响应 |
| `GET /dependencies?source=draft` | 返回 `{dependencies: [{field_path, target}]}` 引用关系表 |
| `GET /diff?source=draft&target=published` | 返回校验报告及 `{changes: [{field_path, before, after}], components}`，其中 `before` 对应 `target`、`after` 对应 `source`，`components` 结构为 `{mcp_reconnect: boolean, reschedule: string[]}` |
| `POST /import/preview` | 请求体 `{expected_draft_revision, document}`，仅在内存中执行规范化、版本升级、校验与差异计算，不落盘写入 |
| `POST /import` | 请求格式与预览相同，校验通过后完整替换当前草稿（应用仍为独立操作） |
| `GET /export?source=draft` | 直接返回纯净配置交换 JSON，支持 `draft`、`published` 或指定快照修订号 |
| `GET /history` | 返回 `{snapshots: [{revision, created_at, saved_at, note}]}` 不可变执行快照列表 |
| `PUT /note` | 请求体 `{source, note}`（`source` 支持 `draft`、`published` 或快照修订号），更新备注而不递增修订号 |
| `POST /history/{revision}/restore` | 请求体 `{expected_draft_revision}`，将指定历史快照内容写回当前草稿并分配递增修订号（内容与当前草稿一致时保持原修订号） |

`/history` 包含在线应用、离线发布与模型探测曾经固定过的全部执行快照；某条快照是否成为线上生效配置，需结合对应控制任务结果与 `published_revision` 判断。`/diff` 对有序数组可能整段返回前后值，前端可按元素的业务主键整理增删改视图。

模型计费严格按 `(provider_id, model)` 精确匹配请求发出的配置模型 ID（上游响应中回报的实际模型版本号仅写入观测记录）。校验器对缺少定价的已启用模型给出 `price_missing` 警告，对指向渠道未配置模型的孤立定价给出 `price_orphan` 警告，对导入 `format_version = 1` 时自动归属或剔除的价格逐条给出 `pricing_upgraded` 警告。单价填 `0` 表示免费，缺少定价条目表示未定价，缓存单价填 `null` 表示按基础输入单价计费；修改单价只影响后续新产生的调用，历史账单保持落库时计算的金额。

## 版本标记

后台界面使用“YYYY-MM-DD HH:mm (备注)”向管理员展示版本，底层接口使用整数 `revision` 做乐观锁并发检查与快照寻址。`config_revisions` 表为每个草稿修订保存时间戳 `saved_at` 与单行备注 `note`（上限 120 字符，换行符自动折为空格），各状态接口统一以 `{saved_at, note}` 结构返回；快照上的 `created_at` 则记录任务固定该执行快照的时刻。保存草稿或发起应用时均可附带 `note`：省略 `note` 时，尚未发布过的连续草稿编辑沿用上一草稿修订的备注，而已发布版本之后的首次新草稿保存自动清空备注从头开始。

`config_revisions`、草稿文档与历史快照均属当前部署环境的受管配置数据，任务队列与心跳保存在独立的 `data/config_runtime.db` 中；旧版本安装的停服升级步骤见[存储迁移](../admin/storage-migration.md)。

## 应用、探测与运行状态

`POST /apply` 接收 `{expected_draft_revision, request_id, note?}`，固定当前草稿为不可变目标快照并入队控制任务，返回 HTTP `202`（此后再编辑草稿不会影响已入队任务）。全局同一时刻最多允许存在一个未结束的应用任务：并发提交新应用返回 `409 operation_conflict`；使用相同 `request_id` 与相同目标修订重复提交则命中幂等逻辑，直接返回原任务对象：

```json
{
  "id": "example-operation-id",
  "kind": "apply",
  "target_revision": 8,
  "status": "queued",
  "stage": "queued",
  "payload": {},
  "result": null,
  "error": null,
  "created_at": 1791680000.0,
  "updated_at": 1791680000.0
}
```

任务查询与控制端点包括 `GET /operations/{id}`、`GET /operations?limit=20` 与 `POST /operations/{id}/cancel`。任务状态流转为 `queued` / `running` / `succeeded` / `failed` / `cancelled`，仅处于 `queued` 状态的排队任务允许取消。Bot 进程领取任务时在运行库内签发私有**领取令牌**（`claim_token`）用于心跳续租与写回终态，Web 接口响应会自动剥离该内部字段。HTTP `202` 仅代表任务入队成功，配置是否真正生效需轮询任务终态及 `/status` 回报确认。

`POST /probe` 接收 `{source, provider_id, model, request_id}`，委托 Bot 进程按指定配置来源发送一次真实模型探活请求（不修改已发布指针），响应附加 `may_charge: true` 与 `automatic_retry: false`；若探活执行中途进程中断，任务收束为 `probe_result_unconfirmed` 且禁止自动重发。诊断路由 `POST /ops/api/diagnostics/providers/probe` 复用同一探活任务契约；采样测试端点 `POST /ops/api/diagnostics/sample-request` 额外支持自定义 `system_prompt`、`user_prompt`、`stream` 与 `max_output_tokens`（默认 `512`，取值范围 `1..16384`），并自动继承所选渠道／模型的有效 `temperature`（未显式配置时默认不下发）。

`GET /status` 汇总返回配置库 `schema_version`、`draft_revision`／`draft_version`、`published_revision`／`published_version`，以及 Bot 最近一次心跳上报的 `boot_id`、`application_version`、`loaded_revision`／`loaded_version`、`heartbeat_at`、`observed_at`（时间戳单位均为 Unix 秒）和各子组件状态（`core`、`mcp`、`environment`）。Bot 尚未首次上报时 `bot` 为 `null`；距离上次心跳超过 20 秒时标记 `stale: true`。活动中的控制任务统一从 `/operations` 查询。

`GET /environment?source=draft` 返回目标配置引用的环境变量名称列表、Bot 进程观察到的赋值布尔状态（尚未观察到新变量时 `configured: null`）以及 `available`／`stale` 标记，不返回任何环境变量明文值。

## 部署服务入口

Python 部署与同步模块通过 `ConfigService.prepare_deployment` 固定部署目标快照，允许线上同时保留另一份独立的后台编辑草稿。离线发布方法 `ConfigService.publish_offline` 要求调用方传入仍然有效的 **Bot 停服证明**（由持有 Bot 生命周期独占锁的进程签发）：方法校验本地配置文件、依赖资产与凭据齐全后直接更新运行库发布指针，返回 `{published_revision, loaded: false}`；相同 `request_id` 重试返回原结果，若运行库中存在未结束的在线应用任务则抛出操作冲突。

## 错误契约

配置管理与关联诊断路由的业务异常统一返回结构化 JSON `{code, message, field_path, details}`：字段与引用校验失败返回 HTTP `422`，版本乐观锁、引用依赖或并发任务冲突返回 `409`，目标快照／渠道／任务不存在返回 `404`，请求体超限返回 `413`；会话未登录与同源校验失败保持 `401`／`403`。所有校验错误详情均自动剔除客户端提交的认证敏感字面量。

```json
{
  "code": "revision_conflict",
  "message": "Draft changed since it was read",
  "field_path": "",
  "details": {"expected": 7, "actual": 8}
}
```

稳定机器错误码包括 `invalid_field`、`dependency_conflict`、`literal_secret`、`revision_conflict`、`operation_conflict`、`configuration_busy`、`database_busy`、`unsupported_schema`、`database_corrupt`、`stale_claim`、`probe_result_unconfirmed`、`profile_owned_header` 与 `profile_owned_body`。调用方应以 `code` 驱动分支逻辑，`message` 仅供界面提示。

修改接口约束后须重新运行 `python scripts/ci/export_llm_configuration_openapi.py` 并提交更新后的 OpenAPI 文件；回归测试采用隔离临时 SQLite 库与真实会话鉴权，覆盖跨进程建表、乐观锁竞争、任务租约、同源保护、导入预览与敏感字段脱敏。

## 请求指纹配置

渠道固定字段 `client_fingerprint` 默认为 `"default"`，仅允许在渠道层级配置（模型 `parameters` 中传入该键会被校验器拒绝）。默认档位下，`openai`、`openai_responses`、`claude`、`gemini` 四类协议分别映射至 OpenCode 2、Codex、Claude Code 与 Gemini CLI 模板策略，并与显式指定同名模板适用完全一致的受管字段保护。`GET /metadata` 的 `client_fingerprints` 数组返回各模板的 `id`、`label` 与适用 `protocols` 供前端按协议筛选。

全局标识字段位于 `settings.runtime`，随配置文档与不可变发布快照整体持久化并经应用任务生效：

- `client_cluster`：可选全局集群标识字符串；自有 `quickquip` Profile 独占管理四个 `x-quickquip-*` 请求头，渠道 `headers` 手工重名冲突时返回 `422 profile_owned_header`。
- `claude_code_device_id`：可选 64 位十六进制字符串（保存时统一规范为小写，留空使用 `data/client_identity.json` 中的持久随机设备身份）。启用 Claude Code 自动 Body 策略时，手工在 `extra_body` 覆盖 `system`、`messages`、`tools` 或受管 `metadata.user_id` 返回 `422 profile_owned_body`，非法 `metadata` 类型返回 `422 invalid_field`。
- `gemini_cli_install_id`：可选小写 UUIDv4 字符串，留空使用持久随机安装身份。

模板编辑与运维指引见[管理员指南](../admin/client-fingerprints.md)，底层投影契约见[请求指纹与协议转换实现](client-fingerprints.md)。

## 作用域配置与私聊状态

`/ops/api/group-settings` 管理群聊（纯数字群号）与私聊（`private:<QQ>`）的作用域级 LLM 参数覆盖，各字段按存储职责分库读写：

- **常规覆盖字段（`config/managed/config.db` `scope_settings`）**：保存模型、渠道、人格、记忆开关、分段交付开关、触发前缀与思考档位等覆盖项；请求体显式传 `null` 清除单项覆盖，省略字段保持原值不变。群聊的 `enabled` 为三态布尔覆盖；私聊条目固定返回 `enabled: null` 并附带实时 `session_active` 状态，向 `private:*` 提交 `enabled` 返回 `422`。
- **群历史查询开关（`data/llm.db` `group_history_flags`）**：三态字段 `history_enabled`（`true` / `false` / `null`）仅适用于群聊作用域，独立持久化在 `data/llm.db` 中（`null` 表示清除本群覆盖、恢复跟随全局 `settings.group_history.enabled`）。私聊条目读取时固定返回 `history_enabled: null`；向 `private:*` 作用域提交 `history_enabled` 返回 HTTP `422`。
- **整组清空联动**：调用 `DELETE /ops/api/group-settings/{group_id}` 清空某个群聊的全部参数覆盖时，后端会同步清除 `scope_settings` 行与 `data/llm.db` `group_history_flags` 中的本群历史开关记录；清空私聊覆盖则保留该用户的私聊活跃状态与对话历史。

独立路由 `GET /ops/api/private-sessions/{user_id}/state` 返回 `{active: boolean}`，同路径 `PUT` 接收 `{active: boolean}` 用于在后台暂停或恢复指定用户的私聊响应（不清空对话历史），共享管理员会话鉴权与同源写入保护。
