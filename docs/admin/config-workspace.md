# 用 qqconf 编辑本地配置

`qqconf` 把本地配置整理成独立工作副本，供编辑器或 LLM 修改，再写回本地。需要 Python 3.11+、已安装的项目依赖，以及完成[存储初始化或迁移](storage-migration.md)的 `config/managed/config.db`。

## 日常使用

在项目根目录执行：

```bash
qqconf unpack
# 在 .config-workspace/ 中修改配置
qqconf refresh
qqconf pack
```

源码环境也可以使用 `python -m quickquip.config_workspace` 替代 `qqconf`。在其他目录执行时，在子命令后加 `--root /path/to/QuickQuip`。自定义工作目录使用 `--workspace /path/to/workspace`。

| 命令 | 结果 |
|---|---|
| `unpack` | 首次建立工作副本；后续接收本地真实配置的变化，保留副本中的独立修改 |
| `refresh` | 只读查看双方变化、冲突、预计写入位置及候选状态 |
| `pack` | 校验完整目标并写回，随后同步工作副本 |

预览可选。`pack` 每次重新比较当前内容，无需复制哈希或操作编号。命令成功退出为 0，校验、冲突或写入失败为 1；`refresh` 输出冲突时仍为成功预览。自动化使用 `--json`。

## 工作副本中有什么

默认目录 `.config-workspace/` 已被 Git 和容器构建忽略。其中含凭据，应按私有配置保存。

| 工作副本路径 | 配置内容 |
|---|---|
| `db/llm/providers/*.toml` | 每个供应商、模型、别名和请求参数 |
| `db/llm/settings/*.toml`、`db/llm/styles/*.toml` | LLM 设置与回复风格 |
| `db/llm/routes.toml`、`db/llm/pricing.toml` | 路由级联与价格 |
| `db/scopes/groups/*.toml`、`db/scopes/private/*.toml` | 群和私聊参数覆盖 |
| `db/games/niuniu.toml` | 群级游戏文案选择 |
| 其余路径 | 按真实相对路径保留的原格式文本，见下表 |
| `.qqconf/` | 工具维护的共同基线和恢复资料 |

数据库内容来自 `config/managed/config.db` 的可编辑配置。配置修订和历史保留在本环境数据库，工作副本编辑 LLM 草稿。

| 真实文件或目录 | 纳入内容 |
|---|---|
| 根 `.env` | 应用环境变量，保留 `${变量}` 引用 |
| `config/` | `generation.toml`、`chat_rules.toml`、`games.toml`、`awakening.toml`、`sensitive_words.toml`、`admins.toml`、`niuniu_text.toml`、`niuniu_text_safe.toml` |
| `config/personas/`、`config/client_profiles/` | 目录中的 TOML 文件，自动发现新增与删除 |
| `llm_about/` 及其数字群目录 | `vocab.yaml`、`identities.yaml` |
| `data/` | `rule_switch.json`、`daily_summary_groups.json`、`daily_briefing_groups.json`、`weekly_report_groups.json`、`monthly_report_groups.json`、`awakening_boredom_groups.json` |
| `config/managed/scheduled_messages.json` | 循环定时消息定义 |
| 根目录和 `prod/` | `compose`、`compose.override`、`docker-compose`、`docker-compose.override` 的 `.yml` / `.yaml` 文件 |
| `docker/searxng/settings.yml`、`prod/sendkey.env` | 项目内的搜索与运维通知配置 |

Skills、LLBot 登录与混合配置、私有部署钩子、Trace 当前开关、一次性定时任务、业务数据库及示例模板由各自工具维护。LLM 设置中的 Skill 选项和 `.env` 中的路径值照常保存，`qqconf` 不跟随路径读取外部文件。

## 编辑供应商和其他对象

供应商文件直接使用业务字段：

```toml
id = "example"
protocol = "openai"
base_url = "https://example.test/v1"
api_key_env = "EXAMPLE_API_KEY"
default_model = "example-model"

[[models]]
model = "example-model"
```

新增对象时在对应目录新建 TOML；删除文件即删除该对象。身份取自文件内的 `id`，重命名文件保留身份。可选的 `db/llm/order.toml` 用 `providers = ["example", "another"]` 指定顺序；未列出的新增供应商按文件名顺序追加。更改供应商 ID 时，一并修改路由和作用域引用，完整目标会统一校验。

普通可选空字段可以省略。任意 JSON 请求体中的 `null` 等特殊值有可逆的 TOML 表示，见[值编码契约](../dev/config-workspace.md#值编码与文本保留)。

校验引用时优先使用目标根 `.env` 的值，未在其中声明的变量沿用当前进程环境；保存的文件保留原始 `${变量}` 引用。

## 合并双方修改

工具比较上次共同基线、工作副本和当前真实配置。不同字段自动组合。例如副本调整温度、Web Admin 调整超时，两项都会保留。同一字段改成不同值，或一方删除、另一方修改同一对象时，写命令停止。

先用 `refresh` 定位字段，再在副本中整理成希望保留的值。也可在本次命令中选择冲突字段的来源：

```bash
qqconf refresh --prefer workspace
qqconf pack --prefer workspace
qqconf unpack --prefer source
```

`--prefer` 只选择冲突字段，双方独立修改继续合并。路由级联、普通数组和自由文本按整个值选择；预览同时给出字段或文本行差异。默认隐藏凭据和全部 dotenv 值，需要查看时加 `refresh --show-secrets`。

线上热修先通过[同步工具](config-sync.md)回流本地真实文件，再运行 `qqconf unpack` 接入工作副本。`refresh` 始终只读。

## pack 写到哪里，何时生效

写入位置由真实根 `.env` 的部署方式决定，两个枚举的设置见[qqsync 指南](config-sync.md#先设置部署方式)。

| 部署位置 | pack 写入位置 | 生效命令 |
|---|---|---|
| `local` | 完整 `.config-staging/` 暂存，服务停止时也采用此路径 | `qqsync push` |
| `cloud` | 本地真实配置，作为云端部署来源 | `qqsync push` 或 deploy-v4 |

云端模式直接写真实文件时，工具持有本地 Bot/Web 生命周期锁。正在运行的本地服务会阻止该写入；缺少历史启停记录不影响已停止环境的写回。

暂存按真实路径包含受管配置和独立配置库。`refresh` 显示暂存是否待部署、真实来源是否已改变；下一次 `pack` 从真实配置重新计算并替换暂存。qqsync 安装成功后消费暂存，不修改工作副本及其基线。

切换默认人格或 Profile 时，可以在同一次编辑中更新引用并删除旧文件。部署会在停止消费者后安装相互匹配的目标配置与资产，再恢复原本运行的服务。

## 中断后继续

普通写入失败会自动还原。进程意外退出时，`refresh` 报告待恢复状态；在原项目和原工作副本路径重新运行 `pack`，工具先恢复，再重新处理当前修改。首次 `unpack` 中断后可重新运行 `unpack`。

真实配置写到一半时，Bot、Web 和配置写入入口会等待恢复。恢复发现其他工具改过文件或数据库时，保留现场并报冲突；先核对这些修改及恢复资料，再处理冲突。恢复完成前保留 `.qqconf/`、`data/qqconf/` 和候选相关目录。

旧版工作副本可以保留作备份，在新的空目录执行 `unpack`，再迁入需要保留的编辑。
