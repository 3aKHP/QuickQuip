# 云端发布与回滚工具（deploy-v4）

`scripts/deploy/` 中的发布脚本通过 SSH 将 QuickQuip 的 Docker Compose 服务发布到远端 Linux 服务器。本地与远端、源码与容器的部署形态划分见[安装与部署方式选择](../../docs/admin/installation.md)，私有生产编排的准备步骤见[生产配置模板](../../prod.example/README.md)。所有命令均在本地项目根目录执行，查看完整参数说明可运行：

```bash
bash scripts/deploy/deploy-v4.sh --help
```

## 前置环境要求

- **远端服务器**：Linux 系统，需安装 Bash、GNU coreutils/find、`rsync`、`flock`、Python >= 3.11.8，以及 Docker 与 Docker Compose >= 2.27。部署用户需具备 Docker 调用权限与服务器部署根目录的读写权限。若历史编排中仍包含属主为 `root` 的旧版 LLBot 配置文件，共享文件的快照、应用与恢复需使用免交互 `sudo`；缺少权限时会在切换新版本前中止。
- **本地 Bash 客户端（Linux／macOS）**：安装 Bash、`rsync`、SSH／SCP、`tar`、Node.js、`pnpm` 以及项目虚拟环境 Python。
- **本地 PowerShell 客户端（Windows）**：安装 PowerShell 5.1 或 7、SSH／SCP、`tar`、Node.js、`pnpm`，并将项目 Python 加入 `PATH`。Windows 端上传归档后由服务器上的 `deploy-state.py`（Python `tarfile`）解包展开，服务器侧 `rsync` 仅用于前置环境检查。
- **应用配置与凭据**：发布前先填写本地根目录 `.env` 及实际启用的配置文件（使用 LLM 时准备好 `config/personas/` 人格文件），并在 `.env` 中通过 `QUICKQUIP_SEARXNG_BASE_URL` 指定外部 SearXNG 检索服务地址。发布脚本会在激活新版本前初始化服务器配置数据库（若服务器仍存有旧版 `llm.toml` 则自动完成一次性迁移）；Bot 与 Web Admin 启动后，再登录后台配置模型渠道。

<a id="ssh-connection"></a>

## SSH 连接配置

发布脚本与配置同步工具默认从本地根目录 `.env` 读取 `QUICKQUIP_DEPLOY_SSH_HOST`（SSH 主机别名）与 `QUICKQUIP_DEPLOY_REMOTE_DIR`（远端部署根目录），命令行显式传入的参数优先级更高。

在本地电脑打开 `~/.ssh/config`（Linux／macOS）或 `%USERPROFILE%\.ssh\config`（Windows，不存在则新建），添加目标服务器条目（以下 `quickquip-prod`、IP 与用户名为示例占位符，请替换为实际服务器信息）：

```sshconfig
Host quickquip-prod
    HostName 192.0.2.10
    User deploy
    Port 22
```

配置好 SSH 公钥免密登录后，先在本地终端执行一次 `ssh quickquip-prod`，完成首次主机公钥指纹确认并验证能正常进入远端 Shell，随后输入 `exit` 返回本地电脑。此后即可在命令中通过 `--host-alias quickquip-prod`（PowerShell 为 `-HostAlias quickquip-prod`）或 `.env` 变量无人值守连接。

外部检索服务与必填环境变量的首次准备见[云端部署指南](../../docs/admin/deployment.md#3-准备生产运维目录和环境变量)，容器启动后的渠道初始化见[首次启用 LLM](../../docs/admin/llm-configuration.md#首次启用-llm)。

## 配置同步与首次部署参数

进行远程同步与发布前，请在本地与服务器的真实根目录 `.env` 中均设置 `QUICKQUIP_DEPLOY_LOCATION=cloud` 与 `QUICKQUIP_DEPLOY_RUNTIME=docker`。

首次接入时按服务器当前状态选择参数：
- **服务器仍在使用旧版混合库 `data/llm_config.db`**：先按[配置存储迁移指南](../../docs/admin/storage-migration.md)执行 `bash scripts/deploy/deploy-v4.sh --migrate-storage`，脚本会自动保留服务器原有配置并在迁移期间跳过配置同步。
- **已完成存储迁移、首次接入 `qqsync` 的现有服务器**：首次代码发布传入 `--config-sync off` 以保留服务器配置；随后通过同步方向选定初始配置基准（例如将服务器已发布配置拉回本地真实文件）：
  ```bash
  qqsync refresh --direction pull
  qqsync pull
  qqconf unpack
  ```
- **全新服务器首次部署**：使用 `--config-sync off --env local` 将本地根目录 `.env` 上传至服务器完成首次引导。

在日常同步中，`pull` 将服务器已发布配置拉回本地真实配置文件，`push` 将本地真实配置部署到服务器；后续双向修改会自动合并互不冲突的字段并提示冲突项，根目录 `.env`、`prod/docker-compose.yml` 与巡检通知配置共享同一套同步计划（受管范围、工作区草稿与冲突消解方式见[配置同步指南](../../docs/admin/config-sync.md)）。

常规代码发布默认采用 `--config-sync push`；传入 `pull` 会在打包前先拉取服务器侧配置变更，传入 `off` 则保留服务器当前配置不变。加上 `--plan` 可在不构建前端、不修改任何配置的情况下预览同步计划；独立的 `--env` 参数仅在配合 `--config-sync off` 执行首次引导或应急维护时指定 `.env` 来源（常规同步本身已包含根 `.env`）。PowerShell 对应使用 `-ConfigSync`、`-Plan` 与 `-EnvSource`。

在单次发布事务中，服务器会先暂存对齐后的配置与环境变量并完成镜像构建校验，暂停消费进程写入新配置，随后切换 `current` 并启动新版本。待容器健康检查与 Bot 配置加载确认全部通过后，服务器才落盘写入提交回执、确认同步基线并清理临时文件（若清理步骤出错会记录日志留待下次重试；若客户端等待回执时网络中断，重连后可凭冻结的事务回执确认结果，恢复材料在确认成功或完成回滚前始终保留）。若发布中途中断，重复运行同一条命令即可按已记录的目标继续完成或恢复。单独运行 `qqsync` 会保持各服务原有的运行或停止状态，而完整代码发布则会启动新版本并校验健康门禁。

## 常用命令对照表

本地 Bash 与 PowerShell 发布脚本共用 `scripts/deploy/server/` 下的远端事务执行器与状态程序。本地 `prod/` 目录保存私有 `docker-compose.yml`、可选的 `sendkey.env` 巡检通知密钥及私有部署钩子；OneBot 协议端的登录态与会话资产由外部协议端服务独立维护。

| 操作目的 | Bash | PowerShell |
|---|---|---|
| 常规发布并推送配置 | `bash scripts/deploy/deploy-v4.sh` | `scripts/deploy/deploy-v4.ps1` |
| 本地构建与归档预览 | `bash scripts/deploy/deploy-v4.sh --dry-run` | `scripts/deploy/deploy-v4.ps1 -DryRun` |
| 查看远端发布与版本状态 | `bash scripts/deploy/deploy-v4.sh --status` | `scripts/deploy/deploy-v4.ps1 -Status` |
| 回滚到上一版本 | `bash scripts/deploy/deploy-v4.sh --rollback` | `scripts/deploy/deploy-v4.ps1 -Rollback` |
| 回滚到指定版本 ID | `bash scripts/deploy/deploy-v4.sh --rollback <id>` | `scripts/deploy/deploy-v4.ps1 -Rollback -ReleaseId <id>` |
| 从平铺目录迁移为版本目录并发布 | `bash scripts/deploy/deploy-v4.sh --migrate --config-sync off` | `scripts/deploy/deploy-v4.ps1 -Migrate -ConfigSync off` |
| 全新服务器首次部署（OneBot 已就绪） | `bash scripts/deploy/deploy-v4.sh --config-sync off --env local` | `scripts/deploy/deploy-v4.ps1 -ConfigSync off -EnvSource local` |
| 全新服务器首次部署（等待 OneBot 登录） | `bash scripts/deploy/deploy-v4.sh --config-sync off --env local --skip-health` | `scripts/deploy/deploy-v4.ps1 -ConfigSync off -EnvSource local -SkipHealth` |

通用参数包括 `--host-alias`、`--remote-dir`（默认 `/opt/QuickQuip`，仅允许字母、数字、`.`、`/`、`_`、`-`）以及 `--keep-releases`（保留历史发行版数量，取值 `2`～`100`，默认 `4`）；PowerShell 使用对应的单横线参数 `-HostAlias`、`-RemoteDir`、`-KeepReleases`。

`--dry-run`（兼容别名 `--local-check` / `-LocalCheck`）仅在本机编译前端并预览待上传清单（PowerShell 会生成并清理临时归档包），不发起任何远端连接，且不能与迁移、回滚或状态查询同时传入。`--skip-health` 必须配合 `--config-sync off` 使用，仅适用于部署与迁移并将本次结果标记为未验证健康门禁；人工回滚始终执行完整健康检查。

每次构建生成的发行版都会携带唯一版本标识，格式为 `pyproject.toml` 版本号加服务端镜像构建完成时的 UTC 时间戳（例如 `1.15.3-dev.2+build.20260909.065235`），并打印在事务日志的 `image built` 与 `release complete` 行中；若你维护有私有运维台账，可在 `remote-deploy-v4.sh` 标注的 `$VersionId` 位置接入记录。

QQ 账号首次登录在外部 OneBot 协议端完成；配置在线状态探针及从本地或服务器 `cron` 执行巡检见[Bot 巡检指南](../ops/README.md)。如需为 `host-healthcheck` Skill 补充宿主机进程数、全盘容量与硬件温度，可按 `scripts/ops/host_metrics_collector.py` 文件头注释配置宿主机定时任务，每分钟原子更新 `<root>/data/host_metrics.json` 供容器通过 `data/` 挂载读取。

### 共享 Skill 目录

共享技能目录位于 `<root>/skills`（与 `data/` 同级），由 `quickquip` 容器只读挂载、`web-admin` 容器读写挂载，因此在后台页面安装或编辑的 Skill 在容器重建和后续版本发布时都会持久保留。

每次发布时，脚本会将本地 `skills/` 目录上传并把其中新增的文件非破坏性地合入服务器共享目录；服务器上已有的同名文件（包括通过 Web Admin 安装或修改的内容）均原样保留，日常更新与删除通过后台“Skill”页面或在服务器上手动维护。首次启用共享目录时，服务器会先从旧 `current` 版本目录继承已有技能（无旧目录则创建空目录），再合入本次上传的新文件。

共享 `skills/` 目录归部署用户所有。由于 `web-admin` 容器内进程默认以 `root` 运行，后台在线写入的文件可能属主为 `root`；合入过程遇到权限受限时会自动通过免交互 `sudo` 重试，并将整个 `skills/` 目录的属主统一恢复为部署用户。若服务器未配置免交互 `sudo`，发布会在切换前安全停止并打印需要手动执行的 `chown` 命令。

<a id="layout-and-transaction"></a>

## 目录布局与发布流程

```text
<root>/
  .env                       应用运行凭据
  config/managed/            共享配置数据库与循环定时消息配置
  data/                      运行与业务数据库、日志、字体及可选贴吧登录态
  skills/                    共享 Skill 目录（Bot 只读挂载，Web Admin 读写挂载）
  prod/                      私有 Compose 配置、sendkey.env 与私有部署钩子
  scripts/ops/               受管的服务端巡检与宿主机指标采集程序
  releases/<id>/             各版本的程序源码、默认配置、前端产物与 Compose 文件
  current -> releases/<id>   当前生效版本软链接
  previous -> releases/<id>  上一生效版本软链接
  .deploy/                   私有暂存区、每次操作的事务日志与退出码记录
```

`deploy-manifest.txt` 定义随版本上传的应用路径，列出的目录会递归打包，发布前请确认其中不含无关私有文件。选定的根目录 `.env`、运维脚本及可选的 `prod/sendkey.env`、自定义字体与 `data/tieba/storage_state.json` 会单独上传至私有暂存区；OneBot 登录资产由外部协议端自行管理。向测试服务器发布时，请使用不含真实线上密钥或贴吧会话态的独立工作副本。

每次部署操作都会分配带 UTC 时间戳与随机后缀的事务 ID：上传内容先进入权限受限的专属暂存目录，所有线上目录改动均在服务器部署文件锁（`flock`）保护下进行。服务器会先结合暂存环境变量校验候选版本的 Compose 配置并完成镜像构建，随后才开始处理共享文件。未改动的应用文件通过 `rsync` 硬链接复用以节省磁盘空间；Web Admin 在线修改配置文件时采用原子替换（写新文件再重命名），不会污染历史版本硬链接指向的旧文件内容。

正式切换前，服务器会为即将改动的共享文件建立快照（若旧编排中仍包含随栈 LLBot，也会一并快照其 WebSocket 配置），随后写入候选环境、切换 `current` 软链接并重建应用容器。健康门禁依次核对：Bot 与 Web Admin 容器运行状态、OneBot 连接状态（配置了状态探针时核对实时会话与在线账号，未配置时核对 Bot 连接日志）、Web Admin HTTP 响应、配置库 Schema 版本、Bot 心跳与配置版本加载回执，以及会话数据库可用性；远端模型渠道或外部 MCP 服务暂不可达不会阻断版本发布。远端事务在后台独立运行，即使中途 SSH 连接断开也会继续执行，重新运行命令即可重连查看实时日志。

发布成功后会自动清理私有暂存目录和回滚临时副本，仅保留 `.deploy/<id>.log`、`.exit` 及同步事务记录 `.transaction.json`（若上传中途断开遗留了暂存目录，请先用 `--status` 核对无进行中任务后再手动清理）。若新版本健康检查未通过，服务端会自动触发回滚并返回非零退出码；一旦自动恢复本身也发生故障，则会完整保留现场私有备份并返回退出码 `2`。

<a id="migration-and-recovery"></a>

## 迁移与回滚恢复

生产镜像构建统一使用受版本控制的 `docker/Dockerfile.prod`。对于旧 `prod/docker-compose.yml` 中保留的 `build.dockerfile: prod/Dockerfile`（包括从服务器 `pull` 回流的配置），发布脚本会在每个候选 `releases/<id>/` 内自动生成同内容的兼容构建文件，无需强改私有 `prod/` 目录；新建部署建议直接填写 `docker/Dockerfile.prod`。

- **平铺目录迁移（`--migrate`）**：首次将传统平铺目录部署升级为 `releases/` 多版本结构时，脚本会先为平铺目录建立基线快照，并固定当前运行中的 `quickquip`、`web-admin` 及 `env-agent`（若已存在）镜像标签；若旧栈仍包含随栈 LLBot 容器，也会一并纳入基线。准备阶段原有平铺文件保持原位不变，确保切换前挂载路径始终有效。若检测到未知额外服务或不受支持的外部绑定挂载，脚本会在切换前停机提示人工处理。迁移基线受永久保护，不会被历史版本清理策略自动回收。
- **自动恢复与人工回滚（`--rollback`）**：发布失败触发自动恢复时，会还原操作前的共享文件、软链接与容器并重新校验健康状态。手动执行 `--rollback` 则会切换到指定的历史 `releases/<id>` 及其本地已留存的镜像，保留当前的根目录 `.env`、`data/` 运行数据以及共享 `skills/` 目录（若目标历史版本的 Compose 挂载共享 `skills/`，同样执行新增文件非破坏性合入；早期挂载版本内私有 `skills/` 的历史版本则继续使用其冻结副本），并执行完整健康门禁。回滚过程严禁重新拉取或重新构建缺失镜像，因此日常请勿手动清理仍在保留期内的 `quickquip-app` 版本标签。
- **数据库与外部副作用边界**：文件系统与容器回滚不会逆转已执行的数据库结构迁移或外部调用结果；跨大版本升级前请务必阅读发行说明并提前备份 `data/` 与 `config/managed/`。
- **配置与执行存储分离迁移（`--migrate-storage`）**：受管配置库与循环定时消息共享存放在 `config/managed/`，发布版本与异步任务队列存放在 `data/config_runtime.db`（常规代码上传会自动排除本地 `.db` 文件与旧 `llm.toml`）。首次平铺迁移在候选镜像构建成功后直接沿用服务器现有配置；若读取 `root` 属主的历史配置资产时遇到权限限制，会使用免交互 `sudo` 读取并将复制后的资产归属给部署用户（读取失败则停止激活，候选目录中已有的同名文件保持优先）。仍在使用 `data/llm_config.db` 混合存储的实例，请运行 `bash scripts/deploy/deploy-v4.sh --migrate-storage`（PowerShell 为 `-MigrateStorage`）：脚本会在构建新镜像后暂停 Bot 与 Web，拆分配置库与运行状态库并验证启动；若迁移未完成则还原原备份，若拆分完成后新版本启动失败则自动反向迁回并保留期间新增的业务数据与任务进度（Schema 1／2 的旧配置库需先用对应旧版程序升级到 Schema 3，详见[配置存储迁移指南](../../docs/admin/storage-migration.md)）。
- **历史版本保留与归档脚本**：超出 `--keep-releases` 数量的旧成功发行目录与对应镜像会被自动清理，`current`、`previous`、迁移基线以及构建失败的候选目录与日志则会保留供排查。`scripts/deploy/legacy/deploy-v4-bak.sh`（及 `.ps1`）仅作为早期平铺部署脚本的历史归档保留，检测到目标服务器含有 `releases/` 目录或 `current` 软链接时会直接拒绝执行，现行环境请统一使用 `deploy-v4`。

<a id="manual-compose-access"></a>

## 手工执行 Compose

在已采用 `deploy-v4` 版本目录布局的服务器上，如需手动执行 `docker compose` 查看日志或进入维护容器，请先导出部署根目录与当前版本变量，再进入 `current/prod`：

```bash
export QUICKQUIP_ROOT=/opt/QuickQuip
export QUICKQUIP_ENV_FILE="$QUICKQUIP_ROOT/.env"
export QUICKQUIP_RELEASE="$(basename "$(readlink "$QUICKQUIP_ROOT/current")")"
cd "$QUICKQUIP_ROOT/current/prod"
docker compose --env-file "$QUICKQUIP_ENV_FILE" logs -f quickquip
```

若在服务器采用手工平铺目录安装（不使用 `deploy-v4`），请先构建前端静态产物，进入 `prod/` 执行 `docker compose --env-file ../.env build quickquip` 构建镜像；首次启动前按[云端部署指南](../../docs/admin/deployment.md)运行一次性 `config_cli init` 初始化配置库，再执行 `docker compose --env-file ../.env up -d` 启动服务——`env-agent`、`quickquip` 和 `web-admin` 三个服务共用同一应用镜像。

## 历史配置维护与旧版回退

`scripts/deploy/legacy/config-v1.sh` 与 `config-v1.ps1` 可通过 SSH 在远端当前生效版本的 `web-admin` 容器内直接调用配置 CLI（适合未启用 `qqconf`／`qqsync` 的环境做导入导出或库级备份恢复）。调用时需配置好主机别名与远端目录，所有密钥继续留在根目录 `.env`，通过 JSON 交换配置并校验草稿修订号（`--revision`）：

```bash
bash scripts/deploy/legacy/config-v1.sh status
bash scripts/deploy/legacy/config-v1.sh export --source published --file llm-export.json
bash scripts/deploy/legacy/config-v1.sh preview --file llm-export.json --revision 1
bash scripts/deploy/legacy/config-v1.sh import --file llm-export.json --revision 1
bash scripts/deploy/legacy/config-v1.sh apply --revision 2
bash scripts/deploy/legacy/config-v1.sh backup --file llm-config-backup.db
bash scripts/deploy/legacy/config-v1.sh restore --file llm-config-backup.db
```

PowerShell 对应使用 `-Action`、`-File`、`-Revision`、`-Source`、`-HostAlias` 与 `-RemoteDir`。执行 `backup` 时会成对保存 `llm-config-backup.db` 与 `llm-config-backup.db.runtime.db`，请将两个文件保存在同一目录；执行 `restore` 时会校验两份文件齐全、停止 Bot 与 Web、备份当前数据库并在恢复成功后自动重启服务（若恢复出错则保持停服以便排查）。注意 `import` 仅写入配置草稿，还需执行 `apply` 提交给 Bot 加载生效。

如需应急回退到早期的 `1.16.1` 版本，需切回迁移前备份的旧版 `llm.toml` 与独立配置文件（迁移后在配置库中做出的新改动不支持反向导出回旧版 TOML），并在变更版本前备份配置库、会话库与 Trace 库。运行过 `1.16.1` 旧代码后若要再次升级，请先停止 Bot 与 Web、备份当前会话库并重置会话表的 Session 身份列，具体数据库路径与维护 SQL 见[回退旧版本后再次升级](../../docs/admin/llm-configuration.md#回退旧版本后再次升级)。

日常在本地编辑配置推荐使用 [qqconf 工作区](../../docs/admin/config-workspace.md)：当部署位置设为 `cloud` 时，`qqconf pack` 会更新本地真实配置文件供 `qqsync` 或 `deploy-v4` 推送；设为 `local` 时，`pack` 写入 `.config-staging/` 并由 `qqsync push` 安装到本机。

## 私有部署钩子

如需在发布或回滚成功后触发自定义通知或私有审计台账，可在本地创建 `prod/hooks/deployment.sh`。当该文件存在时，客户端会将其作为私有共享资产上传；每次新版本激活或人工回滚成功后，服务端事务程序会以部署用户身份执行 `bash deployment.sh <action> <version> <release>`（超时 30 秒发送终止信号，再过 5 秒强制结束；钩子执行失败仅记录日志，不会推翻已完成的发布结果）。

客户端传入 `--message` / `-m`（PowerShell 为 `-Message`）时，UTF-8 备注文本会编码为 Base64 并通过环境变量 `DEPLOY_NOTE_B64` 传给钩子脚本解码使用。该钩子脚本由部署者在本地自行维护，`qqconf`／`qqsync` 不会同步其脚本正文。
