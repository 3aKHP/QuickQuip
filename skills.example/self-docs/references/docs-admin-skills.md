<!-- Generated from docs/admin/skills.md; do not edit -->

# Skill 系统（skills/）

本文面向部署者和管理员，说明 Skill 系统的部署方式与安全约束。

Skill 是受信任的部署资产：部署者把技能包放进 `skills/` 目录，AI 在对话中按描述匹配自行激活使用。每个技能是一个子目录，内含 `SKILL.md`（frontmatter 元数据 + 指令正文）、可选的 `references/`（参考资料）和 `scripts/`（可执行脚本）。典型用途：让 AI 基于内置文档副本回答机器人用法提问、汇报部署主机健康状态。

## 部署目录

先确认 Bot 正在运行且已有正常 AI 对话，并能登录 Web 管理后台。在“LLM 工坊 → LLM 配置 → 工具与技能 → Skill 运行时”查看“Skill 目录”：留空使用 Bot 项目根的 `skills/`（已被 Git 忽略）；非空使用指定目录，相对路径按项目根解析。文件应放在运行 Bot 的机器上。

将需要的技能包从 `skills.example/` 复制到实际目录。下面的 Bash 命令适用于 `skills.example/` 与目标 `skills/` 同在项目根的首次安装：

```bash
mkdir -p skills
cp -r skills.example/self-docs skills/
```

Windows 可在文件管理器创建目标 `skills` 文件夹，再复制整个 `self-docs` 文件夹，确认存在 `skills/self-docs/SKILL.md`。已有同名包时按下文“预置 Skill”节更新。自定义目录需替换命令目标；版本目录部署在部署根使用 `cp -r current/skills.example/self-docs skills/`，复制到共享目录。自建文本文件的保存步骤见[Skill 编写教程](../dev/skill-tutorial.md#43-第三步写-skillmd)。

Docker 镜像与 Windows 懒人包携带 `skills.example/`；Windows `start.bat` 首启自动复制整个目录。版本目录部署使用部署根共享 `skills/`：Bot 只读挂载，Web Admin 读写挂载，已安装内容随数据保留。每次部署合入仓库新增文件，现有文件和删除操作由 Web 管理页或服务器手动维护。目录供给见[生产模板](../../prod.example/README.md)。

直接使用根 Compose 模板时，需同时启用 Bot 与 Web Admin 的 `skills` 卷挂载；在项目根运行 `docker compose -f docker-compose.example.yml up -d quickquip web-admin` 应用新挂载。容器内的 Skill 目录对应挂载目标，服务器上传与文件管理则操作其主机来源目录。

目录约定：

- 一个子目录一个 Skill，目录名即 Skill 名；只允许小写字母、数字和连字符（`^[a-z0-9][a-z0-9-]*$`，最长 64 字符），且必须与 `SKILL.md` frontmatter 里的 `name` 一致。
- `SKILL.md` 为 YAML frontmatter + Markdown 正文，必填 `name` 和 `description`；单文件上限 256KiB，`description` 上限 1024 字符。
- `description` 帮助 AI 判断适用请求，应写清触发条件（例如“当用户询问机器人用法或配置时使用”）。
- 解析或校验不通过的 Skill 会被跳过并记录告警日志，不影响同目录的其他 Skill。

## 配置（`settings.skills`）

通过 Web Admin“LLM 配置”或配置 CLI 编辑并保存草稿，单独应用后由 Bot 接纳。资源上限与开关保存在 `config/managed/config.db`，Skill 内容继续由独立目录维护。完整流程见 [LLM 配置管理](llm-configuration.md)。

首次启用在“LLM 工坊 → LLM 配置 → 工具与技能”操作：

1. 切到“工具与搜索”，在“工具调用轮次与上限”开启“启用工具调用”（`settings.runtime.tool_calling_enabled`）。
2. 切到“Skill 运行时”，开启“启用 Skill”（`settings.skills.enabled`），确认“Skill 目录”。
3. 默认空工具名单可保持。若“工具与搜索 → 内置工具白名单与发现”已有非空“额外启用工具”且“启用方式”为“替换”（`settings.tools.enabled_mode = "replace"`），将下表四个 Skill 工具名加入现有名单，保留其他需要的工具。
4. 点击“保存草稿”，再点击“应用到 Bot”，等待状态条显示 Bot 已加载目标版本。应用持续排队时先检查 Bot 进程是否正在运行。

新建配置库的工具调用缺省关闭。工具发现设置见[工具发现配置](tool-discovery.md)。

开关、目录及资源上限的完整字段表见[配置参考](configuration.md#settingsskills--skill-系统)。保存时会校验取值并返回具体字段路径及约束。目录为空或缺失时，模型使用基础工具与提示词。

文件增删和内容更新在模型下一轮请求构建提示词时重新扫描并生效。LLM 配置中的开关、目录和资源参数通过保存草稿、应用生效。部署侧文件管理与在线入口见下文“Web 管理与导入”。

群内 `/skill list` 可查看已安装 Skill 与当前会话已激活项（只读）；与当前版本预置副本分叉的条目会附带更新提示（见“预置 Skill”节）。安装 `self-docs` 后发送 `/ai 你的 /quote 命令怎么用？`，再看激活项是否出现 `self-docs`。名单总数取决于已有安装内容；验证时核对目标名称与激活结果。`/ai` 是默认前缀，已有自定义配置时使用对应前缀。

## 工具面

清单、激活与按需读取的设计依据见 [ADR-0015](../dev/adr/0015-progressive-skill-loading.md)。

启用后，系统提示包含已安装 Skill 的名称和描述清单，AI 据此决定何时激活；激活后 `SKILL.md` 正文才进入对话。四个工具：

| 工具 | 行为 |
|------|------|
| `activate_skill` | 激活一个已安装 Skill，注入其指令正文；同会话重复激活自动去重 |
| `read_skill_resource` | 读取已激活 Skill 目录内的单个文件（需先激活），支持按行段分块读取 |
| `search_skill_resources` | 在已激活 Skill 目录内按关键词或正则检索文本（需先激活） |
| `run_skill_script` | 执行已激活 Skill `scripts/` 下的 `.py` / `.sh` 脚本（需先激活） |

脚本按扩展名选择解释器：`.py` 优先使用 PATH 中的 `python3`，找不到时使用运行 Bot 的 Python；`.sh` 使用 PATH 中的 `sh`。解释器直接读取脚本，执行位与 shebang 不影响选择。Windows 主机优先使用 `.py`；需要 `.sh` 时须先在 Bot 环境提供 `sh`，缺失会返回错误。

## 安全模型

资产信任与脚本执行的设计依据见 [ADR-0016](../dev/adr/0016-trusted-skill-execution.md)。

Skill 源由部署者严格把控——只放置审阅过的 Skill：其指令正文会进入对话上下文，脚本会在部署主机上执行。运行时按以下规则读取资源和执行脚本：

- **内容维护**：技能包由部署者通过文件操作或 Web Admin 管理页维护，AI 工具负责激活、读取、检索和执行随包脚本。
- **路径加固**：读取、检索、执行都限制在对应 Skill 目录内，拒绝 `..` 穿越、绝对路径与符号链接逃逸。
- **脚本环境**：按脚本类型启动解释器，参数逐项传递；工作目录为该 Skill 目录。子进程只继承 `PATH`／`LANG`／`TZ`，Bot 进程环境中的凭据不会传给脚本。
- **执行前复验**：脚本执行前做 SHA-256 快照比对，目录扫描之后内容有变化即拒绝执行。
- **资源上限**：超时与输出上限见配置参考；目录内检索不起子进程，另有单次匹配 1s 引擎超时与单次调用 4s 墙钟预算兜底（复杂正则可能占用数秒）；含嵌套量词或交叠分支的量化组、相邻可空量化原子链等病态正则形态会被静态检查拒绝（防灾难性回溯），被拒绝的模式可改用字面搜索或改写；scripts/ 单文件超 256KiB 不编入清单、不可执行。
- **统一合规扫描**：Skill 相关的全部工具产出（清单描述、激活正文、资源内容、检索结果、脚本输出）与 `search_web` 等外部工具结果走同一敏感词扫描流程，见 [sensitive-filter.md](sensitive-filter.md)；`description` 命中拦截词的 Skill 会被从清单剔除并记录告警日志，不进入系统提示与激活面。

### 禁止把 `run_skill_script` 当通用 shell

`run_skill_script` 只用于执行 Skill 自带、服务于该 Skill 用途的脚本。编写 `SKILL.md` 时不要指引 AI 借脚本执行 grep/find 等通用命令来绕过检索工具——`search_skill_resources` 已覆盖 Skill 目录内检索。运维侧审查第三方 Skill 时，同样应拒绝包含此类指引的 Skill。

## 预置 Skill

可选副本、漂移检测与显式同步的选择依据见 [ADR-0017](../dev/adr/0017-preset-skill-distribution.md)。

`skills.example/` 随附两个官方 Skill：

- `self-docs`：内置公开文档副本（用户手册、管理手册、配置参考、项目治理与协作约定等；同步源名单见 `scripts/ci/sync_self_docs_references.py`），AI 被问到机器人用法、命令、配置或项目协作约定时激活检索后作答。
- `host-healthcheck`：汇报部署主机健康状态，默认采集容器内可见的宿主机指标与容器自身限额，零配置可用。可选的宿主机 cron 采集器与 compose 只读挂载增强见 `prod.example/` 模板注释。

### 版本对齐：漂移检测与同步

预置 Skill 经复制到达 `skills/`；QuickQuip 版本升级会更新 `skills.example/`，已复制的本地副本不会随之自动更新。可通过以下入口查看差异并同步：

- **运行时漂移检测（只读）**：bot 每次扫描 Skill 目录时，对 `skills/` 与 `skills.example/` 中的同名 Skill 做全文件字节级指纹比对。分叉时记录 WARNING 日志（分叉名单变化才记录，同状态只记录一次；回归一致时记 INFO），`/skill list` 在对应条目标注“与当前版本预置不同，可运行 scripts/maintenance/sync_preset_skills.py 更新”。检测结果只进日志与命令回复，不进入 catalog 块、系统提示与任何模型注入面，也不占用 catalog 预算。`skills.example/` 缺失时（pip 安装形态）检测自动跳过。
- **同步脚本**：`python scripts/maintenance/sync_preset_skills.py`（或 `--check`）报告每个预置 Skill 的四态——`current`（与预置副本一致）、`diverged`（已安装但不同）、`missing`（未安装）、`conflict`（存在同名非目录项或符号链接，需人工处理）；发现冲突时退出码为 2，人工处理后重试。`--apply` 安装缺失项并把分叉项覆盖为预置副本，原副本整体备份为 `skills/.preset-backups/<name>.preset-backup-<时间戳>`（备份容器自身无 SKILL.md，运行时扫描不感知；备份保存原有定制，确认后自行清理）。脚本只依赖 Python 标准库，Docker / Linux 裸机 / Windows 形态通用；bot 每轮现扫 `skills/`，下一轮请求读取同步后的文件，无需重启。
- **部署入口**：`scripts/deploy/deploy-v4.sh` / `deploy-v4.ps1` 在 deploy、dry-run 与 migrate 时自动执行一次 `--check` 报告并给出同步命令（best-effort，不阻断部署）；源码形态部署在版本升级后按 Release notes 的“预置 Skill 变动”小节指引手动执行同步（该小节是 release PR 模板的固定检查项）。
- **Web 管理面**：Web Admin“Skill”页顶面板按同一判定语义展示各预置 Skill 状态，支持勾选同步与一键同步全部待处理，覆盖分叉项前同样自动备份至 `skills/.preset-backups/`；详见“Web 管理与导入”。

## Web 管理与导入

Web Admin 导航“LLM 工坊”区的“Skill”页（`/ops/#/skills`）提供 Skill 目录的在线管理面，作用目录与 `settings.skills.catalog_dir` 的生效目录一致。所有写入直接落盘：运行时下次构建系统提示即重新扫描目录，下一轮请求读取更新后的文件，无需重启。容器化部署下写入落在部署根共享 `skills/`（web-admin 容器读写挂载），容器重建与版本部署后仍然保留；部署流程只向共享目录合入仓库新增的 Skill，不覆盖也不删除已有内容。全部写操作（新建、编辑、删除、预置同步、安装）记入审计日志（`data/audit.db`，Web Admin 审计页可见）。

### 管理与在线编辑

- 列表覆盖目录内全部 Skill：解析或校验不通过、被运行时扫描静默跳过的坏项同样列出并附诊断（缺 `SKILL.md`、非 UTF-8、frontmatter 校验失败等）；与预置副本一致/已偏离的条目附预置态标注，含 `scripts/` 的条目附“含脚本”标注。
- 详情页展示 frontmatter metadata、资源清单（路径、类型、大小）与诊断；`SKILL.md`、`references/`、`scripts/` 等文本资源可在线编辑或删除（`SKILL.md` 不可删，保存时按运行时同一 parser 校验），单文件读写上限 256KiB。
- 新建 Skill 校验目录名规范（`^[a-z0-9][a-z0-9-]*$`，≤64 字符）并生成 frontmatter 骨架；删除 Skill 移除整个目录，不可恢复。

### 预置同步（页面内）

页顶“预置同步”面板与 `scripts/maintenance/sync_preset_skills.py` 同一判定语义，逐项报告 `current`（已安装，与预置副本一致）/ `diverged`（已安装，与预置副本不同）/ `missing`（未安装）/ `conflict`（存在同名非目录项，需人工处理）；仅本地（非预置）的 Skill 单独列出。勾选后“同步所选”，或“一键同步全部待处理”；`diverged` 项覆盖前旧副本整体备份至 `skills/.preset-backups/`，确认本地定制无丢失后自行清理。

### 安装第三方 Skill

三种来源：本地 `.zip` 压缩包（≤16MiB）、本地文件夹（整目录上传）、GitHub 仓库链接。包内每个含 `SKILL.md` 的目录都会成为一个候选；安装以 frontmatter `name` 为目录名，压缩包内的原始目录名不参与校验。与现有 Skill 同名时须显式勾选覆盖安装，旧副本自动备份至 `skills/.preset-backups/`。

安装是两阶段“检查 → 确认”交互：检查阶段只读产出候选报告——`description`、文件数与体积、解析诊断、是否携带 `scripts/` 可执行脚本（含脚本时红色警示并列出脚本清单）；确认后才写入目录。检查载荷在服务端暂存 30 分钟，超时需重新检查。候选验收与运行时扫描共用同一 parser（Agent Skills 开放标准的可移植核心），通过检查的 Skill 安装后即可被运行时装载。

导入大小限制：zip 条目 ≤500、单文件 ≤1MiB、解压总量 ≤32MiB；拒绝符号链接与绝对路径条目。

GitHub 导入经 `codeload.github.com` 下载仓库 zip：仅支持公开仓库，下载硬上限 32MiB、超时 20s，部署主机需可访问 `github.com` / `codeload.github.com`。接受 `https://github.com/<owner>/<repo>`、`…/tree/<ref>` 与 `…/tree/<ref>/<子目录>` 三种链接；多 Skill 仓库（monorepo）必须用 `/tree/` 子目录链接定位单个 Skill——按整仓摄取会把仓库其余部分一并计入大小限制，容易触发条目数/体积上限；`/blob/` 单文件链接不受支持。

### Web 管理面的安全边界

持有 Web 管理会话的人可以写入和导入 Skill。页面在含脚本标注、编辑横幅和安装报告中列出可执行内容，部署者须在确认安装前逐文件审阅。脚本以 Bot 进程权限在部署主机执行；上文的环境变量限制、路径检查和资源上限同样适用于在线安装与编辑的 Skill。
