<!-- Generated from docs/admin/skills.md; do not edit -->

# Skill 系统（skills/）

本文面向部署者和管理员，说明 Skill 系统的部署方式与安全约束。

Skill 是受信任的部署资产：部署者把技能包放进 `skills/` 目录，AI 在对话中按描述匹配自行激活使用。每个技能是一个子目录，内含 `SKILL.md`（frontmatter 元数据 + 指令正文）、可选的 `references/`（参考资料）和 `scripts/`（可执行脚本）。典型用途：让 AI 基于内置文档副本回答机器人用法提问、汇报部署主机健康状态。

## 部署目录

运行目录为项目根的 `skills/`（已被 git 忽略），仓库随附的 `skills.example/` 承载官方预置 Skill 模板。部署照 `config/personas.example/` → `config/personas/` 的同一先例：从 `skills.example/` 复制或合并需要的 Skill 到 `skills/`，再按环境调整；Windows 懒人包首启（`start.bat`）会自动完成整目录复制。Docker 镜像与 Windows 懒人包均只携带 `skills.example/`；容器化部署的目录供给方式见 `prod.example/` 模板。

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

Skill 的增删就是部署侧的文件操作：目录在每次构建系统提示时重新扫描（每轮请求一次），无需重启，进行中的会话下一轮请求即可看到增删；catalog 块字节变化只影响当轮的前缀缓存命中。运行时没有任何安装、更新或删除 Skill 的路径。

群内 `/skill list` 可查看已安装 Skill 与当前会话已激活项（只读）。

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

- **无运行时变更路径**：AI 侧没有任何创建、修改或删除 Skill 文件的工具，Skill 内容只能经部署者文件操作变更。
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
