# LLM 配置后端接口

LLM 配置使用 `data/llm_config.db`。Web Admin、CLI 与 bot 通过同一个配置应用服务协调修订、快照与控制任务。人格文件、Skill 内容、群覆盖、历史记录、用量及 Trace 保持各自存储职责。

接口前缀为 `/ops/api/llm-configuration`，需要现有管理员会话 Cookie `quickquip_admin_session`。写请求必须携带同源 `Origin` 或 `Referer`。请求体上限为 1 MiB，分块传输也执行此限制。完整机器契约见 [OpenAPI JSON](llm-configuration.openapi.json)；运行中的管理 API 在 `/openapi.json` 提供同一字段约束。

前端设计与操作流程见[前端交付契约](llm-configuration-frontend.md)，其中说明中文字段含义、参数继承控件、保存与应用、冲突处理及设计验收场景。

配置交换格式为 JSON，`format_version` 当前为 `1`。顶层字段为 `providers`、`style_profiles`、`pricing`、`routes` 与 `settings`。渠道身份为公开 `id`，模型身份为 wire 名称；引用使用 `{provider_id, model}`，支持包含 `/` 的模型名称。认证信息保存 `.env` 变量名称或 `${VARIABLE}` 引用。导出、字段错误及审计日志保留引用，运行时展开值不进入接口。

## 修订与读写

| 请求 | 响应与行为 |
|---|---|
| `GET /metadata` | 请求参数和设置字段的类型、范围、枚举、默认值、继承及覆盖能力 |
| `GET /?source=draft` | `{revision, document}`；省略 source 使用 draft，source 支持 published 或快照修订号；实际 URL 使用前缀且无末尾斜杠 |
| `PUT` 前缀 | `{expected_draft_revision, document}`，完整替换草稿，返回 `{revision, document}` |
| `GET /providers` | `{revision, providers}` |
| `GET /providers/{id}` | 聚合 `{revision, provider, pricing, effective_parameters}`；包含匹配的渠道价格与纯模型名回退价格，以及按模型名索引的有效参数 |
| `PUT /providers/{id}` | `{expected_draft_revision, value: provider}`，新增或完整替换渠道 |
| `PATCH /providers/{id}` | `{expected_draft_revision, fields}`，省略字段保持原值，渠道 id 保持稳定 |
| `DELETE /providers/{id}?expected_draft_revision=N` | 删除无引用渠道；引用冲突附上依赖列表 |
| `PUT /providers/{id}/models` | `{expected_draft_revision, value: models}`，完整替换有序模型条目 |
| `PUT /providers/{id}/aliases` | `{expected_draft_revision, value: aliases}`，完整替换有序别名条目 |
| `GET /providers/{id}/effective?model=wire` | `{revision, parameters}`，每个字段包含 `configured/value/source` |
| `GET /sections/{section}` | `{revision, value}`，section 为 style_profiles、pricing、routes 或 settings |
| `PUT /sections/{section}` | `{expected_draft_revision, value}`，完整替换对应配置域 |
| `PUT /settings/{name}` | `{expected_draft_revision, value}`，替换单一设置域 |
| `POST /batch` | `{expected_draft_revision, changes:[{section,value}]}`，一次事务完整替换多个配置域 |

所有草稿有效修改增加修订号。相同内容保存保持原修订号。版本冲突返回 `409 revision_conflict`；调用方重新取得草稿并处理冲突后提交。渠道或模型参数的 `null` 表示继承，`false`、合法零值、空字符串及空对象表示显式值。`extra_body` 覆盖整个对象。

`/llm-effort` 兼容入口读取草稿修订；`PUT /llm-effort/{id}` 需要 `{expected_draft_revision, effort}`，保存后返回 `effect: saved_draft`。旧 `/config/llm` 入口返回 `410 llm_configuration_migrated`。

## 校验、导入与历史

| 请求 | 响应与行为 |
|---|---|
| `POST /validate` | `{document?}`；省略 document 校验草稿，合法时返回 `{valid:true,warnings,dependencies}`，非法文档通过错误响应报告 |
| `GET /dependencies?source=draft` | `{dependencies:[{field_path,target}]}` |
| `GET /diff?source=draft&target=published` | 校验报告加 `{changes:[{field_path,before,after}],components}`；before 为 target，after 为 source；components 为 `{mcp_reconnect:boolean,reschedule:string[]}` |
| `POST /import/preview` | `{expected_draft_revision,document}`，返回规范化 document、差异、警告及依赖，不写入 |
| `POST /import` | 相同请求格式，完整替换草稿；应用为独立操作 |
| `GET /export?source=draft` | 直接返回配置 JSON，支持 published 或快照修订号 |
| `GET /history` | `{snapshots:[{revision,created_at}]}`；第一版保留全部执行快照 |
| `POST /history/{revision}/restore` | `{expected_draft_revision}`，将历史内容保存为当前草稿，修订号保持递增 |

历史列表包含应用和探测使用过的快照，是否成功发布需结合任务结果与发布版本判断。恢复内容与当前草稿相同时保持原修订号。差异中的数组可能整体返回，前端可按公开身份组织增删改展示。

未配置价格产生 `price_missing` 警告。价格为零表示免费；缺失价格为未定价；缓存价格 `null` 使用输入价格。价格修改影响后续任务，历史费用保持原值。

## 应用、探测与运行状态

`POST /apply` 接受 `{expected_draft_revision,request_id}`，返回 HTTP `202` 与控制任务。任务创建时绑定不可变目标快照，继续编辑草稿不会改变该任务。任意时刻最多一个未结束的应用；再次提交返回 `409 operation_conflict`。相同请求编号和目标重复提交返回原任务。

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

`GET /operations/{id}` 查询任务，`GET /operations?limit=20` 返回最近任务，`POST /operations/{id}/cancel` 取消排队任务。状态为 `queued/running/succeeded/failed/cancelled`，只有排队任务可取消。领取令牌供 bot 内部续租与结果写入，Web 响应排除该令牌。`202` 表示已经入队，最终结论通过任务状态取得。

`POST /probe` 接受 `{source,provider_id,model,request_id}`，使用 bot 环境执行单次模型请求，不发布草稿。响应额外包含 `may_charge: true` 和 `automatic_retry: false`。运行中探测被中断后返回 `probe_result_unconfirmed`，不会自动重发。`POST /diagnostics/providers/probe` 使用相同任务契约；`POST /diagnostics/sample-request` 支持 `system_prompt`、`user_prompt`、`stream` 和 `max_output_tokens` 等采样请求字段。

`GET /status` 返回数据库 schema、草稿及发布版本，以及 bot 的 `boot_id`、`loaded_revision`、应用版本、心跳时间、观察时间及组件状态。bot 心跳超过 20 秒时 `stale: true`；尚未回报时 `bot: null`。MCP 的连接及工具发现状态属于组件状态，配置版本接纳和远端组件就绪分别回报。

status 不包含活动任务字段，任务从 `/operations` 查询。返回的时间为 Unix 秒。有效参数的 `configured` 通常为 `{provider,model}`，`context_window` 的 configured 为整数或 null；有效值仅解析配置层级，不含具体调用或会话覆盖。

`GET /environment?source=draft` 返回配置引用的变量名、bot 观察到的已配置布尔值及 `available/stale` 状态。bot 尚未观察到变量时 `configured: null`。接口不返回变量内容。

## 错误契约

新配置接口统一返回 `{code,message,field_path,details}`。字段错误为 `422`，修订、依赖或控制任务冲突为 `409`，找不到快照或任务为 `404`，请求体超限为 `413`。认证与同源保护保持 `401/403`。字段错误排除客户端认证输入值。

```json
{
  "code": "revision_conflict",
  "message": "Draft changed since it was read",
  "field_path": "",
  "details": {"expected": 7, "actual": 8}
}
```

稳定错误代码包括 `invalid_field`、`dependency_conflict`、`literal_secret`、`revision_conflict`、`operation_conflict`、`database_busy`、`unsupported_schema`、`database_corrupt`、`stale_claim` 和 `probe_result_unconfirmed`。前端按 code 处理状态，message 用于展示。

更新约束或路由后运行 `python scripts/ci/export_llm_configuration_openapi.py`，同时提交生成的 OpenAPI 文件。接口回归使用隔离 SQLite 数据库与管理员会话，覆盖跨进程初始化、事务、租约、并发编辑、HTTP 鉴权、同源保护、导入预览与敏感数据边界。

## 请求指纹配置

Provider 的固定字段 `client_fingerprint` 缺省为 `default`，不可通过模型参数覆盖。metadata 的 `client_fingerprints` 数组提供 `id`、`label` 和支持的 `protocols`；Web 按协议提供选择。`settings.runtime.client_cluster` 是可选全局字符串，沿用草稿、保存和应用流程。四个 `x-quickquip-*` 专有头由自有 Profile 管理，附加头冲突返回 `profile_owned_header`。Profile 文件与安装身份契约见[请求指纹 Profile](../admin/client-fingerprints.md)。配置 schema 1 在初始化中事务性升级为 2，交换格式仍为 1。
