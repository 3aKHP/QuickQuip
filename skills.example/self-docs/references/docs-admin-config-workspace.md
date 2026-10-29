<!-- Generated from docs/admin/config-workspace.md; do not edit -->

# 用 qqconf 编辑本地配置

QuickQuip 的部分核心配置存储在 SQLite 数据库（`config/managed/config.db`）中，其余分布在多个目录下的 TOML、YAML、JSON 和 `.env` 文件里。

`qqconf` 的作用是：**把数据库里的配置和分散的配置文件，统一提取到一个独立的工作目录（`.config-workspace/`）中，全部展开为直观的文本文件**。你可以直接用编辑器或 LLM 修改这些文件，改完后再用 `qqconf` 校验，按部署方式打包到暂存目录或本地真实配置目录。

> **环境要求**：Python 3.11+、已安装项目依赖，且 `config/managed/config.db` 已完成[存储初始化或迁移](storage-migration.md)。

---

## 核心概念：配置是怎么流转的？

在开始前，先了解 `qqconf` 和 [qqsync](config-sync.md) 在两种部署方式下的配置流向。工作副本（`.config-workspace/`）是你和 LLM 日常编辑文件的地方：

```text
本地部署（local）：
本地真实配置 ── qqconf unpack ──> 工作副本
工作副本 ── qqconf pack ──> .config-staging/ ── qqsync push ──> 本地真实配置

云端部署（cloud）：
本地真实配置 ── qqconf unpack ──> 工作副本
工作副本 ── qqconf pack ──> 本地真实配置 ── qqsync push ──> 服务器配置
服务器配置 ── qqsync pull ──> 本地真实配置
```

---

## 日常使用流程

在项目根目录下执行：

```bash
# 1. 建立或更新工作副本（拉取本地真实配置的最新变化）
qqconf unpack

# 2. 在 .config-workspace/ 目录中自由修改配置文件...

# 3. （可选）预览改了哪些内容、有没有冲突
qqconf refresh

# 4. 校验所有配置并写回
qqconf pack
```

### 三个核心命令对比

| 命令 | 作用说明 |
|---|---|
| `unpack` | **解包到工作区**：首次运行时创建 `.config-workspace/`；后续运行时把本地真实配置的新变化同步进工作区，同时**保留**你在工作区里尚未打包的独立修改。 |
| `refresh` | **只读预览**：查看工作区与真实配置双方的变化、是否有冲突、预计写入位置以及暂存区的候选状态（始终只读，不改任何文件）。 |
| `pack` | **校验并写回**：每次都会重新比较当前内容并整体校验（无需手动复制哈希或操作编号），写回成功后自动同步工作副本的基线。 |

> **其他运行方式与常用参数**：
> - **源码环境替代命令**：可用 `python -m quickquip.config_workspace` 代替 `qqconf`。
> - **不在项目根目录执行**：在子命令后加上 `--root /path/to/QuickQuip`。
> - **自定义工作区路径**：加上 `--workspace /path/to/workspace`。
> - **脚本自动化与退出码**：加上 `--json` 输出结构化结果。命令成功退出码为 `0`；校验失败、存在冲突或写入失败退出码为 `1`（注：`refresh` 即使预览出冲突，只要预览本身成功，退出码仍为 `0`）。

---

## pack 写到哪里？何时真正生效？

`qqconf pack` 把文件写到哪，取决于真实项目根 `.env` 中设置的部署方式（`QUICKQUIP_DEPLOY_LOCATION`，详见 [qqsync 指南](config-sync.md#先设置部署方式)）：

| 部署方式 (`QUICKQUIP_DEPLOY_LOCATION`) | `qqconf pack` 的写入位置 | 如何让配置真正生效？ |
|---|---|---|
| **`local`（本地部署）** | 写入 `.config-staging/` 暂存目录（即使本地服务当前已停止，也同样先写到这里） | 运行 `qqsync push` 将暂存安装到本地真实目录并通知服务生效 |
| **`cloud`（云端部署）** | 直接写入**本地真实配置目录**（作为待推送到云端的来源） | 运行 `qqsync push` 或 `deploy-v4` 同步到服务器 |

### 写入与暂存机制说明

- **本地模式（`local`）的暂存机制**：
  - `.config-staging/` 按真实目录结构存放受管配置和独立的配置数据库。
  - 运行 `qqconf refresh` 可以查看暂存区是否处于“待部署”状态，以及本地真实配置在此期间是否又发生了改变。
  - 如果还没执行 `qqsync push` 就再次运行 `qqconf pack`，工具会基于当前真实配置重新计算并直接替换暂存区。
  - 执行 `qqsync push` 安装成功后，暂存区会被自动清理（消费），不会修改 `.config-workspace/` 及其基线。
- **云端模式（`cloud`）的本地锁保护**：
  - 因为 `cloud` 模式下 `pack` 会直接改写本地真实文件，工具在写入时会持有本地 Bot/Web 的生命周期锁。
  - 如果本地刚好有正在运行的 Bot/Web 服务，会阻止写入；但如果服务已停止（哪怕缺少历史启停记录），则可以正常写回。
- **重命名/替换人格或 Profile**：
  - 切换默认人格（Persona）或客户端 Profile 时，可以在同一次编辑中“更新引用 + 删除旧文件”。部署时会自动先暂停正在运行的 Bot/Web 服务，将相互匹配的新配置与资产文件一起安装好，再恢复原本运行的服务。

---

## 工作副本（`.config-workspace/`）里有什么？

默认工作目录 `.config-workspace/` 已被 Git 和容器构建忽略。**注意：其中包含 API Key 等敏感凭据，请按私有配置妥善保管。**

### 1. 从数据库提取出的 TOML 配置（`db/` 目录）

数据库内容提取自 `config/managed/config.db` 中的可编辑配置。工作副本中编辑的是 **LLM 草稿**（配置的历史修订记录仍保留在当前环境的数据库中）。

| 工作副本路径 | 对应的配置内容 |
|---|---|
| `db/llm/providers/*.toml` | 每个 LLM 供应商、模型列表、别名和请求参数 |
| `db/llm/settings/*.toml`、`db/llm/styles/*.toml` | LLM 全局/功能设置与回复风格 |
| `db/llm/routes.toml`、`db/llm/pricing.toml` | 路由级联策略与模型价格 |
| `db/scopes/groups/*.toml`、`db/scopes/private/*.toml` | 群聊和私聊的参数覆盖 |
| `db/games/niuniu.toml` | 群级游戏文案选择 |
| `.qqconf/` | `qqconf` 内部维护的共同基线与故障恢复资料（请勿手动删除） |

### 2. 按原样路径映射的普通配置文件

除了 `db/` 和 `.qqconf/`，工作副本中的其余路径均按项目真实相对路径保留原格式文本：

| 真实文件或目录 | 纳入工作副本的内容 |
|---|---|
| 根目录 `.env` | 应用环境变量（保存时保留原始 `${变量}` 引用格式） |
| `config/` | `generation.toml`、`chat_rules.toml`、`games.toml`、`awakening.toml`、`sensitive_words.toml`、`admins.toml`、`niuniu_text.toml`、`niuniu_text_safe.toml` |
| `config/personas/`、`config/client_profiles/` | 目录下的所有 TOML 文件（支持在工作区直接新建或删除文件） |
| `llm_about/` 及其数字群子目录 | `vocab.yaml`、`identities.yaml` |
| `data/` | `rule_switch.json`、`daily_summary_groups.json`、`daily_briefing_groups.json`、`weekly_report_groups.json`、`monthly_report_groups.json`、`awakening_boredom_groups.json` |
| `config/managed/scheduled_messages.json` | 循环定时消息定义 |
| 根目录与 `prod/` | `compose`、`compose.override`、`docker-compose`、`docker-compose.override` 的 `.yml` / `.yaml` 文件 |
| `docker/searxng/settings.yml`、`prod/sendkey.env` | 项目内的 SearXNG 搜索配置与运维通知配置 |

### 3. 不在 `qqconf` 管理范围内的内容

以下内容由各自专用工具维护，**不在**工作副本中展开：
- Skills 本体文件、LLBot 登录与混合配置、私有部署钩子、Trace 当前开关、一次性定时任务、业务数据库及示例模板。
- **关于外部路径引用**：LLM 设置中的 Skill 选项以及 `.env` 中的文件路径值会照常作为文本保存，但 `qqconf` 不会顺着这些路径去读取外部文件。

---

## 怎么编辑供应商和其他对象？

以 `db/llm/providers/*.toml` 为例，文件中直接编写业务字段：

```toml
id = "example"
protocol = "openai"
base_url = "https://example.test/v1"
api_key_env = "EXAMPLE_API_KEY"
default_model = "example-model"

[[models]]
model = "example-model"
```

### 增删改与校验规则

- **新增与删除对象**：在对应目录下新建 `.toml` 文件即新增对象；删除该文件即删除对应对象。
- **对象身份与重命名**：对象的唯一身份取决于文件内的 `id` 字段，而不是文件名。因此直接重命名 `.toml` 文件不会丢失或改变对象身份。
- **控制供应商排序**：可以通过可选的 `db/llm/order.toml` 文件（写入 `providers = ["example", "another"]`）指定供应商顺序；未在该列表中列出的新增供应商，会按文件名顺序自动追加在后面。
- **修改供应商 ID**：如果修改了某个供应商的 `id`，请务必在同一次编辑中一并修改路由（`routes.toml`）和作用域（`scopes/`）中对该 ID 的引用，`pack` 时会对完整目标做统一校验。
- **空字段与特殊值**：普通的可选空字段可以直接省略不写。如果需要在自定义 JSON 请求体中表达 `null` 等特殊值，请使用可逆的 TOML 表示法，详见[值编码契约](../dev/config-workspace.md#值编码与文本保留)。
- **环境变量校验优先级**：校验环境变量引用（如 `api_key_env`）时，优先读取目标根 `.env` 中的值；如果 `.env` 中未声明，则回退使用当前终端进程的环境变量。写回文件时，原有的 `${变量}` 引用文本会原样保留。

---

## 冲突处理：工作区和真实配置同时改了怎么办？

如果你在编辑 `.config-workspace/` 的同时，本地真实配置也发生了变化（例如通过 Web Admin 改了配置，或者刚从线上把热修 `qqsync pull` 回了本地），`qqconf` 会基于“上次共同基线、当前工作副本、当前真实配置”进行三路比较：

1. **改了不同字段 $\rightarrow$ 自动合并**：
   比如你在工作副本里调了“温度”，Web Admin 里调了“超时时间”，两边互不干扰，`pack` 或 `unpack` 时两项修改都会自动保留。
2. **改了同一字段（或一方删除、另一方修改同一对象） $\rightarrow$ 报冲突并停止写入**：
   此时写入命令会安全中止，不会覆盖任何一方。

### 解决冲突的两种办法

- **办法 A（手动整理）**：先运行 `qqconf refresh` 查看具体是哪个字段冲突，将工作副本中的冲突字段改成与当前真实配置一致的值，再重新 `pack`。如果希望保留工作副本中的值（包括手动整理的新值），请使用办法 B 的 `--prefer workspace`。
- **办法 B（命令行指定优先级）**：在本次命令中用 `--prefer` 指定“遇到冲突字段时听谁的”：

```bash
# 预览：假设冲突字段全部以工作副本（workspace）为准
qqconf refresh --prefer workspace

# 打包写回：冲突字段以工作副本为准
qqconf pack --prefer workspace

# 解包更新：冲突字段以本地真实配置（source）为准
qqconf unpack --prefer source
```

> **合并粒度与安全提示**：
> - `--prefer` **只影响有冲突的字段**，双方不冲突的独立修改依然会自动合并保留。
> - **整块替换项**：路由级联（routes）、普通数组和自由文本文件不支持内部拆分合并，冲突时按整个值/整份文件选择。`refresh` 预览会同时展示字段级差异或文本行差异。
> - **查看隐藏的密钥**：预览默认会隐藏 API 凭据和全部 `.env` 变量值；如需在终端明文核对，请运行 `qqconf refresh --show-secrets`。
> - **接入线上热修的标准顺序**：如果线上环境做过热修，请先用 [同步工具](config-sync.md)（`qqsync pull`）把线上改动拉回本地真实文件，再运行 `qqconf unpack` 合入工作副本。

---

## 故障恢复：命令意外中断了怎么办？

- **普通写入失败**：工具会自动还原现场，无需手动干预。
- **进程意外退出（断电、被强行 Kill 等）**：
  - 此时运行 `qqconf refresh` 会报告“待恢复”状态。
  - **恢复方法**：在原项目根目录和原工作副本路径下，直接**重新运行一次 `qqconf pack`**（如果是首次 `unpack` 时中断，则重新运行 `qqconf unpack`）。工具会自动先完成恢复，再继续处理你当前的修改。
  - **写到一半时的并发保护**：如果中断发生在真实配置写到一半时，Bot、Web 以及其他配置写入入口都会自动等待恢复完成。
  - **恢复期间的外部改动检测**：如果恢复时发现其他工具趁中断期间改过了文件或数据库，`qqconf` 会保留现场并报告冲突。请先核对这些外部修改及恢复资料，再处理冲突。
  - **切勿删除恢复目录**：在恢复彻底完成前，请保留 `.qqconf/`、`data/qqconf/` 以及候选暂存相关目录。
- **旧版工作副本升级**：如果你有旧版工具留下的工作副本，可以将其保留作为备份，然后执行 `qqconf unpack --root /path/to/QuickQuip --workspace /path/to/new-workspace`（分别替换为项目根目录和新的空工作目录），再把备份里需要保留的修改迁入新工作区。
