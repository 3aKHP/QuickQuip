<!-- Generated from docs/admin/config-sync.md; do not edit -->

# 用 qqsync 同步和部署配置

`qqsync` 连接本地真实配置与部署环境。日常只需三个命令：`refresh` 看变化，`push` 推送，`pull` 回流。它与[qqconf 工作副本](config-workspace.md)配合使用，完整配置范围见该页的受管清单。

## 先设置部署方式

在真实项目根 `.env` 中明确设置两个值：

```dotenv
QUICKQUIP_DEPLOY_LOCATION=cloud
QUICKQUIP_DEPLOY_RUNTIME=docker
```

| 配置 | 可选值 |
|---|---|
| `QUICKQUIP_DEPLOY_LOCATION` | `local` 本地部署、`cloud` 云端部署 |
| `QUICKQUIP_DEPLOY_RUNTIME` | `source` 原生 Python 进程、`docker` Docker Compose |

[安装指南](installation.md)说明四种组合。源码运行和 Windows 懒人包使用 `source`；容器内挂载源码的部署使用 `docker`。云端同步时，本地与服务器的根 `.env` 都填写 `cloud` 和相应运行方式。

云端连接使用 SSH 配置中的别名，默认 `quickquip-prod`、远端根目录 `/opt/QuickQuip`。可以在本地根 `.env` 中设置：

```dotenv
QUICKQUIP_DEPLOY_SSH_HOST=quickquip-prod
QUICKQUIP_DEPLOY_REMOTE_DIR=/opt/QuickQuip
```

首次安装或升级先补齐真实 `.env` 中的两个部署值，再运行 `qqconf unpack`。日常修改在工作副本中完成。读取与预览可以报告缺失的部署方式；写入要求两个值均已设置。

## 本地修改后生效

```bash
qqconf unpack
# 编辑 .config-workspace/ 中的配置
qqconf refresh
qqconf pack
qqsync refresh
qqsync push
```

两个预览命令都可省略。

- **本地部署**：`pack` 始终生成 `.config-staging/`，`push` 将其安装到真实目录并生效。成功后消费暂存，工作副本保持原样。没有暂存时，`push` 报告无待部署配置。
- **云端部署**：`pack` 写入本地真实目录，`push` 将本地修改同步到服务器。首次推送以本地完整配置为准。

本地修改 `.env` 中的 API key 与修改其他配置采用同一流程。根 `.env`、Compose、运维通知配置一起进入同步计划。

源码环境可使用 `python -m quickquip.config_sync` 替代 `qqsync`。升级源码安装后，运行 `python -m pip install --no-deps -e .` 更新命令入口。Windows 懒人包使用 `python\python.exe -m quickquip.config_sync`。在子命令后加 `--root /path/to/QuickQuip` 可以指定本地项目根。

## 把线上热修带回来

在 Web Admin 完成线上修改和应用后：

```bash
qqsync refresh --direction pull
qqsync pull
qqconf unpack
```

`pull` 更新本地真实配置，`unpack` 再接入工作副本。首次回流以线上完整配置为准。两端均需已完成[配置存储初始化或迁移](storage-migration.md)。

默认回流线上**已发布**的 LLM 配置。要带回尚未应用的草稿，执行 `qqsync pull --source draft`；该操作保留草稿尚未发布的事实，随后 `push` 仍可将其部署到线上。

本地部署下，`qqsync pull` 提示使用 `qqconf unpack`，不执行写入。qqsync 的桥接对象始终是真实目录与部署环境，工作副本由 qqconf 管理。

## 两边都修改时怎么办

同步严格按照命令方向写入接收端。工具记录上次双方一致的字段：不同字段的修改自动组合，接收端的独立修改保留，下一次反向同步仍能发现它们。

例如本地调整模型温度、线上调整超时：`push` 把温度传到线上并保留线上超时；随后 `pull` 可以把超时带回本地。

同一字段两边改成不同值时，预览列出冲突，写入停止。整理配置后重试，或选择本次冲突字段的来源：

```bash
qqsync push --prefer source
qqsync pull --prefer target
```

`source` 指本次发送端，`target` 指本次接收端。选择只影响冲突字段。需要整份来源覆盖接收端时使用 `--overwrite`，它与 `--prefer` 互斥。

线上独立未发布草稿会保留，并接入部署带来的非冲突变化。草稿与部署修改同一字段，或资产变更使草稿引用失效时，会报告冲突供处理。

## 服务如何生效

qqsync 保留各服务原来的启停状态：运行中的服务按变更需要热应用或重启，原本停止的服务保持停止。

纯 LLM 文档更新在 Bot 运行时热应用。文件、环境变量或组合配置变化会暂停消费者，安装完整目标后恢复；Docker 按新的 Compose 和环境配置启动原本运行的服务。停止状态下也会完成 LLM 发布，下一次 Bot 启动直接加载目标版本。实际加载状态由 Bot 回报。

源码服务通过新版 `bot.py`、`web_api.py` 或 Windows `start.bat` 启动，自动具备暂停与恢复能力。升级前已经运行的原生进程需要先通过新版入口重启一次。

跨环境交换的是配置内容。本环境修订历史、运行任务、聊天和业务数据保留在各自环境。

## 与代码一起部署

将公开模板更新到自己的 `prod/` 后，deploy-v4 默认推送配置：

```bash
bash scripts/deploy/deploy-v4.sh --plan
bash scripts/deploy/deploy-v4.sh
bash scripts/deploy/deploy-v4.sh --config-sync pull
```

PowerShell 使用 `scripts/deploy/deploy-v4.ps1`、`-Plan` 和 `-ConfigSync pull`。部署脚本复用 qqsync 的计划和安装流程，把候选配置、镜像构建、停服发布、版本切换及健康检查放进同一笔部署。代码发布会启动新版本并检查健康状态。

仍使用 `data/llm_config.db` 的服务器先按[存储迁移](storage-migration.md)执行 `--migrate-storage`；该选项自动关闭本次同步并保留服务器配置。已经完成存储迁移、首次升级 qqsync 的服务器使用 `--config-sync off`；新服务器首次部署再加 `--env local`。`off` 保留服务器配置，独立的 `--env` / `-EnvSource` 选项用于这个流程。普通 push/pull 部署已经包含 `.env`。平铺目录迁移和完整运维步骤见[生产模板](../../prod.example/README.md)。

## 预览、输出与中断

预览按字段显示变化，文本文件同时展示可读差异。凭据默认隐藏；需要在自己的终端查看时使用 `qqsync refresh --show-secrets`。自动化可使用 `--json`，无参数运行显示帮助。没有 `auto` 或 `apply` 命令。

发生中断后，重复原来的 `push`、`pull` 或部署命令。工具从私有记录继续确认或恢复，使用中断前固定的目标和服务状态，无需输入哈希或操作编号。恢复完成前保留 `data/config-sync/` 与部署的 `.deploy/` 资料。旧工具已经完成的共同基线会接入字段同步；未完成的旧事务先按原目标处理。
