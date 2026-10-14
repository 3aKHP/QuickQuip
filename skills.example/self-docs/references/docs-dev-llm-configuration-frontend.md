<!-- Generated from docs/dev/llm-configuration-frontend.md; do not edit -->

# LLM 配置管理前端交付契约

本页供负责 QuickQuip 管理前端设计与实现的 Agent 使用。目标是让管理员能理解配置、完成修改，并确认机器人实际使用了哪个版本。页面结构、视觉风格和控件布局由前端设计 Agent 决定；本文规定配置含义、操作结果和接口契约。

开发入口为 `/ops/#/llm-config`。后端接口、数据库和控制任务已经实现，前端可以重新组织现有页面。完整字段约束见 [OpenAPI](llm-configuration.openapi.json)、[API 文档](llm-configuration-api.md)和[公开 JSON 示例](../../config/llm.json.example)。管理员操作背景见[配置管理说明](../admin/llm-configuration.md)。

## 1 用户需要完成的事

管理员应能顺利完成以下操作：

1. 添加一个渠道，填写地址、协议和密钥变量名，添加模型并选择渠道默认模型。
2. 找到某个模型，调整它的请求参数，理解哪些值继承自渠道。
3. 选择默认聊天渠道，以及报告、快速判定和图片预处理使用的模型。
4. 保存草稿，查看与当前已发布配置的差异，再发起应用。
5. 确认 Bot 是否在线、是否加载了目标版本、MCP 等组件是否就绪。
6. 导入配置前检查变更，导出配置，或把历史快照恢复成草稿。

界面文案使用中文业务名称。原始字段名可出现在帮助文字或高级视图中。普通操作通过表单、选择器、列表和顺序调整完成；JSON 用于导入导出和适合自由对象的高级字段。

### 信息组织建议

以下分区可作为设计起点，具体导航与布局由前端决定。

| 分区 | 用户看到的内容 |
|---|---|
| 概览与变更 | 未保存编辑、草稿版本、已发布版本、Bot 加载版本、待应用差异、当前应用任务 |
| 渠道与模型 | 可搜索的渠道列表、渠道连接信息、模型列表、别名、默认参数、模型覆盖和价格 |
| 模型选择 | 默认聊天渠道、四类报告的候选顺序、快速判定、图片预处理 |
| 行为与能力 | 触发方式、工具、Skill 设置、MCP 服务、记忆与回复行为、报告设置 |
| 高级参数 | 重试、上下文纪元、输入与媒体预算、协议特有参数 |
| 配置交换与历史 | JSON 导入预览、导出、历史快照、任务记录 |

渠道较多时，先选择渠道，再加载其详情；模型较多时，按需展开模型。日常参数和高级参数应具有清楚的层次。列表需要搜索、空状态和停用标记。

## 2 保存与应用

### 四种状态

| 名称 | 含义 | 用户可见文案示例 |
|---|---|---|
| 页面中的编辑 | 当前浏览器表单里的修改，还未提交 | “有未保存的修改” |
| 草稿 `draft_revision` | 已保存到数据库，等待应用 | “草稿 2026-10-14 15:30 (接入新渠道)” |
| 已发布 `published_revision` | Bot 已接纳的发布指针，重启从这里加载 | “已发布 2026-10-12 09:05” |
| Bot 加载 `loaded_revision` | Bot 最近心跳回报的实际内存版本 | “Bot 已加载 2026-10-12 09:05” |

修订号供接口检查并发修改和识别快照；界面使用保存时间与备注标记版本。版本标记由 `draft_version`、`published_version`、`loaded_version` 及历史条目的 `{saved_at, note}` 组合为「YYYY-MM-DD HH:mm (备注)」；保存时间未知时显示“未记录时间”。备注随保存或应用提交，也可通过 `PUT /note` 修改任意快照修订。

“保存草稿”和“应用配置”是独立操作。保存成功后显示“草稿已保存”；收到应用任务的 HTTP `202` 后显示“已提交应用，等待 Bot 执行”。应用任务成功、Bot 心跳新鲜且加载版本符合目标时，才展示实际加载成功。发布指针和内存切换之间可以短暂出现版本差异。

新任务使用应用后的版本。已经开始的对话、报告和计费继续使用任务开始时的配置与价格。重启 Bot 加载已发布快照，草稿继续等待应用。

### 保存流程

1. 读取草稿，保留返回的 `revision` 作为编辑基准，同时保留一份基准内容。
2. 用户修改本地表单，显示未保存状态。
3. 保存请求带上 `expected_draft_revision`。
4. 成功后采用后端返回的规范化 `document` 和新 `revision`，更新编辑基准。
5. 内容没有变化时，后端可以返回原修订号。

修订号覆盖整个配置库。即使两个管理员编辑不同渠道，也可能发生版本冲突。遇到 `409 revision_conflict`，保留本地编辑，提供重新读取、比较和处理冲突的入口；用户确认处理方式后再保存。避免自动重试覆盖他人的修改。切换页面、关闭编辑器或恢复历史时，应处理未保存内容。

### 应用流程

1. 用户先保存要应用的内容，再检查草稿与已发布配置的差异。
2. 提交明确的草稿修订号和唯一 `request_id`。
3. 记录返回的操作 ID，轮询任务与运行状态。
4. 应用期间可以继续编辑和保存。任务始终使用提交时固定的快照。
5. 同时最多一个未结束的应用任务；展示已有任务进度，暂缓提交新的应用。

例如应用目标是 15:30 保存的修订，用户随后在 15:40 再次保存。任务成功后，页面显示 Bot 已加载 15:30 版本，并提示 15:40 草稿等待应用。

## 3 配置对象与表单语义

JSON 顶层固定为 `format_version`、`providers`、`style_profiles`、`pricing`、`routes`、`settings`。`format_version` 当前为整数 `2`；导入 `1` 时后端按确定规则升级价格并在预览中逐条说明。

### 渠道

渠道是一套连接信息及其模型列表。公开 ID 保持稳定，API 的 PATCH 不允许修改 ID。

| 字段 | 人类可读名称与规则 |
|---|---|
| `id` | 渠道 ID；唯一，仅含英文字母、数字、点、下划线、连字符 |
| `protocol` | 协议；`openai`、`claude`、`gemini`、`openai_responses` |
| `base_url` | 服务地址；必填 |
| `api_key_env` | 密钥环境变量名，如 `OPENAI_API_KEY`；必填，填写变量名称 |
| `default_model` | 渠道默认模型；必须是该渠道模型列表中的真实模型名 |
| `enabled` | 渠道是否启用 |
| `client_fingerprint` | 客户端 Profile；从 metadata 返回的当前协议可用模板中选择，缺省为 `default` |
| `auth_method` | 认证方式；`api_key` 或 `bearer` |
| `headers` | 额外请求 Header；键值编辑器，认证值使用环境变量引用 |
| `fallback_urls` | 有序备用地址列表 |
| `proxy` | 代理地址；空字符串表示没有显式代理 |
| `parameters` | 渠道默认请求参数 |
| `models`、`aliases` | 有序模型列表、有序别名列表 |

创建渠道的编辑流程需要同时准备至少一个模型和默认模型，提交时形成合法渠道。停用保留配置、会话和历史记录。删除可能受到默认选择、报告候选、别名等引用限制，需要向用户展示依赖并引导处理。

### 模型与别名

| 字段 | 含义 |
|---|---|
| `model` | 发给上游的真实模型名，也称 wire 名；同一渠道内唯一，允许包含 `/` |
| `enabled` | 模型是否启用 |
| `vision` | 是否具备图片理解能力 |
| `context_window` | 上下文容量，单位 token；`null` 为自动识别，显式值为至少 1024 的整数 |
| `parameters` | 该模型的请求参数覆盖 |

模型身份由 `{provider_id, model}` 共同确定。前端保持这两个字段独立，构造 URL 时分别编码。别名为 `{alias, model}`，目标必须是同渠道内的真实模型名；别名不得重复或与真实模型名冲突。报告候选等结构化引用使用真实模型名。

渠道、模型、别名和候选数组保持显式顺序。改变模型身份时需要同步处理引用；当前接口没有独立重命名操作。删除模型通过完整替换模型列表完成，后端会校验剩余引用。

### 参数继承

每个可覆盖字段都需要表达“继承”和“显式设置”两种意图。

| 数据 | 意图 | 控件行为 |
|---|---|---|
| 覆盖字段 `null` | 从更低优先级配置取得值 | 展示“继承”，并说明当前有效值与来源 |
| PATCH 省略字段 | 保留已有设置 | 保存局部修改时保留未编辑字段 |
| `false` | 显式关闭 | 保留为 false |
| 合法的 `0` | 显式零值 | 保留为 0；例如媒体预算 0 表示不限 |
| `""` | 显式空字符串 | 保留清空意图；例如思考档位为空表示使用模型默认档 |
| `{}` | 显式空对象 | 可用于清空额外请求体 |

布尔覆盖适合“继承／开启／关闭”三态。数值字段需要独立的“继承”入口，避免把空输入直接转换为 0。`context_window: null` 的文案使用“自动识别”；设置字段的 `nullable` 和参数字段的 `inherit` 含义分别按 metadata 处理。

请求参数有效值优先级为：调用专用或会话覆盖 → 模型覆盖 → 渠道默认 → 具有该字段职责的全局设置 → 内置默认。部分报告会传入调用专用参数。有效值接口展示模型、渠道、全局与内置默认的解析结果。排查某次请求时，在此基础上核对会话覆盖和调用专用参数。

`extra_body` 每次整体替换。模型选择共享风格的 `style_profile`，与追加文本 `style_overrides` 分别覆盖渠道对应字段；最终风格由共享风格文本与有效追加文本拼接。`style_profile: ""` 表示不选择共享风格，`style_overrides: ""` 表示清空追加文本。

常用参数包括超时秒数、温度、最大输出 token、流式、思考档位、缓存和风格。高级参数包括 User-Agent、`extra_body`、重试策略、上下文纪元、输入预算、媒体字节预算、历史重放预算、Responses profile 和原生搜索。原生搜索 `builtin_search` 的请求效果适用于 Gemini；协议特有字段应说明适用协议。

### 有效值与字段约束

`GET /metadata` 提供 `parameters`、`settings`、`protocols` 和 `route_names`。参数 metadata 包含 `type`、`nullable`、`inherit`、`default`、可用的 `minimum/maximum/enum`，以及 `provider_override/model_override`。它提供约束；中文名称、用途说明、单位和分组由前端维护。MCP server 等嵌套结构结合 OpenAPI 和对应配置说明实现专用编辑器。

metadata 的 default 描述字段缺省值；模型当前继承的值从有效值接口取得。渲染表单时保持 null 的继承意图，显示缺省值不会自动形成显式覆盖。minimum 或 maximum 为 null 时，该侧没有对应范围限制。

例如模型温度继承渠道 0.8 时，有效值接口返回：

```json
{
  "configured": {"provider": 0.8, "model": null},
  "value": 0.8,
  "source": "provider"
}
```

参数来源为 `model/provider/runtime/builtin`，分别显示“模型设置／渠道默认／全局运行设置／内置默认”。`context_window` 的 `configured` 直接是整数或 null，其来源为 `model/automatic/unknown`，显示“手动指定／自动识别／未知”。风格选择和追加文本返回各自有效字段，界面可据此组织风格预览。

后端拒绝越界值，不会在保存时静默截断。主要约束示例：温度 0～2，超时至少 0.01 秒，输出 token 至少 1，工具最多 16 轮、每轮最多 32 次调用，搜索每轮最多 32 次。完整约束读取 metadata；后端同时校验跨字段关系，例如纪元预算顺序与回复拆分阈值。

## 4 模型选择 风格 价格与能力设置

### 模型选择

| 功能 | 存储位置 | 编辑语义 |
|---|---|---|
| 默认聊天 | `settings.runtime.default_provider` + 渠道 `default_model` | 渠道选择器与渠道默认模型共同决定默认聊天模型；启用聊天时需要可用选择 |
| 每日总结／每日播报／周报／月报 | `routes.daily_summary/daily_briefing/weekly_report/monthly_report` | 有序候选列表；按顺序尝试，可以调整顺序 |
| 快速判定 | `settings.quick_judge.provider_id/model` | 两项均为空时使用默认聊天选择；选定渠道且 model 为空时使用该渠道默认模型 |
| 图片预处理 | `settings.image_preprocessing` | 开启后需要选择可用视觉渠道与模型；model 为空时使用所选渠道默认模型 |

候选项为 `{provider_id, model}` 或字符串 `"@default"`。`@default` 展示为“跟随默认聊天模型”，在运行时按任务配置解析，存储时保留该标记。空的报告候选列表使用默认聊天选择。候选显示渠道和模型，不能靠拆分 `/` 识别模型。

停用选项可以保留在编辑视图并标明状态。新的选择应引导到可用对象。保存检查结构和引用；应用时还检查启用状态、本地人格文件、环境变量及已有群覆盖等条件。

### 风格

`style_profiles` 为“名称 → 提示文本”的对象。提供命名列表、文本编辑和引用情况。渠道和模型从已有名称中选择共享风格，并分别编辑追加文本。人格提示词与共享风格具有独立职责，页面文案应清楚说明。

### 价格

计费单位是 `(provider_id, model)`：`provider_id` 必须是已存在的渠道，`model` 是该渠道配置的模型 ID，与请求发出的模型名一致。价格按渠道与模型精确匹配。按渠道分组展示，模型从渠道模型清单中选择；渠道已不再配置的价格行保留并提示（`price_orphan`）。删除渠道时一并删除其价格。

输入、输出、缓存读取、缓存写入单价均为美元／百万 token。0 表示免费；缺少价格规则表示未定价；缓存单价 `null` 表示按输入单价计费。新增规则的输入和输出单价留空，必须填写后才能保存，避免缺省 0 被当作免费。缺少价格产生警告，允许继续保存。价格变更影响后续任务，历史费用保持原值。

`source` 和 `confidence` 保存价格来源与确认程度，现有字段为字符串。保留已有值；日期、币种和价格历史接口当前未提供。

### 设置范围

| 设置域 | 用户应理解的内容 |
|---|---|
| `runtime` | 聊天开关、默认人格、记忆、历史、工具轮数、回复分段、高级预算与全局客户端身份字段 |
| `triggers` | 命令前缀、是否响应前缀或艾特、空问题提示 |
| `auto_search` | 自动联网搜索与每轮搜索上限 |
| `quick_judge` | 快速判定模型、超时与输出预算 |
| `image_preprocessing` | 图片预处理开关、视觉模型、提示词与输出预算 |
| `tools` | 工具清单、append/replace 模式、工具发现策略和常驻工具 |
| `skills` | Skill 开关、目录和执行／读取资源上限；Skill 文件内容由现有 Skill 页面管理 |
| `mcp` | 总开关、独立服务列表、传输方式、连接信息、工具过滤与协商设置 |
| 四类报告设置 | 各自开关、生成／发送时间、消息门槛与内容预算；模型顺序在 routes 中编辑 |

工具名单为空时使用默认工具与已注册 MCP 工具。非空名单中，`enabled_mode: append` 在默认集合上追加，`replace` 按指定名称精确过滤。

MCP 按 transport 展示连接字段：stdio 使用命令，HTTP/SSE 使用地址和 Header，Docker 使用镜像与运行参数。auto/modern 协商需要 HTTP 和非空支持版本列表。报告 cron 可提供时间说明，提交使用后端支持的五段表达式。全局客户端身份字段按 metadata 展示，并链接[Profile 说明](../admin/client-fingerprints.md)解释用途、自动值与覆盖规则。

人格文件、Skill 内容、群级覆盖、聊天记录、用量和 Trace 使用各自存储，页面链接相应管理入口。恢复配置快照会更新配置库草稿；部署和业务数据的备份恢复见[管理员操作](../admin/llm-configuration.md)。

## 5 运行状态与凭据

Web Admin 是管理员的唯一访问入口。前端只请求 Web API；Bot 在另一进程或容器中执行应用与探测。

`GET /status` 返回：

```json
{
  "schema_version": 3,
  "draft_revision": 12,
  "draft_version": {"saved_at": 1791690000.0, "note": "接入新渠道"},
  "published_revision": 10,
  "published_version": {"saved_at": 1791680000.0, "note": ""},
  "bot": {
    "boot_id": "example-boot-id",
    "application_version": "1.16.2-dev.0",
    "loaded_revision": 10,
    "loaded_version": {"saved_at": 1791680000.0, "note": ""},
    "heartbeat_at": 1791680000.0,
    "observed_at": 1791680003.0,
    "stale": false,
    "components": {
      "core": {"state": "ready"},
      "mcp": {"state": "preparing", "servers": []},
      "environment": [{"name": "OPENAI_API_KEY", "configured": true}]
    }
  }
}
```

该样例说明响应结构，版本和时间仅用于示例。当前 schema 版本从接口取得，保持与应用版本独立。

- `bot: null`：Bot 尚未回报，显示“暂无 Bot 状态”。
- `stale: true`：最近回报已过期，显示最近观察时间和“Bot 状态过期”。
- 新鲜心跳且版本相符：可以显示 Bot 已加载目标版本。
- `components.core.state` 为 `ready/failed`；MCP 为 `ready/preparing/degraded`，分别显示就绪、准备中、部分不可用。

应用成功和 MCP 远端服务就绪分别呈现。组件部分不可用时保留实际已加载版本，不把全部状态压成一个成功或失败图标。

Bot 约每 5 秒回报心跳，超过 20 秒标为过期。前端在轮询失败或网络断开时也需要让旧状态逐渐过期；可以用 `observed_at - heartbeat_at` 加上本地经过时间判断，避免设备时钟偏差。轮询间隔可由前端设计，建议运行状态约 5 秒、活动任务约 2 秒；页面卸载后停止轮询。

凭据值只来自服务器根目录 `.env`。密钥变量名和 `${VARIABLE}` 引用可以编辑；编辑器接收变量名称或引用，真实密钥在服务器上配置。认证 Header 例如 `Bearer ${OPENAI_API_KEY}`。

`GET /environment?source=draft` 返回 `variables:[{name,configured}]`、`available`、`stale`。`configured: true/false/null` 分别为已配置、缺失、尚无观察结果。信息来自 Bot；过期观察和新变量尚未被观察时需要标明状态。接口不会返回变量值。

## 6 应用任务与模型探测

应用请求为：

```json
{"expected_draft_revision": 12, "request_id": "a-unique-client-request-id"}
```

返回任务包含 `id`、`kind`、`target_revision`、`status`、`stage`、`payload`、`result`、`error`、`created_at`、`updated_at`。时间是 Unix 秒，转换为 JavaScript 日期时乘以 1000。可能附带内部管理字段，界面只消费约定字段。

| status | 用户文案 | 允许的操作 |
|---|---|---|
| `queued` | 等待 Bot 执行 | 查询、取消 |
| `running` | 正在执行 | 查询进度 |
| `succeeded` | 已完成 | 展示结果及实际版本 |
| `failed` | 执行失败 | 展示原因，保留草稿，允许用户处理后重新发起 |
| `cancelled` | 已取消 | 保留记录 |

`stage` 是阶段说明，当前包括 queued、preparing、switching、published、finished、cancelled、unconfirmed。核心状态判断使用 `status`，未知 stage 需要有通用展示。只有排队任务可以取消；取消发生竞争时重新查询任务。

同一次用户操作在网络重试时复用 `request_id`。更改目标或主动发起新的操作使用新编号。页面刷新后通过任务列表恢复进度，不自动提交新应用。`GET /status` 当前不提供 `active_operation`，活动任务从 `/operations` 查询。

探测先选择配置来源 draft、published 或指定快照修订号，再选择渠道和真实模型。它使用 Bot 环境执行固定快照的单次请求，返回 HTTP `202`；响应声明 `may_charge: true`、`automatic_retry: false`。发起前清楚显示“探测可能产生模型费用”。

探测不会保存页面里的未提交编辑，也不会发布草稿。用户要测试这些修改时先保存草稿并选择 draft。草稿在提交时绑定快照；如需固定已知修订号，可选择存在的历史快照。`probe_result_unconfirmed` 表示请求中断后结果未确认，禁止前端自动再次探测；用户可以明确发起新的探测。

## 7 导入 导出与历史

导入 JSON 为完整替换草稿，流程为：选择文件 → 校验与预览 → 展示增删改、警告及影响 → 用户确认保存草稿。预览不写库。确认请求继续使用预览的基准修订号；其他人修改草稿后需要重新预览。

导入前要处理当前未保存编辑。导入完成后独立提供应用操作。请求体最多 1 MiB，上传前按 UTF-8 字节数检查，并保留后端 `413` 处理。

导出明确标注来源：草稿、已发布、指定历史快照。导出内容是 JSON 配置，不含密钥值、任务、运行状态或数据库内部行号。数据库备份恢复通过 CLI／运维工具执行。

历史列表包含应用和探测使用过的快照；根据任务结果与发布指针标记快照的实际用途和结果。恢复历史会把快照内容保存为当前草稿，修订号保持前进；内容相同时可以保持原草稿修订号。恢复不会直接切换 Bot。

## 8 API 接线清单

下面 URL 均相对 `/ops/api/llm-configuration`。所有请求使用现有管理员会话 Cookie；写请求沿用同源保护。新页面可以复用 `frontend/src/api/index.ts`，其 BASE 已包含 `/ops`，调用时使用 `/api/llm-configuration`，避免重复前缀。结构化错误位于该封装的 `error.data`。

| 功能 | 请求 | 主要响应 |
|---|---|---|
| 字段约束 | `GET /metadata` | parameters、settings、protocols、route_names |
| 读取配置 | `GET ?source=draft` | `{revision,document}`；source 也支持 published 或快照号 |
| 保存完整草稿 | `PUT` 根路径，`{expected_draft_revision,document}` | `{revision,document}` |
| 渠道列表／详情 | `GET /providers`、`GET /providers/{id}` | 列表，或含 provider、pricing、effective_parameters 的聚合详情，均带 revision |
| 新增／替换渠道 | `PUT /providers/{id}`，`{expected_draft_revision,value}` | 更新后的完整配置 envelope；value.id 与 URL 一致 |
| 渠道局部修改 | `PATCH /providers/{id}`，`{expected_draft_revision,fields}` | envelope；省略字段保留，parameters 按字段修改 |
| 删除渠道 | `DELETE /providers/{id}?expected_draft_revision=N` | envelope 或依赖冲突 |
| 模型／别名 | `PUT /providers/{id}/models` 或 `/aliases`，`{expected_draft_revision,value}` | 完整替换相应有序数组，返回 envelope |
| 有效参数 | `GET /providers/{id}/effective?model=wire&source=draft` | `{revision,parameters}` |
| 配置域 | `GET/PUT /sections/{section}` | GET 为 `{revision,value}`；PUT 带 expected_draft_revision 和完整 value |
| 单个设置域 | `PUT /settings/{name}`，`{expected_draft_revision,value}` | envelope；value 完整替换该设置域，缺省字段会规范化为默认值 |
| 多域事务 | `POST /batch`，`{expected_draft_revision,changes:[{section,value}]}` | 一次事务替换所列域，返回 envelope |
| 校验 | `POST /validate`，`{document}` 或 `{}` | 合法时 `{valid:true,warnings,dependencies}`；非法时 422／409 错误 |
| 依赖 | `GET /dependencies?source=draft` | `{dependencies:[{field_path,target}]}` |
| 差异与影响 | `GET /diff?source=draft&target=published` | 校验报告 + changes、components |
| 导入预览 | `POST /import/preview`，`{expected_draft_revision,document}` | 规范化 document、基准修订号、校验报告、changes、components |
| 导入保存 | `POST /import`，相同请求格式 | envelope |
| 导出 | `GET /export?source=published` | 直接返回配置 JSON |
| 历史／恢复 | `GET /history`；`POST /history/{revision}/restore`，`{expected_draft_revision}` | 快照列表；恢复返回 envelope |
| 应用 | `POST /apply`，`{expected_draft_revision,request_id}` | HTTP 202 + 任务对象 |
| 探测 | `POST /probe`，`{source,provider_id,model,request_id}` | HTTP 202 + 任务对象及计费／重试声明 |
| 任务记录 | `GET /operations?limit=20`、`GET /operations/{id}` | `{operations:[...]}` 或单个任务 |
| 取消排队任务 | `POST /operations/{id}/cancel`，`{}` | 任务对象 |
| 实际状态／凭据状态 | `GET /status`、`GET /environment?source=draft` | 见运行状态章节 |

sections 允许 style_profiles、pricing、routes、settings；batch 还允许 providers。batch 每项含 section 和 value，最多 100 项。它是多个顶层域的完整替换事务，提交内容需要包含这些域内所有应保留的条目。

差异返回 `changes:[{field_path,before,after}]`。默认查询的 before 是 published，after 是 draft。数组变化可能整段返回，前端可按公开身份整理成人类可读的增删改列表。

`components` 是对象 `{mcp_reconnect:boolean,reschedule:string[]}`。它提供配置层面的影响概览；报告设置变化会列入 reschedule，Bot 执行时处理实际调度替换。价格等无关变化不需要 MCP 重连。普通校验检查结构和引用。应用时检查 Bot 侧的环境变量、人格文件等条件；模型连通性通过探测任务检查。

## 9 错误与文案

新配置 API 错误为 `{code,message,field_path,details}`。按 code 和 HTTP 状态决定交互，展示中文解释并保留后端诊断信息。field_path 可能使用点路径或数组下标；映射到具体控件，无法定位时显示在所属区域。details 的结构随错误代码变化，应稳健读取。

| 状态或错误 | 用户需要得到的反馈 |
|---|---|
| 401 | 登录已失效，重新登录；保留可恢复的编辑状态 |
| 403 | 请求被同源保护拒绝，检查访问与代理地址 |
| 422 invalid_field／invalid_reference | 明确哪个字段或目标需要修改 |
| 422 literal_secret | 填写环境变量引用，并在服务器 `.env` 配置真实密钥 |
| 409 revision_conflict | 他人修改了草稿；保留编辑并处理冲突 |
| 409 dependency_conflict | 存在引用；展示位置或引用对象，必要时查询 dependencies |
| 409 operation_conflict | 存在应用任务，或请求编号已用于其他操作；查询任务后处理 |
| 409 database_busy | 配置库正忙；保留编辑，允许稍后重试 |
| 404 not_found | 渠道、任务或快照不存在，更新列表 |
| 413 body_too_large | 请求超过 1 MiB |
| unsupported_schema／database_corrupt | 配置库无法正常使用，提示管理员通过运维入口处理 |
| 任务 missing_environment／missing_persona／vision_required | 缺少 Bot 侧凭据、人格文件或视觉能力；展示可操作的修复提示 |
| 任务 probe_result_unconfirmed | 探测结果未确认，等待用户明确决定是否再次请求 |
| 网络错误 | 当前数据未确认；保留编辑、停止成功提示、让运行状态按时间过期 |

`price_missing` 等 warning 不等同于字段错误。展示警告和影响，允许用户按契约继续保存。后端无效文档通常通过错误响应报告，不能只依赖 `valid:false`。

## 10 前端验收场景

1. 新库无渠道、聊天关闭：页面有明确添加入口，保存合法配置。
2. 多渠道与长模型列表：能快速定位某一模型，界面按需展示参数。
3. 三态布尔、继承数值、显式空字符串、合法 0、空 extra_body：保存往返保持意图。
4. 保存新草稿后 Bot 加载已发布版本：显示“已保存，等待应用”。应用期间再次保存：任务绑定提交时的修订。
5. 两个页面编辑同一修订：第二次保存遇到 409，原编辑内容可继续比较和处理。
6. 删除有引用的模型或渠道：显示依赖，用户能找到对应配置位置。
7. Bot 从未回报、心跳过期、轮询断网、MCP 部分不可用：四种状态清楚呈现。
8. queued 可以取消，running 无取消入口；刷新页面后能找回活动任务。
9. JSON 预览不修改草稿，导入保存不自动应用；恢复历史不自动切换 Bot。
10. 模型名含 `/`、免费价格、未定价、缓存价继承、凭据观察未知：正确读写与展示。
11. 探测标明来源、目标和可能计费；未知结果不自动重发。
12. 桌面与移动布局可操作，键盘可定位控件，字段标签、单位、帮助和错误可读。

测试替身使用公开示例和隔离配置库，覆盖上述状态；联调只经 Web API。交付运行 `pnpm type-check`、`pnpm test`、`pnpm build`，并展示关键操作的桌面与移动效果。已有前端 API 封装与类型可复用，响应结构以本契约和后端实际响应为准，尤其留意 components 为对象、有效值 configured 的两种结构，以及 status 不带活动任务。
