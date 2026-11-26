<!-- Generated from docs/dev/llm-configuration-frontend.md; do not edit -->

# LLM 配置管理前端交付契约

本文面向维护 QuickQuip 管理后台前端的开发者，规定 `/ops/#/llm-config` 配置工作台的信息组织、表单数据语义、保存与应用状态机、API 接线及前端验收标准。完整后端机器契约见 [OpenAPI](llm-configuration.openapi.json)、[后端接口说明](llm-configuration-api.md)与[公开 JSON 示例](../../config/llm.json.example)，管理员操作说明见[配置管理指南](../admin/llm-configuration.md)。

## 1 用户需要完成的事

工作台围绕管理员的六类核心任务组织交互：

1. 新增或编辑渠道，填写协议、服务地址与密钥环境变量名，维护有序模型列表并指定渠道默认模型。
2. 定位任意渠道或模型，调整请求参数，直观区分“继承上层”与“显式覆盖”的实际生效值及来源。
3. 配置默认聊天渠道，以及四类周期报告、唤醒快速判定、前置图片预处理和群历史调查执行器的模型路由。
4. 将本地修改保存为数据库草稿，对比草稿与当前已发布版本的字段差异及组件影响，再发起在线应用。
5. 实时查看 Bot 是否在线、实际内存加载的配置版本，以及核心运行时与 MCP 服务的就绪状态。
6. 执行 JSON 配置导入预览与保存、按来源导出配置，或将任意历史快照恢复为当前草稿。

界面统一采用清晰的中文业务标签，底层字段标识符用于悬浮提示、帮助说明或高级视图。常规配置均通过结构化表单、下拉选择器与可排序列表完成；JSON 编辑器仅用于导入导出及 `extra_body` 等自由键值对象。

### 工作台分区结构

| 分区 | 承载内容 |
|---|---|
| 概览与变更 | 本地未保存提示、草稿版本、已发布版本、Bot 加载版本、待应用差异摘要与当前控制任务进度 |
| 渠道与模型 | 支持搜索的渠道列表、连接与鉴权设置、有序模型与别名列表、渠道默认参数、模型级参数覆盖及模型单价 |
| 模型选择 | 默认聊天渠道、四类报告的有序模型级联、快速判定模型、图片预处理模型、历史调查执行器模型 |
| 行为与能力 | 触发前缀与艾特开关、内置工具与按需发现、群历史查询设置、Skill 运行时、MCP 服务列表、记忆与分段交付、报告定时设置 |
| 高级参数 | 退避重试、上下文纪元水位、输入与内联媒体预算、客户端指纹与协议专属参数 |
| 配置交换与历史 | JSON 导入差异预览、分来源导出、历史快照恢复、应用与探测任务记录 |

当渠道或模型数量较多时，界面采用“左侧选中渠道 → 右侧按需展开详情与模型覆盖”的分级视图，将高频参数与低频高级参数分层收纳，并为所有列表提供搜索过滤、空状态引导与已停用标识。

## 2 保存与应用

### 四层配置状态

| 状态层 | 业务含义 | 界面文案示例 |
|---|---|---|
| 页面未保存编辑 | 当前浏览器表单内尚未提交到后端的修改 | “有未保存的修改” |
| 数据库草稿 `draft_revision` | 已写入 `config.db`，等待发起应用任务 | “草稿 2026-10-14 15:30 (接入新渠道)” |
| 已发布快照 `published_revision` | 运行库已接纳的发布指针，Bot 重启后从此版本加载 | “已发布 2026-10-12 09:05” |
| Bot 内存版本 `loaded_revision` | Bot 最近一次有效心跳上报的内存生效版本 | “Bot 已加载 2026-10-12 09:05” |

接口层通过整数修订号执行并发乐观锁检查，界面层则将 `draft_version`、`published_version`、`loaded_version` 及历史快照的 `{saved_at, note}` 格式化为“YYYY-MM-DD HH:mm (备注)”展示（`saved_at` 缺失时显示“未记录时间”）。版本备注可在保存草稿或发起应用时一并提交，也可随时调用 `PUT /note` 单独修改而不递增修订号。

“保存草稿”与“应用配置”严格分离：保存成功仅更新草稿；应用接口返回 HTTP `202` 时展示“已提交应用，等待 Bot 执行”；仅当应用任务状态变为 `succeeded`、Bot 心跳未过期且 `loaded_revision` 追上目标修订时，才显示“Bot 已加载目标版本”。正在执行中的对话、周期报告与计费继续持有各自启动时的旧快照，新进入的请求切换至新版本；直接重启 Bot 会加载 `published_revision`，未应用的草稿继续保留待发。

### 保存流程

1. 加载页面时读取 `GET ?source=draft`，记录当前 `revision` 与基准文档副本。
2. 用户修改表单控件后立即标记本地脏状态，在切换子面板、离开路由或恢复历史快照前提示处理未保存修改。
3. 提交保存时携带 `expected_draft_revision`。
4. 保存成功后采用后端返回的规范化 `document` 与新 `revision` 刷新本地基准（若内容无实质变化，后端保持原 `revision`）。
5. 乐观锁覆盖整座配置库，多人同时编辑不同配置域同样可能触发 `409 revision_conflict`；前端遇到冲突时必须完整保留用户本地输入，提供重新拉取远端版本、核对差异后再提交的交互，严禁静默覆盖他人修改。

### 应用流程

1. 先保存当前修改为草稿，并展示草稿与 `published` 之间的字段差异及组件影响（如是否触发 MCP 重连或定时任务重排）。
2. 生成客户端唯一 `request_id`，连同目标 `expected_draft_revision` 提交 `POST /apply`。
3. 记录返回的任务 `id`，轮询 `/operations/{id}` 与 `/status` 跟进执行阶段。
4. 应用任务排队或执行期间允许用户继续编辑并保存下一版草稿（例如 15:30 的修订正在应用时，15:40 又保存了新草稿；待前者执行完毕后，状态栏准确呈现“Bot 已加载 15:30 版本，15:40 草稿待应用”）。
5. 全局同一时刻最多存在一个未结束的应用任务；存在活动应用时界面展示当前进度并禁用重复发起按钮。

## 3 配置对象与表单语义

配置文档顶层由 `format_version`（当前固定为整数 `2`；导入旧版 `1` 时由后端升级价格并在预览报告中列出警告）、`providers`、`style_profiles`、`pricing`、`routes` 与 `settings` 六部分组成。

### 渠道（Provider）

每个渠道封装一组上游协议端点、认证引用及其下属模型列表。已保存的既有渠道固定其公开 `id`（`PATCH` 接口拒绝改名）；新建尚未首次保存的渠道在前端允许编辑 `id`，若同时录入了关联价格行，改名时前端自动同步更新本地未保存价格行的 `provider_id`。

| 字段 | 界面语义与校验规则 |
|---|---|
| `id` | 渠道唯一 ID，仅允许英文字母、数字、点、下划线与连字符 |
| `protocol` | 协议类型：`openai`、`claude`、`gemini`、`openai_responses` |
| `base_url` | 上游服务基础 URL（必填） |
| `api_key_env` | 密钥环境变量名（如 `OPENAI_API_KEY`，必填变量名称而非密钥明文） |
| `default_model` | 渠道默认模型，必须存在于本渠道的 `models` 列表中 |
| `enabled` | 渠道启用开关；停用后保留配置与关联历史记录 |
| `client_fingerprint` | 客户端请求指纹 Profile，按当前 `protocol` 从 `metadata.client_fingerprints` 筛选可选模板，默认为 `"default"` |
| `auth_method` | 认证头格式：`api_key` 或 `bearer` |
| `headers` | 自定义附加请求头键值表，涉密值须使用 `${ENV_VAR}` 引用 |
| `fallback_urls` | 有序备用地址列表 |
| `proxy` | 显式 HTTP 代理地址，空字符串 `""` 表示不走显式代理 |
| `parameters` | 渠道级默认请求参数对象 |
| `models`、`aliases` | 有序模型条目数组与有序模型别名数组 |

- **新建渠道的准备条件**：新建渠道向导须引导用户至少添加一个模型并选定 `default_model`，保证首次保存时即构成合法文档。删除渠道受默认聊天、报告路由、群覆盖等引用关系保护，遇到 `409 dependency_conflict` 时向用户列出具体引用位置。
- **新建未保存渠道切换协议的推荐参数联动**：当渠道仍处于尚未首次保存的新建态（`canEditProviderId` 为真）时，用户在下拉框中切换 `protocol` 会自动在渠道 `parameters` 中填入目标协议的推荐默认项（切换至 `claude` 自动填入 `prompt_caching: true`，切换至 `gemini` 自动填入 `gemini_empty_response_recovery: true`），同时自动移除前一个协议自动带入且未被手动改为其他值的推荐项；对已保存的既有渠道切换协议时，保持其现有 `parameters` 不做自动增删。

### 模型与别名

| 字段 | 含义 |
|---|---|
| `model` | 发往上游的真实 wire 模型名；同渠道内唯一，允许包含 `/` |
| `enabled` | 模型启用开关 |
| `vision` | 是否支持原生视觉图片输入 |
| `context_window` | 模型上下文容量（token）；`null` 展示为“自动识别”，手动指定时须为 `>= 1024` 的整数 |
| `parameters` | 模型级请求参数覆盖对象 |

跨模块模型引用统一采用 `{provider_id, model}` 二元组，前端构造请求 URL 时需对两个字段分别做 URI 编码，严禁按 `/` 切分字符串猜测渠道与模型。别名为 `{alias, model}`，目标 `model` 必须属于同一渠道的真实模型且 `alias` 不得重名或与真实模型名碰撞。渠道、模型、别名及路由候选列表均保持显式顺序。

### 参数继承与控件契约

所有支持层级覆盖的参数控件都必须清晰区分“继承上层”与“显式覆盖”两种状态，防止空输入框误写为数字 `0` 或布尔 `false`：

| JSON 取值 | 表达意图 | 前端控件行为 |
|---|---|---|
| `null` | 向上层配置继承 | 展示继承标签并旁注当前有效值与来源；其中**渠道级的 `temperature: null` 专门显示为“默认不发送”**（表示请求体不下发 `temperature`，采用上游模型自身默认温度），其余可继承字段显示为“跟随上层” |
| `PATCH` 省略字段 | 保持库内原值 | 局部更新渠道字段时不改动未编辑项 |
| `false` | 显式关闭 | 序列化保留布尔 `false`（三态布尔选择器提供“跟随上层／开启／关闭”） |
| `0` | 显式零值 | 序列化保留整数 `0`（例如内联媒体预算 `0` 代表不限制总字节数） |
| `""` | 显式空字符串 | 序列化保留 `""`（例如清空思考档位以使用模型默认档，或清空 `style_profile`／`style_overrides`） |
| `{}` | 显式空对象 | 序列化保留 `{}`（用于清空下层 `extra_body` 覆盖） |

静态配置层级的参数解析优先级为：`模型覆盖 (model) → 渠道默认 (provider) → 同职责全局运行设置 (runtime) → 内置默认 (builtin)`（排查具体请求时，之上还可能叠加群／私聊会话覆盖或单次任务专用参数）。`style_profile`（选择共享风格名）与 `style_overrides`（附加文本）分别独立继承，最终生效风格由两者拼接而成；`extra_body` 则在覆盖时整块替换。

生成与高级分组涵盖的可覆盖参数包括：采样温度（`temperature`）、最大输出上限（`max_output_tokens`）、共享风格与附加文本（`style_profile` / `style_overrides`）、Persona v3 少样本对话示例开关（`persona_few_shot`，`auto | on | off`）、思考档位（`reasoning_effort`）、提示词缓存与有效期（`prompt_caching` / `cache_ttl`）、Gemini／Claude 原生联网搜索开关（`builtin_search`）、Gemini 空回复补正开关与额度上限（`gemini_empty_response_recovery` / `gemini_empty_response_recovery_max_output_tokens`）、OpenAI Responses 协议档位（`responses_profile`），以及超时、流式开关、User-Agent、指数退避重试、上下文纪元水位、输入与内联媒体字节预算、历史工具回放预算和 `extra_body`。协议专属参数应在说明文字中注明适用协议。

### 有效值与字段约束

前端启动时调用 `GET /metadata` 获取 `parameters`、`settings`、`protocols`、`route_names` 与 `client_fingerprints` 的类型、`nullable`、`inherit`、`default` 及数值上下界（`minimum` 或 `maximum` 为 `null` 表示该侧无上限／下限）；中文标签、单位、帮助提示与面板分组由前端 `frontend/src/lib/llmConfig.ts` 维护。模型当前继承到的实时有效值通过 `GET /providers/{id}/effective` 读取，渲染未覆盖字段时保持 `null` 绑定，不把默认值写回草稿。

例如某模型未覆盖温度、继承渠道设置的 `0.8` 时，有效值接口返回：

```json
{
  "configured": {"provider": 0.8, "model": null},
  "value": 0.8,
  "source": "provider"
}
```

前端将 `source` 的 `builtin`、`runtime`、`provider`、`model` 分别映射展示为“内置默认／全局设置／渠道覆盖／模型覆盖”；`context_window` 的 `configured` 直接为整数或 `null`，其 `source`（`model` / `automatic` / `unknown`）映射展示为“模型覆盖／自动识别／无法确定”。后端对越界值（如温度超出 `0..2`、超时 `< 0.01` 秒、输出上限 `< 1`、工具循环 `> 16` 轮等）及跨字段水位顺序直接返回 `422` 拒绝，不做静默截断。

## 4 模型选择、风格、价格与能力设置

### 模型选择路由

| 业务功能 | 配置路径 | 选择与回退语义 |
|---|---|---|
| 默认聊天 | `settings.runtime.default_provider` + 对应渠道 `default_model` | 由默认渠道选择器与该渠道默认模型共同确定；开启全局聊天开关时必须指向可用渠道与模型 |
| 每日总结／每日播报／周报／月报 | `routes.daily_summary` / `daily_briefing` / `weekly_report` / `monthly_report` | 有序候选列表（支持调整顺序），元素为 `{provider_id, model}` 或 `"@default"`（展示为“跟随默认聊天模型”）；列表为空时回退默认聊天模型 |
| 唤醒快速判定 | `settings.quick_judge.provider_id` / `model` | 两项均留空时跟随默认聊天选择；指定渠道而 `model` 留空时使用该渠道 `default_model` |
| 前置图片预处理 | `settings.image_preprocessing.provider_id` / `model` | 启用后须选择具备视觉能力的渠道与模型；`model` 留空时使用所选渠道 `default_model` |
| 历史调查执行器 | `settings.group_history.investigation_provider_id` / `investigation_model` | 渠道留空时跟随当前对话渠道；未切换渠道且模型留空时跟随当前对话模型，显式指定渠道而模型留空时使用目标渠道 `default_model` |

已被停用的渠道或模型若仍存在于既有引用中，编辑视图应保留显示并醒目标注停用状态，引导用户迁移到启用中的目标。保存草稿校验结构与内部引用完整性；在线应用还会校验启用状态、本地人格文件与环境变量凭据。

### 回复风格与模型定价

- **回复风格（`style_profiles`）**：维护“风格名称 → 提示词正文”键值映射及各渠道／模型的引用统计，文案中明确区分共享风格与独立 `config/personas/` 人格文件的职责。
- **模型定价（`pricing`）**：按 `(provider_id, model)` 精确计费，单价单位统一为**美元／百万 token**。`0` 表示免费，未配置价格条目表示未定价（产生 `price_missing` 警告但允许保存），缓存读／写单价为 `null` 时按输入单价计费；新增价格行的输入与输出单价初始留空，须明确填写后方可提交，防止漏填被误记为免费。模型从渠道中移除后残留的孤立价格行保留展示并提示 `price_orphan`；删除整条渠道时联动清理其名下价格。价格条目上的 `source` 与 `confidence` 字符串原样保留读写。

### `settings` 设置子域

| 设置域 | 界面配置内容 |
|---|---|
| `runtime` | 全局聊天开关、默认渠道与默认人格、记忆容量、工具轮次上限、分段交付默认开关、上下文纪元与预算参数、全局客户端身份字段 |
| `triggers` | 默认命令前缀、前缀触发开关、艾特触发开关与空提问兜底文案 |
| `auto_search` | 本地自动联网搜索开关与单轮搜索次数上限 |
| `quick_judge` | 唤醒轻量判定模型路由、请求超时与输出 Token 上限 |
| `image_preprocessing` | 非视觉主模型的前置识图开关、视觉模型路由、转述提示词与输出上限 |
| `tools` | 内置工具白名单、`append`／`replace` 启用模式、工具发现模式、数量／Schema 体积双触发线与 `always_loaded` 常驻列表 |
| `group_history` | 群聊历史查询全局默认开关，以及专用历史调查执行器的渠道／模型选择、总超时秒数、模型调用上限与历史工具调用上限 |
| `skills` | Skill 总开关、自定义目录路径及目录／读取／检索／脚本超时与输出字节上限（Skill 包文件本身在独立“Skill”页面查看管理） |
| `mcp` | MCP 总开关与服务列表（按 `stdio` / `docker` / `http` / `sse` 动态切换连接表单、工具过滤名单与 `legacy` / `auto` / `modern` 版本协商字段） |
| 四类报告子域 | `daily_summary`、`daily_briefing`、`weekly_report`、`monthly_report` 各自的开关、生成／发布五段 Cron 表达式、最少消息门槛与篇幅预算 |

`settings.tools.enabled` 为空数组时启用默认内置工具集加全部已注册 MCP 工具；非空时，`append` 在默认集合之上追加，`replace` 严格按所列名称过滤。人格文件、群级覆盖（含群历史单群开关）、对话记录、用量统计、HTTP Trace 与根目录环境变量各自拥有独立后台页面，工作台通过跳转链接引导。

## 5 运行状态与凭据

前端仅调用同源 Web API，不直连 Bot 进程。`GET /status` 返回配置版本与 Bot 心跳快照：

```json
{
  "schema_version": 4,
  "draft_revision": 12,
  "draft_version": {"saved_at": 1791690000.0, "note": "接入新渠道"},
  "published_revision": 10,
  "published_version": {"saved_at": 1791680000.0, "note": ""},
  "bot": {
    "boot_id": "example-boot-id",
    "application_version": "1.16.5",
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

（注：上方时间戳与版本号仅为结构示意，前端实际读取响应返回的实时值。）

状态栏按以下规则分项呈现，避免将配置加载状态与外部 MCP 连通性混为单一红绿灯：

- `bot: null`：Bot 从未上报心跳，展示“暂无 Bot 状态”。
- `stale: true`（Bot 每 5 秒上报一次心跳，超过 20 秒判为过期）：展示最近观察时间与“Bot 状态已过期”；若浏览器轮询请求失败或断网，前端结合 `(observed_at - heartbeat_at) + 本地流逝时间` 自动将旧快照标为过期，避免受客户端本机时钟偏差干扰。
- 心跳新鲜且 `loaded_revision` 等于目标修订：展示“Bot 已加载目标版本”。
- `components.core.state` 区分 `ready`／`failed`；`components.mcp.state` 区分 `ready`（就绪）、`preparing`（连接准备中）与 `degraded`（部分服务异常，保留已加载的配置版本号并单独提示降级详情）。
- 建议页面活跃期间约每 5 秒轮询一次 `/status`、存在活动任务时约每 2 秒轮询一次 `/operations`，组件卸载时立即清理定时器。

所有认证密钥明文仅保存在服务器根目录 `.env` 中，配置表单只接收变量名或 `Bearer ${OPENAI_API_KEY}` 等占位引用。`GET /environment?source=draft` 返回 `{variables: [{name, configured}], available, stale}`，其中 `configured` 取 `true`（已配置）、`false`（未找到该变量）或 `null`（新增引用尚待 Bot 心跳观察），前端在渠道密钥输入框旁据此展示实时凭据状态标签。

## 6 应用任务与模型探测

发起在线应用的请求体为 `{"expected_draft_revision": 12, "request_id": "a-unique-client-request-id"}`。返回的任务对象包含 `id`、`kind`、`target_revision`、`status`、`stage`、`payload`、`result`、`error`、`created_at` 与 `updated_at`（Unix 秒，前端渲染时间需乘以 `1000`）：

| `status` | 界面文案 | 允许的操作 |
|---|---|---|
| `queued` | 排队中（等待 Bot 领取） | 查看进度、取消排队任务 |
| `running` | 执行中 | 查看实时 `stage` 阶段 |
| `succeeded` | 已成功 | 展示完成时间与实际加载版本 |
| `failed` | 失败 | 展示错误码与修复提示，保留当前草稿供修正后重发 |
| `cancelled` | 已取消 | 保留任务历史记录 |

`stage` 提供细粒度阶段提示（已知值包括 `queued`、`preparing`、`switching`、`published`、`finished`、`cancelled`、`unconfirmed`，遇到未来新增枚举时回退通用文本展示），核心业务流转一律以 `status` 为准。同一次按钮点击触发的网络层重试复用同一个 `request_id`；用户修改草稿后重新发起应用或刷新页面后手动重发时生成新 `request_id`（刷新页面时只通过 `GET /operations` 恢复已有活动任务视图，不自动重提应用）。

模型探测（`POST /probe`）支持选择配置来源（`draft`、`published` 或指定历史快照修订号）及目标 `{provider_id, model}`，调用前醒目提示“探测会发送真实请求并可能产生模型费用”（响应带 `may_charge: true`、`automatic_retry: false`）。探测不会自动保存页面上尚未提交的表单改动——测试未保存修改前需先点击保存草稿再选择 `draft` 来源。若探测因进程中断返回 `probe_result_unconfirmed`，前端必须停止自动重发，交由管理员确认是否再次发起。

## 7 导入、导出与历史

- **导入 JSON**：完整流程固定为“选择本地文件（前端预检 UTF-8 体积 `<= 1 MiB`）→ 调用 `POST /import/preview` 校验并计算差异 → 展示增删改明细、价格升级或缺失警告及组件影响 → 用户确认后按同一 `expected_draft_revision` 调用 `POST /import` 写入草稿”。若当前页面存在未保存修改，导入前先提示用户处理；预览期间若其他管理员修改了草稿导致 `409`，提示重新执行预览；导入保存成功后由用户独立决定何时点击应用。
- **导出 JSON**：明确区分“当前草稿（`draft`）”“已发布版本（`published`）”与“指定历史快照”三种导出源。导出的 JSON 仅含可移植的业务配置，不含密钥明文、控制任务或运行库状态（底层 SQLite 物理备份恢复见运维 CLI）。
- **历史快照与恢复**：历史列表结合 `/operations` 结果与 `published_revision` 标注各条快照的来源与生效状态；点击恢复时调用 `POST /history/{revision}/restore` 将目标快照内容写回当前草稿（不直接切换线上 Bot 运行版本）。

## 8 API 接线清单

以下路径均相对于 `/ops/api/llm-configuration`。前端复用 `frontend/src/api/index.ts`（其 `BASE` 已带 `/ops` 前缀，调用时传 `/api/llm-configuration/...`），后端返回的结构化错误对象挂载在封装异常的 `error.data` 上。

| 功能 | 请求端点与参数 | 主要响应结构 |
|---|---|---|
| 字段约束与枚举 | `GET /metadata` | `{parameters, settings, protocols, route_names, client_fingerprints}` |
| 读取完整配置 | `GET ?source=draft` | `{revision, document}`（`source` 支持 `draft`、`published` 或快照号） |
| 整份保存草稿 | `PUT` 根路径，`{expected_draft_revision, document, note?}` | `{revision, document}` |
| 渠道列表与聚合详情 | `GET /providers`、`GET /providers/{id}` | 渠道摘要列表，或含 `{revision, provider, pricing, effective_parameters}` 的单渠道详情 |
| 新增或替换渠道 | `PUT /providers/{id}`，`{expected_draft_revision, value}` | 更新后的配置信封（`value.id` 须与路径一致） |
| 局部更新渠道 | `PATCH /providers/{id}`，`{expected_draft_revision, fields}` | 更新后的配置信封（省略字段保留原值） |
| 删除渠道 | `DELETE /providers/{id}?expected_draft_revision=N` | 更新后的配置信封，或 `409 dependency_conflict` |
| 替换模型或别名数组 | `PUT /providers/{id}/models` 或 `/aliases`，`{expected_draft_revision, value}` | 完整替换对应有序数组并返回配置信封 |
| 查询有效参数 | `GET /providers/{id}/effective?model=wire&source=draft` | `{revision, parameters}` |
| 读写顶层配置域 | `GET/PUT /sections/{section}` | `section` 允许 `style_profiles`、`pricing`、`routes`、`settings` |
| 替换单个设置子域 | `PUT /settings/{name}`，`{expected_draft_revision, value}` | 完整替换指定 `settings` 子域（缺省字段规范化为默认值） |
| 多域原子替换 | `POST /batch`，`{expected_draft_revision, changes: [{section, value}]}` | 单次事务替换所列顶层域（允许含 `providers`，最多 100 项） |
| 校验与依赖查询 | `POST /validate`、`GET /dependencies?source=draft` | `{valid: true, warnings, dependencies}` 或引用关系数组 |
| 版本差异与影响 | `GET /diff?source=draft&target=published` | 校验报告 + `changes` + `components: {mcp_reconnect, reschedule}` |
| 导入预览与保存 | `POST /import/preview`、`POST /import` | 预览返回规范化文档与差异报告；保存完整替换草稿 |
| 导出配置 | `GET /export?source=published` | 纯净配置交换 JSON |
| 历史列表、备注与恢复 | `GET /history`、`PUT /note`、`POST /history/{revision}/restore` | 快照列表、备注更新状态或恢复后的配置信封 |
| 在线应用与模型探测 | `POST /apply`、`POST /probe` | HTTP `202` + 控制任务对象（探测附计费与不自动重试声明） |
| 任务查询与取消 | `GET /operations?limit=20`、`GET /operations/{id}`、`POST /operations/{id}/cancel` | 任务列表或单条任务状态 |
| 运行状态与凭据状态 | `GET /status`、`GET /environment?source=draft` | 配置／Bot 心跳状态与被引用环境变量观察结果 |

## 9 错误与文案映射

配置接口异常统一遵循 `{code, message, field_path, details}` 结构。前端依据 HTTP 状态码与 `code` 决定交互动作，将点分或带数组下标的 `field_path` 定位到对应表单控件（无法精确映射时展示在所属分区顶部），并稳健读取随错误码变化的 `details`：

| HTTP 状态或错误码 | 前端反馈与交互处理 |
|---|---|
| `401` | 会话已过期，引导重新登录并尽量保留未提交表单状态 |
| `403` | 同源校验未通过，提示核对浏览器访问域名与反向代理配置 |
| `422 invalid_field` / `invalid_reference` / `profile_owned_*` | 高亮定位具体字段或受管冲突项，展示修正要求 |
| `422 literal_secret` | 拦截明文密钥输入，引导改填环境变量名并在服务器 `.env` 配置真实密钥 |
| `409 revision_conflict` | 提示远端草稿已被他人更新，保留本地编辑并提供拉取比对入口 |
| `409 dependency_conflict` | 展示阻断删除的引用路径列表，辅助跳转清理引用 |
| `409 operation_conflict` | 提示已有进行中的应用任务或重复使用了 `request_id`，刷新任务面板 |
| `409 configuration_busy` / `database_busy` | 提示配置同步维护中或数据库繁忙，保留编辑供稍后重试 |
| `404 not_found` | 目标渠道、快照或任务已不存在，刷新当前列表 |
| `413 body_too_large` | 提示提交或导入内容超出 1 MiB 限制 |
| `unsupported_schema` / `database_corrupt` | 提示配置数据库异常，引导管理员通过运维命令备份修复 |
| 任务失败 `missing_environment` / `missing_persona` / `vision_required` | 明确指出 Bot 侧缺失的环境变量、人格文件或视觉能力并给出修复入口 |
| 任务终态 `probe_result_unconfirmed` | 提示探测中途中断、结果未确认，等待用户手动决定是否再次探测 |
| 网络断开或请求超时 | 保留本地编辑、清除虚假成功提示，并随本地计时将旧运行状态标为过期 |

注意区分校验警告（如 `price_missing`、`price_orphan`）与阻断错误：警告在界面显式提示影响但允许继续保存草稿；非法文档由后端直接通过 `4xx` 错误响应拦截，前端不能仅靠判断 `valid === false` 捕获错误。

## 10 前端验收场景

1. **空库初始化**：初始无任何渠道且全局聊天关闭时，工作台提供清晰的新增渠道引导，完成填写后能成功保存首份合法草稿。
2. **多渠道与长列表检索**：存在多个渠道及长模型列表时，支持按关键词快速筛选渠道并按需展开模型覆盖项。
3. **继承与显式零值往返保真**：三态布尔、数值继承（`null`）、渠道级 `temperature: null` 的“默认不发送”标签、新建未保存渠道切换协议时的推荐参数预填与清理、显式空串 `""`、合法 `0` 与空 `extra_body: {}` 在保存往返后均保持原始意图。
4. **保存与异步应用解耦**：保存草稿后状态栏准确提示待应用；在应用任务执行期间再次编辑并保存新草稿时，原任务继续绑定提交时的旧快照直至完成。
5. **并发编辑乐观锁保护**：两个浏览器标签页同时基于同一修订修改草稿时，后提交的一方收到 `409 revision_conflict` 且本地输入不丢失，可重新比对后处理。
6. **引用依赖拦截**：尝试删除仍被默认聊天、报告路由或群覆盖引用的渠道／模型时，界面清晰列出所有依赖位置。
7. **四类运行状态区分**：Bot 从未回报、心跳超时过期、前端网络断开以及 MCP 部分服务降级四种场景均能独立准确呈现。
8. **控制任务生命周期**：`queued` 排队任务支持手动取消，`running` 执行中任务隐藏取消入口；中途刷新浏览器页面后能从 `/operations` 自动找回活动任务进度。
9. **导入导出与历史恢复**：JSON 导入预览不改动数据库草稿，确认导入与恢复历史快照均只更新草稿而不自动触发线上 Bot 切换。
10. **特殊模型名与计费展示**：含 `/` 的模型名、免费定价（`0`）、未定价警告、缓存价继承（`null`）及新增环境变量 `configured: null` 状态均能正常编码与渲染。
11. **安全探测交互**：发起模型探测前标明配置来源、目标模型与计费风险；遇到 `probe_result_unconfirmed` 时绝不自动重发请求。
12. **响应式与无障碍可用性**：桌面端与移动端窄屏布局均可顺畅完成完整编辑与应用流程，表单控件支持键盘焦点导航并具备可读的标签、单位与错误提示。

前端变更交付前须基于隔离测试数据覆盖上述状态，并依次通过 `pnpm --dir frontend type-check`、`pnpm --dir frontend test` 与 `pnpm --dir frontend build` 验证（留意后端 `components` 为对象、`/effective` 中 `configured` 的双形态结构，以及 `/status` 不内联携带活动任务等契约细节）。
