<!-- Generated from docs/admin/skills.md; do not edit -->

# Skill 系统（skills/）

本文面向部署者和管理员，说明 Skill 系统的部署方式与安全约束。

Skill 是受信任的部署资产：部署者把技能包放进 `skills/` 目录，AI 在对话中按描述匹配自行激活使用。每个技能是一个子目录，内含 `SKILL.md`（frontmatter 元数据 + 指令正文）、可选的 `references/`（参考资料）和 `scripts/`（可执行脚本）。典型用途：让 AI 基于内置文档副本回答机器人用法提问、汇报部署主机健康状态。

## 部署目录

运行目录为项目根的 `skills/`（已被 git 忽略），仓库随附的 `skills.example/` 承载官方预置 Skill 模板。部署照 `config/personas.example/` → `config/personas/` 的同一先例：从 `skills.example/` 复制或合并需要的 Skill 到 `skills/`，再按环境调整；Windows 懒人包首启（`start.bat`）会自动完成整目录复制。Docker 镜像与 Windows 懒人包均只携带 `skills.example/`；release 布局的容器化部署把 `skills/` 作为部署根共享目录（与 data/ 同级）：bot 容器只读挂载、web-admin 容器读写挂载，Web 管理页的安装成果在容器重建与后续部署后仍然保留；每次部署把仓库 `skills/` 中新增的 Skill 非破坏性合并进共享目录（已存在文件不被覆盖、删除不传播），已安装 Skill 的更新与删除经 Web 管理页或服务器手动维护；目录供给细节见 `prod.example/` 模板。

目录约定：

- 一个子目录一个 Skill，目录名即 Skill 名；只允许小写字母、数字和连字符（`^[a-z0-9][a-z0-9-]*$`，最长 64 字符），且必须与 `SKILL.md` frontmatter 里的 `name` 一致。
- `SKILL.md` 为 YAML frontmatter + Markdown 正文，必填 `name` 和 `description`；单文件上限 256KiB，`description` 上限 1024 字符。
- `description` 是 AI 决定何时激活的唯一依据，必须写清触发条件（例如“当用户询问机器人用法或配置时使用”）。
- 解析或校验不通过的 Skill 会被跳过并记录告警日志，不影响同目录的其他 Skill。

## 配置（config/llm.toml `[skills]`）

| 键 | 说明 | 默认值 |
|----|------|--------|
| `enabled` | Skill 系统总开关 | `true` |
| `catalog_dir` | Skill 目录；留空 = 项目根 `skills/`，相对路径按项目根解析 | `""` |
| `catalog_max_bytes` | 系统提示中 Skill 清单的字节预算上限，实际预算取 min(模型上下文窗口 2%, 此值) | `8192` |
| `resource_max_bytes` | `read_skill_resource` 单次读取上限（字节） | `65536` |
| `search_max_results` | `search_skill_resources` 命中条数上限 | `50` |
| `search_max_output_bytes` | `search_skill_resources` 输出字节上限 | `32768` |
| `script_timeout_ms` | `run_skill_script` 默认超时（毫秒）；单次调用可另行指定，硬上限 120000 | `30000` |
| `script_max_output_bytes` | 脚本 stdout/stderr 各自的输出字节上限，超限截断 | `65536` |

非法取值回退默认值并记录告警。`skills/` 为空目录或不存在时，Skill 工具不注册、系统提示不增加任何内容——未部署 Skill 的实例行为与此前完全一致。

Skill 的增删就是部署侧的文件操作：目录在每次构建系统提示时重新扫描（每轮请求一次），无需重启，进行中的会话下一轮请求即可看到增删；catalog 块字节变化只影响当轮的前缀缓存命中。运行时（bot 进程与 AI 工具面）没有任何安装、更新或删除 Skill 的路径；部署侧的在线管理入口见「Web 管理与导入」。

群内 `/skill list` 可查看已安装 Skill 与当前会话已激活项（只读）；与当前版本预置副本分叉的条目会附带更新提示（见「预置 Skill」节）。

## 工具面

全部已安装 Skill 的 name + description 清单常驻系统提示，AI 据此语义匹配决定何时激活；激活后 `SKILL.md` 正文才进入对话。四个工具：

| 工具 | 行为 |
|------|------|
| `activate_skill` | 激活一个已安装 Skill，注入其指令正文；同会话重复激活自动去重 |
| `read_skill_resource` | 读取已激活 Skill 目录内的单个文件（需先激活），支持按行段分块读取 |
| `search_skill_resources` | 在已激活 Skill 目录内按关键词或正则检索文本（需先激活） |
| `run_skill_script` | 执行已激活 Skill `scripts/` 下的 `.py` / `.sh` 脚本（需先激活） |

脚本按扩展名映射解释器（`.py` → `python3`，`.sh` → `sh`），不依赖 shebang 与执行位；主机 PATH 上没有 `sh` 时 `.sh` 脚本直接报错拒绝执行（Windows 主机请使用 `.py` 脚本）。

## 安全模型

Skill 源由部署者严格把控——只放置审阅过的 Skill：其指令正文会进入对话上下文，脚本会在部署主机上执行。运行时的结构性防御：

- **无运行时变更路径**：AI 侧没有任何创建、修改或删除 Skill 文件的工具，Skill 内容只能经部署侧通道（文件操作或 Web Admin 管理页，见「Web 管理与导入」）变更。
- **路径加固**：读取、检索、执行都限制在对应 Skill 目录内，拒绝 `..` 穿越、绝对路径与符号链接逃逸。
- **脚本执行隔离**：脚本经结构化 argv 直接启动，无 shell，参数逐字传递不经解释层；子进程环境白名单仅 `PATH`/`LANG`/`TZ`，不继承 bot 进程环境，`.env` 中的凭证对脚本不可见；工作目录固定为该 Skill 目录。
- **执行前复验**：脚本执行前做 SHA-256 快照比对，目录扫描之后内容有变化即拒绝执行。
- **资源上限**：超时与输出上限见上表；目录内检索不起子进程，另有单次匹配 1s 引擎超时与单次调用 4s 墙钟预算兜底（病态正则最坏损失数秒，不会冻结实例）；含嵌套量词或交叠分支的量化组、相邻可空量化原子链等病态正则形态会被静态检查拒绝（防灾难性回溯），被拒之模式可改用字面搜索或改写；scripts/ 单文件超 256KiB 不编入清单、不可执行。
- **统一合规扫描**：Skill 相关的全部工具产出（清单描述、激活正文、资源内容、检索结果、脚本输出）与 `search_web` 等外部工具结果走同一敏感词扫描接缝，见 [sensitive-filter.md](sensitive-filter.md)；`description` 命中拦截词的 Skill 会被整只从清单剔除并记录告警日志，不进入系统提示与激活面。

### 禁止把 `run_skill_script` 当通用 shell

`run_skill_script` 只用于执行 Skill 自带、服务于该 Skill 用途的脚本。编写 `SKILL.md` 时不要指引 AI 借脚本执行 grep/find 等通用命令来绕过检索工具——`search_skill_resources` 已覆盖 Skill 目录内检索。运维侧审查第三方 Skill 时，同样应拒绝包含此类指引的 Skill。

## 预置 Skill

`skills.example/` 随附两个官方 Skill：

- `self-docs`：内置公开文档副本（用户手册、管理手册、配置参考、项目治理与协作约定等；同步源名单见 `scripts/ci/sync_self_docs_references.py`），AI 被问到机器人用法、命令、配置或项目协作约定时激活检索后作答。
- `host-healthcheck`：汇报部署主机健康状态，默认采集容器内可见的宿主机指标与容器自身限额，零配置可用。可选的宿主机 cron 采集器与 compose 只读挂载增强见 `prod.example/` 模板注释。

### 版本对齐：漂移检测与同步

预置 Skill 经复制到达 `skills/`；QuickQuip 版本升级会更新 `skills.example/`，已复制的本地副本不会随之自动更新。四层配套闭合这一摩擦：

- **运行时漂移检测（只读）**：bot 每次扫描 Skill 目录时，对 `skills/` 与 `skills.example/` 中的同名 Skill 做全文件字节级指纹比对。分叉时记录 WARNING 日志（分叉名单变化才记录，同状态不逐轮重复；回归一致时记 INFO），`/skill list` 在对应条目标注「与当前版本预置不同，可运行 scripts/sync_preset_skills.py 更新」。检测结果只进日志与命令回复，不进入 catalog 块、系统提示与任何模型注入面，也不占用 catalog 预算。`skills.example/` 缺失时（pip 安装形态）检测自动跳过。
- **同步脚本**：`python scripts/sync_preset_skills.py`（或 `--check`）报告每个预置 Skill 的三态——`current`（与预置副本一致）、`diverged`（已安装但不同）、`missing`（未安装）；`--apply` 安装缺失项并把分叉项覆盖为预置副本，原副本整体备份为 `skills/.preset-backups/<name>.preset-backup-<时间戳>`（备份容器自身无 SKILL.md，运行时扫描不感知；本地定制不丢，确认后自行清理）。脚本只依赖 Python 标准库，Docker / Linux 裸机 / Windows 形态通用；bot 每轮现扫 `skills/`，同步当轮生效，无需重启。
- **部署入口**：`prod.example/deploy-v4.sh` / `deploy-v4.ps1` 在 deploy、dry-run 与 migrate 时自动执行一次 `--check` 报告并给出同步命令（best-effort，不阻断部署）；源码形态部署在版本升级后按 Release notes 的「预置 Skill 变动」小节指引手动执行同步（该小节是 release PR 模板的固定检查项）。
- **Web 管理面**：Web Admin「Skill」页顶面板按同一判定语义展示各预置 Skill 状态，支持勾选同步与一键同步全部待处理，覆盖分叉项前同样自动备份至 `skills/.preset-backups/`；详见「Web 管理与导入」。

## Web 管理与导入

Web Admin 导航「LLM 工坊」区的「Skill」页（`/ops/#/skills`）提供 Skill 目录的在线管理面，作用目录与 `[skills].catalog_dir` 的生效目录一致。所有写入直接落盘：运行时下次构建系统提示即重新扫描目录，保存即热生效，无需 reload 或重启。容器化部署下写入落在部署根共享 `skills/`（web-admin 容器读写挂载），容器重建与版本部署后仍然保留；部署流程只向共享目录合入仓库新增的 Skill，不覆盖也不删除已有内容。全部写操作（新建、编辑、删除、预置同步、安装）记入审计日志（`data/audit.db`，Web Admin 审计页可见）。

### 管理与在线编辑

- 列表覆盖目录内全部 Skill：解析或校验不通过、被运行时扫描静默跳过的坏项同样列出并附诊断（缺 `SKILL.md`、非 UTF-8、frontmatter 校验失败等）；与预置副本一致/已偏离的条目附预置态标注，含 `scripts/` 的条目附「含脚本」标注。
- 详情页展示 frontmatter metadata、资源清单（路径、类型、大小）与诊断；`SKILL.md`、`references/`、`scripts/` 等文本资源可在线编辑或删除（`SKILL.md` 不可删，保存时按运行时同一 parser 校验），单文件读写上限 256KiB。
- 新建 Skill 校验目录名规范（`^[a-z0-9][a-z0-9-]*$`，≤64 字符）并生成 frontmatter 骨架；删除 Skill 移除整个目录，不可恢复。

### 预置同步（页面内）

页顶「预置同步」面板与 `scripts/sync_preset_skills.py` 同一判定语义，逐项报告 `current`（已安装，与预置副本一致）/ `diverged`（已安装，与预置副本不同）/ `missing`（未安装）/ `conflict`（存在同名非目录项，需人工处理）；仅本地（非预置）的 Skill 单独列出。勾选后「同步所选」，或「一键同步全部待处理」；`diverged` 项覆盖前旧副本整体备份至 `skills/.preset-backups/`，确认本地定制无丢失后自行清理。

### 安装第三方 Skill

三种来源：本地 `.zip` 压缩包（≤16MiB）、本地文件夹（整目录上传）、GitHub 仓库链接。包内每个含 `SKILL.md` 的目录都会成为一个候选；安装以 frontmatter `name` 为目录名，压缩包内的原始目录名不参与校验。与现有 Skill 同名时须显式勾选覆盖安装，旧副本自动备份至 `skills/.preset-backups/`。

安装是两阶段「检查 → 确认」交互：检查阶段只读产出候选报告——`description`、文件数与体积、解析诊断、是否携带 `scripts/` 可执行脚本（含脚本时红色警示并列出脚本清单）；确认后才写入目录。检查载荷在服务端暂存 30 分钟，超时需重新检查。候选验收与运行时扫描共用同一 parser（Agent Skills 开放标准的可移植核心），通过检查的 Skill 安装后即可被运行时装载。

摄取护栏：zip 条目 ≤500、单文件 ≤1MiB、解压总量 ≤32MiB；拒绝符号链接与绝对路径条目。

GitHub 导入经 `codeload.github.com` 下载仓库 zip：仅支持公开仓库，下载硬上限 32MiB、超时 20s，部署主机需可访问 `github.com` / `codeload.github.com`。接受 `https://github.com/<owner>/<repo>`、`…/tree/<ref>` 与 `…/tree/<ref>/<子目录>` 三种链接；多 Skill 仓库（monorepo）必须用 `/tree/` 子目录链接定位单个 Skill——按整仓摄取会把仓库其余部分一并计入护栏，容易触发条目数/体积上限；`/blob/` 单文件链接不受支持。

### Web 管理面的安全边界

项目安全原则是「尽提醒义务的最高自由度」：Web 管理面把 Skill 写入与导入能力开放给全部持有管理会话的人，页面在列表「含脚本」标注、脚本编辑横幅、安装检查报告的红色警示等处尽提醒义务，但不替代人工审阅。「只放置审阅过的 Skill」这一要求不变——Skill 可携带以 bot 进程权限在部署主机执行的 `scripts/` 脚本，导入第三方 Skill 前必须逐文件审阅其内容，检查报告即审阅界面。Web 写侧与运行时共用路径加固（拒绝 `..` 穿越、绝对路径与符号链接逃逸）；运行时的脚本执行隔离、执行前复验与资源上限对在线编辑/安装的 Skill 同样生效。
