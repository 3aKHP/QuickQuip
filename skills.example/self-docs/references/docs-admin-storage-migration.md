<!-- Generated from docs/admin/storage-migration.md; do not edit -->

# 将配置与运行数据分开存储

本文面向从 1.16.3 升级到 1.16.4，以及使用 `data/llm_config.db`、业务库中群设置或混合定时消息文件的已有安装。迁移统一 SQLite 配置存储，并保留聊天、记忆、游戏记录、配置历史和任务进度。新安装直接执行普通配置初始化。

## 迁移前准备

1. 确认旧 LLM 配置库已经是 schema 3。schema 1、2 先使用支持 schema 3 的旧版本，按其升级说明完成升级。
2. 备份根 `.env`、`config/`、`data/`、`llm_about/`、`skills/` 和私有运维配置；保留协议端登录资产、旧程序或镜像标识。SQLite 使用一致备份，或在停止写入后完整备份数据目录。确保磁盘有空间保存迁移产生的三个旧数据库及定时文件备份。
3. 停止 Bot 和 Web，并暂停会自动拉起它们的服务管理任务。LLBot 可以继续运行。准备停服窗口，待迁移及检查完成后恢复服务。
4. 合入新版 Compose 的共享可写 `config/managed/` 挂载和 `QUICKQUIP_MANAGED_CONTAINER=1`。准备使用配置工具时，在真实根 `.env` 设置 `QUICKQUIP_DEPLOY_LOCATION=local|cloud` 和 `QUICKQUIP_DEPLOY_RUNTIME=source|docker`，见[部署方式](config-sync.md#先设置部署方式)。

新版 Bot/Web 检测到旧存储会返回 `migration_required`。普通 `init` 和 Windows `start.bat` 都要求先完成以下停服迁移。

## 源码安装

停止 Bot 和 Web 后，准备新版源码，在其 Python 环境更新依赖和项目命令入口；启用 Web 时使用仓库 `.node-version` 与 pnpm 构建同版前端。在项目根目录执行：

```bash
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m quickquip.llm.config_cli migrate-storage --services-stopped
```

命令输出迁移结果及 `backup` 目录。校验通过后启动新版 Bot 和 Web，检查配置页的草稿、已发布版本与 Bot 加载状态，再检查群设置、私聊及定时消息。

云端源码在服务器项目目录执行相同步骤。通过新版 `bot.py`、`web_api.py` 启动服务，并核对自定义进程管理器对父子进程的停止和重启行为。

## Windows 懒人包

将新版 ZIP 解压到独立目录。停止旧 Bot/Web 后，将已备份的配置、数据和私有资产复制到新包的对应位置，保留旧包供回退。在新包目录打开终端，先执行：

```powershell
python\python.exe -m quickquip.llm.config_cli migrate-storage --services-stopped
```

保存输出中的备份目录后运行 `start.bat`。后台需要重新登录；检查配置修订、私聊响应状态和定时消息，再恢复日常使用。旧 `.env` 保留原值，使用 qqconf/qqsync 前补齐 local/source 部署设置。

## 本地 Docker 与手工 Compose

保留旧镜像版本和数据备份，更新 Compose 挂载，将 `config-init`、`quickquip`、`web-admin` 固定为同一新版镜像。根模板的步骤如下，在项目根执行：

```bash
docker compose -f docker-compose.example.yml pull config-init quickquip web-admin
docker compose -f docker-compose.example.yml stop quickquip web-admin
docker compose -f docker-compose.example.yml run --rm --no-deps config-init \
  python -m quickquip.llm.config_cli migrate-storage --services-stopped
docker compose -f docker-compose.example.yml up -d quickquip web-admin
```

迁移命令必须成功后再启动服务。保留 `backup` 输出及 `data/storage-migration.json`。手工生产 Compose 没有 `config-init` 服务时，先构建候选镜像，再用挂载真实配置和数据的 `web-admin` 维护容器执行相同迁移命令。根模板的 Bot 在只读 `config/` 下叠加可写 `config/managed/`；生产 release 布局的 Bot/Web 均需挂载部署根的共享目录。

## 生产部署

将新版生产模板合入自己的运维目录后执行：

```bash
bash scripts/deploy/deploy-v4.sh --migrate-storage
```

PowerShell：

```powershell
scripts/deploy/deploy-v4.ps1 -MigrateStorage
```

此选项保留服务器配置，自动关闭本次配置同步。根 `.env` 默认使用服务器版本，显式指定 `--env local` 或 `-EnvSource local` 可上传本地凭据。驱动先构建候选镜像，再停止 Bot 和 Web、迁移、启动候选并执行健康检查。迁移失败时恢复原存储；候选启动后检查失败时反向转换存储，再启动旧版本。备份保留在共享数据目录。

`config/managed/` 需要采用新版 Compose 的共享挂载。迁移要求健康检查，不能与跳过健康检查或配置推送组合使用。平铺部署可将 `--migrate` 与存储迁移选项组合。

迁移成功后再建立配置同步基线。两端完成初始化或迁移并设置 cloud/docker 后，先用 `qqsync refresh --direction pull` 核对范围，再选择 `qqsync pull` 回流服务器配置，最后 `qqconf unpack` 建立工作副本。首次回流包含根 `.env` 和运维配置，执行前保留本地副本。日常 deploy-v4 默认推送本地配置。

## 迁移结果

| 内容 | 位置 |
|---|---|
| LLM、群和私聊参数、牛牛文案模式 | `config/managed/config.db` |
| 配置任务、发布指针和 Bot 心跳 | `data/config_runtime.db` |
| 循环定时任务 | `config/managed/scheduled_messages.json` |
| 一次性待办 | `data/pending_scheduled_messages.json` |
| 私聊响应状态 | `data/llm.db` 的会话运行状态 |

独立 TOML、YAML 和根 `.env` 保持原位置与格式。Web 参数页中的私聊“暂停／恢复响应”单独维护会话状态，重置参数保留会话。

迁移后核对：草稿与已发布修订保持原有区别；群参数中的关闭、零值和继承值保留；私聊启停状态符合升级前状态；牛牛玩家记录与文案模式可读；循环任务和一次性待办数量、ID 正确。Bot 启动后确认新鲜心跳、目标修订加载及调度注册。

配置 CLI 的 `backup` 现在生成主备份及同目录 `.runtime.db` 配套文件，恢复时两份一同保存。Trace 启用媒体去重时，额外按[Trace 备份说明](configuration.md#trace-媒体存储)成组备份数据库和 blob 目录。游戏升级保留玩家长度；离线重置按[游戏维护](game-config.md#离线生成牛牛重置库)单独执行。

## 中断与回退

迁移中断后保持服务停止，重新执行迁移命令。工具先恢复未完成操作的备份，再重新迁移；已完成的迁移重复执行时返回已有结果。

回退存储布局时停止 Bot 和 Web，然后使用输出中的备份目录：

```bash
python -m quickquip.llm.config_cli migrate-storage --services-stopped --rollback <备份目录>
```

生产环境通过候选版本的维护容器运行同一命令，备份目录使用容器中的路径。完整迁移的回退会保留迁移后的业务记录与任务进度，并重建旧存储格式；随后启动支持 schema 3 的旧程序。生产驱动的普通版本回退会提示先完成此维护步骤。

Windows 使用新包的 `python\python.exe` 执行上述回退命令，再将已反向转换的配置和业务数据交给旧包。根 Compose 使用候选 `config-init` 维护容器执行回退，再将三个应用镜像切回旧版。生产 release 布局先停 Bot/Web，用候选 `web-admin` 维护容器完成反向转换，然后执行 `scripts/deploy/deploy-v4.sh --rollback`。全程保留同一份共享配置和业务数据。

回退后核对新增消息仍在、最新配置可读、私聊状态正确、已消费一次性任务未重新出现。再次升级使用同一迁移入口，并保留回退期间产生的新记录。旧 schema 3 单库备份应恢复到旧布局后再迁移；新版配套备份用于新版配置恢复。

## 同步更新运维入口

部署程序位于 `scripts/deploy/`，巡检与指标位于 `scripts/ops/`，数据维护位于 `scripts/maintenance/`，生产 Dockerfile 位于 `docker/Dockerfile.prod`。更新 cron、快捷方式及自定义脚本中的路径。生产驱动为旧 `prod/Dockerfile` 引用生成兼容构建文件；手工 Compose 按新版模板核对构建路径。维护程序随代码分发，`prod/` 保留真实配置及协议登录资产。
