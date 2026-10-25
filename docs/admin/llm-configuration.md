# LLM 配置数据库操作

本文面向部署者，说明 LLM 配置的初始化、修改、生效及备份恢复。配置保存在 `config/managed/config.db`。渠道、模型、别名、请求参数、风格、价格、级联与全局设置通过 Web Admin 的“LLM 配置”页面维护。JSON 交换示例见 [`config/llm.json.example`](../../config/llm.json.example)，字段类型、继承规则与范围见受保护接口 `/ops/api/llm-configuration/metadata`，开发者接口契约见 [API 文档](../dev/llm-configuration-api.md)。

页面包含渠道与模型、对话与上下文、工具与技能、报告与路由、模型价格、发布与历史六个模块。渠道模块包含模型参数与回复风格，工具模块包含 MCP 状态，发布模块提供 JSON 导入导出与历史管理。顶部状态条展示草稿→已发布→Bot 运行的版本管道；渠道与模型的参数覆盖以“跟随上层/覆盖”表达继承，渠道详情内可直接查看生效参数与发起模型探测。

草稿、修订、快照与加载版本的含义见[配置术语](../glossary.md#config-draft)。

## 首次启用 LLM

目标是让机器人在测试群回答一次提问。开始前按 [README 的安装步骤](../../README.md#安装步骤)或[云端部署指南](deployment.md)启动 Bot 和 Web Admin，并确认机器人能收到群消息。你需要后台管理口令，以及一个模型渠道提供的协议、API 地址、模型名和 API key。

1. **准备人格与密钥。** 首次安装将 `config/personas.example/` 复制为 `config/personas/`，使用其中的 `quickquip-default` 人格；Windows 懒人包已在首启创建。根 `.env` 填写所选渠道的密钥，例如 `OPENAI_API_KEY=你的密钥`。服务运行后修改 `.env` 时，源码或懒人包先停止 Bot 和 Web，再重新启动；容器按[环境变量更新步骤](deployment.md#日常维护)重建这两个服务，使新值进入容器。
2. **登录并添加渠道。** 打开后台，进入“LLM 工坊 → LLM 配置 → 渠道与模型”，点击“添加渠道”。“渠道 ID”可填 `my-provider`；“协议”和“API 地址”按渠道服务商的说明填写；“密钥环境变量”填写第 1 步使用的变量名，例如 `OPENAI_API_KEY`。保持渠道已启用。
3. **添加模型并选为默认。** 在“模型清单”点击“添加模型”，填写服务商给出的模型名并保持启用；回到“连接与认证”，在“默认模型”中选中它，再点击“设为默认渠道”。模型的上下文容量按服务商说明填写；留空时由系统识别，无法识别的模型需手动填写。
4. **开启全局 LLM。** 进入“对话与上下文”的“总开关与全局默认”，打开“启用 LLM 功能”，确认“默认渠道”为刚添加的渠道，“默认人格”为 `quickquip-default`。
5. **保存并应用。** 点击页面顶部“保存草稿”，再点击“应用到 Bot”。等待任务成功，确认顶部“Bot 实际运行”与“已发布版本”一致，心跳为新鲜状态。Bot 每 5 秒领取配置任务，运行它的终端或容器应保持启动。
6. **在测试群提问。** 由群主、群管理员或[全局管理员](global-admins.md)先发送 `/llm on`，再发送 `/llm status` 确认本群 AI 已开启。随后发送 `/ai 请回复“测试成功”`，收到模型回答即完成这条路线。`/ai` 是默认前缀；已自定义前缀的群使用实际设置。提问会发出真实模型请求，按渠道计费。

应用任务一直排队时，先确认 Bot 正在运行并与后台共享配置及运行数据库；任务失败时查看该任务的错误，核对密钥变量、默认模型和人格文件。配置已加载而群内没有回复时，先看 `/llm status` 与触发前缀，再查 Bot 日志中的渠道请求错误。

## 初始化与升级

源码安装在项目根目录执行：

```bash
python -m quickquip.llm.config_cli init
```

初始化检查 `config/llm.toml`。有旧文件时只迁移一次；没有旧文件时建立关闭 LLM、无渠道的配置。已有数据库始终具有权威性，库损坏或 schema 不支持会明确报错。Windows `start.bat` 在启动服务前执行初始化；根 `docker-compose.example.yml` 的 `config-init` 在可写配置挂载中完成迁移，bot 和 Web 等待该服务成功后启动。生产部署脚本在切换前初始化服务器配置；手动生产安装先构建镜像，再按[部署指南第 4 步](deployment.md#4-启动服务)借用 Web 容器运行初始化命令。

配置数据库为 schema 4，发布执行状态单独保存在 `data/config_runtime.db`。已有 schema 3 安装先按[存储迁移](storage-migration.md)停服切换；schema 1、2 使用支持 schema 3 的旧版本先完成升级。新安装的 `init` 创建配置与运行库，保留草稿保存、单独应用和版本标记的操作方式。Profile 选择缺省为 `default`，配置见[请求指纹 Profile](client-fingerprints.md)。


迁移保留认证变量引用。发现认证字面量时，先将密钥写入根目录 `.env` 并把字段改为 `${VARIABLE}`。`api_key_env` 保存环境变量名称。认证 Header 可使用 `Bearer ${VARIABLE}`。数据库、导出、日志和操作错误不包含展开的认证值。

迁移备份与报告存放在 `data/llm-config-migration/<源文件摘要>/`。报告列出字段转换、限制调整、移除和外部资产处理结果。内联人格写入 `config/personas/migrated-*.toml`，使用 `inherit_shared = false` 保持原提示应用语义；已有独立人格按加载优先级保留。已有 `config/generation.toml` 继续提供多模态配置，缺失时迁移提取旧段。原文件始终保留。文件冲突需要查看报告并处理后重新初始化。

### 首次迁移的 Profile 字段冲突

旧 TOML 的 `extra_body` 或 Header 可能覆盖新版默认 Profile 管理的字段，例如 Claude 的 `system`／`messages`／`tools`、Gemini 的 `contents`／`systemInstruction`／`tools`、Responses 的 `prompt_cache_key`，以及自动 Session Header。初始化返回 `profile_owned_body` 或 `profile_owned_header` 时，数据库尚未准备完成，须先处理迁移输入：

1. 停止旧服务，保留旧 TOML、人格、多模态资产及数据目录备份，认证字面量先转为根 `.env` 的变量引用。
2. 根据错误字段路径，从用于迁移的 TOML 中移除冲突的手工字段，保留原值于备份；重新运行 `python -m quickquip.llm.config_cli init`。
3. 启动新版 Bot 与 Web 后，在渠道详情选择兼容策略：Claude／Gemini 可选 `legacy-claude`／`legacy-gemini`；其他情况按[自定义 Profile](client-fingerprints.md#编辑-profile-文件)定义未管理该字段的策略，并在放置模板后重启 Bot 与 Web。
4. 将需要使用的手工字段填回渠道 `parameters.extra_body` 或固定 `headers`，预览实际变更，保存草稿并应用，确认 Bot 已加载。认证 Header 继续使用变量引用。

旧 TOML 加入 `client_fingerprint` 不会迁移为渠道选择；Profile 选择通过新版配置维护。原备份用于旧版本回退，迁移输入的调整与新版配置分别保存。

## 保存与应用

Web Admin 以“YYYY-MM-DD HH:mm (备注)”标记版本：时间是该修订的保存时刻，备注可在状态条、发布页或历史快照上随时修改。尚未发布的草稿在多次保存间保留备注，发布后的下一次保存从空备注开始。

保存增加 `draft_revision`，机器人继续使用已发布快照。应用指定草稿修订号，建立不可变快照并返回配置任务 ID。后续草稿编辑继续允许；已有应用尚未结束时，再次应用返回冲突。只有 bot 已切换并回报实际版本后，任务才成功。

`published_revision` 是已接纳的快照，`loaded_revision` 是 bot 实际加载版本。启动和重启加载已发布配置。心跳超过 20 秒未更新会显示过期；Web 的模型或 MCP 实例不会代表 bot 状态。MCP 准备中或部分服务不可用会单独显示。价格修改影响新任务，历史费用与已经开始的任务保持原价格。

核心状态包含配置与业务存储的初始化结果。部署使用 `status --require-loaded` 检查新鲜心跳、发布修订加载和核心就绪；业务库不可用时返回失败。MCP 的准备或降级状态单独报告。

每次 LLM 任务固定配置与资源至结束。MCP 配置变化后，新任务使用新连接，已开始的任务使用原连接直到结束。报告时间变更替换对应调度，已经开始的报告继续执行，不补发因调整时间错过的消息。配置修订号覆盖配置库；人格文件、Skill 内容、群覆盖与其他业务数据保持各自存储职责。

## 模型参数与引用

渠道身份、协议、URL、认证变量、Header、备用地址和代理保持渠道级。模型可以覆盖请求参数，包括超时、温度、输出、流式、User-Agent、缓存、原生搜索、Responses profile、思考档位、重试、纪元和预算。

有效值顺序为调用或会话覆盖、模型覆盖、渠道默认、具有该字段职责的全局设置、内置默认。覆盖参数 `null` 继承上一层；空字符串、空对象、false 和允许的零值保存明确意图。`extra_body` 整体替换。`style_profile` 选择共享风格，`style_overrides` 保存追加文本，两者独立覆盖。新写入拒绝越界数值。

JSON 模型引用使用 `{ "provider_id": "渠道ID", "model": "wire模型名" }`。级联数组顺序就是尝试顺序，`"@default"` 在任务运行时解析默认选择。模型名可以包含 `/`。

价格以“渠道 + 配置的模型 ID”为唯一计费单位，`provider_id` 必须是已存在的渠道。用量按请求发出的模型名匹配价格，上游响应改写的模型名（中转去前缀、带日期的快照名等）不影响定价；同名模型在不同渠道需要各自定价，不存在全渠道兜底。免费价格是零，未定价缺少记录，缓存价格 `null` 使用输入单价。导入旧格式（`format_version: 1`）JSON 时，`渠道ID/模型` 形式的兜底价格归属到该渠道；纯模型名兜底价格只在恰好一个尚未定价的渠道配置了该模型时归属，否则移除；导入预览逐条列出结果。

Web Admin 的“模型价格”按渠道分组：模型从该渠道的模型清单中选择，未定价模型可点击补行，新行的单价留空、填写后才能保存；可以把一行价格复制到同样配置了该模型的其他渠道。删除渠道时一并删除它的价格。

删除被引用对象会返回依赖。停用渠道和模型保留会话与历史记录。群覆盖只允许已发布且可用的渠道与模型；应用前会重新检查已有覆盖。

### 迁移群绑定与退役渠道

应用返回 `dependency_conflict` 且字段路径为 `scope_settings.<scope>` 时，检查该群或私聊的渠道／模型覆盖。已关闭的群或私聊仍可保留覆盖，`/llm off` 不会删除引用。替换渠道时按以下顺序操作：

1. 添加新渠道与模型，保存并应用，使目标成为已发布可用对象。
2. 在“群 LLM”找到受影响 scope，将渠道／模型改为新目标或跟随默认并保存；私聊也可用 `/llm use <provider> [model]` 迁移。需要移除全部覆盖时，先核对页面“清空”将同时重置的设置。
3. 再停用或删除旧渠道／模型，检查功能路由等其他引用，保存草稿后应用。

群覆盖保存后用于后续请求，正在执行的请求使用原绑定与配置。

## CLI

需要分文件审阅、注释和长期编辑时，使用[TOML 工作副本](config-workspace.md)。组装保存本地草稿，再按本文流程应用或同步。

在项目根目录运行，可用全局 `--db <路径>` 指定配置库。JSON 导入上限为 1 MiB。除初始化外，命令需要已有配置库。下方演示从修订 1 导入并应用修订 2；执行前用 `status` 查询当前草稿修订，并替换 `--expected-revision`。任务 ID、快照 ID 和请求标识也须按本次操作填写；同一请求重试时复用请求标识。

```bash
python -m quickquip.llm.config_cli validate
python -m quickquip.llm.config_cli export --source published --output llm-export.json
python -m quickquip.llm.config_cli import llm-export.json --expected-revision 1 --preview
python -m quickquip.llm.config_cli import llm-export.json --expected-revision 1
python -m quickquip.llm.config_cli diff
python -m quickquip.llm.config_cli apply --expected-revision 2 --request-id unique-request-id
python -m quickquip.llm.config_cli status
python -m quickquip.llm.config_cli status --require-loaded
python -m quickquip.llm.config_cli status --operation returned-operation-id
python -m quickquip.llm.config_cli backup data/llm-config-backup.db
python -m quickquip.llm.config_cli restore --snapshot 1 --expected-revision 2
```

导入完整替换草稿，应用需要独立操作。修订冲突时重新读取草稿并审查差异。历史恢复生成新草稿，修订号不倒退。`migrate-legacy --legacy <文件>` 在已有库上需要 `--expected-revision`，只导入草稿。

备份使用 SQLite backup API，覆盖活跃 WAL 中的已提交状态。停止 bot 与 Web 后，才能恢复数据库：

```bash
python -m quickquip.llm.config_cli restore --file data/llm-config-backup.db --services-stopped
```

恢复前检查 schema 并备份当前库，恢复后清除旧心跳与未结束任务租约，再启动服务。不要直接复制正在运行的主数据库文件。

## 生产与回退

生产配置通过 Web 或配置运维驱动变更。deploy-v4 使用[共同基线进行双向配置同步](config-sync.md)，排除本地 DB 和旧 LLM TOML 的原始上传。首次升级同步能力使用 `--config-sync off` 保留服务器配置，随后选择初始来源建立基线。候选版本构建通过后初始化配置，配置变更通过服务提交和 Bot 应用确认。

`prod/config-v1.sh` 与 `prod/config-v1.ps1` 提供 SSH CLI 驱动，支持 `status`、`export`、`preview`、`import`、`apply`、`backup` 和 `restore`，见 [生产模板](../../prod.example/README.md)。配置回流支持[共同基线同步](config-sync.md)和单独 JSON 导出；数据库回流通过一致备份。

回退至 1.16.1 使用迁移前 TOML、独立人格与 generation 资产。保留新库便于再次升级；升级后的新配置修改不反向导出为 TOML。部署前核对实际配置来源、服务启动顺序和备份。

### 回退旧版本后再次升级

升级或回退前，备份配置数据库及业务会话库 `data/llm.db`、追踪库 `data/llm_trace.db`；这些数据库分别保存配置、聊天／存档与 HTTP 观测记录。使用一致备份，或先停止 Bot 与 Web 后备份实际数据目录。配置 CLI 的 `backup` 自动保存配置库及同目录配套的 `.runtime.db` 文件，恢复时两份文件一同保留。

若已经运行过 1.16.2，随后回退旧代码并产生会话操作，再次升级时需重新分配业务会话身份。旧程序不会维护新增身份字段：在停止 Bot 与 Web、备份当前 `data/llm.db` 后，对该会话库执行以下维护 SQL，完成后启动新版：

```sql
BEGIN IMMEDIATE;
UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL;
UPDATE session_archives SET session_id = NULL, session_created_at = NULL;
COMMIT;
```

可在项目根通过 Python 执行，无需另外安装 SQLite 命令行工具：

```bash
python -c "import sqlite3; c = sqlite3.connect('file:data/llm.db?mode=rw', uri=True); c.executescript('BEGIN IMMEDIATE; UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL; UPDATE session_archives SET session_id = NULL, session_created_at = NULL; COMMIT;'); c.close()"
```

Windows 懒人包将 `python` 换为 `python\python.exe`；容器部署在挂载真实数据目录的维护环境中执行，并核对数据库路径。该操作用于已经包含身份字段的会话库，保留消息、存档、设置和 generation；活动聊天与恢复的存档在新版中重新懒分配身份。追踪库的历史身份保留为观测记录。常规首次升级无需这项身份维护。
