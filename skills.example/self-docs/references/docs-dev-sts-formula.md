<!-- Generated from docs/dev/sts-formula.md; do not edit -->

# STS 公式化回复模块

本文面向维护尖塔梗功能的开发者，说明词表来源、两条公式的触发链路与模块扩展入口。群友侧指令用法见[群内指令速查](../user/group-commands.md#3-玩梗转写)。

## 1. 模块定位

`quickquip.sts` 存放《杀戮尖塔》（Slay the Spire）玩梗功能的词表数据、提示词构造、输出校验与被动匹配逻辑。每个公式独立为一个子包，底层模型调用委托 `quickquip.llm` 编排，事件监听与命令入口在应用组合根及 NoneBot 适配层接线。

当前提供两套公式：

- **“xxx了”**（`formulas/card_le/`）：将卡牌或遗物名称当作动词事件使用，输出“卡牌／遗物名 + 了”。
- **“故障化”**（`formulas/defectify/`）：通过 `/defectify` 命令，将输入内容改写为读音依次贴近“故障机器人”（初始角色 Defect 的官方简中译名）的五字谐音梗并附一行笑点说明。

---

## 2. 词表来源与更新

两代游戏的卡牌与遗物简中名称随包内置在 JSON 词表中，文件头部的元信息记录上游快照版本：

- **数据来源**：[`nkhoit/spire-archive`](https://github.com/nkhoit/spire-archive)，涵盖《杀戮尖塔》初代（361 张卡牌／181 件遗物）与二代抢先体验版（577 张卡牌／289 件遗物，EA 快照 `v0.107.1`）的卡牌、遗物及官方简中本地化文本。
- **离线构建**：维护脚本 `scripts/maintenance/refresh_sts_lexicon.py` 按条目 ID 关联简中译名并跨两代按中文名去重，生成 `src/quickquip/sts/sts_lexicon.json`（共 1117 条，对应上游提交 `14e05c09dc38`，快照日期 `2026-07-23`）。同步上游更新时，先核对目标提交并修改脚本内的 `SOURCE_SHA` 与 `SOURCE_DATE`，在仓库根目录运行 `python scripts/maintenance/refresh_sts_lexicon.py`，最后检查生成的词条差异与元信息。
- **运行期加载与歧义词剔除**：`lexicon.py` 通过 `importlib.resources` 读取随包 JSON，扣除 `config.EXCLUDED_NAMES` 后得到活跃词集 `NAMES`。各角色初始基础牌跨代去重后坍缩为“打击”“防御”两个双字日常高频词，在普通聊天中极易误判，因此列入 `EXCLUDED_NAMES` 排除（含该子串的“完美打击”“究极防御”等完整卡名照常保留）；后续发现新的高歧义短词直接追加到 `EXCLUDED_NAMES` 即可，无需手动修改生成的 JSON 文件。

---

## 3. “xxx了”的两条触发路径

被动与主动路径共用 `formulas/card_le/prompting.py`（在系统提示词中注入完整活跃词表闭集）与 `parsing.py`（使用 `extract_card_le_name` 校验模型输出确实属于合法词表条目后才允许外发）。

### 3.1 被动路径（`passive.py`）

监听群友发送的**独立短句**“X了”：

1. 正则 `^([一-鿿]{2,5})了$` 整句锚定快筛（仅匹配 2–5 个汉字加句末“了”，跳过带标点或长句的普通发言）。
2. 若捕获词 `X` 已经是活跃词表中的合法卡牌／遗物名，则直接**保持静默**（群友已经在自己玩原版尖塔梗，无需机器人画蛇添足）。
3. 若 `X` 不在词表中，则调用 `LLMService.generate_card_le_nearest` 从词表闭集中挑选字面或语义最接近的合法名称 `Y`（经输出敏感词扫描与词表校验），回复“Y了”。

被动分支挂接在 `app/message_pipeline.py` `resolve_reply()` 规则链末尾（时区猜测之后）：快筛命中后依次检查群级规则开关、限频预检与触发概率掷骰（写入 `PROBABILITY_CHECKED` 标记），实际回复送出时再扣减 `sts_card_le` 群级限频配额。捕获词与生成结果在内存中跨群缓存 300 秒，相同短词短期内再次通过概率检查时直接复用缓存结果。

### 3.2 主动路径（`/turmfluch` 命令）

显式命令 `/turmfluch`（德语 *Turm* 尖塔 + *Fluch* 诅咒）：

- 支持命令跟随文本、命令内附图或引用历史消息／图片（`adapters/nonebot/command_parts/sts.py`）。
- 经 `LLMService.generate_turmfluch_reply` 送入模型，从词表闭集中选出最贴合当前语境或画面的名称拼成“名了”，通过输入／输出敏感词扫描与 `extract_card_le_name` 合法性校验后返回，并在模型调用异常时记录渠道错误日志。
- 受全局作用域的 `sts_turmfluch` 限频桶保护。

---

## 4. “故障化”公式（`/defectify` 命令）

仅提供主动命令入口，不设被动触发：

- 将输入文本或图片内容改写为读音依次贴近“故·障·机·器·人”五个音节的五字谐音梗，并附一行简短笑点解析。
- 输入形态与 `/turmfluch` 完全一致（跟随文字、附图或引用消息），两者共用 `llm/single_shot.py` 的 `CommandSingleShotSpec` 单轮生成管线：两个命令均不硬编码采样温度，统一继承当前会话所选渠道／模型的有效 `temperature`（未显式配置时默认不下发）与 `max_output_tokens`。故障化使用专属谐音提示词并原样采纳非空文本输出，受全局 `sts_defectify` 限频桶保护（与常规 `llm_chat` 额度相互独立）。

---

## 5. 架构与扩展

```text
src/quickquip/sts/
├── lexicon.py            # 加载词表、应用排除集与查询接口（NAMES / is_card_name / get / meta）
├── sts_lexicon.json      # 随包分发的去重词表（1117 条，由 importlib.resources 读取）
├── config.py             # 歧义排除项、被动正则、规则名与限频键常量
└── formulas/
    ├── card_le/          # 公式“xxx了”
    │   ├── prompting.py  # 提示词构造（注入词表闭集）
    │   ├── parsing.py    # 输出提取与合法卡名校验
    │   └── passive.py    # 被动快筛匹配器（接入 resolve_reply 规则链末尾）
    └── defectify/        # 公式“故障化”
        └── prompting.py  # 五字谐音提示词构造
```

分层职责上，框架无关的词表、正则与提示词全部留在 `src/quickquip/sts/`；`llm/service_parts/single_shot.py` 通过 `CommandSingleShotSpec` 负责渠道模型解析、输入／输出敏感词扫描与单轮模型调用；NoneBot 命令注册位于 `adapters/nonebot/command_parts/sts.py`，被动规则链装配位于 `app/message_pipeline.py`。

新增玩梗公式时，在 `formulas/` 下创建新子包编写提示词与输出校验函数，按需复用 `lexicon` 与 `config`，再参照 `defectify`／`turmfluch` 在 `SingleShotEntriesMixin` 暴露服务方法并在适配层注册命令（若需被动触发则接入 `message_pipeline.py`）。

---

## 6. 相关文件速查

| 关注点 | 源码路径 |
|---|---|
| 随包词表数据 | `src/quickquip/sts/sts_lexicon.json` |
| 词表加载与排除查询 | `src/quickquip/sts/lexicon.py` |
| 排除列表、正则与限频键常量 | `src/quickquip/sts/config.py` |
| 词表离线刷新脚本 | `scripts/maintenance/refresh_sts_lexicon.py` |
| “xxx了”被动匹配器 | `src/quickquip/sts/formulas/card_le/passive.py` |
| “故障化”提示词 | `src/quickquip/sts/formulas/defectify/prompting.py` |
| NoneBot 命令注册 | `src/quickquip/adapters/nonebot/command_parts/sts.py` |
| LLM 单轮编排入口 | `src/quickquip/llm/service_parts/single_shot.py`（骨架位于 `src/quickquip/llm/single_shot.py`） |
| 内置限频规则定义 | `src/quickquip/chat/config.py`（`_BUILTIN_RATE_LIMIT_RULES`） |
