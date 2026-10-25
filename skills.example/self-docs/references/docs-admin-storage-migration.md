<!-- Generated from docs/admin/storage-migration.md; do not edit -->

# 将配置与运行数据分开存储

本文面向使用 `data/llm_config.db`、业务库中群设置或混合定时消息文件的已有安装。迁移统一 SQLite 配置存储，并保留聊天、记忆、游戏记录、配置历史和任务进度。新安装直接执行普通配置初始化。

## 迁移前准备

1. 确认旧 LLM 配置库已经是 schema 3。schema 1、2 先使用支持 schema 3 的旧版本，按其升级说明完成升级。
2. 确保数据磁盘有空间保存现有三个数据库及定时消息文件的备份。
3. 安排停止 Bot 和 Web。LLBot 可以继续运行。

## 源码安装

停止 Bot 和 Web 后，在项目根目录执行：

```bash
python -m quickquip.llm.config_cli migrate-storage --services-stopped
```

命令输出迁移结果及 `backup` 目录。校验通过后启动新版 Bot 和 Web，检查配置页的草稿、已发布版本与 Bot 加载状态，再检查群设置、私聊及定时消息。

## 生产部署

将新版生产模板合入自己的运维目录后执行：

```bash
bash prod/deploy-v4.sh --migrate-storage
```

PowerShell：

```powershell
prod/deploy-v4.ps1 -MigrateStorage
```

此选项保留服务器配置，自动关闭本次配置同步。根 `.env` 默认使用服务器版本，显式指定 `--env local` 或 `-EnvSource local` 可上传本地凭据。驱动先构建候选镜像，再停止 Bot 和 Web、迁移、启动候选并执行健康检查。迁移失败时恢复原存储；候选启动后检查失败时反向转换存储，再启动旧版本。备份保留在共享数据目录。

`config/managed/` 需要采用新版 Compose 的共享挂载。迁移要求健康检查，不能与跳过健康检查或配置推送组合使用。平铺部署可将 `--migrate` 与存储迁移选项组合。

## 迁移结果

| 内容 | 位置 |
|---|---|
| LLM、群和私聊参数、牛牛文案模式 | `config/managed/config.db` |
| 配置任务、发布指针和 Bot 心跳 | `data/config_runtime.db` |
| 循环定时任务 | `config/managed/scheduled_messages.json` |
| 一次性待办 | `data/pending_scheduled_messages.json` |
| 私聊响应状态 | `data/llm.db` 的会话运行状态 |

独立 TOML、YAML 和根 `.env` 保持原位置与格式。Web 参数页中的私聊“暂停／恢复响应”单独维护会话状态，重置参数保留会话。

## 中断与回退

迁移中断后保持服务停止，重新执行迁移命令。工具先恢复未完成操作的备份，再重新迁移；已完成的迁移重复执行时返回已有结果。

回退存储布局时停止 Bot 和 Web，然后使用输出中的备份目录：

```bash
python -m quickquip.llm.config_cli migrate-storage --services-stopped --rollback <备份目录>
```

生产环境通过候选版本的维护容器运行同一命令，备份目录使用容器中的路径。完整迁移的回退会保留迁移后的业务记录与任务进度，并重建旧存储格式；随后启动支持 schema 3 的旧程序。生产驱动的普通版本回退会提示先完成此维护步骤。
