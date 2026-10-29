<!-- Generated from docs/admin/llm-configuration.md; do not edit -->

# LLM 配置数据库操作指南

本文面向部署与运维人员，说明 QuickQuip 的 LLM 配置是如何初始化、修改、发布生效以及备份恢复的。

所有结构化的 LLM 配置统一保存在 SQLite 数据库 `config/managed/config.db` 中。日常你可以通过 Web Admin 后台的 **“LLM 配置”** 页面，一站式维护渠道、模型、别名、请求参数、回复风格、模型价格、路由级联与全局设置。

从[首次启用](#首次启用-llm)开始可以配置第一条 AI 回复。已有可用配置时，直接看[日常修改](#日常修改保存后让-bot-用上新配置)；命令行、备份恢复和升级说明分别放在后文。

配置术语见[术语表](../glossary.md#config-draft)，JSON 示例见 [`config/llm.json.example`](../../config/llm.json.example)。参数、枚举与继承信息也可通过受保护的 `/ops/api/llm-configuration/metadata` 查询，接口契约见[开发文档](../dev/llm-configuration-api.md)。

<a id="首次启用-llm"></a>

## 首次启用 LLM（6 步快速跑通）

本节的目标是：**从零开始，让机器人在测试群里成功回答你的第一次提问。**

> **开始前确认**：你已经按照 [README 安装步骤](../../README.md#安装步骤) 或 [云端部署指南](deployment.md) 启动了 Bot 和 Web Admin，确认机器人能正常收发普通群消息，并且手头已准备好：**Web 后台管理密码**，以及至少一个模型服务商提供的 **协议类型、API Base URL、模型名称和 API Key**。

1. **准备默认人格与 API Key 环境变量**
   - **复制默认人格**：首次源码或容器安装时，请将 `config/personas.example/` 复制为 `config/personas/`，系统会默认使用其中的 `quickquip-default` 人格（注：Windows 懒人包在首次启动时已自动创建，无需手动复制）。
   - **填入 API Key**：打开项目根目录的 `.env` 文件，填入所选模型渠道的密钥变量，例如：
     ```dotenv
     OPENAI_API_KEY=sk-你的真实密钥
     ```
   - **让新的 `.env` 生效**：如果修改 `.env` 时服务已经在运行——源码或懒人包环境请先停止 Bot 和 Web 再重新启动；Docker 容器环境请按[环境变量更新步骤](deployment.md#日常维护)重新 `up -d` 创建这两个容器，使新环境变量注入容器。

2. **登录后台并添加渠道（Provider）**
   - 打开 Web Admin 后台，进入 **“LLM 工坊 → LLM 配置 → 渠道与模型”**，点击 **“添加渠道”**。
   - **渠道 ID**：可自定义填写（如 `my-provider`）。
   - **协议**与 **API 地址**：按你的模型服务商文档填写。
   - **密钥环境变量**：填写第 1 步在 `.env` 中定义的**变量名**（例如填 `OPENAI_API_KEY`，注意不要直接填密钥明文！）。
   - 保持该渠道处于 **“已启用”** 状态。

3. **添加模型并设为默认**
   - 在当前渠道下方的 **“模型清单”** 中点击 **“添加模型”**，填入服务商提供的模型名称（如 `gpt-4o`）并保持启用。
   - **上下文容量**：按服务商说明填写；留空时系统会尝试自动识别，若遇到无法自动识别的自定义模型则必须手动填写。
   - 回到渠道上方的 **“连接与认证”** 区域，在 **“默认模型”** 下拉框中选中刚才添加的模型，然后点击 **“设为默认渠道”**。

4. **开启全局 LLM 总开关**
   - 切换到左侧 **“对话与上下文 → 总开关与全局默认”**。
   - 打开 **“启用 LLM 功能”** 开关，并确认 **“默认渠道”** 是你刚添加的渠道、**“默认人格”** 是 `quickquip-default`。

5. **保存草稿并应用到 Bot**
   - 点击页面顶部的 **“保存草稿”**，随后点击 **“应用到 Bot”**。
   - 等待配置发布任务完成，确认顶部状态条中的 **“Bot 实际运行”** 版本已更新为与 **“已发布版本”** 一致，且 Bot 心跳显示为绿色新鲜状态（Bot 每 5 秒轮询领取一次配置任务，请确保运行 Bot 的终端或容器保持启动）。

6. **在测试群发送第一条提问**
   - 使用群主、群管理员或[全局管理员](global-admins.md)账号，在测试群内先发送 `/llm on` 开启本群 AI，再发送 `/llm status` 确认状态已开启。
   - 发送 `/ai 请回复“测试成功”`（`/ai` 是默认触发前缀；如果该群自定义过前缀请使用实际前缀）。收到机器人的回答即大功告成！（注：该提问会发出真实的模型 API 请求，按渠道规则计费。）

> **首次启用常见排障**：
> - **点击“应用到 Bot”后任务一直处于排队中？** 请检查 Bot 进程是否正在运行，以及 Bot 与 Web Admin 是否共享了同一个配置库（`config/managed/config.db`）和运行库（`data/config_runtime.db`）。
> - **应用任务提示失败？** 点开该任务查看具体报错原因，重点核对 `.env` 中的密钥变量名是否拼写一致、默认模型是否已选、以及 `config/personas/quickquip-default.toml` 人格文件是否存在。
> - **显示已加载成功，但群里发消息没反应？** 先在群里发 `/llm status` 检查本群开关与触发前缀，再去查看 Bot 终端/容器日志中是否有上游渠道返回的请求报错。

---

## 日常修改：保存后让 Bot 用上新配置

已有可用渠道后，可以按下面的顺序调整模型参数、工具开关或报告设置：

1. 在对应模块修改配置。例如调整单个模型的温度，进入“渠道与模型”选中该模型，在参数覆盖中填写温度；只想跟随渠道设置时选择“跟随上层”。
2. 点击“保存草稿”。此时改动已经保存，Bot 继续使用已发布版本，方便你检查其他相关设置。
3. 确认草稿内容后点击“应用到 Bot”，等待任务完成。若失败，先看任务中的字段路径和错误，修正后重新保存、应用。
4. 确认顶部“Bot 实际运行”与目标版本一致、心跳正常，再通过相关功能检查结果。

已有任务排队时先检查 Bot 是否运行。重启会加载已发布配置，未应用的草稿仍需单独提交。具体状态与参数继承见下文；替换正在被群聊使用的渠道时，按[迁移群绑定](#迁移群绑定与退役旧渠道处理-dependency_conflict)先迁移引用。

## 保存草稿与应用生效机制

### 1. 版本标记与修订号（Revision）管道

Web Admin 使用 **`YYYY-MM-DD HH:mm (备注)`** 的格式标记每一个配置版本（时间戳为该修订的保存时刻；备注文字可以随时在顶部状态条、发布页或历史快照列表上修改）：

- **保存草稿（Save Draft）**：
  - 每次点击保存会使草稿修订号 `draft_revision` 加 1，尚未发布的草稿在多次保存之间会自动保留你写的版本备注；一旦正式发布后，下一次新保存的草稿会从空备注重新开始。
  - **保存草稿绝对不会影响正在运行的机器人**——Bot 始终继续使用上一次已发布的快照。
- **应用到 Bot（Apply）**：
  - 点击应用时，系统会锁定当前指定的草稿修订号，生成一份**待应用的不可变快照**，并创建一个异步配置任务（返回任务 ID）。排队期间已发布版本保持不变；Bot 处理任务进入发布阶段时，才会更新 `published_revision`。
  - 在等待 Bot 领取任务期间，你依然可以继续编辑新草稿；但如果**上一个应用任务还没执行完**就再次点击应用，系统会返回冲突提示。
  - **何时算应用成功？** 只有当 Bot 进程实际完成配置切换，并向数据库回报了最新的实际加载版本号（使 `loaded_revision == published_revision`）后，该配置任务才算最终成功。

### 2. 心跳监测、状态检查与运行期隔离

- **Bot 心跳与 Web 状态隔离**：
  - Bot 启动或重启时会自动加载最新的 `published_revision`。如果 Bot 心跳超过 **20 秒**未更新，后台状态条会提示“心跳已过期”。
  - Bot 的状态以它自己的回报为准。MCP 正在初始化或部分服务不可用时，后台会单独显示连接状态。
- **部署健康检查接口（`status --require-loaded`）**：
  - 核心状态涵盖配置存储与业务存储的初始化结果。自动部署脚本会调用 `config_cli status --require-loaded` 同时校验三件事：**Bot 心跳新鲜 + 最新已发布修订已加载 + 核心业务数据库就绪**（若业务库不可用会直接返回失败；MCP 的准备中或降级状态则单独报告，不阻塞核心就绪）。
- **正在执行的任务不受中途改配置影响**：
  - 每一次 LLM 对话任务在开始时都会锁定它当时使用的配置、模型价格与连接资源，直到该次回答结束。
  - **修改模型价格**：仅对修改后新发起的任务生效；历史账单与正在执行中的任务保持原价格。
  - **修改 MCP 配置**：新任务使用新的 MCP 连接，正在执行中的任务继续使用旧连接直到结束。
  - **修改定时报告时间**：会替换对应的调度器计划；但已经在生成中的报告会继续执行完毕，且不会补发因调整时间而错过的历史定时消息。
  - **管理边界**：配置修订号（Revision）仅覆盖 `config.db` 中的结构化配置；外部人格文件、Skill 内容、群文件词表与其他业务数据各自独立维护。

---

<a id="模型参数与引用"></a>

## 模型参数继承、路由引用与计费定价

### 1. 参数五层继承顺序与覆盖规则

- **渠道级固定属性**：渠道 ID、协议类型、Base URL、认证环境变量、自定义 Header、备用地址（Fallback URLs）和网络代理，固定在**渠道（Provider）层级**维护。
- **模型级可覆盖参数**：超时时间、温度（Temperature）、最大输出 Token、流式开关（Stream）、User-Agent、提示词缓存、原生搜索开关、Responses Profile、思考档位（Reasoning Effort）、重试次数、纪元与思考预算等，均支持在单个模型上进行覆盖。
- **最终生效值的五层优先级（从高到低）**：
  ```text
  1. 单次调用或会话级覆盖 (Highest)
  2. 模型级覆盖 (Model Override)
  3. 渠道级默认参数 (Provider Default)
  4. 负责该字段的全局设置 (Global Settings)
  5. 系统内置默认值 (Built-in Default)
  ```
- **空值与特殊字段语义**：
  - 覆盖参数设为 `null`（或在界面选择“跟随上层”）表示**继承上一层的值**；
  - 而显式填入空字符串 `""`、空对象 `{}`、`false` 或合法的 `0` 值，则代表**明确覆盖为该值**（新写入时会严格拦截越界数值）。
  - `extra_body` 在覆盖时采用**整块替换**（不与上层做深度合并）。
  - 回复风格中，`style_profile`（选择共享风格模板）与 `style_overrides`（追加自定义风格指令）两者相互独立，可分别覆盖。

### 2. 模型引用格式与路由级联（Routes）

- 在 JSON 配置中引用模型时，统一使用结构化对象：`{ "provider_id": "渠道ID", "model": "上游实际模型名(wire name)" }`（模型名中允许包含 `/` 字符）。
- **路由级联数组**：级联数组中的排列顺序就是请求失败时的依次回退尝试顺序；支持使用特殊标识 `"@default"`，它会在任务实际运行时动态解析为当前的全局默认渠道与模型。

### 3. 模型价格与计费匹配规则

- **唯一计费单位**：价格严格以 **`渠道 (provider_id) + 配置的模型 ID`** 为唯一计费单位（`provider_id` 必须是已存在的渠道）。
  - 同一个模型名如果在多个不同渠道中配置，**必须在每个渠道下各自独立定价**，系统不存在跨渠道的“全局同名模型兜底价”（Web Admin 的“模型价格”页支持将某一行价格一键复制到同样配置了该模型的其他渠道；删除渠道时会自动一并删除该渠道下的所有价格记录）。
- **按请求发出名匹配（不受中转改名影响）**：
  - 用量计费严格按照 QuickQuip **发出请求时配置的模型名**匹配价格；上游 API 响应中如果改写了模型名（例如中转站去掉了前缀，或将 `gpt-4o` 返回为带日期的快照名 `gpt-4o-2024-11-20`），**不会影响定价匹配**。
- **免费、未定价与缓存价格**：
  - **免费模型**：请将单价显式填为 `0`。
  - **未定价模型**：没有价格记录的模型视为未定价（在 Web Admin“模型价格”页按渠道分组展示时，未定价模型可点击“补行”，新补行的单价默认留空，填写具体数值后才能保存）。
  - **缓存价格**：若缓存单价设为 `null`（留空），计费时自动按普通输入单价计算。
- **旧版（`format_version: 1`）价格导入兼容**：
  导入旧格式 JSON 时，形如 `渠道ID/模型名` 的兜底价格会自动归属到对应渠道；而纯模型名（无渠道前缀）的旧兜底价格，**只有当全库恰好仅有一个尚未定价的渠道配置了该模型时**才会自动归属过去，否则会被移除（导入预览界面会逐条列出每个价格的处理结果）。

---

### 迁移群绑定与退役旧渠道（处理 `dependency_conflict`）

系统具有严格的引用完整性保护：
- **停用（Disable）** 某个渠道或模型时，会保留现有的会话与历史记录；
- 但直接**删除（Delete）** 仍被其他地方引用的渠道或模型，或者将群聊/私聊绑定到未发布或已停用的渠道/模型时，系统会报错拦截（群级覆盖只允许指向**已发布且启用中**的渠道与模型，每次点击“应用到 Bot”前都会重新校验所有现存的群覆盖）。

如果你在删除/停用旧渠道并点击应用时，收到 **`dependency_conflict`** 错误且字段路径指向 **`scope_settings.<scope>`**，说明还有某个群聊或私聊覆盖绑定在该渠道上（**注意：即使某个群已经执行了 `/llm off` 关闭 AI，它之前保存的群级渠道覆盖依然留在库里，不会自动清除**）。

请按以下标准三步法安全替换并退役旧渠道：

1. **先上架新渠道**：添加新的渠道与模型，点击“保存草稿”并“应用到 Bot”，让新渠道先成为**已发布且可用**的正式对象。
2. **迁移受影响的群/私聊绑定**：
   - 进入后台 **“群 LLM”** 页面，找到报错提示的群或私聊（Scope），将其绑定的渠道／模型修改为刚才发布的新渠道，或者改为“跟随全局默认”并保存（私聊也可以直接在聊天窗发送 `/llm use <新provider> [新model]` 完成迁移；如果打算点击页面上的“清空”按钮移除全部覆盖，请先留意界面提示，确认它会一并重置的其它群级参数）。
3. **最后下架旧渠道**：回到“LLM 配置”页面，停用或删除旧渠道／模型，并检查“报告与路由”等功能路由中是否还有残留引用，最后保存草稿并应用（注：群覆盖保存后对后续新请求生效，正在执行中的请求仍使用原绑定直到结束）。

---

## 命令行工具（`config_cli`）参考

> **日常批量修改推荐用 `qqconf`**：如果你需要把配置拆成多份 TOML 文件来审阅、写注释或让 LLM 修改，请直接使用 [qqconf 工作副本工具](config-workspace.md)（`qqconf pack` 会根据根 `.env` 的部署位置写入本地 `.config-staging/` 暂存或本地真实配置，再由 `qqsync` 部署生效）。
> 下方的 `config_cli` 则用于底层的整库 JSON 导入导出、单步修订控制与数据库级备份恢复。

在项目根目录下运行（可通过全局参数 `--db <路径>` 指定配置库路径；JSON 导入文件大小上限为 **1 MiB**；除 `init` 外，其余子命令均要求配置库已存在）：

### 查看状态与导出配置

```bash
python -m quickquip.llm.config_cli validate
python -m quickquip.llm.config_cli status
python -m quickquip.llm.config_cli export --source published --output llm-export.json
```

`status --require-loaded` 额外要求 Bot 心跳新鲜且加载了已发布配置，适合启动后检查。

### 预览、导入并应用修改

先编辑导出的 JSON。以下示例假设当前草稿修订号为 1；实际使用时从 `status` 获取修订号，分别替换导入和应用命令中的值。

```bash
python -m quickquip.llm.config_cli import llm-export.json --expected-revision 1 --preview
```

预览符合预期后导入，检查差异。导入会整份替换草稿，示例中生成修订 2：

```bash
python -m quickquip.llm.config_cli import llm-export.json --expected-revision 1
python -m quickquip.llm.config_cli diff
```

确认后单独应用。`request-id` 填本次操作的新标识；同一请求超时重试时复用它：

```bash
python -m quickquip.llm.config_cli apply --expected-revision 2 --request-id unique-request-id
```

用返回的任务 ID 替换 `returned-operation-id`，查看结果：

```bash
python -m quickquip.llm.config_cli status --operation returned-operation-id
python -m quickquip.llm.config_cli status --require-loaded
```

### 从历史快照恢复草稿

先在历史中选定快照，并查询当前草稿修订号。下面将快照 1 恢复成新草稿；它会递增草稿修订号，之后还需检查并应用：

```bash
python -m quickquip.llm.config_cli restore --snapshot 1 --expected-revision 2
```

### 备份数据库

```bash
python -m quickquip.llm.config_cli backup data/llm-config-backup.db
```

命令通过 SQLite backup 读取已提交数据，同时生成配套的 `.runtime.db` 文件。两份文件一起保留，恢复方法见下节。



- **乐观锁与导入规则说明**：
  - 执行 `import`、`apply`、`restore --snapshot` 或在已有库上运行 `migrate-legacy --legacy <文件>` 时，都必须通过 `--expected-revision` 传入当前草稿修订号；如果期间别人改过草稿导致修订号不匹配，命令会报修订冲突，请重新运行 `status` / `diff` 审查差异后再试。
  - `import` 和 `migrate-legacy` 都**只会更新草稿（整体替换草稿）**，不会自动发布，需要再单独执行一次 `apply` 才会让 Bot 生效。

### 停服恢复整个数据库文件（`restore --file`）

**切勿在服务运行时直接用文件复制的方式覆盖主数据库文件！** 如需从备份的 `.db` 文件恢复数据库，必须先停止 Bot 和 Web 服务，再执行：

```bash
python -m quickquip.llm.config_cli restore --file data/llm-config-backup.db --services-stopped
```
> 工具在恢复前会自动检查备份文件的 schema 版本，并先将当前库做一次安全备份；恢复完成后会自动清除旧的 Bot 心跳与未结束的任务租约，随后即可正常启动服务。

---

## 初始化与升级

### 1. 配置库初始化命令与各环境执行时机

在源码环境中，可在项目根目录下执行初始化命令：

```bash
python -m quickquip.llm.config_cli init
```

- **`init` 命令的行为逻辑**：
  - **已有数据库具有最高权威**：如果配置库已经存在，系统始终以现有数据库为准（若数据库文件损坏或 schema 版本不受支持，会明确报错停止）。
  - **存在旧版 `config/llm.toml` 时**：自动执行**仅一次**的旧配置迁移入库。
  - **全新安装（既无库也无旧 `llm.toml`）**：自动创建一个“LLM 总开关关闭、无任何渠道”的干净初始库，以及配套的 `data/config_runtime.db` 运行库（默认请求指纹 Profile 设为 `default`，详见[请求指纹 Profile](client-fingerprints.md)）。
- **不同部署方式的自动初始化**：
  - **Windows 懒人包**：运行 `start.bat` 时会在启动服务前自动执行 `init`。
  - **根目录 Docker Compose 模板（`docker-compose.example.yml`）**：由专门的 `config-init` 容器在可写配置挂载中完成初始化/迁移，Bot 和 Web 容器会等待它执行成功后才启动。
  - **生产部署脚本（`deploy-v4`）**：在切换版本前会自动在服务器端完成初始化。
  - **手动生产 Docker 安装**：需先构建镜像，再按[云端部署指南第 4 步](deployment.md#4-启动服务)借用 `web-admin` 容器手动运行一次 `init` 命令。

### 2. 数据库 Schema 版本与升级路径

当前最新配置数据库版本为 **`schema 4`**（发布执行状态与心跳单独保存在 `data/config_runtime.db`）：
- **从 `schema 3`（v1.16.3）升级**：请先严格按照[存储迁移指南](storage-migration.md)执行停服存储拆分迁移。
- **从更早的 `schema 1` 或 `schema 2` 升级**：必须先使用支持 `schema 3` 的旧版本程序完成升级，再升级到当前版本。

### 3. 从旧版 `llm.toml` 首次迁移的规则与报告

当 `init` 从旧版 `config/llm.toml` 迁移数据时，会自动完成以下处理，并将**迁移备份与详细报告**保存在 `data/llm-config-migration/<源文件摘要>/` 目录下（原有的旧文件始终保留不被删除）：

- **凭据安全脱敏**：迁移会保留 `${VARIABLE}` 形式的环境变量引用（`api_key_env` 仅保存变量名，自定义认证 Header 可使用 `Bearer ${VARIABLE}` 格式）。迁移生成的配置、JSON 导出和迁移诊断保留变量引用，不写入展开后的认证值。如果旧 `llm.toml` 中直接硬编码了密钥明文（字面量），迁移会报错拦截——请先将密钥写入根目录 `.env`，并把 TOML 中的字段改为 `${VARIABLE}` 引用后再试。
- **内联人格提取**：旧配置中的内联人格会被自动提取为 `config/personas/migrated-*.toml` 独立文件（自动设置 `inherit_shared = false` 以保持原有的提示词拼接语义；如果同名独立人格文件已存在，则按加载优先级保留现有文件）。
- **多模态配置提取**：如果 `config/generation.toml` 已存在则继续使用；若不存在，迁移会自动从旧配置中提取多模态段落生成该文件。
- **迁移报告审查**：迁移报告会详细列出所有的字段转换、数值越界修正、已移除废弃项以及外部资产处理结果。如果遇到文件冲突，请先查看报告并处理冲突文件后，再重新运行 `init`。

---

### 首次迁移的 Profile 字段冲突

旧版 `llm.toml` 中手动编写的 `extra_body` 或自定义 `headers`，可能会与新版默认请求指纹 Profile（Client Fingerprint）自动接管的协议字段发生冲突——例如：
- Claude 协议的 `system` / `messages` / `tools`
- Gemini 协议的 `contents` / `systemInstruction` / `tools`
- OpenAI Responses 协议的 `prompt_cache_key` 以及自动生成的 Session Header

如果运行 `init` 时报错返回 **`profile_owned_body`** 或 **`profile_owned_header`**，说明数据库尚未初始化完成，请按以下 4 步处理：

1. **备份与脱敏**：停止旧版服务，备份好旧版 TOML、人格、多模态资产及 `data/` 目录；如果旧 TOML 中有密钥明文，先将其转为根 `.env` 的环境变量引用。
2. **移除冲突字段并重新初始化**：根据报错提示的字段路径，先从待迁移的 `llm.toml` 中删掉冲突的手工字段（原值保留在你的备份文件中），然后重新运行 `python -m quickquip.llm.config_cli init` 完成入库。
3. **在后台切换兼容 Profile**：启动新版 Bot 和 Web，进入对应渠道详情页调整请求指纹策略：
   - 如果是 Claude 或 Gemini 渠道，可直接选择内置的兼容策略 `legacy-claude` 或 `legacy-gemini`；
   - 其他情况请按[自定义 Profile 指南](client-fingerprints.md#编辑-profile-文件)编写一个不接管该字段的自定义 Profile 模板，放置好文件后重启 Bot 和 Web。
   - *(注：旧版 TOML 中如果写过 `client_fingerprint` 字段，不会自动迁移为渠道的 Profile 选择，需在新版后台手动指定。)*
4. **填回自定义字段并应用**：切换为兼容 Profile 后，把第 2 步删掉的手工字段重新填回该渠道的 `parameters.extra_body` 或固定 `headers`（认证 Header 请继续使用 `${变量}` 引用），预览变更无误后点击“保存草稿”并“应用到 Bot”。

---

## 生产环境同步与跨版本回退

### 1. 生产环境配置发布与旧版驱动兼容
- **标准生产流程**：生产环境的配置通过 Web Admin 或配置同步工具变更。日常运行 `deploy-v4` 默认通过 [qqsync 单向推送配置](config-sync.md)（自动排除本地 `.db` 文件和旧版 `llm.toml` 的原始文件上传；候选版本镜像构建通过后会自动初始化配置，并通过服务提交和等待 Bot 确认加载来完成变更）。
- **老服务器升级参数**：
  - 仍在使用 `data/llm_config.db` 的老服务器：首次升级先按[存储迁移指南](storage-migration.md)执行 `--migrate-storage`（保留服务器配置并关闭本次同步）。
  - 已完成存储迁移、首次升级同步能力的服务器：使用 `--config-sync off`，随后选择初始来源建立同步基线。
- **配置回流与旧版 SSH 驱动**：
  - 配置回流推荐使用 [qqsync 共同基线同步](config-sync.md) 或单独导出 JSON；完整数据库回流则通过一致性备份完成。
  - 仓库的 `scripts/deploy/legacy/config-v1.sh` 与 `scripts/deploy/legacy/config-v1.ps1` 仍保留了基于 SSH 的 CLI 远程驱动（支持远程执行 `status`、`export`、`preview`、`import`、`apply`、`backup` 和 `restore`，详见[生产模板说明](../../prod.example/README.md)）。

---

### 回退旧版本后再次升级

无论是大版本升级还是回退，操作前都请完整备份以下三个核心数据库（建议使用 SQLite 一致性备份，或在停止 Bot 和 Web 后直接备份整个数据目录）：
1. **配置数据库**：`config/managed/config.db`（使用 `config_cli backup` 时会自动同目录生成配套的 `.runtime.db`，恢复时两份文件需一同保留）
2. **业务会话库**：`data/llm.db`（保存聊天记录、会话存档、群设置与多模态生成记录）
3. **调用追踪库**：`data/llm_trace.db`（保存 LLM HTTP 观测记录）

> **回退至 v1.16.1 的说明**：回退到 1.16.1 时，旧程序会重新读取首次迁移前保留的旧 `llm.toml`、独立人格与 `generation.toml` 资产（升级到新版数据库后所做的新配置修改不会反向导出回旧 TOML；请保留新版数据库不动以便日后再次升级，回退前请核对好实际配置来源与服务启动顺序）。

#### 特殊维护：运行过 v1.16.2+ 后回退旧代码，又再次升级时的 Session 身份重置

如果你**常规首次升级**，完全不需要做下面这步。
但如果你**之前已经升级并运行过 v1.16.2（或更高版本），随后回退到了旧版本代码并产生过聊天会话操作，现在又准备再次升级回新版本**：

因为旧版本代码不会维护新版在 `data/llm.db` 中引入的会话身份字段（`session_id` / `session_created_at`），再次升级启动新版前，需要在**停止 Bot 和 Web、并备份好当前 `data/llm.db`** 后，对该会话库执行以下维护 SQL 将身份字段置空：

```sql
BEGIN IMMEDIATE;
UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL;
UPDATE session_archives SET session_id = NULL, session_created_at = NULL;
COMMIT;
```

你可以直接在项目根目录下用一行 Python 命令完成上述操作（无需额外安装 `sqlite3` 命令行工具）：

```bash
python -c "import sqlite3; c = sqlite3.connect('file:data/llm.db?mode=rw', uri=True); c.executescript('BEGIN IMMEDIATE; UPDATE agent_scopes SET session_id = NULL, session_created_at = NULL; UPDATE session_archives SET session_id = NULL, session_created_at = NULL; COMMIT;'); c.close()"
```

- **不同环境的执行方式**：
  - **Windows 懒人包**：将命令开头的 `python` 替换为 `python\python.exe`。
  - **Docker 容器部署**：在挂载了真实 `data/` 目录的维护容器中执行，并注意核对容器内的 `llm.db` 路径。
- **执行后会改变什么**：该 SQL 将两张表的 `session_id`、`session_created_at` 置空，保留消息、存档及其他字段。新版程序在使用活跃聊天或恢复存档时重新分配会话身份；追踪库中的历史身份继续保留，供查询旧请求。
## Web Admin “LLM 配置”页面结构总览

后台的“LLM 配置”页面包含以下 **6 个核心模块** 与 **1 个顶部状态条**：

- **顶部版本管道状态条**：实时展示 `草稿 (Draft) → 已发布 (Published) → Bot 实际运行 (Loaded)` 的版本号管道与 Bot 心跳状态。
- **模块 1：渠道与模型**：管理 API 渠道连接、模型清单、模型级参数覆盖与回复风格。在渠道详情内可直接查看最终生效的参数，并一键发起模型探活测试（参数继承关系在界面上统一以“**跟随上层 / 覆盖**”清晰标示）。
- **模块 2：对话与上下文**：管理 LLM 全局总开关、默认渠道、默认人格及上下文窗口策略。
- **模块 3：工具与技能**：管理内置工具、Skill 技能开关，并实时查看外部 MCP 服务的连接状态。
- **模块 4：报告与路由**：管理定时报告生成与多模型级联回退路由（Routes）。
- **模块 5：模型价格**：按渠道维护各个模型的输入/输出/缓存计费单价。
- **模块 6：发布与历史**：提供整库配置的 JSON 导入/导出、历史发布快照对比与恢复草稿。

---
