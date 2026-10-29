# 用 qqsync 同步和部署配置

`qqsync` 负责在**本地真实配置**与**最终部署环境（本地运行服务或远端服务器）**之间建立桥梁。

日常使用只需要三个命令：
- `qqsync refresh`：预览双方变化与冲突
- `qqsync push`：将本地配置推送/安装到运行环境并生效
- `qqsync pull`：将线上（Web Admin）的热修改动拉回本地

它与 [qqconf 工作副本工具](config-workspace.md) 配合使用（受管配置的完整清单见 `qqconf` 文档）。

---

## 先设置部署方式

首次安装或升级后，建议先在**真实项目根目录的 `.env`** 中明确设置以下两个变量，再开始日常配置管理。`qqconf unpack` 可以在未设置时运行；执行 `qqconf pack` 或 `qqsync` 的配置写入操作前，必须补齐这两个变量：

```dotenv
QUICKQUIP_DEPLOY_LOCATION=cloud
QUICKQUIP_DEPLOY_RUNTIME=docker
```

### 两个核心配置项说明

| 环境变量 | 可选值与含义 | 适用场景说明 |
|---|---|---|
| `QUICKQUIP_DEPLOY_LOCATION` | `local`（本地部署）<br>`cloud`（云端部署） | 决定 `qqconf pack` 和 `qqsync` 的工作流向。**注意**：使用云端同步（`cloud`）时，本地与服务器两端的根 `.env` 都必须设为 `cloud`。 |
| `QUICKQUIP_DEPLOY_RUNTIME` | `source`（原生 Python 进程）<br>`docker`（Docker Compose） | 源码直接运行、Windows 懒人包填 `source`；使用容器（含容器内挂载源码）填 `docker`。四种组合详见[安装指南](installation.md)。 |

### 云端部署（`cloud`）的 SSH 连接配置

当设置为 `cloud` 时，`qqsync` 通过本地 SSH 配置中的主机别名连接服务器。默认主机别名为 `quickquip-prod`，默认远端路径为 `/opt/QuickQuip`。如需自定义，可在本地根 `.env` 中添加：

```dotenv
QUICKQUIP_DEPLOY_SSH_HOST=quickquip-prod
QUICKQUIP_DEPLOY_REMOTE_DIR=/opt/QuickQuip
```

---

## 场景一：本地修改配置并让它生效

无论是修改普通配置文件、调整 LLM 参数，还是修改根 `.env` 里的 API Key、Docker Compose 或运维通知配置，都走同一套标准连招：

```bash
# 1. 更新工作区并在 .config-workspace/ 中修改配置
qqconf unpack
# （编辑配置文件...）

# 2. 校验并打包工作区（refresh 可选）
qqconf refresh
qqconf pack

# 3. 推送并让服务生效（refresh 可选）
qqsync refresh
qqsync push
```

### 本地部署 vs 云端部署的底层区别

虽然你敲的命令完全一样，但两种部署方式在后台的流转路径不同：

- **本地部署（`local`）**：
  1. `qqconf pack` 总是先把改动生成到 `.config-staging/` 暂存目录。
  2. `qqsync push` 把暂存目录中的配置安装到本地真实目录，并触发本地服务生效。
  3. 安装成功后，`.config-staging/` 暂存被自动清理，`.config-workspace/` 工作副本保持原样。如果当前没有待安装的暂存，`qqsync push` 会直接提示“无待部署配置”。
- **云端部署（`cloud`）**：
  1. `qqconf pack` 直接把改动写入本地真实配置目录。
  2. `qqsync push` 通过 SSH 将本地真实目录的修改同步到远端服务器并触发服务生效（首次推送时，以本地完整配置为准）。

> **不同环境下的命令替代写法**：
> - **源码环境**：可用 `python -m quickquip.config_sync` 替代 `qqsync`（升级源码安装后，请运行 `python -m pip install --no-deps -e .` 更新命令入口）。
> - **Windows 懒人包**：使用 `python\python.exe -m quickquip.config_sync`。
> - **指定项目根目录**：在子命令后加上 `--root /path/to/QuickQuip`。

---

## 场景二：把线上（Web Admin）的热修拉回本地

如果你在服务器的 Web Admin 网页后台直接修改并应用了配置，需要把这些改动同步回本地（要求本地与服务器两端均已完成[配置存储初始化或迁移](storage-migration.md)）：

```bash
# 1. （可选）预览线上有哪些改动会被拉回
qqsync refresh --direction pull

# 2. 将线上配置拉回本地真实配置目录
qqsync pull

# 3. 将本地真实配置的改动合入 .config-workspace/ 工作副本
qqconf unpack
```

### 关于 `pull` 的重要规则

- **首次回流**：首次执行 `pull` 时，以线上完整配置为准。
- **已发布配置 vs 未发布草稿（Draft）**：
  - 默认情况下，`qqsync pull` 拉取的是线上**已发布**的 LLM 配置；实际生效版本以 Bot 的加载状态为准。
  - 如果你想把线上 Web Admin 里保存了但**尚未点击应用（未发布）的草稿**拉回本地，请执行：
    ```bash
    qqsync pull --source draft
    ```
    该操作会记录“这份草稿在线上尚未发布”的状态；你在本地继续改完后，依然可以用 `qqsync push` 将它正式部署并发布到线上。
- **本地部署（`local`）不需要 `pull`**：
  在 `local` 模式下，本地真实目录就是运行环境本身。此时如果运行 `qqsync pull`，工具不会执行任何写入，而是会提示你直接运行 `qqconf unpack`（因为 `qqsync` 只负责连接“真实目录”与“部署环境”，工作副本始终归 `qqconf` 管）。

---

## 场景三：本地和线上同时改了配置（冲突处理）

`qqsync` 严格按照命令方向写入接收端（`push` 写线上，`pull` 写本地），并且会记录双方上次一致的字段基线：

### 1. 修改了不同字段 $\rightarrow$ 自动合并不丢数据
假设你在本地调了“模型温度”，同时线上 Web Admin 调了“请求超时”：
- 执行 `qqsync push` 时，会把本地的“温度”推到线上，同时**保留**线上的“超时”修改；
- 随后你再执行 `qqsync pull` 时，就能把线上的“超时”改动也带回本地。

### 2. 修改了同一个字段 $\rightarrow$ 报冲突并停止写入
如果两边把同一个字段改成了不同的值，预览会列出冲突，写入命令会自动停止。你可以手动修改配置后重试，或者用参数决定冲突字段听谁的：

```bash
# 推送时：冲突字段以发送端（即本地 source）为准
qqsync push --prefer source

# 拉取时：冲突字段以接收端（即本地 target）为准
qqsync pull --prefer target
```

- **`source` 与 `target` 的含义**：`source` 永远代表本次命令的**发送端**，`target` 永远代表本次命令的**接收端**（例如 `push` 时本地是 `source`、线上是 `target`；`pull` 时线上是 `source`、本地是 `target`）。
- **`--prefer` vs `--overwrite`**：
  - `--prefer` **只决定冲突字段听谁的**，两边不冲突的独立修改依然会自动合并保留。
  - 如果你想完全抛弃接收端的改动、用发送端整份覆盖接收端，请使用 `--overwrite`（`--overwrite` 与 `--prefer` 互斥，不能同时使用）。
- **对线上未发布草稿的保护**：
  如果线上存在未发布的独立草稿，`push` 部署时会保留该草稿，并把不冲突的部署变更同步合入草稿中；但如果部署内容与草稿改了同一个字段，或者部署删除了草稿正在引用的资产文件，工具会报告冲突供你处理。

---

## 配置推送后，服务是如何生效的？

`qqsync` 的核心原则是**保持各服务原本的启停状态不变**：原本运行中的服务会根据变更类型自动热应用或重启；原本处于停止状态的服务，同步后依然保持停止。

| 变更类型 | 服务处于【运行中】时的生效方式 | 服务处于【已停止】时的处理方式 |
|---|---|---|
| **仅修改 LLM 文档（如渠道、模型、请求参数）** | Bot 运行时直接**热应用**（无需重启进程），实际加载状态由 Bot 回报。 | 直接在数据库中完成 LLM 配置发布，下次启动 Bot 时直接加载目标版本。 |
| **群／私聊参数、牛牛文案模式、普通文件、`.env` 或组合配置变化** | 自动先**暂停**正在运行的 Bot/Web 服务，安装完整目标配置后再**恢复**运行；Docker 环境下会按新的 Compose 和 `.env` 重新启动原本运行的服务。 | 直接安装配置，保持服务停止状态。 |

> **源码运行（`source`）的进程要求**：
> 原生 Python 进程必须通过新版的 `bot.py`、`web_api.py` 或 Windows `start.bat` 启动，才具备自动暂停与恢复的能力。如果你在升级前就已经启动了旧版原生进程，请先用新版入口手动重启一次。

> **哪些数据不会跨环境同步？**
> `qqsync` 跨环境交换的仅仅是**配置内容**。各个环境自己的配置修订历史、正在运行的任务、聊天记录以及业务数据库，都各自独立保留在原环境中，不会被同步覆盖。

---

## 与代码一起部署（`deploy-v4`）

当你把公开模板更新到自己的 `prod/` 目录后，使用 `deploy-v4` 部署代码时，默认会自动执行 `qqsync` 推送配置。部署脚本复用了 `qqsync` 的计划与安装流程，会把**候选配置、镜像构建、停服发布、版本切换及健康检查**打包在同一次部署事务中完成（代码发布会启动新版本并检查健康状态）。

### 常用部署命令

**Linux / macOS (Bash)**：
```bash
# 仅预览部署与配置同步计划
bash scripts/deploy/deploy-v4.sh --plan

# 部署代码并默认推送（push）本地配置到服务器
bash scripts/deploy/deploy-v4.sh

# 部署代码，但配置方向改为从服务器回流（pull）到本地
bash scripts/deploy/deploy-v4.sh --config-sync pull
```

**Windows (PowerShell)**：
```powershell
scripts/deploy/deploy-v4.ps1 -Plan
scripts/deploy/deploy-v4.ps1
scripts/deploy/deploy-v4.ps1 -ConfigSync pull
```

### 老服务器迁移与新服务器首次部署参数

针对处于不同升级阶段的服务器，请按对应情况附加参数（平铺目录迁移和完整运维步骤见[生产模板](../../prod.example/README.md)）：

| 服务器状态 | 应使用的 `deploy-v4` 参数 | 作用说明 |
|---|---|---|
| **仍在使用旧版 `data/llm_config.db` 的老服务器** | `--migrate-storage` | 先按[存储迁移](storage-migration.md)执行迁移；该选项会自动关闭本次配置同步，并完整保留服务器现有配置。 |
| **已完成存储迁移，但首次升级到 `qqsync` 的服务器** | `--config-sync off` | 关闭本次配置同步，保留服务器现有配置。 |
| **全新服务器首次部署** | `--config-sync off --env local`（PowerShell 用 `-EnvSource local`） | 独立的 `--env` / `-EnvSource` 选项专门配合 `off` 流程把本地 `.env` 初始化过去（注：日常普通的 `push` / `pull` 部署本身就已经包含 `.env`，无需加此参数）。 |

---

## 预览选项、CLI 说明与中断恢复

- **预览与终端输出**：
  - `qqsync refresh` 会按字段展示配置变化，对于普通文本文件会同时展示可读的行级 Diff。
  - **密钥保护**：凭据与敏感值默认隐藏；如需在自己的终端明文查看，请加 `--show-secrets`（即 `qqsync refresh --show-secrets`）。
  - **CLI 行为**：自动化脚本可加 `--json`；不带参数直接运行 `qqsync` 会显示帮助信息。注意：`qqsync` **没有** `auto` 或 `apply` 子命令。
- **意外中断后的恢复**：
  - 如果 `push`、`pull` 或 `deploy-v4` 在执行中途意外中断，**直接重新运行刚才那条命令即可**。
  - 工具会自动读取私有记录，使用中断前已经锁定的目标配置和服务状态继续确认或恢复，无需手动输入任何哈希或操作编号。
  - **切勿删除恢复目录**：在恢复彻底完成前，请保留 `data/config-sync/` 和部署生成的 `.deploy/` 目录。
  - **旧工具升级兼容**：旧版同步工具已经完成的共同基线会自动接入新的字段级同步；如果旧工具留有未完成的旧事务，会先按原目标处理完毕。
