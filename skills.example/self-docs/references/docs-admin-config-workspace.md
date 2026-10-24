<!-- Generated from docs/admin/config-workspace.md; do not edit -->

# 在 TOML 工作副本中编辑配置

本文面向在 VSCode 中审阅配置或委托 LLM 修改配置的部署者。需要 Python 3.11+、当前项目依赖和已初始化的本地 `data/llm_config.db`。工作副本保留文本注释；组装保存本地草稿，发布和推送继续使用[配置管理](llm-configuration.md)及[配置同步](config-sync.md)。

## 建立工作副本

在项目根目录执行，选择活动 `config/`、`data/`、`llm_about/` 之外的空目录：

```bash
python -m quickquip.config_workspace init /path/to/config-workspace
```

来源为当前本地草稿和受管资产。已有非空目录会被拒绝。在其他位置执行时，在子命令前指定 `--root /path/to/QuickQuip`。

| 位置 | 内容 |
|---|---|
| `workspace.toml` | 文件清单及有序集合的顺序 |
| `providers/*.toml` | 每个渠道及其模型、别名、参数 |
| `settings/*.toml`、`styles/*.toml` | 分组设置及回复风格 |
| `routes.toml`、`pricing.toml` | 有序级联及模型价格 |
| `assets/` | 按源相对路径保留的人格、Profile 和其他受管文件 |
| `.quickquip/` | 私有来源、基线、操作日志和恢复副本 |

逻辑文件以 `value` 为根：渠道字段位于 `[value]`，模型位于 `[[value.models]]`。新增、删除或重命名文件时，同时更新清单；渠道清单顺序决定组装后的渠道顺序。未登记的配置 TOML 会报错，编辑器 `.bak` 等辅助文件不参与组装。

空值写为 `context_window = { __quickquip_value__ = "null" }`。缺少字段和显式空值按配置自身规则解释。大整数和包含保留键的对象由工具编码，见[格式契约](../dev/config-workspace.md)。应用密钥继续由项目根 `.env` 管理。CLI 读取所选根目录的 `.env`，已设置的进程变量优先；工作副本保留变量引用。离线校验含环境引用的资产时，提供对应变量或用 `--root` 指定含 `.env` 的项目。

## 校验并组装

```bash
python -m quickquip.config_workspace validate /path/to/config-workspace
python -m quickquip.config_workspace plan /path/to/config-workspace --action pack
python -m quickquip.config_workspace pack /path/to/config-workspace --expected-plan PLAN_HASH
```

把 `PLAN_HASH` 替换为预览输出的 `plan_hash`。预览包含配置单元变化、字段差异、文件变化和冲突。预览后继续编辑文件或数据库，计划即失效，应重新预览。

组装完成后，数据库获得目标草稿，工作副本基线推进到此次结果。正文未改变时保持修订号，只改注释也保持修订号。已发布快照、Bot 加载状态和服务器同步基线由各自现有流程管理。

含受管资产变更时，先停止本地 Bot 和 Web，再给 `pack` 增加 `--services-stopped`。Bot 心跳须过期，待处理配置任务须先结束。目标资产还须支持当前发布启动；删除发布态正在引用的人格或 Profile 时，先发布引用迁移，再组装删除改动。

确认草稿后可以按需应用到本地 Bot，或预览并推送服务器：

```bash
bash prod/config-v1.sh sync --plan
bash prod/config-v1.sh sync --mode auto
```

## 接收数据库和线上修改

线上 Web Admin 热修先回流本地，再刷新工作副本：

```bash
bash prod/config-v1.sh sync --mode pull
python -m quickquip.config_workspace plan /path/to/config-workspace --action refresh
python -m quickquip.config_workspace refresh /path/to/config-workspace --expected-plan PLAN_HASH
```

刷新组合数据库变化和工作副本单边修改，以此次数据库内容为新基线。已有 TOML 按节点更新，未变文件保持原字节，注释随工作副本保存。尚未组装的单边修改继续保留，`status` 的 `dirty` 可以仍为 `true`。

## 冲突与覆盖

比较采用共同基线、工作副本和当前本地配置。整份 LLM 文档是一个单元，每个资产文件各是一个单元。双方不同修改同一单元时，普通组装和刷新停止写入。

显式覆盖仍须先预览：

```bash
python -m quickquip.config_workspace plan /path/to/config-workspace --action pack --overwrite
python -m quickquip.config_workspace pack /path/to/config-workspace --overwrite --expected-plan PLAN_HASH
```

`pack --overwrite` 选择完整工作副本，`refresh --overwrite` 选择完整数据库配置。预览的 `discarded_units` 列出目标侧将被替换的独立修改。手工组合双方修改时，先保留编辑副本，再刷新取得当前数据库内容，在其上补入要保留的修改并重新预览。

## 中断后继续或恢复

```bash
python -m quickquip.config_workspace status /path/to/config-workspace
python -m quickquip.config_workspace resume /path/to/config-workspace --operation OPERATION_ID
python -m quickquip.config_workspace recover /path/to/config-workspace --operation OPERATION_ID --services-stopped
```

文件组装的继续操作同样需要停止服务并加 `--services-stopped`。数据库已经写入的失败操作在恢复前也须停止服务；已确认内容通过新修订回退。外部修改与恢复副本不一致时，工具保留现场并报冲突。数据库已确认而客户端回执中断时，继续操作仅补齐回执，保留确认后的新修改。

操作完成前保留工作副本的原路径、`.quickquip/` 及源项目的同步状态目录；复制或移动的进行中工作副本不能接管原操作。工作副本绑定创建时的来源，包含私有配置并采用私有权限；换来源使用新的空目录。
