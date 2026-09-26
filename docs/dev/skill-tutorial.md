# 从零开始编写 Skill —— 以 QuickQuip 项目为例

> **面向读者：** 想给机器人扩充"领域知识包"的部署者（§1–§4，零编程门槛，只需要会编辑文本文件和复制目录），以及想给 Skill 挂脚本的开发者（§5，需要 Python 基础）。
>
> **前置要求：** §1–§4 无编程要求；§5 需要了解 Python 基础语法（函数、字典、标准库导入）。
>
> **源码指引：** Skill 系统实现位于 `src/quickquip/llm/skills/`（frontmatter 校验 `parser.py`、目录扫描与路径加固 `catalog.py`、四个工具 `tools/`），工具注册与激活门控位于 `src/quickquip/llm/service_parts/skills.py`，`/skill` 命令位于 `src/quickquip/adapters/nonebot/command_parts/skills.py`。部署与安全模型的权威文档是 [docs/admin/skills.md](../admin/skills.md)，配置键与默认值见 `config/llm.toml.example` 的 `[skills]` 段。

---

## 目录

1. [什么是 Skill？](#1-什么是-skill)
2. [规范速查](#2-规范速查)
3. [怎么用：安装、查看与激活](#3-怎么用安装查看与激活)
4. [实战一：从零写一个无脚本 Skill](#4-实战一从零写一个无脚本-skill)
5. [实战二：写一个带脚本的 Skill](#5-实战二写一个带脚本的-skill)
6. [常见问题与排障](#6-常见问题与排障)
7. [延伸阅读](#7-延伸阅读)

---

## 1. 什么是 Skill？

**Skill 是一段随机器人部署的"领域知识包"。** 部署者把一个文件夹放进 `skills/` 目录，机器人的 AI 在群聊里遇到与该 Skill 描述匹配的请求时自主激活它，然后按其中的指引查阅附带资料、回答问题，必要时运行附带脚本。典型用途：让 AI 基于内置文档副本回答机器人用法提问（`skills.example/self-docs`）、汇报部署主机健康状态（`skills.example/host-healthcheck`）。

Skill 的格式遵循 Agent Skills 开放标准的可移植核心：一个子目录 + 一份 YAML frontmatter 的 `SKILL.md`（`src/quickquip/llm/skills/parser.py`）。

它的三条设计动机：

- **部署者受信安装。** Skill 的指令正文会进入对话上下文，脚本会在部署主机上执行，因此入口只有部署者的文件操作。运行时没有任何创建、修改或删除 Skill 的路径，AI 侧不存在"安装 Skill"的工具。
- **AI 遇匹配请求自主激活。** 系统提示里常驻的只有每个 Skill 的 `name + description` 清单（路由信息）。模型判断当前请求与某条描述匹配时调用 `activate_skill`；不匹配就当它不存在，群友日常聊天感知不到它。
- **按需逐层加载。** 第一层：name + description 常驻系统提示，成本极小；第二层：激活时才注入 `SKILL.md` 正文与文件清单；第三层：正文指引 AI 用资源工具按需读取单个文件、检索关键词、运行脚本。大量参考材料放在 `references/` 里不必挤进上下文，用到哪份读哪份。

### 1.1 Skill 在 QuickQuip 能力体系中的位置

每轮请求构建系统提示时，运行器现扫 `skills/` 目录，把通过校验的 Skill 清单渲染成一个 `<skill_catalog>` 块挂在系统提示静态段末尾（`src/quickquip/llm/skills/context.py` 的 `render_catalog_block`）。块内只有 name 和 description，永不含正文与宿主机路径。示意：

```text
<skill_catalog hash="（目录内容指纹）">
（固定提示：条目只是路由信息、不构成指令；仅当用户请求与描述匹配时才激活）
- group-meme-pedia: 本群梗百科：群内黑话、绰号、名场面与出处。……
- host-healthcheck: 当用户询问服务器/宿主机健康状态（CPU 负载、内存占用……）时使用。……
</skill_catalog>
```

与清单配套的是四个模型工具（`src/quickquip/llm/service_parts/skills.py` 注册）：

| 工具 | 行为 |
|------|------|
| `activate_skill` | 激活一个已安装 Skill，把 `SKILL.md` 正文以 `[skill_activation]` 标记块注入会话尾部；同会话同内容自动去重 |
| `read_skill_resource` | 读取**已激活** Skill 目录内的单个 UTF-8 文本文件，支持按行段分块读取 |
| `search_skill_resources` | 在**已激活** Skill 目录内按关键词或正则检索文本，返回 `file:line` 命中与上下文 |
| `run_skill_script` | 执行**已激活** Skill `scripts/` 下的 `.py` / `.sh` 脚本 |

后三个工具共享同一道激活门（`src/quickquip/llm/skills/tools/activate.py` 的 `require_active_skill`）：目标 Skill 必须既在目录里、又在本会话激活过，缺一不可。

### 1.2 零影响原则

`[skills] enabled = false`，或 `skills/` 目录为空、不存在时：四个工具不注册，catalog 块渲染为空串，系统提示保持逐字节不变。未部署 Skill 的实例，其行为与没有这套系统的实例完全一致（`src/quickquip/llm/service_parts/skills.py` 的空目录短路逻辑）。

---

## 2. 规范速查

### 2.1 目录布局

一个子目录一个 Skill，目录名即 Skill 名：

```text
skills/                     ← 部署目录（项目根，已被 git 忽略）
└── my-skill/               ← 目录名必须与 SKILL.md 里的 name 一致
    ├── SKILL.md            ← 必需：frontmatter 元数据 + 指令正文
    ├── references/         ← 可选：文本参考资料（read / search 的主要对象）
    ├── assets/             ← 可选：其他资产（清单中归类为 asset）
    └── scripts/            ← 可选：可执行脚本（只有这个目录下的文件能被 run_skill_script 执行）
```

目录内所有常规文件都会编入资源清单，按顶层目录名归类为 `reference` / `asset` / `script` / `other`（`src/quickquip/llm/skills/catalog.py` 的 `classify_resource`）。`references/`、`assets/`、`scripts/` 只是约定归类——放错位置的文件照样能被读取检索，但 `scripts/` 之外的一切都不可执行。

### 2.2 SKILL.md 校验规则

`SKILL.md` 必须以一行 `---` 开头，中间是 YAML frontmatter，再以单独一行 `---` 收尾，随后是指令正文。校验规则（全部落在 `src/quickquip/llm/skills/parser.py`）：

| 校验项 | 规则 | 失败后果 |
|--------|------|---------|
| 文件大小 | ≤ 256KiB（262144 字节） | 整个 Skill 被跳过，记 WARNING |
| 编码 | UTF-8（允许 BOM，读取时剥掉） | 整个 Skill 被跳过 |
| 文件形态 | 常规文件，符号链接被拒绝 | 整个 Skill 被跳过 |
| `name` | 必填；1–64 字符；匹配 `^[a-z0-9][a-z0-9-]*$`（小写字母、数字、连字符，以字母或数字开头）；必须与所在目录名一致 | 整个 Skill 被跳过 |
| `description` | 必填非空；≤ 1024 字符 | 整个 Skill 被跳过 |
| 可选字段 | `license`、`compatibility`（字符串）、`metadata`（字符串到标量的映射）正常解析；`allowed-tools` 仅作兼容性解析、运行时忽略；其余未识别字段留名忽略并记诊断 | 诊断随激活块披露，不影响装载 |

单个坏 Skill 会被跳过并记一条 `跳过无效 skill <name> [<原因>]` 告警，同目录其他 Skill 照常工作。

### 2.3 数值上限一览

| 项 | 默认值 | 配置键（`config/llm.toml` `[skills]`） |
|----|--------|------|
| 系统提示清单字节预算 | 8192 字节；实际预算取 min(模型上下文窗口 2%，此值) | `catalog_max_bytes` |
| 单次读取资源 | 65536 字节（64KiB），超限截断前段 | `resource_max_bytes` |
| 检索命中条数 | 50 条 | `search_max_results` |
| 检索输出体积 | 32768 字节 | `search_max_output_bytes` |
| 脚本默认超时 | 30000ms；单次调用可覆盖，硬上限 120000ms | `script_timeout_ms` |
| 脚本输出 | stdout / stderr 各 65536 字节，超限截断并终止脚本 | `script_max_output_bytes` |

代码内固定的硬限额：每个 Skill 资源条数 ≤ 200（超出部分不编入清单）；检索单文件只读前 1MiB；检索词 ≤ 200 字符；`SKILL.md` ≤ 256KiB、`description` ≤ 1024 字符（`src/quickquip/llm/skills/catalog.py`、`tools/search_resource.py`）。

清单预算超限时的降级序（`src/quickquip/llm/skills/catalog.py` 的 `_apply_budget`）：先把所有 description 统一截短到 160 字符，仍超再截到 80 字符，仍超则按 name 字典序保前弃后淘汰整条（被淘汰者当轮不可激活），永不淘汰到空。系统提示中会注明"另有 N 个 Skill 因目录预算超限未列出"。

---

## 3. 怎么用：安装、查看与激活

### 3.1 安装

运行目录为项目根的 `skills/`（已被 git 忽略）；仓库随附的 `skills.example/` 是官方模板。安装就是文件操作：

```bash
# 从官方模板复制（在项目根执行）
cp -r skills.example/self-docs skills/          # 装一个
cp -r skills.example/. skills/                  # 全装

# 或自建目录
mkdir -p skills/group-meme-pedia/references
```

目录在每轮构建系统提示时现扫一次，**无需重启**：放入或删掉 Skill 后，进行中会话的下一轮请求即可看到变化。Docker 镜像只含 `skills.example/`，容器化部署经 compose 挂载供给 `skills/`，方式见 `prod.example/` 模板与 [docs/admin/skills.md](../admin/skills.md)。配置键 `catalog_dir` 可把目录指到别处：留空 = 项目根 `skills/`，相对路径按项目根解析。

### 3.2 用 `/skill list` 查看

群里发送 `/skill list` 可查看已安装 Skill 与当前会话已激活项（只读）。输出形如（`src/quickquip/llm/skills/context.py` 的 `render_skill_list`）：

```text
已安装 Skill（2）：
- group-meme-pedia：本群梗百科：群内黑话、绰号、名场面与出处。……
- host-healthcheck：当用户询问服务器/宿主机健康状态……时使用。……
当前会话已激活：（无）
```

`/skill` 只有 `list` 一个子参数，其他写法会收到用法提示。`[skills] enabled = false` 时该命令直接提示功能未启用。

### 3.3 激活机制

一次完整的激活使用流程：

```text
群友提问"服务器还活着吗"
      │
      ▼
系统提示里的 <skill_catalog> 清单：host-healthcheck 的描述与问题匹配
      │
      ▼
模型调用 activate_skill(name="host-healthcheck")
      │
      ▼
[skill_activation name="…" hash="…" status="activated"] 标记块
（SKILL.md 正文 + 附带文件清单）注入会话尾部
      │
      ▼
模型按正文指引调用 read_skill_resource / search_skill_resources / run_skill_script
      │
      ▼
模型汇总工具结果，转述给群友
```

几个要点：

- `activate_skill` 的 `name` 参数枚举值就是当轮目录名单，模型编不出未安装的名字。
- 同一会话内重复激活同一 Skill：正文内容未变时只返回"已激活"简短文本，不重复注入；部署者改了 `SKILL.md`，下一轮扫描指纹变化，再激活会注入新正文。
- 激活登记是纯进程内存、按会话（scope）隔离，重启即清空——无所谓，模型需要时会重新激活。
- 激活是纯上下文注入：Skill 指令从属于机器人规则、当前人格与用户的明确请求，不能新增工具或改变权限。

### 3.4 敏感词扫描对 Skill 的影响

Skill 相关的全部模型可见产出与 `search_web` 等外部工具走同一敏感词扫描接缝（详见 [docs/admin/sensitive-filter.md](../admin/sensitive-filter.md)）。对 Skill 的两层影响：

- **描述静态拦截**：description 会进入系统提示静态段（对全群可见），命中拦截词的 Skill 会被整只从清单剔除并记告警日志（`跳过 skill <name> [description-blocked]`），既不出现在系统提示里，也无法激活。
- **激活正文预扫**：激活时注入的正文若命中拦截词，会被输出管道整段替换；此时系统不留激活登记，部署者修正 `SKILL.md` 措辞后模型重试即可拿到新正文。

写 Skill 时避开拦截词表里的词汇，是最省事的预处理。

---

## 4. 实战一：从零写一个无脚本 Skill

目标：写一个"本群梗百科"——群友问"某个梗/绰号是什么意思"时，AI 查内置词条作答。全程只需要编辑 Markdown 文件。以下示例中的群友昵称、梗出处均为虚构占位，请替换成你自己群里的内容（注意不要写入真实 QQ 号等隐私信息）。

### 4.1 第一步：想清楚触发条件

`description` 是 AI 决定何时激活的唯一依据。动笔前先回答两个问题：

1. **什么请求该触发它？**——"XX 是什么梗""某某绰号指谁""这个名场面哪来的"。
2. **回答纪律是什么？**——以词条为准，查不到就如实说没收录。

把这两个答案写进 description，激活命中率会高很多。

### 4.2 第二步：建目录

在项目根执行：

```bash
mkdir -p skills/group-meme-pedia/references
```

目录名 `group-meme-pedia` 满足命名规则（小写字母 + 连字符，与 frontmatter 的 `name` 一致）。

### 4.3 第三步：写 SKILL.md

创建 `skills/group-meme-pedia/SKILL.md`，完整内容如下（可直接复制后修改）：

```markdown
---
name: group-meme-pedia
description: 本群梗百科：群内黑话、绰号、名场面与出处。当用户询问某个群内梗或黑话是什么意思、某个绰号指谁、某句名场面的来历，或想了解本群文化时使用。回答以 references/ 下的词条为准，词条未收录的梗如实说明，不要编造出处。
---

# 本群梗百科

你在回答群友关于本群黑话与梗的问题。全部词条在 references/ 下，按需查阅。

## 工作方式

1. 判断问题类型：词语与梗查 references/memes.md，人物绰号查 references/people.md。
2. 文件不大时直接用 read_skill_resource（skill="group-meme-pedia"）整读；
   记不准在哪时先用 search_skill_resources 按关键词定位。
3. 词条间有"参见"引用时，继续查被引用的文件。
4. 转述时带上词条"起源"字段里的首次出现时间，让新群友也能看懂。
5. 词条未收录的梗，如实回复"百科还没收录"，可请群友找管理员补充词条。

## 分寸提醒

玩梗以词条记载为准，不对词条之外的真人真事做调侃。
```

要点：frontmatter 两个必填字段一个都不能少；正文写给 AI 看，用编号步骤交代工作流程；长篇材料全部外置到 `references/`，`SKILL.md` 只留路由和纪律——正文在激活时会整体进入上下文，保持精炼就是控制成本。

### 4.4 第四步：放参考资料

创建 `skills/group-meme-pedia/references/memes.md`：

```markdown
# 梗词条

## 红温
- 起源：2026-03，某晚连败语音局后群友"北辰"的语音转写名场面。
- 释义：形容人急躁上头、面红耳赤的状态。用法："别说了，他要红温了"。
- 参见：people.md 的"北辰"。

## 赛博灯泡
- 起源：2026-05，群里流行把群公告改成灯泡字符画。
- 释义：指在群里发无关字符画打断话题的行为。
```

创建 `skills/group-meme-pedia/references/people.md`：

```markdown
# 人物绰号表

## 阿柴
- 本群常驻群友，机械键盘爱好者；绰号来自其头像里的柴犬。
- 相关键词：键盘、柴犬。

## 北辰
- 固定车队队长，"红温"名场面的当事人。
- 相关键词：红温、语音局。
```

### 4.5 第五步：部署与验证

文件放好后即为部署完成，无需重启。验证两件事：

```bash
# 1. 目录结构（在项目根执行）
ls -R skills/group-meme-pedia
# skills/group-meme-pedia:
# references  SKILL.md
# skills/group-meme-pedia/references:
# memes.md  people.md
```

2. 群里发送 `/skill list`，应看到：

```text
已安装 Skill（1）：
- group-meme-pedia：本群梗百科：群内黑话、绰号、名场面与出处。……
当前会话已激活：（无）
```

清单里没有它，就对照 §2.2 逐项检查（最常见：frontmatter 的 `name` 与目录名写得不一致），并看日志里的 `跳过无效 skill` 告警。

### 4.6 第六步：群里试用

在群里这样问（措辞贴近 description 的触发条件即可）：

```text
@bot 群里说的"红温"是什么梗？
```

预期过程：AI 匹配描述 → 激活 `group-meme-pedia`（正文与文件清单注入）→ 检索"红温"命中 `references/memes.md:3` → 读词条 → 按正文纪律带起源时间作答。激活是模型语义判断，问法太绕可能不触发，把 description 的触发条件写具体就是提高命中率的手段。

---

## 5. 实战二：写一个带脚本的 Skill

前半篇的 Skill 只有静态资料；想让 AI 拿到**实时数据**（宿主机指标、外部状态），就给它配 `scripts/` 脚本。这半篇面向开发者，以官方 `host-healthcheck` 为例拆解脚本契约与沙箱。

### 5.1 脚本契约

`run_skill_script` 的执行形态（`src/quickquip/llm/skills/tools/run_script.py`）：

- **输入**：模型传入的 `args` 字符串数组，逐字传给脚本（不经 shell 解释），不能含 NUL 字节。运行器只为 stdout/stderr 建立管道，没有为 stdin 建立输入通道——脚本不要指望从标准输入读到模型数据，模型侧的一切输入只有 `args`。
- **输出**：stdout 是给模型看的主通道；stderr 同样会被收集展示，适合放人类可读的告警。两者各受 `script_max_output_bytes`（默认 65536 字节）上限约束，超限即终止脚本并截断。
- **退出码**：0 = 成功；非 0 或超时按错误处理。工具结果带固定包装：

```text
[skill_script name="host-healthcheck" path="scripts/collect.py" interpreter="python3"]

stdout:
{ ...JSON... }

stderr: (empty)

退出码：0
```

- **解释器**：按扩展名映射——`.py` 用 `python3`（PATH 上找不到时回退当前解释器），`.sh` 用 `sh`；不依赖 shebang 与执行位。主机 PATH 上没有 `sh` 时 `.sh` 直接拒绝执行，Windows 主机请写 `.py`。

### 5.2 沙箱约束

脚本在部署主机上真实执行，运行器加上了一组结构性约束：

| 约束 | 内容 |
|------|------|
| 无 shell | 脚本经结构化 argv 直接启动，参数逐字传递，没有解释层 |
| 最小环境 | 子进程环境白名单仅 `PATH` / `LANG` / `TZ`，bot 进程其余环境变量（含 `.env` 凭证）一律不继承——脚本读不到自定义环境变量，配置要么走 `args`，要么写在脚本默认值里 |
| 固定工作目录 | cwd 固定为该 Skill 目录，脚本内访问文件以该目录为基准 |
| 墙钟超时 | 默认 `script_timeout_ms`（30000ms），单次调用可指定 `timeout_ms`，硬上限 120000ms；超时按进程组 SIGKILL 整组清理 |
| 执行前复验 | 执行前对脚本做 SHA-256 快照比对，目录扫描之后内容有变化即拒绝执行（防扫描与执行之间被替换） |
| 路径限制 | 只能执行 `scripts/` 下的常规文件；`..` 穿越、绝对路径、符号链接逃逸一律拒绝 |

另有纪律层面的要求（写在 [docs/admin/skills.md](../admin/skills.md)）：`run_skill_script` 只用于执行 Skill 自带、服务于该 Skill 用途的脚本，`SKILL.md` 里不要指引 AI 借它跑 grep/find 等通用命令——目录内检索已由 `search_skill_resources` 覆盖。

### 5.3 逐步拆解 host-healthcheck

`skills.example/host-healthcheck/` 只有两个文件：`SKILL.md` 和 `scripts/collect.py`。

**SKILL.md 侧**（摘自正文"工作方式"）：

```markdown
1. 用 `run_skill_script` 执行 `scripts/collect.py`，无需 `args`。
2. 首次执行前可用 `read_skill_resource` 查看脚本源码确认行为。
3. stdout 是单个 JSON 文档，解析后按本手册转述；不要把整段 JSON 原样贴给用户。
```

SKILL.md 承担"输出契约 + 转述纪律"：告诉模型输出长什么样（顶层字段、指标组、来源视图）、哪些数字该怎么解读、什么必须如实说明。模型只做转述员，脚本只做采集器，职责干净分开。

**collect.py 侧**（`skills.example/host-healthcheck/scripts/collect.py`）是纯 Python 3 标准库的只读探测，一秒内完成。主函数：

```python
def main() -> int:
    report = build_report(**resolve_config(os.environ))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0
```

四个值得学的决定：

1. **stdout 输出单个 JSON 文档**：结构化数据模型解析可靠、体积可控（远低于 64KiB 上限），比自然语言文本稳。
2. **退出码恒为 0**：文件缺失、平台不适配等"数据拿不到"的情况，编码成对应指标组的 `status: "unavailable"`，让模型照常读取并如实转述；脚本自身只在程序性错误时才非 0 退出。每个采集函数都是这个模式：

```python
def _collect_load(proc_root: Path) -> dict:
    source = proc_root / "loadavg"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "loadavg 不可读")
    ...
```

3. **只用标准库**（`json` / `os` / `shutil` / `pathlib` …）：部署环境不保证第三方包，可移植性靠零依赖达成。
4. **快进快出**：全部探测是几次文件读取，秒级完成，离默认 30s 超时很远；也不起子进程、不写任何文件。

另外注意它对沙箱的适配：`resolve_config` 从环境变量读探测根的覆盖项（`QQ_HC_*`），但沙箱白名单只放行 `PATH` / `LANG` / `TZ`，所以实际运行永远走脚本内默认值（`/proc`、`/sys/fs/cgroup` 等）——默认值即生产值的设计让同一份脚本在沙箱内外行为一致。

### 5.4 写脚本 Skill 的检查清单

动手写自己的脚本 Skill 时，逐条对照：

1. 纯标准库，零第三方依赖。
2. 只读、无副作用、可重复执行。
3. 快：目标秒级完成，给 `script_timeout_ms` 留一个数量级的余量。
4. stdout 输出紧凑的机器可读文本（推荐 JSON），总量控制在 64KiB 内。
5. "数据缺失"编码进输出内容，退出码 0 只留给程序性成功；崩溃信息走 stderr。
6. 不依赖沙箱外的环境变量；需要参数就约定 `args` 并写进 SKILL.md。
7. 路径以 Skill 目录（cwd）为基准计算。
8. SKILL.md 里写清输出契约（字段语义）与转述纪律（哪些必须如实说明）。

---

## 6. 常见问题与排障

| 症状 | 常见原因 | 处置 |
|------|---------|------|
| `/skill list` 里没有新 Skill | name 校验失败（正则、超 64 字符、与目录名不一致）；description 缺失或超 1024 字符；缺 frontmatter 围栏；文件超 256KiB；非 UTF-8；SKILL.md 是符号链接 | 对照 §2.2 逐项检查；日志里搜 `跳过无效 skill`，告警带具体原因 |
| 描述没问题，AI 从不激活 | description 没写清触发条件；或命中敏感词被整只剔除（日志 `[description-blocked]`） | 把触发条件写具体（"当用户询问……时使用"）；对照敏感词表改措辞 |
| 激活了但正文没出现 | 注入正文命中拦截词，被输出管道整段替换 | 修正 SKILL.md 措辞；系统未留登记，直接重试即可 |
| 脚本被终止："脚本运行超过 N ms" | 超过超时上限（默认 30s，硬上限 120s） | 精简脚本耗时；必要时调大 `script_timeout_ms` |
| 脚本结果带"[输出超过 N 字节上限，已截断]" | stdout 或 stderr 超过 65536 字节 | 输出汇总数字，避免全量明细；必要时分多次运行 |
| 脚本拒绝执行："内容在目录扫描后已变化" | 扫描之后改过脚本文件，SHA-256 复验失败 | 等下一轮请求重新扫描后再试 |
| 检索报错"正则形态不被允许" | 查询含嵌套量词或交叠分支的量化组等病态形态（防灾难性回溯的静态检查） | 改用字面搜索（`is_regex=false`）或改写正则 |
| 系统提示注明"因目录预算超限未列出" | Skill 总量超过 min(上下文窗口 2%, `catalog_max_bytes`) | 精简各 description、减少 Skill 数量，或调大 `catalog_max_bytes` |
| 读取报错"不是有效 UTF-8 文本" | 该文件是二进制 | 二进制资产放 `assets/`（激活时的资源清单会披露），文本资料放 `references/` |
| 资源清单不完整 | 单 Skill 文件数超过 200 条上限，超出部分不编入清单 | 精简文件数量或合并资料 |

通用排查入口：`/skill list`（装载面）、日志 WARNING（`跳过无效 skill` / `description-blocked` / `skill catalog 超过 … 字节预算`）、`config/llm.toml` 的 `[skills]` 段（上限面）。

---

## 7. 延伸阅读

- [docs/admin/skills.md](../admin/skills.md)：Skill 系统的部署方式与安全模型（部署者视角的权威文档）。
- [docs/dev/llm-module.md](llm-module.md)：LLM 模块运行时架构（工具注册、系统提示构建、工具调用循环）。
- `config/llm.toml.example` 的 `[skills]` 段：全部配置键与默认值的带注释参考。
- `skills.example/`：两个官方 Skill——`self-docs`（无脚本、纯 references 路由检索的范本）与 `host-healthcheck`（带脚本、输出契约与转述纪律的范本）。

---

> **文档信息**
>
> - 本文档基于 QuickQuip 项目编写，规范与数值以 `src/quickquip/llm/skills/` 现行实现为准
> - 示例中的群友昵称、梗出处均为虚构占位
> - 最后更新：2026-09-19
