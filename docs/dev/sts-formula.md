# STS 公式化回复模块

## 1. 模块定位

`quickquip.sts` 是承载《杀戮尖塔》（Slay the Spire）相关“公式化”梗能力的**独立顶层域**。它与规则引擎（`chat/`）和 LLM 运行时（`llm/`）平行，按“每个公式一个子包”的方式组织，互不耦合，方便后续追加策略不同的新公式。

当前公式：

- **“xxx了”**（`formulas/card_le/`）——把卡牌/遗物名当事件用，加“了”输出。
- **“故障化”**（`formulas/defectify/`）——`/defectify` 命令，把输入转写成读音贴近「故障机器人」（STS 初始角色 Defect 的官方中文名）的五字梗。实现先于本域存在（prompt 原在 `llm/defectify.py`），已迁入归位。

“我说xxxx”“假如xxxx”等以后以兄弟子包形式加入。

---

## 2. 词表（地基）

公式的前提是一份有时效性的卡牌/遗物中文名表。

- **数据源**：[`nkhoit/spire-archive`](https://github.com/nkhoit/spire-archive)。两代游戏的 cards/relics 数据 + 简中本地化，从游戏文件解析（非手抄），覆盖 STS1（361 卡 / 181 遗物）与 STS2（577 卡 / 289 遗物，EA 快照 v0.107.1）。
- **构建**：`scripts/refresh_sts_lexicon.py` 把两代数据按 ID join 简中、按中文名跨代去重，输出 `src/quickquip/sts/sts_lexicon.json`（1117 条，带来源 SHA / 版本元信息）。刷新时核对 spire-archive 最新 commit、改脚本里的 `SOURCE_SHA` 重跑即可。
- **加载**：`lexicon.py` 经 `importlib.resources` 读取 vendored JSON，套用 `config.EXCLUDED_NAMES` 得到活跃集合 `NAMES`。vendored 文件保持完整（与上游一致），排除项集中、可审计、刷新不回退。
- **排除标准打防牌**：每个角色的初始 Strike/Defend 跨代去重后坍缩为“打击”“防御”两个 2 字裸词，歧义过大（群聊里几乎不会是玩梗），故排除；含该子串的“完美打击”“究极防御”等不受影响。新增歧义词只需追加到 `EXCLUDED_NAMES`。

> 词表文件平铺在包根（`sts/sts_lexicon.json`），不放在 `data/` 子目录——根 `.gitignore` 的 `data/` 规则会忽略任意层级的 `data` 目录。

---

## 3. “xxx了”的两条触发路径

两条路径共用 `prompting.py`（system prompt 注入完整活跃词表作为闭集约束、利于 prompt 缓存）与 `parsing.py`（从模型输出提取并校验合法名，保证 bot 永不发出虚构名字）。

### 3.1 被动路径（`passive.py`）

群友发言里的**独立短句**“X了”：

1. 正则 `^([一-鿿]{2,5})了$` 整句锚定命中（只接 2–5 汉字 + 了、句末，避免长句误触发）；
2. X 是合法卡牌/遗物名（在活跃词表里）→ **静默**（别人已在玩梗，无需插话）；
3. X 不是合法名 → LLM 从词表里挑语义/字面最近的真名 Y → 回复“Y了”。

反直觉点是“命中真名反而闭嘴、没命中才接话”——喜剧来自把非卡词强行映射进卡牌语义空间。

- LLM 调用经 `LLMService.generate_card_le_nearest`（provider 解析 + 输出敏感词扫描，输出经 `extract_card_le_name` 校验）。
- **限频**：`sts_card_le` 桶，按群分桶、强限频，保持“偶发荒诞乱入”而非刷屏。
- **缓存**：按捕获词的短期 TTL 缓存（300s），降低同一“X了”的重复 LLM 调用——因为 LLM 调用发生在 `resolve_reply` 内、早于框架层的限频判定，缓存能把被限频情形的成本压低（同 `chat/context_rules.py` 的 judge 缓存思路）。

接入点：`app/message_pipeline.py` 的 `resolve_reply()` 规则链，位于 `timezone` 之后、规则链末尾（按符号定位：`resolve_reply` 中的 `match_card_le` block，代码注释明写不得抢占时区等具体规则），复用 `rule_switch`（按群开关）与框架的 `rate_limit`。

### 3.2 主动路径（`/turmfluch` 命令）

显式命令（`turmfluch` = 德语 Turm 尖塔 + Fluch 诅咒），与 `/defectify` 同构：

- 吃跟随文字 / 命令内图片 / 引用消息（`command_parts/sts.py`）；
- `LLMService.generate_turmfluch_reply` 把内容喂给 LLM，从词表闭集里选一个最贴切的名字，输出“名了”，经 `extract_card_le_name` 校验 + 输入/输出敏感词扫描；
- `sts_turmfluch` 限频桶（global scope，保护 LLM 用量）。

---

## 4. 「故障化」公式（`/defectify` 命令）

只有主动路径，无被动触发：

- 「故障机器人」=《杀戮尖塔》初始角色 **Defect** 的官方中文名。公式把输入转写成读音依次贴近「故·障·机·器·人」的五字，附一行笑点解析；
- 输入形态与 `/turmfluch` 相同（跟随文字 / 命令内图片 / 引用消息），共用 `llm/single_shot.py` 的 `CommandSingleShotSpec` 管线；差异点只有 prompt（`formulas/defectify/prompting.py`）、解析器（原样透传，无词表闭集校验）、temperature 与限频桶；
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

> 依赖方向说明：STS 公式逻辑（prompt/词表/正则）在 `sts/`，但 LLM 调用编排（provider 解析、敏感词扫描、complete）驻留在 `LLMService`（`llm/` 域），因此存在 `llm/service.py` → `quickquip.sts.*` 的单向导入；`sts/` 本身不反向依赖 `llm/`。命令型入口的重复骨架已在 v1.12.1 收敛为 `llm/single_shot.py` 的 `CommandSingleShotSpec`；若公式进一步增多，再考虑把编排彻底下沉到公式包内。

框架无关的业务逻辑都在 `sts/`；NoneBot 接线在适配层：命令注册在 `adapters/nonebot/command_parts/sts.py`，被动匹配器在 `app/message_pipeline.py`。

**加新公式**：在 `formulas/` 加一个兄弟子包，自带触发与生成策略，复用 `lexicon` 与 `config` 即可。LLM 调用仍走 `LLMService` 的方法（参照 defectify / turmfluch 的编排位置），不直接伸手进 LLMService 私有成员。当前不为“公式”做抽象注册框架（两个公式的差异点已由 `CommandSingleShotSpec` 承载），等公式进一步增多再视需要抽象。

---

## 6. 相关文件速查

| 关注点 | 位置 |
|---|---|
| 词表数据 | `src/quickquip/sts/sts_lexicon.json` |
| 词表加载/排除/查询 | `src/quickquip/sts/lexicon.py` |
| 排除项与正则、规则名 | `src/quickquip/sts/config.py` |
| 词表刷新脚本 | `scripts/refresh_sts_lexicon.py` |
| 被动匹配器 | `src/quickquip/sts/formulas/card_le/passive.py` |
| 故障化 prompt | `src/quickquip/sts/formulas/defectify/prompting.py` |
| 命令注册 | `src/quickquip/adapters/nonebot/command_parts/sts.py`（turmfluch + defectify） |
| LLM 编排 | `src/quickquip/llm/service.py`（`generate_defectify_reply` / `generate_turmfluch_reply` / `generate_card_le_nearest`；共享管线骨架已抽至 `llm/single_shot.py`，v1.12.1） |
| 限频桶 | `src/quickquip/chat/config.py`（`_BUILTIN_RATE_LIMIT_RULES`） |
