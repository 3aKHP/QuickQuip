<!-- Generated from docs/admin/llm-configuration.md; do not edit -->

# LLM 配置数据库操作

LLM 配置由 `data/llm_config.db` 保存。渠道、模型、别名、请求参数、风格、价格、级联与全局设置通过 Web Admin 的“LLM 配置”页面维护。JSON 交换示例见 [`config/llm.json.example`](../../config/llm.json.example)，字段类型、继承规则与范围见受保护接口 `/ops/api/llm-configuration/metadata`，完整后端契约见 [API 文档](../dev/llm-configuration-api.md)。

页面按任务分区：配置（渠道与模型、功能路由、价格、回复风格）、行为（总开关与默认、触发与回复、上下文与记忆、纪元与代理、重试、工具与搜索、Skill、MCP 服务、报告调度）、管理（发布与历史、导入导出）。顶部状态条展示草稿→已发布→Bot 运行的版本管道；渠道与模型的参数覆盖以“跟随上层/覆盖”表达继承，渠道详情内可直接查看生效参数与发起模型探测。

## 初始化与升级

源码安装执行：

```bash
python -m quickquip.llm.config_cli init
```

初始化检查 `config/llm.toml`。有旧文件时只迁移一次；没有旧文件时建立关闭 LLM、无渠道的配置。已有数据库始终具有权威性，库损坏或 schema 不支持会明确报错。Windows `start.bat` 在启动服务前执行初始化；公开 Docker compose 的 `config-init` 在可写配置挂载中完成迁移，bot 和 Web 等待该服务成功后启动。

请求指纹 Profile 基础设施使用配置 schema 2。初始化会事务性升级已验证的 schema 1，保留草稿修订、已发布快照和操作记录。schema 1 配置库需要先停止旧 Bot 与 Web、备份数据库，再执行 `python -m quickquip.llm.config_cli init --services-stopped`。普通 Web 请求与部署准备中的初始化会拒绝直接升级这类库，保持旧程序可用。升级后的数据库需要支持 schema 2 的程序。回退旧程序时使用升级前备份。schema 1 的历史备份可先复制到独立目录，运行新程序的 `init --services-stopped` 升级副本，再按恢复流程导入。Profile 选择缺省为 `default`，自有品牌需要显式启用，配置见[请求指纹 Profile](client-fingerprints.md)。


迁移保留认证变量引用。发现认证字面量时，先将密钥写入根目录 `.env` 并把字段改为 `${VARIABLE}`。`api_key_env` 保存环境变量名称。认证 Header 可使用 `Bearer ${VARIABLE}`。数据库、导出、日志和操作错误不包含展开的认证值。

迁移备份与报告存放在 `data/llm-config-migration/<源文件摘要>/`。报告列出字段转换、限制调整、移除和外部资产处理结果。内联人格写入 `config/personas/migrated-*.toml`，使用 `inherit_shared = false` 保持原提示应用语义；已有独立人格按加载优先级保留。已有 `config/generation.toml` 继续提供多模态配置，缺失时迁移提取旧段。原文件始终保留。文件冲突需要查看报告并处理后重新初始化。

## 保存与应用

保存增加 `draft_revision`，机器人继续使用已发布快照。应用指定草稿修订号，建立不可变快照并返回配置任务 ID。后续草稿编辑继续允许；已有应用尚未结束时，再次应用返回冲突。只有 bot 已切换并回报实际版本后，任务才成功。

`published_revision` 是已接纳的快照，`loaded_revision` 是 bot 实际加载版本。启动和重启加载已发布配置。心跳超过 20 秒未更新会显示过期；Web 的模型或 MCP 实例不会代表 bot 状态。MCP 准备中或部分服务不可用会单独显示。价格修改影响新任务，历史费用与已经开始的任务保持原价格。

核心状态包含配置与业务存储的初始化结果。部署使用 `status --require-loaded` 检查新鲜心跳、发布修订加载和核心就绪；业务库不可用时返回失败。MCP 的准备或降级状态单独报告。

每次 LLM 任务固定配置与资源至结束。MCP 变更建立新资源代际，旧任务继续使用旧连接。报告时间变更替换对应调度，已经开始的报告继续执行，不补发因调整时间错过的消息。配置修订号覆盖配置库；人格文件、Skill 内容、群覆盖与其他业务数据保持各自存储职责。

## 模型参数与引用

渠道身份、协议、URL、认证变量、Header、备用地址和代理保持渠道级。模型可以覆盖请求参数，包括超时、温度、输出、流式、User-Agent、缓存、原生搜索、Responses profile、思考档位、重试、纪元和预算。

有效值顺序为调用或会话覆盖、模型覆盖、渠道默认、具有该字段职责的全局设置、内置默认。覆盖参数 `null` 继承上一层；空字符串、空对象、false 和允许的零值保存明确意图。`extra_body` 整体替换。`style_profile` 选择共享风格，`style_overrides` 保存追加文本，两者独立覆盖。新写入拒绝越界数值。

JSON 模型引用使用 `{ "provider_id": "渠道ID", "model": "wire模型名" }`。级联数组顺序就是尝试顺序，`"@default"` 在任务运行时解析默认选择。模型名可以包含 `/`。价格允许 `provider_id: null` 表示纯响应模型名回退，明确渠道价格优先。免费价格是零，未定价缺少记录，缓存价格 `null` 使用输入单价。

删除被引用对象会返回依赖。停用渠道和模型保留会话与历史记录。群覆盖只允许已发布且可用的渠道与模型；应用前会重新检查已有覆盖。

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

回退至 1.16.1 使用迁移前 TOML、独立人格与 generation 资产。保留新库便于再次升级；升级后的新配置修改不反向导出为 TOML。生产发布需验证 Windows、新旧 Docker 消费者及真实双容器路径，前端联调完成后才进入正式 1.16.2 发布流程。
