# 本地与线上配置同步

配置同步面向同时使用本地工作区与服务器 Web Admin 的部署者。工具记录双方上次一致的内容作为基线，判断本地修改应推送、线上热修应回流，或双方修改需要人工处理。需要本地已安装项目 Python 环境、可用 SSH，以及运行新版 Bot 和 Web 的版本目录服务器。

## 建立第一次同步

先将 `prod.example/` 中的新驱动合入自己的 `prod/`。已有服务器升级同步能力时，执行一次 `bash prod/deploy-v4.sh --config-sync off`，保留服务器配置与根 `.env`。平铺目录同时指定 `--migrate`。新服务器首次部署使用 `--config-sync off --env local`；等待 QQ 登录时可以再加 `--skip-health`，登录和健康检查完成后建立配置基线。

在本地项目根目录选择首次配置来源。以下命令以线上已发布配置覆盖本地草稿和受管文件，覆盖前保存恢复副本：

```bash
bash prod/config-v1.sh sync init --from remote --host-alias quickquip-prod
```

以本地配置为初始来源时改为 `--from local`。已有本地旧 TOML 需要迁移时，先运行 `python -m quickquip.llm.config_cli init`。首次回流可以初始化空的本地数据库。首次来源选择后，两端基线保存在各自的 `data/config-sync/`，不要单独删除其中一端的状态。

PowerShell 对应命令：

```powershell
prod/config-v1.ps1 -Action sync -SyncAction init -From remote -HostAlias quickquip-prod
```

每个本地工作区与服务器环境分别维护同步关系。复制数据目录建立新环境时，将复制的 `data/config-sync/` 移至备份位置，再初始化新的同步身份；两端身份相同会被拒绝。改变 SSH 目标前核对端点身份，未完成操作使用原连接参数恢复。

## 查看和执行同步

```bash
bash prod/config-v1.sh sync --plan
bash prod/config-v1.sh sync --mode auto
bash prod/config-v1.sh sync status
```

预览显示变更方向、删除、冲突、线上未发布草稿、重启需求，以及认证变量是否已配置。变量值不进入预览。预览不建立基线、不修改配置、不构建前端。

| 状态 | auto 行为 |
|---|---|
| 两端均未修改 | 保持内容并确认同步关系 |
| 仅本地修改 | 推送本地修改 |
| 仅线上修改 | 回流线上修改 |
| 双方修改为相同内容 | 接受共同结果 |
| 同一配置单元双方修改不同 | 返回冲突，保留双方内容 |

LLM 文档整体为一个配置单元，每个文件各为一个配置单元。不同单元的修改会组合后统一校验。同一单元的修改由部署者选择处理方向，工具展示 LLM 字段差异，不自动合并文档内容。

显式推送与回流使用 `--mode push`、`--mode pull`。确认要替换目标侧独立修改时加 `--overwrite`，例如：

```bash
bash prod/config-v1.sh sync --mode pull --overwrite
```

覆盖也会检查目标的修订和内容摘要。目标在读取后发生变化时操作停止，需要重新查看差异。推送改变 LLM 文档且服务器已有未发布草稿时，需要先完成草稿或明确覆盖；回流读取已发布配置，保留线上草稿。

PowerShell 使用 `-Action sync -Mode auto -Plan` 预览，去掉 `-Plan` 执行，使用 `-Overwrite` 明确覆盖。

## 配置范围与生效

本地草稿和受管资产可导出为[持久 TOML 工作副本](config-workspace.md)审阅、编辑和校验。线上热修先回流本地，再刷新工作副本。

同步包括 LLM 草稿／发布文档、`config/personas/*.toml`、`config/client_profiles/*.toml`，以及 generation、chat_rules、games、awakening、sensitive_words、admins、niuniu_text、niuniu_text_safe 的 TOML 文件。`llm_about` 的全局和群目录中 `vocab.yaml`、`identities.yaml` 同时同步。

两份牛牛文案受 Git 追踪，回流会成为本地工作区修改。示例文件和内置 Profile 随代码分发；旧 `llm.toml`、数据库历史、运行任务、聊天数据、群覆盖、Skills 和登录态不进入配置包。文件内容保持原字节，新写入的私有资产采用 owner-only 权限，两份公开文案采用普通可读权限。

线上纯 LLM 文档更新通过 Bot 热应用，只有目标任务成功、Bot 已加载目标修订且核心就绪后才确认。文件推送会短暂停止并重建 Bot 与 Web；候选资产须支持当前已发布配置启动，随后应用目标配置。需要同时删除旧默认人格并切换默认人格时，可以先发布新的默认选择，再删除旧文件。

本地回流更新草稿与文件，不自动应用到本地 Bot。本地委托 LLM 编辑时，使用配置服务／CLI 提交，维护正文、修订和关系投影。直接 SQL 修改导致投影不一致时，同步返回 `projection_mismatch`，应先核对修改意图并通过配置服务修复。

## 随部署同步

建立基线后，无参数部署默认使用 `--config-sync auto`。文件回流发生在打包前，候选版本激活后完成配置应用，整个部署成功后确认基线。

```bash
bash prod/deploy-v4.sh --plan
bash prod/deploy-v4.sh
bash prod/deploy-v4.sh --config-sync off
```

`off` 保留服务器受管配置，暂停旧服务写入后复制到候选版本，不推进同步基线。`--dry-run` 保持本地构建和上传预览功能。`--skip-health` 仅与 `--config-sync off` 配合使用。

已有服务器默认保留根 `.env`。需要更新应用凭据时显式指定 `--env local`；PowerShell 使用 `-EnvSource local`。同步检查认证变量引用，凭据文件由此独立选项管理。人工代码回滚不倒退同步基线，下一次同步按实际配置检测变化。

## 中断与恢复

操作编号、恢复副本和两端回执保存在私有同步状态中；服务器执行日志位于 `.deploy/sync-<操作编号>.log`。部署联动同时保留 `.deploy/<release>.transaction.json` 恢复记录、`<release>.log` 执行日志和 `<release>.exit` 结果回执。恢复完成前保留这些文件及对应上传目录。出现失败时使用输出中的操作编号：

```bash
bash prod/config-v1.sh sync status --operation <操作编号>
bash prod/config-v1.sh sync resume --operation <操作编号>
```

尖括号内容替换为本次 32 位操作编号。同一操作重试复用原任务，远端成功后断线可继续确认，不重复发布。部署联动等待对应部署完成。原部署进程已经退出时，恢复执行器读取持久化部署日志，恢复共享文件、版本链接和配置；部署已成功时继续完成两端确认。

远端已经确认成功时，恢复命令会补齐本地确认。需要撤销未完成操作时使用 `sync recover --operation <操作编号>`。服务器恢复工作会停止 Bot／Web、还原配置并验证健康。本地已写入配置时，先停止本地应用服务，再追加 `--services-stopped` 恢复本地配置；仅处于准备阶段的本地操作可直接解除。

恢复检测到维护期间的外部修改时会停止覆盖并保留状态。失败恢复不推进基线，维护状态持续阻止应用配置写入。`sync status --operation` 保留应用失败的错误原因，供数据库恢复后继续排查。检查日志、备份和当前内容后继续恢复，不要通过删除维护标记解锁。

单独应用现有草稿时，可用 `bash prod/config-v1.sh apply --revision <修订号> --wait --timeout 150` 等待目标加载，或用 `status --operation <任务编号>` 查询任务。完整数据库备份恢复见 [LLM 配置管理](llm-configuration.md)。
