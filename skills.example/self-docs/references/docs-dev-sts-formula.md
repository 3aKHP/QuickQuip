<!-- Generated from docs/dev/sts-formula.md; do not edit -->

# STS 公式化回复模块

本文面向维护尖塔梗功能的开发者，说明词表来源、两种公式的触发方式与扩展入口。群友使用命令时可查[群内指令速查](../user/group-commands.md#3-玩梗转写)。

## 1. 模块定位

`quickquip.sts` 存放《杀戮尖塔》（Slay the Spire）梗的词表、提示词、输出解析与被动触发逻辑。每个公式占一个子包，LLM 调用由 LLM 服务编排，消息与命令入口由应用管线和适配层接入。

当前公式：

- **“xxx了”**（`formulas/card_le/`）——把卡牌/遗物名当事件用，加“了”输出。
- **“故障化”**（`formulas/defectify/`）——`/defectify` 命令，把输入转写成读音贴近“故障机器人”（STS 初始角色 Defect 的官方中文名）的五字梗。

---

## 2. 词表来源与更新

卡牌与遗物中文名存放在随包分发的词表中，生成元信息记录来源快照。

- **数据源**：[`nkhoit/spire-archive`](https://github.com/nkhoit/spire-archive)。两代游戏的卡牌、遗物数据与简中本地化，覆盖 STS1（361 卡 / 181 遗物）与 STS2（577 卡 / 289 遗物，EA 快照 v0.107.1）。
- **构建**：`scripts/maintenance/refresh_sts_lexicon.py` 按 ID 关联两代条目与简中名称，再按中文名跨代去重，输出 `src/quickquip/sts/sts_lexicon.json`（1117 条，来源提交 `14e05c09dc38`，日期 2026-07-23）。刷新时在项目根运行 `python scripts/maintenance/refresh_sts_lexicon.py`；先核对要采用的上游提交，并更新脚本的 `SOURCE_SHA` 和 `SOURCE_DATE`，生成后检查词条与元信息。
- **加载**：`lexicon.py` 经 `importlib.resources` 读取 vendored JSON，套用 `config.EXCLUDED_NAMES` 得到活跃集合 `NAMES`。词表文件保留上游去重结果，排除项单独维护，刷新词表时继续生效。
- **排除标准打防牌**：每个角色的初始 Strike/Defend 跨代去重后坍缩为“打击”“防御”两个 2 字裸词，歧义过大（群聊里几乎不会是玩梗），故排除；含该子串的“完美打击”“究极防御”等不受影响。新增歧义词只需追加到 `EXCLUDED_NAMES`。

词表作为包资源存放在 `src/quickquip/sts/sts_lexicon.json`，随安装与打包分发。

---

## 3. “xxx了”的两条触发路径

两条路径共用 `prompting.py`（在系统提示中提供完整活跃词表）与 `parsing.py`（从模型输出提取合法名字，校验通过后才发送）。

### 3.1 被动路径（`passive.py`）

群友发言里的**独立短句**“X了”：

1. 正则 `^([一-鿿]{2,5})了$` 整句锚定命中（只接 2–5 汉字 + 了、句末，避免长句误触发）；
2. X 是合法卡牌/遗物名（在活跃词表里）→ **静默**（别人已在玩梗，无需插话）；
3. X 不是合法名 → LLM 从词表里挑语义/字面最近的真名 Y → 回复“Y了”。

梗的效果来自把日常词语映射成卡牌名；群友已经说出合法卡牌名时，机器人保持安静。

- LLM 调用经 `LLMService.generate_card_le_nearest`（provider 解析 + 输出敏感词扫描，输出经 `extract_card_le_name` 校验）。
- **触发控制**：`sts_card_le` 按群限频。调用 LLM 前先检查群规则开关、剩余配额与触发概率；回复送出时再记录配额。
- **缓存**：捕获词与生成结果缓存 300 秒，跨群复用。相同词语再次通过触发检查时，可以直接使用缓存，减少 LLM 请求。

接入点在 `app/message_pipeline.py` 的 `resolve_reply()` 规则链末尾、时区猜测之后，复用群级规则开关与限流器。

### 3.2 主动路径（`/turmfluch` 命令）

显式命令（`turmfluch` = 德语 Turm 尖塔 + Fluch 诅咒），与 `/defectify` 同构：

- 接受跟随文字、命令内图片或引用消息（`command_parts/sts.py`）；
- `LLMService.generate_turmfluch_reply` 把内容交给 LLM，从词表闭集里选一个最贴切的名字，输出“名了”，经过输入／输出敏感词扫描，并用 `extract_card_le_name` 校验卡牌名；
- `sts_turmfluch` 限频桶（global scope，保护 LLM 用量）。

---

## 4. “故障化”公式（`/defectify` 命令）

只有主动路径，无被动触发：

- “故障机器人”=《杀戮尖塔》初始角色 **Defect** 的官方中文名。公式把输入转写成读音依次贴近“故·障·机·器·人”的五字，附一行笑点解析；
- 输入形态与 `/turmfluch` 相同（跟随文字 / 命令内图片 / 引用消息），共用 `llm/single_shot.py` 的 `CommandSingleShotSpec` 管线。故障化使用自己的提示词，解析器原样接收生成文本，temperature 为 0.9；`turmfluch` 的 temperature 为 0.7，并按词表校验输出。两者使用各自的限频桶，`turmfluch` 还会记录渠道异常日志；
- `sts_defectify` 限频桶（global scope，独立于 `llm_chat`，不与 LLM 聊天共享额度）；
- LLM 编排同 turmfluch：`LLMService.generate_defectify_reply`，prompt 在本域、编排在 `llm/` 域。

---

## 5. 架构与扩展

```
src/quickquip/sts/
├── lexicon.py            # 加载词表 + 排除 + 查询（NAMES / is_card_name / get / meta）
├── sts_lexicon.json      # vendored 词表（1117 条，包数据，importlib.resources 加载）
├── config.py             # 排除项、正则、规则名/限频键等共用配置
└── formulas/
    ├── card_le/          # 公式“xxx了”
    │   ├── prompting.py  # LLM prompt（注入词表闭集）
    │   ├── parsing.py    # 输出校验（提取合法名）
    │   └── passive.py    # 被动匹配器（返回规则 dict，插 resolve_reply 链尾）
    └── defectify/        # 公式“故障化”
        └── prompting.py  # LLM prompt（音槽谐音梗，无词表）
```

`llm/service_parts/single_shot.py` 导入 STS 提示词和解析器，负责渠道选择、敏感词扫描与模型调用。命令型公式通过 `llm/single_shot.py` 的 `CommandSingleShotSpec` 声明输入处理、生成与错误处理策略；STS 公式逻辑保持框架无关。

框架无关的业务逻辑都在 `sts/`；NoneBot 接线在适配层：命令注册在 `adapters/nonebot/command_parts/sts.py`，被动匹配器在 `app/message_pipeline.py`。

**添加公式**：在 `formulas/` 新建子包，编写提示词、解析或触发策略，并按需复用 `lexicon` 与 `config`。参照 `defectify` 和 `turmfluch` 在 LLM 服务中添加公开编排方法，在适配层注册命令；被动公式则接入应用消息管线。命令型公式复用 `CommandSingleShotSpec`。

---

## 6. 相关文件速查

| 关注点 | 位置 |
|---|---|
| 词表数据 | `src/quickquip/sts/sts_lexicon.json` |
| 词表加载/排除/查询 | `src/quickquip/sts/lexicon.py` |
| 排除项与正则、规则名 | `src/quickquip/sts/config.py` |
| 词表刷新脚本 | `scripts/maintenance/refresh_sts_lexicon.py` |
| 被动匹配器 | `src/quickquip/sts/formulas/card_le/passive.py` |
| 故障化 prompt | `src/quickquip/sts/formulas/defectify/prompting.py` |
| 命令注册 | `src/quickquip/adapters/nonebot/command_parts/sts.py`（turmfluch + defectify） |
| LLM 编排 | `src/quickquip/llm/service_parts/single_shot.py`（`generate_defectify_reply` / `generate_turmfluch_reply` / `generate_card_le_nearest`；共享管线骨架在 `llm/single_shot.py`，经 `LLMService` mixin 组装暴露） |
| 限频桶 | `src/quickquip/chat/config.py`（`_BUILTIN_RATE_LIMIT_RULES`） |
