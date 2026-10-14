# LLM 配置数据库操作

LLM 配置由 `data/llm_config.db` 保存。渠道、模型、别名、请求参数、风格、价格、级联与全局设置通过 Web Admin 的“LLM 配置”页面维护。JSON 交换示例见 [`config/llm.json.example`](../../config/llm.json.example)，字段类型、继承规则与范围见受保护接口 `/ops/api/llm-configuration/metadata`，完整后端契约见 [API 文档](../dev/llm-configuration-api.md)。

页面包含渠道与模型、对话与上下文、工具与技能、报告与路由、模型价格、发布与历史六个模块。渠道模块包含模型参数与回复风格，工具模块包含 MCP 状态，发布模块提供 JSON 导入导出与历史管理。顶部状态条展示草稿→已发布→Bot 运行的版本管道；渠道与模型的参数覆盖以“跟随上层/覆盖”表达继承，渠道详情内可直接查看生效参数与发起模型探测。

## 初始化与升级

源码安装执行：

```bash
python -m quickquip.llm.config_cli init
```

初始化检查 `config/llm.toml`。有旧文件时只迁移一次；没有旧文件时建立关闭 LLM、无渠道的配置。已有数据库始终具有权威性，库损坏或 schema 不支持会明确报错。Windows `start.bat` 在启动服务前执行初始化；公开 Docker compose 的 `config-init` 在可写配置挂载中完成迁移，bot 和 Web 等待该服务成功后启动。

配置数据库当前为 schema 3：schema 2 增加请求指纹 Profile 字段，schema 3 增加版本标记（修订保存时间与备注）并把价格统一为按渠道计费。初始化会事务性升级已验证的 schema 1 或 2，保留草稿修订、已发布快照和操作记录。旧 schema 的配置库需要先停止旧 Bot 与 Web、备份数据库，再执行 `python -m quickquip.llm.config_cli init --services-stopped`。普通 Web 请求与部署准备中的初始化会拒绝直接升级这类库，保持旧程序可用。升级后的数据库需要支持 schema 3 的程序。回退旧程序时使用升级前备份。旧 schema 的历史备份可先复制到独立目录，运行新程序的 `init --services-stopped` 升级副本，再按恢复流程导入。升级到 schema 3 时，价格表中的全渠道兜底行会归属到渠道或移除，逐条结果写入升级报告，规则见下文价格。Profile 选择缺省为 `default`，自有品牌需要显式启用，配置见[请求指纹 Profile](client-fingerprints.md)。


迁移保留认证变量引用。发现认证字面量时，先将密钥写入根目录 `.env` 并把字段改为 `${VARIABLE}`。`api_key_env` 保存环境变量名称。认证 Header 可使用 `Bearer ${VARIABLE}`。数据库、导出、日志和操作错误不包含展开的认证值。

迁移备份与报告存放在 `data/llm-config-migration/<源文件摘要>/`。报告列出字段转换、限制调整、移除和外部资产处理结果。内联人格写入 `config/personas/migrated-*.toml`，使用 `inherit_shared = false` 保持原提示应用语义；已有独立人格按加载优先级保留。已有 `config/generation.toml` 继续提供多模态配置，缺失时迁移提取旧段。原文件始终保留。文件冲突需要查看报告并处理后重新初始化。

### 首次迁移的 Profile 字段冲突

旧 TOML 的 `extra_body` 或 Header 可能覆盖新版默认 Profile 管理的字段，例如 Claude 的 `system`／`messages`／`tools`、Gemini 的 `contents`／`systemInstruction`／`tools`、Responses 的 `prompt_cache_key`，以及自动 Session Header。初始化返回 `profile_owned_body` 或 `profile_owned_header` 时，数据库尚未准备完成，须先处理迁移输入：

1. 停止旧服务，保留旧 TOML、人格、多模态资产及数据目录备份，认证字面量先转为根 `.env` 的变量引用。
2. 根据错误字段路径，从用于迁移的 TOML 中移除冲突的手工字段，保留原值于备份；重新运行 `python -m quickquip.llm.config_cli init`。
3. 启动新版 Bot 与 Web 后，在渠道详情选择兼容策略：Claude／Gemini 可选 `legacy-claude`／`legacy-gemini`；其他情况按[自定义 Profile](client-fingerprints.md#编辑-profile-文件)定义未管理该字段的策略，并在放置模板后重启 Bot 与 Web。
4. 将仍需使用的手工字段填回渠道 `parameters.extra_body` 或固定 `headers`，预览实际变更，保存草稿并应用，确认 Bot 已加载。认证 Header 继续使用变量引用。

旧 TOML 加入 `client_fingerprint` 不会迁移为渠道选择；Profile 选择通过新版配置维护。原备份用于旧版本回退，迁移输入的调整与新版配置分别保存。

## 保存与应用

Web Admin 以「YYYY-MM-DD HH:mm (备注)」标记版本：时间是该修订的保存时刻，备注可在状态条、发布页或历史快照上随时修改。尚未发布的草稿在多次保存间保留备注，发布后的下一次保存从空备注开始。

保存增加 `draft_revision`，机器人继续使用已发布快照。应用指定草稿修订号，建立不可变快照并返回配置任务 ID。后续草稿编辑继续允许；已有应用尚未结束时，再次应用返回冲突。只有 bot 已切换并回报实际版本后，任务才成功。

`published_revision` 是已接纳的快照，`loaded_revision` 是 bot 实际加载版本。启动和重启加载已发布配置。心跳超过 20 秒未更新会显示过期；Web 的模型或 MCP 实例不会代表 bot 状态。MCP 准备中或部分服务不可用会单独显示。价格修改影响新任务，历史费用与已经开始的任务保持原价格。

核心状态包含配置与业务存储的初始化结果。部署使用 `status --require-loaded` 检查新鲜心跳、发布修订加载和核心就绪；业务库不可用时返回失败。MCP 的准备或降级状态单独报告。

每次 LLM 任务固定配置与资源至结束。MCP 变更建立新资源代际，旧任务继续使用旧连接。报告时间变更替换对应调度，已经开始的报告继续执行，不补发因调整时间错过的消息。配置修订号覆盖配置库；人格文件、Skill 内容、群覆盖与其他业务数据保持各自存储职责。

## 模型参数与引用

渠道身份、协议、URL、认证变量、Header、备用地址和代理保持渠道级。模型可以覆盖请求参数，包括超时、温度、输出、流式、User-Agent、缓存、原生搜索、Responses profile、思考档位、重试、纪元和预算。

有效值顺序为调用或会话覆盖、模型覆盖、渠道默认、具有该字段职责的全局设置、内置默认。覆盖参数 `null` 继承上一层；空字符串、空对象、false 和允许的零值保存明确意图。`extra_body` 整体替换。`style_profile` 选择共享风格，`style_overrides` 保存追加文本，两者独立覆盖。新写入拒绝越界数值。

JSON 模型引用使用 `{ "provider_id": "渠道ID", "model": "wire模型名" }`。级联数组顺序就是尝试顺序，`"@default"` 在任务运行时解析默认选择。模型名可以包含 `/`。

价格以「渠道 + 配置的模型 ID」为唯一计费单位，`provider_id` 必须是已存在的渠道。用量按请求发出的模型名匹配价格，上游响应改写的模型名（中转去前缀、带日期的快照名等）不影响定价；同名模型在不同渠道需要各自定价，不存在全渠道兜底。免费价格是零，未定价缺少记录，缓存价格 `null` 使用输入单价。导入旧格式（`format_version: 1`）JSON 时，`渠道ID/模型` 形式的兜底价格归属到该渠道；纯模型名兜底价格只在恰好一个尚未定价的渠道配置了该模型时归属，否则移除；导入预览逐条列出结果。

Web Admin 的「模型价格」按渠道分组：模型从该渠道的模型清单中选择，未定价模型可点击补行，新行的单价留空、填写后才能保存；可以把一行价格复制到同样配置了该模型的其他渠道。删除渠道时一并删除它的价格。

删除被引用对象会返回依赖。停用渠道和模型保留会话与历史记录。群覆盖只允许已发布且可用的渠道与模型；应用前会重新检查已有覆盖。

### 迁移群绑定与退役渠道

应用返回 `dependency_conflict` 且字段路径为 `group_settings.<scope>` 时，检查该群或私聊的渠道／模型覆盖。已关闭的群或私聊仍可保留覆盖，`/llm off` 不会删除引用。替换渠道时按以下顺序操作：

1. 添加新渠道与模型，保存并应用，使目标成为已发布可用对象。
2. 在「群 LLM」找到受影响 scope，将渠道／模型改为新目标或跟随默认并保存；私聊也可用 `/llm use <provider> [model]` 迁移。需要移除全部覆盖时，先核对页面“清空”将同时重置的设置。
3. 再停用或删除旧渠道／模型，检查功能路由等其他引用，保存草稿后应用。

群覆盖保存影响后续请求，已在途请求仍使用原绑定与快照。

## CLI

在项目根目录运行，可用全局 `--db <路径>` 指定配置库。JSON 导入上限为 1 MiB。除初始化外，命令需要已有配置库。

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

生产配置通过 Web 或配置运维驱动变更。普通 deploy-v4 保留服务器配置数据库，上传排除本地 DB 和本地旧 LLM TOML；首次切换选择服务器迁移输入，并在候选构建通过后、启动前初始化。迁移后生成的人格文件随生产部署保留。

`prod/config-v1.sh` 与 `prod/config-v1.ps1` 提供 SSH CLI 驱动，支持 `status`、`export`、`preview`、`import`、`apply`、`backup` 和 `restore`，见 [生产模板](../../prod.example/README.md)。配置回流通过 JSON 导出；数据库回流通过一致备份。

回退至 1.16.1 使用迁移前 TOML、独立人格与 generation 资产。保留新库便于再次升级；升级后的新配置修改不反向导出为 TOML。发布检查与专项验收范围按[发布工作流](../dev/branching.md#release)确定；部署前核对实际配置来源、服务启动顺序和备份，平台与真实双容器路径的验证结果在交付记录中注明。

### 回退旧版本后再次升级

升级或回退前，备份配置数据库及业务会话库 `data/llm.db`、追踪库 `data/llm_trace.db`；这些数据库分别保存配置、聊天／存档与 HTTP 观测记录。使用一致备份，或先停止 Bot 与 Web 后备份实际数据目录。配置库的 CLI `backup` 只覆盖 `llm_config.db`。

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
