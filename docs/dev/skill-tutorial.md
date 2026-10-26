# 从零开始编写 Skill —— 以 QuickQuip 项目为例

本教程帮助部署者安装和编写 Skill，为机器人补充领域知识。§1–§4 只需要编辑文本文件和复制目录；§5 面向希望附带脚本的开发者，需要了解 Python 函数、字典和标准库。

开始前，请确认 Bot 正在运行且已能进行 AI 对话，Web 管理后台已启动并可登录，你能写入 Bot 使用的 Skill 目录。部署、启用与安全要求见 [Skill 部署说明](../admin/skills.md)。本文的复制命令使用 Bash，按 §3.1 确定执行目录；Windows 部署者可用文件管理器完成同样的目录创建和复制。实现入口列在文末。

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

**Skill 是随机器人部署的“领域知识包”。** 部署者把一个文件夹放进 `skills/` 目录，机器人的 AI 在群聊里遇到与该 Skill 描述匹配的请求时自主激活它，然后按其中的指引查阅附带资料、回答问题，必要时运行附带脚本。典型用途：让 AI 基于内置文档副本回答机器人用法提问（`skills.example/self-docs`）、汇报部署主机健康状态（`skills.example/host-healthcheck`）。

每个 Skill 占一个子目录，核心文件是 `SKILL.md`：开头用 YAML frontmatter 记录名称和描述，后面用 Markdown 编写指令。

编写时需要理解三个原则：

- **部署者受信安装。** Skill 的指令正文会进入对话上下文，脚本会在部署主机上执行，因此由部署者通过部署机器或管理后台安装、更新和删除。
- **AI 遇匹配请求自主激活。** 系统提示里常驻的只有每个 Skill 的 `name + description` 清单（路由信息）。模型判断当前请求与某条描述匹配时调用 `activate_skill`；其他请求按常规对话处理。
- **按需逐层加载。** 第一层：name + description 常驻系统提示，成本极小；第二层：激活时才注入 `SKILL.md` 正文与文件清单；第三层：正文指引 AI 用资源工具按需读取单个文件、检索关键词、运行脚本。大量参考材料放在 `references/` 里不必挤进上下文，用到哪份读哪份。

### 1.1 Skill 在 QuickQuip 能力体系中的位置

开启工具调用和 Skill 后，机器人每轮扫描 `skills/`，将通过校验的名称与描述写入系统提示的 `<skill_catalog>` 清单。模型用这份简短清单选择要激活的 Skill，激活时再加载正文。示意：

```text
<skill_catalog hash="（目录内容指纹）">
（固定提示：条目只是路由信息、不构成指令；仅当用户请求与描述匹配时才激活）
- group-meme-pedia: 本群梗百科：群内黑话、绰号、名场面与出处。……
- host-healthcheck: 当用户询问服务器/宿主机健康状态（CPU 负载、内存占用……）时使用。……
</skill_catalog>
```

AI 使用四个工具完成激活与资料访问。下面的工具名称用于编写 Skill 指引；群友向机器人发送自然语言问题即可。

| 工具 | 输入与结果 |
|------|------|
| `activate_skill` | `name` 填已安装的 Skill 名；返回其指令正文，同会话同内容自动去重 |
| `read_skill_resource` | `skill` 填已激活的 Skill 名，`path` 填包内路径（如 `references/memes.md`）；返回 UTF-8 文本，支持按行段读取 |
| `search_skill_resources` | `skill` 填已激活的 Skill 名，`query` 填关键词或正则；返回文件路径、行号和命中上下文 |
| `run_skill_script` | `skill` 填已激活的 Skill 名，`path` 填 `scripts/` 下的 `.py` / `.sh` 文件；可选 `args` 传参数，返回输出、错误信息和退出码 |

读取、检索和执行前，目标 Skill 必须已安装，并在当前会话中激活。

### 1.2 启用条件

工具调用与 Skill 均开启、且目录内有可用 Skill 时，模型才能看到清单与 Skill 工具。启用步骤见 §3.2。

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

附带常规文件按所在目录归为参考资料、资产、脚本或其他资源。读取和检索工具可以访问这些文本文件；执行工具接受 `scripts/` 中的 `.py` 和 `.sh` 文件。资源数量上限见 §2.3。

### 2.2 SKILL.md 校验规则

`SKILL.md` 必须以一行 `---` 开头，中间是 YAML frontmatter，再以单独一行 `---` 收尾，随后是指令正文。校验规则如下：

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

| 项 | 默认值 | 配置键（`config/managed/config.db` `settings.skills`） |
|----|--------|------|
| 系统提示清单字节预算 | 8192 字节；实际预算取 min(模型上下文窗口 2%，此值) | `catalog_max_bytes` |
| 单次读取资源 | 65536 字节（64KiB），超限截断前段 | `resource_max_bytes` |
| 检索命中条数 | 50 条 | `search_max_results` |
| 检索输出体积 | 32768 字节 | `search_max_output_bytes` |
| 脚本默认超时 | 30000ms；单次调用可覆盖，硬上限 120000ms | `script_timeout_ms` |
| 脚本输出 | stdout / stderr 各 65536 字节，超限截断并终止脚本 | `script_max_output_bytes` |

代码内固定的硬限额：每个 Skill 资源条数 ≤ 200（超出部分不编入清单）；检索单文件只读前 1MiB；检索词 ≤ 200 字符；`SKILL.md` ≤ 256KiB、`description` ≤ 1024 字符。

清单超过预算时，机器人依次把描述截短到 160 字符、80 字符，再按名称字典序移除靠后的条目，至少保留一个。被移除的条目当轮无法激活，系统提示会注明“另有 N 个 Skill 因目录预算超限未列出”。

---

## 3. 怎么用：安装、查看与激活

### 3.1 安装

先确认文件要放在哪台机器、哪个目录。在 Web 管理后台打开“LLM 工坊 → LLM 配置 → 工具与技能 → Skill 运行时”，查看“Skill 目录”：留空时使用 Bot 项目根的 `skills/`；非空时使用指定目录，相对路径以 Bot 项目根为基准。远程部署应把文件放到运行 Bot 的服务器。

版本目录部署使用部署根共享的 `skills/`，与 `current` 指向的代码目录分开。容器部署先确认 Bot 和 Web Admin 已挂载同一份 `skills/`；主机目录与容器目录的对应关系见 [Skill 部署说明](../admin/skills.md#部署目录)。下文以默认目录为例，自定义目录时替换命令的目标路径。

仓库随附的 `skills.example/` 是官方模板。源码部署在项目根执行以下 Bash 命令，先安装一个无脚本预置包。版本目录部署在部署根操作，将下文复制命令的来源 `skills.example/` 换为 `current/skills.example/`，目标仍是共享 `skills/`；例如 `cp -r current/skills.example/self-docs skills/`。

```bash
mkdir -p skills
cp -r skills.example/self-docs skills/
```

Windows 用文件管理器在目标位置新建 `skills` 文件夹，把 `skills.example` 里的整个 `self-docs` 文件夹复制进去，形成 `skills/self-docs/SKILL.md`。已安装同名包时跳过复制，更新方式见管理员文档“预置 Skill”节。

也可选择一次安装全部官方包：将上面的单包复制命令换为 `cp -r skills.example/. skills/`，或用文件管理器复制其中的两个子文件夹；两种安装方式任选一种。目录在每轮构建系统提示时现扫一次，放入文件后下一轮请求即可看到变化。

### 3.2 用 `/skill list` 查看

在 Web 管理后台按以下步骤启用：

1. 打开“LLM 工坊 → LLM 配置 → 工具与技能 → 工具与搜索”，在“工具调用轮次与上限”开启“启用工具调用”。
2. 切到“Skill 运行时”，开启“启用 Skill”，确认“Skill 目录”与 §3.1 一致。
3. 默认空工具名单可保持原样。若“工具与搜索 → 内置工具白名单与发现”已有非空“额外启用工具”且“启用方式”为“替换”，将 §1.1 的四个 Skill 工具名加入现有名单，保留其他需要的工具。
4. 点击“保存草稿”，再点击“应用到 Bot”，等待状态条显示 Bot 已加载刚应用的版本。停在排队状态时，先确认 Bot 进程正在运行。

完整配置要求见[Skill 部署说明](../admin/skills.md#配置settingsskills)。

群里发送 `/skill list` 可查看已安装 Skill 与当前会话已激活项（只读）。仅安装 `self-docs` 时输出形如：

```text
已安装 Skill（1）：
- self-docs：当用户询问 QuickQuip 机器人的用法、命令、配置或报错时使用。……
当前会话已激活：（无）
```

安装数量取决于目录已有内容。再发送 `/ai 你的 /quote 命令怎么用？`，应收到基于文档的用法说明；再次发送 `/skill list`，查看当前会话已激活项中是否出现 `self-docs`。本文使用默认 `/ai` 前缀；已修改前缀的部署使用自己的前缀。AI 对话会请求已配置的模型，费用按渠道计费。

与当前版本预置副本（`skills.example/`）字节级分叉的已安装条目会附带标注“（与当前版本预置不同，可运行 scripts/maintenance/sync_preset_skills.py 更新）”，提示部署者同步预置更新，见 [docs/admin/skills.md](../admin/skills.md) 的“预置 Skill”节。

`/skill` 只有 `list` 一个子参数，其他写法会收到用法提示。`settings.skills.enabled = false` 时该命令直接提示功能未启用。

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

- `activate_skill` 接受当轮目录名单内的 Skill 名称。
- 同一会话内重复激活同一 Skill：正文内容未变时只返回“已激活”简短文本，不重复注入；部署者改了 `SKILL.md`，下一轮扫描指纹变化，再激活会注入新正文。
- 激活状态按会话分别记录在进程内存中。重启后，模型在需要时重新激活。
- 激活是纯上下文注入：Skill 指令从属于机器人规则、当前人格与用户的明确请求，不能新增工具或改变权限。

### 3.4 敏感词扫描对 Skill 的影响

Skill 工具结果会经过与其他外部工具相同的敏感词扫描（详见 [docs/admin/sensitive-filter.md](../admin/sensitive-filter.md)）。对 Skill 的两层影响：

- **描述静态拦截**：description 会进入系统提示静态段（供模型选择 Skill），命中拦截词的 Skill 会从清单剔除并记告警日志（`跳过 skill <name> [description-blocked]`），既不出现在系统提示里，也无法激活。
- **激活正文预扫**：激活时注入的正文若命中拦截词，会被输出管道整段替换；此时系统不留激活登记，部署者修正 `SKILL.md` 措辞后模型重试即可拿到新正文。

写 Skill 时避开拦截词表里的词汇，是最省事的预处理。

---

## 4. 实战一：从零写一个无脚本 Skill

目标：写一个“本群梗百科”——群友问“某个梗/绰号是什么意思”时，AI 查内置词条作答。全程只需要编辑 Markdown 文件。以下示例中的群友昵称、梗出处均为虚构占位，请替换成你自己群里的内容；公开分享示例时使用合成昵称与标识。

### 4.1 第一步：想清楚触发条件

`description` 帮助 AI 判断 Skill 适合哪些请求。动笔前先回答两个问题：

1. **什么请求该触发它？**——“XX 是什么梗”“某某绰号指谁”“这个名场面哪来的”。
2. **回答纪律是什么？**——以词条为准，查不到就如实说没收录。

把这两个答案写进 description，帮助 AI 判断何时使用。

### 4.2 第二步：建目录

在 §3.1 确定的目录执行；Windows 在已有 `skills` 文件夹中依次新建 `group-meme-pedia`、`references` 文件夹：

```bash
mkdir -p skills/group-meme-pedia/references
```

目录名 `group-meme-pedia` 满足命名规则（小写字母 + 连字符，与 frontmatter 的 `name` 一致）。

### 4.3 第三步：写 SKILL.md

用纯文本编辑器（如记事本或 VS Code）创建 `skills/group-meme-pedia/SKILL.md`。复制下面代码块内部的完整内容，文件第一行是 `---`；网页上的代码块标记无需复制。Windows 记事本“另存为”时选择“所有文件”、UTF-8 编码，并在文件管理器开启“文件扩展名”，确认文件名为 `SKILL.md`，避免保存成 `SKILL.md.txt`。后面的两个参考文件用同样方式保存。

```markdown
---
name: group-meme-pedia
description: 本群梗百科：群内黑话、绰号、名场面与出处。当用户询问某个群内梗或黑话是什么意思、某个绰号指谁、某句名场面的来历，或想了解本群文化时使用。回答以 references/ 下的词条为准，词条未收录的梗如实说明，不要编造出处。
---

# 本群梗百科

你在回答群友关于本群黑话与梗的问题。全部词条在 references/ 下，按需查阅。

## 工作方式

1. 判断问题类型：词语与梗查 references/memes.md，人物绰号查 references/people.md。
2. 文件不大时，用 read_skill_resource 读取上一步选定的包内路径；
   记不准在哪时先用 search_skill_resources 按关键词定位。两者的 skill 均为 group-meme-pedia。
3. 词条间有"参见"引用时，继续查被引用的文件。
4. 转述时带上词条"起源"字段里的首次出现时间，让新群友也能看懂。
5. 词条未收录的梗，如实回复"百科还没收录"，可请群友找管理员补充词条。

## 分寸提醒

玩梗以词条记载为准，不对词条之外的真人真事做调侃。
```

要点：frontmatter 填写 `name` 和 `description`；正文写给 AI 看，用编号步骤交代工作流程；长篇材料全部外置到 `references/`，`SKILL.md` 写清适用请求和工作步骤。正文在激活时会整体进入上下文，将长篇参考材料外置可以减少输入。

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

文件放好并完成 §3.2 的启用设置后，验证以下两项：

1. 在 §3.1 确定的目录查看结构（Windows 可直接在文件管理器查看）：

   ```bash
   ls -R skills/group-meme-pedia
   ```

   应包含 `SKILL.md`、`references/memes.md` 和 `references/people.md`。

2. 群里发送 `/skill list`，应看到 `group-meme-pedia`。原目录为空时，按前面的单包路径安装后此时共两项；全装官方包后则共三项。已有其他 Skill 时总数相应增加。下面只节选新条目：

```text
- group-meme-pedia：本群梗百科：群内黑话、绰号、名场面与出处。……
```

清单里没有它，就对照 §2.2 逐项检查（最常见：frontmatter 的 `name` 与目录名写得不一致），并看日志里的 `跳过无效 skill` 告警。

### 4.6 第六步：群里试用

在群里这样问（措辞贴近 description 的触发条件即可）：

```text
/ai 群里说的“红温”是什么梗？
```

也可以在 QQ 输入框中选择机器人形成真实艾特，再输入问题。预期回复会引用梗词条，说明“红温”的含义和首次出现时间（2026-03）。用 `/skill list` 确认当前会话已激活 `group-meme-pedia`。AI 根据请求含义决定是否激活；测试时可使用 description 中列出的典型问法。

---

## 5. 实战二：写一个带脚本的 Skill

想让 AI 拿到实时数据，就给 Skill 配 `scripts/` 脚本。本节先安装和运行完整官方 `host-healthcheck`，再拆解其契约，最后写一个只依赖 Python 标准库的小例子。

### 5.1 脚本契约

模型通过 `run_skill_script` 调用脚本，按以下契约交换数据：

- **输入**：模型传入的 `args` 字符串数组，逐字传给脚本（不经 shell 解释），不能含 NUL 字节。模型输入通过 `args` 传入，脚本从命令行参数读取；stdout 和 stderr 用于返回结果。
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

其中 `stdout` 是 `print` 等语句写出的正常结果，`stderr` 是错误或告警通道；退出码 `0` 表示程序正常完成。`argv` 是脚本收到的命令行参数列表，`cwd` 是执行时所在文件夹。在 Skill 工具中，`cwd` 固定为当前 Skill 的根目录。

### 5.2 执行约束

脚本在部署主机上真实执行，运行器加上了以下执行限制。脚本沿用机器人进程的主机权限，部署前由部署者审阅：

| 约束 | 内容 |
|------|------|
| 无 shell | 脚本经结构化 argv 直接启动，参数逐字传递，没有解释层 |
| 最小环境 | 子进程环境白名单仅 `PATH` / `LANG` / `TZ`，需要配置时，通过 `args` 传入或使用脚本内默认值；Bot 的其他环境变量（含 `.env` 凭证）由运行器过滤 |
| 固定工作目录 | cwd 固定为该 Skill 目录，脚本内访问文件以该目录为基准 |
| 墙钟超时 | 默认 `script_timeout_ms`（30000ms），单次调用可指定 `timeout_ms`，硬上限 120000ms；超时终止脚本，POSIX 系统同时清理其进程组，其他平台终止直接子进程 |
| 执行前复验 | 执行前对脚本做 SHA-256 快照比对，目录扫描之后内容有变化即拒绝执行（防扫描与执行之间被替换） |
| 路径限制 | 只能执行 `scripts/` 下的常规文件；`..` 穿越、绝对路径、符号链接逃逸一律拒绝 |

另有纪律层面的要求（写在 [docs/admin/skills.md](../admin/skills.md)）：`run_skill_script` 只用于执行 Skill 自带、服务于该 Skill 用途的脚本，`SKILL.md` 里不要指引 AI 借它跑 grep/find 等通用命令——目录内检索已由 `search_skill_resources` 覆盖。

### 5.3 逐步拆解 host-healthcheck

`skills.example/host-healthcheck/` 只有两个文件：`SKILL.md` 和 `scripts/collect.py`。

先复制完整目录，已全装官方包的读者可跳过此步。在 §3.1 确定的目录执行：

```bash
cp -r skills.example/host-healthcheck skills/
```

Windows 用文件管理器复制整个 `host-healthcheck` 文件夹。随后在能看到目标 `skills/` 的目录，用已有 Python 环境直接执行完整脚本：

```bash
python skills/host-healthcheck/scripts/collect.py
```

Windows 源码虚拟环境可将 `python` 换为 `.venv/Scripts/python.exe`。自定义 Skill 目录时替换脚本路径。容器部署在实际 Compose 所在目录执行下方命令；若部署时使用了 `-f` 指定文件，沿用相同选项：

```bash
docker compose exec quickquip python /app/skills/host-healthcheck/scripts/collect.py
```

预期输出是一个 JSON 文档，其中 `groups` 列出负载、内存、磁盘等指标；平台不支持的指标会标为 `unavailable`。

在群里发送 `/skill list` 确认安装，再发送 `/ai 请用 host-healthcheck 检查机器人运行环境的内存和磁盘`。应收到关键指标摘要及来源说明，已激活项中出现 `host-healthcheck`。模型执行时工具输入为 `{"skill":"host-healthcheck","path":"scripts/collect.py"}`，无需 `args`。直接执行脚本的结果来自当前终端所在环境，群里执行的结果来自 Bot 运行环境。

**SKILL.md 侧**（摘自正文“工作方式”）：

```markdown
1. 用 `run_skill_script` 执行 `scripts/collect.py`，无需 `args`。
2. 首次执行前可用 `read_skill_resource` 查看脚本源码确认行为。
3. stdout 是单个 JSON 文档，解析后按本手册转述；不要把整段 JSON 原样贴给用户。
```

SKILL.md 说明输出字段、指标含义和转述要求。脚本采集数据，模型根据这些说明向用户解释结果。

**collect.py 侧**（`skills.example/host-healthcheck/scripts/collect.py`）使用 Python 3 标准库进行只读探测。以下主函数与后面的采集函数都是原理片段；完整可执行文件来自刚复制的官方包：

```python
def main() -> int:
    report = build_report(**resolve_config(os.environ))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0
```

这个示例采用四项设计：

1. **stdout 输出单个 JSON 文档**：使用固定字段组织指标与状态，便于模型解析。
2. **用输出状态表示数据缺失**：文件缺失、平台不适配等“数据拿不到”的情况，编码成对应指标组的 `status: "unavailable"`，让模型照常读取并如实转述；脚本自身只在程序性错误时才非 0 退出。例如负载采集在读取失败时返回不可用状态：

```python
def _collect_load(proc_root: Path) -> dict:
    source = proc_root / "loadavg"
    text = _read_text(source)
    if text is None:
        return _unavailable(VIEW_HOST_PROC, source, "loadavg 不可读")
    ...
```

3. **使用标准库**（`json` / `os` / `shutil` / `pathlib` 等）：部署者可以直接运行，省去额外安装。
4. **读取后及时退出**：通过文件读取收集指标，省去子进程启动与文件写入。

在 Skill 运行器中，`resolve_config` 从环境变量读探测根的覆盖项（`QQ_HC_*`），而环境变量白名单只放行 `PATH` / `LANG` / `TZ`，因此通过 Skill 工具执行时采用脚本默认探测路径（`/proc`、`/sys/fs/cgroup` 等）。直接运行脚本时，可以用 `QQ_HC_*` 覆盖路径；结果对应所选路径的主机或容器视图。

### 5.4 写脚本 Skill 的检查清单

动手写自己的脚本 Skill 时，逐条对照：

1. 纯标准库，零第三方依赖。
2. 只读、无副作用、可重复执行。
3. 快：目标秒级完成，给 `script_timeout_ms` 留一个数量级的余量。
4. stdout 输出紧凑的机器可读文本（推荐 JSON），总量控制在 64KiB 内。
5. “数据缺失”编码进输出内容，退出码 0 只留给程序性成功；崩溃信息走 stderr。
6. 需要参数时约定 `args`，并在 SKILL.md 写清字段与默认值。
7. 路径以 Skill 目录（cwd）为基准计算。
8. SKILL.md 里写清输出契约（字段语义）与转述纪律（哪些必须如实说明）。

### 5.5 写一个完整的日期脚本 Skill

这个小例子让 AI 读取 Bot 运行环境的当天日期。按 §4 的文件保存方法，在目标 `skills/` 下创建 `calendar-today/scripts/`，再保存以下两个完整文件。

`skills/calendar-today/SKILL.md`：

```markdown
---
name: calendar-today
description: 当用户询问机器人运行环境今天的日期或星期几时使用，执行自带日期脚本后回答。
---

# 今天的日期

1. 用 run_skill_script 执行 scripts/today.py，无需 args。
2. 输出为 JSON，date 是运行环境的本地日期，weekday 是中文星期名。
3. 按结果回答日期和星期，说明采用机器人运行环境的本地时间。
```

`skills/calendar-today/scripts/today.py`：

```python
import json
from datetime import date


def main() -> None:
    today = date.today()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    print(json.dumps({"date": today.isoformat(), "weekday": weekdays[today.weekday()]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

在能看到目标 `skills/` 的目录执行 `python skills/calendar-today/scripts/today.py`，应输出当天日期和星期的 JSON；Windows 和容器执行方式沿用 §5.3，替换对应脚本路径。然后发送 `/skill list` 确认 `calendar-today` 已安装，再问 `/ai 请用 calendar-today 告诉我机器人那里今天是几号、星期几`，核对回复及已激活项。此处的小脚本可完整复制，后续修改脚本时同步更新 `SKILL.md` 的输入与输出说明。

---

## 6. 常见问题与排障

| 症状 | 常见原因 | 处置 |
|------|---------|------|
| `/skill list` 里没有新 Skill | 文件放到了其他机器或目录；误保存成 `SKILL.md.txt`；name 与目录名不一致等校验失败 | 先按 §3.1 确认运行目录与文件名，再对照 §2.2；日志里搜 `跳过无效 skill`，告警带具体原因 |
| 复制提问后机器人没有回复 | 使用了普通文字艾特；AI 前缀已自定义；基础 AI 对话尚未可用 | 使用实际配置的前缀，或在 QQ 中选择机器人形成真实艾特；先确认普通 AI 对话能回复 |
| 描述没问题，AI 从不激活 | 工具调用或 Skill 开关关闭；严格工具名单没有 Skill 工具；description 没写清触发条件；或描述命中敏感词被剔除（日志 `[description-blocked]`） | 检查 `settings.runtime.tool_calling_enabled`、`settings.skills.enabled` 与工具名单，保存应用；再核对触发条件及敏感词措辞 |
| 激活了但正文没出现 | 注入正文命中拦截词，被输出管道整段替换 | 修正 SKILL.md 措辞；系统未留登记，直接重试即可 |
| 脚本被终止：“脚本运行超过 N ms” | 超过超时上限（默认 30s，硬上限 120s） | 精简脚本耗时；必要时调大 `script_timeout_ms` |
| 脚本结果带“[输出超过 N 字节上限，已截断]” | stdout 或 stderr 超过 65536 字节 | 输出汇总数字，避免全量明细；必要时分多次运行 |
| 脚本拒绝执行：“内容在目录扫描后已变化” | 扫描之后改过脚本文件，SHA-256 复验失败 | 等下一轮请求重新扫描后再试 |
| 检索报错“正则形态不被允许” | 查询含嵌套量词或交叠分支的量化组等病态形态（防灾难性回溯的静态检查） | 改用字面搜索（`is_regex=false`）或改写正则 |
| 系统提示注明“因目录预算超限未列出” | Skill 总量超过 min(上下文窗口 2%, `catalog_max_bytes`) | 精简各 description、减少 Skill 数量，或调大 `catalog_max_bytes` |
| 读取报错“不是有效 UTF-8 文本” | 该文件是二进制 | 二进制资产放 `assets/`（激活时的资源清单会披露），文本资料放 `references/` |
| 资源清单不完整 | 单 Skill 文件数超过 200 条上限，超出部分不编入清单 | 精简文件数量或合并资料 |

排查时先用 `/skill list` 查看装载结果，再检查日志中的 WARNING。需要调整上限时，在 LLM 配置工作台编辑 `settings.skills`，保存草稿后应用。

---

## 7. 延伸阅读

| 实现职责 | 源码入口 |
|---|---|
| 元数据校验、目录扫描与预算 | `src/quickquip/llm/skills/parser.py`、`catalog.py` |
| 激活、资源读取与脚本执行 | `src/quickquip/llm/skills/tools/` |
| 工具注册、每轮清单与启用条件 | `src/quickquip/llm/service_parts/skills.py` |
| `/skill` 命令 | `src/quickquip/adapters/nonebot/command_parts/skills.py` |

- [docs/admin/skills.md](../admin/skills.md)：Skill 系统的部署方式与安全模型（部署者视角的权威文档）。
- [docs/dev/llm-module.md](llm-module.md)：LLM 模块运行时架构（工具注册、系统提示构建、工具调用循环）。
- [配置参考](../admin/configuration.md) 的 `settings.skills` 表与 metadata 接口：配置键、默认值、类型及范围。
- `skills.example/`：两个官方 Skill——`self-docs`（无脚本、纯 references 路由检索的范本）与 `host-healthcheck`（带脚本、输出契约与转述纪律的范本）。

---

> **文档信息**
>
> - 本文档基于 QuickQuip 项目编写，规范与数值以 `src/quickquip/llm/skills/` 现行实现为准
> - 示例中的群友昵称、梗出处均为虚构占位
> - 最后核对：2026-10-14
