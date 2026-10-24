# 在 TOML 工作副本中审阅配置

本文面向在 VSCode 中审阅配置或委托 LLM 修改配置的部署者。需要 Python 3.11+、当前项目依赖和已初始化的本地 `data/llm_config.db`。工作副本保存分组文本、注释和来源基线。

## 建立工作副本

在项目根目录执行，选择活动 `config/`、`data/`、`llm_about/` 之外的空目录：

```bash
python -m quickquip.config_workspace init /path/to/config-workspace
python -m quickquip.config_workspace validate /path/to/config-workspace
```

来源为当前本地草稿和受管资产。已有非空目录会被拒绝。在其他位置执行时，在子命令前指定 `--root /path/to/QuickQuip`。

| 位置 | 内容 |
|---|---|
| `workspace.toml` | 文件清单及有序集合的顺序 |
| `providers/*.toml` | 每个渠道及其模型、别名、参数 |
| `settings/*.toml`、`styles/*.toml` | 分组设置及回复风格 |
| `routes.toml`、`pricing.toml` | 有序级联及模型价格 |
| `assets/` | 按源相对路径保留的受管文件 |
| `.quickquip/` | 私有来源、基线、操作日志和恢复副本 |

逻辑文件以 `value` 为根：渠道字段位于 `[value]`，模型位于 `[[value.models]]`。新增、删除或重命名文件时，同时更新清单；渠道清单顺序决定渠道顺序。未登记的配置 TOML 会报错，编辑器 `.bak` 等辅助文件不参与解析。

空值写为 `context_window = { __quickquip_value__ = "null" }`。缺少字段和显式空值按配置自身规则解释。大整数和包含保留键的对象由工具编码，见[格式契约](../dev/config-workspace.md)。应用密钥继续由项目根 `.env` 管理。

## 接收数据库和线上修改

线上 Web Admin 热修先[回流本地](config-sync.md)，再刷新工作副本：

```bash
python -m quickquip.config_workspace plan /path/to/config-workspace --action refresh
python -m quickquip.config_workspace refresh /path/to/config-workspace --expected-plan PLAN_HASH
python -m quickquip.config_workspace status /path/to/config-workspace
```

把 `PLAN_HASH` 替换为预览输出的 `plan_hash`。预览包含配置单元变化、字段差异、文件变化和冲突。预览后继续编辑文件或数据库，计划即失效，应重新预览。

刷新组合数据库变化和工作副本单边修改，以此次数据库内容为新基线。已有 TOML 按节点更新，未变文件保持原字节，注释随工作副本保存。单边修改继续保留，`status` 的 `dirty` 可以仍为 `true`。初始化、校验和刷新均保持来源数据库与受管资产。

整份 LLM 文档是一个冲突单元，每个资产文件各是一个单元。双方不同修改同一单元时，刷新停止写入。需要采用完整数据库配置时，在预览和执行命令中均增加 `--overwrite`；预览的 `discarded_units` 列出将被替换的工作副本修改。先保留要继续编辑的副本。

## 中断后继续或恢复

```bash
python -m quickquip.config_workspace status /path/to/config-workspace
python -m quickquip.config_workspace resume /path/to/config-workspace --operation OPERATION_ID
python -m quickquip.config_workspace recover /path/to/config-workspace --operation OPERATION_ID
```

继续完成计划中的刷新，恢复还原刷新前的工作文件与基线。外部修改与恢复副本不一致时，工具保留现场并报冲突。操作完成前保留工作副本的原路径和 `.quickquip/`。工作副本绑定创建时的来源，包含私有配置并采用私有权限；换来源使用新的空目录。
