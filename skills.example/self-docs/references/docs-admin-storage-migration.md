<!-- Generated from docs/admin/storage-migration.md; do not edit -->

# 将配置与运行数据分开存储（存储迁移指南）

本文面向**从 1.16.3 升级到 1.16.4** 的已有安装环境（包括仍在使用 `data/llm_config.db`、在业务数据库中存放群设置、或使用混合定时消息文件的环境）。

本次迁移会将 LLM 配置、群和私聊参数、牛牛文案模式收拢到独立的 SQLite 配置存储中，将发布与执行状态另存到运行期数据库，并把循环定时任务与一次性待办任务分开保存；同时完整保留现有的聊天记录、记忆、游戏记录、配置修订历史和任务进度。

> **我是全新安装的用户吗？**
> 全新安装的环境**不需要**执行本文的迁移步骤，直接执行普通的配置初始化即可。如果新版 Bot 或 Web 启动时检测到旧版存储结构，会报错返回 `migration_required`；此时普通的 `init` 和 Windows `start.bat` 都会拒绝启动，要求先按本文完成停服迁移。

---

## 本次迁移改了什么？（迁移结果总览）

本次迁移涉及的配置与运行期数据会按下表分别存储：

| 数据内容 | 迁移后的新位置 | 补充说明 |
|---|---|---|
| **LLM 配置、群和私聊参数、牛牛文案模式** | `config/managed/config.db` | 核心可编辑配置库 |
| **配置任务、发布指针、Bot 心跳** | `data/config_runtime.db` | 运行期状态库（与主配置库分离） |
| **循环定时任务** | `config/managed/scheduled_messages.json` | 属于受管配置，纳入配置同步范围 |
| **一次性待办定时任务** | `data/pending_scheduled_messages.json` | 属于运行期数据，留在 `data/` |
| **私聊响应状态（暂停/恢复）** | `data/llm.db`（会话运行状态） | Web 参数页中的私聊“暂停／恢复响应”现作为独立会话状态维护；重置参数时不会丢失该会话状态 |

- **保持原位的文件**：独立的 TOML、YAML 配置文件以及根目录 `.env` 均保持原有位置与格式不变。

---

## 第一步：迁移前准备（所有环境必做）

在开始执行任何环境的迁移命令前，请依次完成以下 4 项准备：

1. **确认旧版配置库已经是 `schema 3`**：
   - 请先确认旧的 LLM 配置数据库（`data/llm_config.db`）已处于 `schema 3` 版本。
   - 如果还是 `schema 1` 或 `schema 2`，必须先用支持 `schema 3` 的旧版本程序，按当时的升级说明升级到 `schema 3`，然后再进行本次迁移。
2. **完整备份现有数据与环境**：
   - **备份文件与目录**：根目录 `.env`、`config/`、`data/`、`llm_about/`、`skills/` 以及私有运维配置。
   - **保留回退资产**：保留协议端（LLBot）登录资产、旧版程序包或旧版 Docker 镜像标识（Tag/Digest）。
   - **数据库备份方式**：SQLite 数据库请使用一致性备份，或者在完全停止服务写入后直接完整复制备份整个数据目录。
   - **预留磁盘空间**：请确保磁盘有充足空间，迁移过程会自动生成并保存**三个旧数据库及定时消息文件的备份**。
3. **停止 Bot 和 Web 服务（预留停服窗口）**：
   - 停止正在运行的 Bot 和 Web 服务，并**暂停会自动拉起它们的守护进程或服务管理任务**（如 systemd timer、cron、supervisor 等）。
   - **LLBot 协议端可以继续保持运行**。请预留好停服维护窗口，待迁移和核对全部完成后再恢复服务。
4. **更新容器挂载与 `.env` 部署变量**：
   - **Docker 环境**：合入新版 Compose 模板中的共享可写挂载 `config/managed/`，以及环境变量 `QUICKQUIP_MANAGED_CONTAINER=1`。
   - **配置工具准备**：如果准备使用 `qqconf` / `qqsync`，请在真实项目根目录的 `.env` 中设置 `QUICKQUIP_DEPLOY_LOCATION=local|cloud` 和 `QUICKQUIP_DEPLOY_RUNTIME=source|docker`（详见[部署方式设置](config-sync.md#先设置部署方式)）。

---

## 第二步：按你的部署方式执行迁移

请根据你实际使用的运行环境，选择以下 4 种方案之一执行：

### 方案 A：源码安装（本地或云端服务器原生运行）

1. **更新代码与前后端环境**：
   - 确保 Bot 和 Web 已停止，拉取新版源码。
   - 如果启用了 Web Admin，请使用仓库 `.node-version` 指定的 Node 版本与 `pnpm` 构建同版本前端。
2. **更新 Python 依赖并执行迁移**：
   在项目根目录下执行：
   ```bash
   python -m pip install -r requirements.txt
   python -m pip install --no-deps -e .
   python -m quickquip.llm.config_cli migrate-storage --services-stopped
   ```
3. **记录备份路径并启动检查**：
   - 命令执行后会输出迁移结果以及自动生成的 **`backup` 备份目录路径**，请妥善保存该路径。
   - 校验通过后，启动新版 Bot 和 Web（参见下方《第三步：迁移后核对清单》进行全面检查）。
   - **云端源码部署特别说明**：在服务器的项目目录下执行完全相同的步骤。请确保通过新版的 `bot.py`、`web_api.py` 启动服务，并核对你的自定义进程管理器（如 systemd/supervisor）对父子进程的停止和重启行为是否正常。

---

### 方案 B：Windows 懒人包

1. **解压新包并迁入旧数据**：
   - 将新版懒人包 ZIP 解压到一个**全新的独立目录**（保留旧包目录不动，以便随时回退）。
   - 确认旧版 Bot 和 Web 已停止后，将已经备份好的配置文件、数据目录（`config/`、`data/` 等）和私有资产复制到新包目录的对应位置。
   - 旧版 `.env` 保留原有配置值即可；但在后续使用 `qqconf` / `qqsync` 之前，记得在 `.env` 中补齐 `local` / `source` 部署方式设置。
2. **执行停服迁移命令**：
   在新包目录下打开终端（PowerShell），先执行迁移：
   ```powershell
   python\python.exe -m quickquip.llm.config_cli migrate-storage --services-stopped
   ```
3. **启动并检查**：
   - 记录下终端输出的**备份目录路径**，然后运行 `start.bat` 启动服务。
   - 启动后 Web Admin 后台需要重新登录；请核对配置修订、私聊响应状态和定时消息无误后，再恢复日常使用。

---

### 方案 C：本地 Docker 与手工 Compose

1. **更新 Compose 配置与镜像**：
   - 保留旧版镜像版本和数据备份。
   - 更新 Compose 文件中的卷挂载配置：
     - **根目录模板布局**：Bot 容器在只读挂载 `config/` 的基础上，叠加挂载可写的 `config/managed/`。
     - **生产 release 布局**：Bot 和 Web 容器均需挂载部署根目录下的共享目录。
   - 将 `config-init`、`quickquip`、`web-admin` 三个服务固定为**同一个新版镜像**。
2. **执行容器迁移流程**：
   如果使用项目根目录的 Compose 模板，在项目根目录依次执行：
   ```bash
   # 1. 拉取新版镜像
   docker compose -f docker-compose.example.yml pull config-init quickquip web-admin

   # 2. 停止正在运行的 Bot 和 Web
   docker compose -f docker-compose.example.yml stop quickquip web-admin

   # 3. 通过一次性维护容器执行存储迁移
   docker compose -f docker-compose.example.yml run --rm --no-deps config-init \
     python -m quickquip.llm.config_cli migrate-storage --services-stopped

   # 4. 确认上一条迁移命令成功（退出码为 0）后，启动新版服务
   docker compose -f docker-compose.example.yml up -d quickquip web-admin
   ```
   > **注意**：
   > - 必须确认迁移命令成功完成后，才能启动服务。请保留好迁移输出的 `backup` 目录以及 `data/storage-migration.json`。
   > - **没有 `config-init` 服务的手工生产 Compose**：请先构建好候选新版镜像，然后使用挂载了真实配置和数据目录的 `web-admin` 维护容器来执行相同的 `migrate-storage --services-stopped` 命令。

---

### 方案 D：生产部署脚本（`deploy-v4`）

将新版生产模板合入你自己的运维目录（确保 `config/managed/` 已采用新版 Compose 的共享挂载）后，使用 `--migrate-storage` 参数运行部署脚本：

**Linux / macOS (Bash)**：
```bash
bash scripts/deploy/deploy-v4.sh --migrate-storage
```

**Windows (PowerShell)**：
```powershell
scripts/deploy/deploy-v4.ps1 -MigrateStorage
```

#### `deploy-v4 --migrate-storage` 的自动执行逻辑与约束：
- **保护服务器现有配置**：该选项会自动关闭本次配置同步，完整保留服务器上的现有配置。根目录 `.env` 默认继续使用服务器上的版本；如果你希望在迁移同时上传本地的 `.env` 凭据，请显式加上 `--env local`（PowerShell 为 `-EnvSource local`）。
- **自动化流水线与自动回滚**：部署驱动会先构建候选镜像 $\rightarrow$ 停止 Bot 和 Web $\rightarrow$ 执行存储迁移 $\rightarrow$ 启动候选新版本 $\rightarrow$ 执行健康检查（生成的备份保留在共享数据目录中）：
  - 如果**迁移过程本身失败**：自动恢复原存储结构。
  - 如果**迁移成功，但候选版本启动后健康检查失败**：会自动将存储**反向转换回旧格式**，并重新启动旧版本服务。
- **参数组合限制**：
  - 存储迁移强制要求执行健康检查，因此**不能**与“跳过健康检查”或“推送配置”选项同时使用。
  - 如果你是旧的平铺目录部署，可以将平铺目录迁移参数 `--migrate` 与 `--migrate-storage` 组合在一起同时执行。

#### 生产迁移成功后的下一步：建立配置同步基线
等服务器迁移成功、且本地与服务器两端都已完成初始化或迁移，并在各自的 `.env` 中设置好 `cloud` / `docker` 后，按以下顺序建立同步基线：
1. 先备份保留好你本地的 `.env` 和运维配置副本（因为首次回流会包含根 `.env` 和运维配置）。
2. 运行 `qqsync refresh --direction pull` 核对将要拉回的变更范围。
3. 运行 `qqsync pull` 将服务器配置回流到本地真实目录。
4. 运行 `qqconf unpack` 建立本地工作副本。
5. 基线建立完毕后，后续日常运行 `deploy-v4` 时就会默认把本地配置推送到服务器了。

---

## 第三步：迁移后核对清单与日常备份变化

### 1. 迁移后必查清单

启动新版 Bot 和 Web 后，请逐项核对以下内容：
- [ ] **LLM 配置修订**：Web 配置页中的“草稿（Draft）”与“已发布版本（Published）”保持原有的区别与内容。
- [ ] **群聊参数**：群参数中的“关闭项”、“零值（0）”以及“继承全局值”均未丢失或被错误覆盖。
- [ ] **私聊状态**：私聊的启用/暂停响应状态与升级前完全一致。
- [ ] **牛牛游戏**：牛牛玩家历史记录与群文案模式均可正常读取（游戏升级会保留玩家长度记录；如需执行赛季离线重置，请按[游戏维护指南](game-config.md#离线生成牛牛重置库)单独操作）。
- [ ] **定时任务**：循环定时任务与一次性待办任务的数量、任务 ID 均正确无误。
- [ ] **Bot 运行态**：确认 Bot 启动后上报了新鲜的心跳（Heartbeat）、已正确加载目标配置修订版本，且定时调度器已完成注册。

### 2. 日常备份机制的变化（重要）

完成本次存储升级后，日常备份有以下两项变化需要注意：
- **配置 CLI 备份成对出现**：现在运行配置 CLI 的 `backup` 命令时，除了生成主配置库备份外，还会在同目录下配套生成一个 `.runtime.db` 备份文件。**保存和恢复备份时，必须将这两份文件放在一起成对处理。**
- **Trace 媒体去重备份**：如果启用了 Trace 媒体去重功能，请额外按照[Trace 备份说明](configuration.md#trace-媒体存储)，将数据库与对应的 `blob` 目录成组备份。

---

## 故障恢复：迁移中断与版本回退

### 1. 迁移中途意外中断怎么办？

如果迁移命令在执行过程中意外中断：
1. **保持 Bot 和 Web 处于停止状态**（不要尝试启动服务）。
2. **直接重新运行完全相同的迁移命令**。
   - 工具会自动先恢复未完成操作的备份，然后再重新执行迁移。
   - 如果实际上迁移已经成功完成，重复运行该命令不会破坏数据，只会直接返回已有的迁移结果。

---

### 2. 如何回退到旧版本存储布局（Rollback）？

如果你在迁移完成后需要回退到旧版本程序，**不能直接启动旧版程序**，必须先使用迁移时生成的备份目录，将存储结构**反向转换**回旧格式。

- **回退的核心优势（不丢新数据）**：对已完成迁移的环境执行 `--rollback` 时，工具**不会**简单粗暴地用老备份覆盖你迁移后新产生的聊天记录，而是会**保留迁移后新产生的业务记录与任务进度**，同时把配置和存储结构重建回旧版（`schema 3`）格式。

#### 通用回退命令

停止 Bot 和 Web 后，执行以下命令（将 `<备份目录>` 替换为迁移时输出的实际备份路径）：

```bash
python -m quickquip.llm.config_cli migrate-storage --services-stopped --rollback <备份目录>
```

#### 不同部署环境的具体回退操作步骤

| 部署环境 | 具体回退步骤 |
|---|---|
| **源码安装** | 1. 停止新版 Bot 和 Web；<br>2. 在新版环境下运行上述 `--rollback <备份目录>` 命令；<br>3. 转换成功后，切回支持 `schema 3` 的旧版代码并启动旧程序。 |
| **Windows 懒人包** | 1. 停止新包的服务；<br>2. 使用**新包**目录里的 `python\python.exe` 执行上述 `--rollback <备份目录>` 命令；<br>3. 将已经反向转换回旧格式的配置和业务数据复制交还给**旧包**目录，再启动旧包。 |
| **本地根 Compose** | 1. 停止 `quickquip` 和 `web-admin`；<br>2. 使用候选（新版）的 `config-init` 维护容器运行上述 `--rollback <备份目录>` 命令（注意：备份目录需填写**容器内的路径**）；<br>3. 将 `config-init`、`quickquip`、`web-admin` 三个服务镜像切回旧版并启动。 |
| **生产 Release 布局 (`deploy-v4`)** | （注：如果直接运行普通的 `deploy-v4.sh --rollback`，脚本会拦截并提示你先完成以下存储反向转换步骤）<br>1. 先停止服务器上的 Bot 和 Web 服务；<br>2. 使用候选（新版）的 `web-admin` 维护容器执行上述 `--rollback <备份目录>` 命令（路径填容器内路径）完成反向转换；<br>3. 执行 `scripts/deploy/deploy-v4.sh --rollback` 切回旧版程序（全程保留同一份共享配置和业务数据）。 |

#### 回退后的核对与再次升级

- **回退后核对清单**：启动旧版程序后，请确认：迁移期间新增的聊天消息仍在、最新配置可正常读取、私聊启停状态正确、且已经执行（消费）过的一次性定时任务**没有**重新出现。
- **回退后如何再次升级**：未来再次升级时，依然使用本文相同的迁移入口命令，回退期间产生的新业务记录同样会被完整保留。
- **新旧备份文件的兼容规则**：
  - 旧版 `schema 3` 的单库备份文件：只能先恢复到旧版存储布局中，然后再运行迁移命令升级。
  - 新版生成的配套双文件备份（含 `.runtime.db`）：仅用于新版存储布局的配置恢复。

---

## 附：同步更新运维脚本路径

本次更新同步整理了仓库内的运维与构建脚本目录结构。如果你配置了定时任务（cron）、桌面快捷方式或自定义运维脚本，请按以下对照表更新路径引用：

| 功能类别 | 新版所在路径 | 迁移与兼容说明 |
|---|---|---|
| **部署程序** | `scripts/deploy/` | 维护程序随代码一起分发；`prod/` 目录现在仅用于保留真实配置及协议端登录资产 |
| **巡检与监控指标** | `scripts/ops/` | 请更新 cron 定时任务及监控脚本中的路径 |
| **数据维护工具** | `scripts/maintenance/` | 请更新自定义维护脚本或快捷方式中的路径 |
| **生产环境 Dockerfile** | `docker/Dockerfile.prod` | 生产部署驱动（`deploy-v4`）会自动为旧的 `prod/Dockerfile` 引用生成兼容构建文件；如果是**手工维护的 Compose 文件**，请对照新版模板手动更新构建路径 |
