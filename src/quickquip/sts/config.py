"""STS 公式化模块的共用配置。

词表排除项、各公式的规则名/限频键/触发模式集中在此。新增公式时按需扩展。
"""

from __future__ import annotations

# ── 词表排除项 ─────────────────────────────────────────
# 标准打防牌：每个角色的初始 Strike/Defend，跨代去重后中文名坍缩为「打击」「防御」。
# 这两个 2 字裸词歧义过大（群聊里「打击了」「防御了」几乎从不是玩梗），故排除；
# 含该子串的其他牌（完美打击、究极防御等）互不干扰。新增歧义词在此追加即可。
EXCLUDED_NAMES: frozenset[str] = frozenset({"打击", "防御"})

# 上游词表快照 SHA（仅供溯源；刷新见 scripts/refresh_sts_lexicon.py）
LEXICON_SOURCE_SHA = "14e05c09dc38"

# ── 公式「xxx了」 ──────────────────────────────────────
# 被动触发：整句锚定，只接独立短句「X了」（2-5 个汉字 + 了），避免长句误触发。
CARD_LE_PATTERN = r"^([一-鿿]{2,5})了$"

# 被动路径（群友发言里的「X了」→ 未命中词表 → LLM 找最近真名）
CARD_LE_RULE_NAME = "sts_card_le"
CARD_LE_RATE_LIMIT_KEY = "sts_card_le"

# 主动路径（显式命令，把跟随/引用内容提炼成一句「名了」）
TURMFLUCH_RULE_NAME = "sts_turmfluch"
TURMFLUCH_RATE_LIMIT_KEY = "sts_turmfluch"
TURMFLUCH_ALIASES: set[str] = set()  # 中文别名可在此追加，如 {"尖塔化"}
TURMFLUCH_MAX_OUTPUT_TOKENS = 64  # 只需输出「名了」，给足余量即可
