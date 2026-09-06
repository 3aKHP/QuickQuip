"""自动回复概率掷骰。

所有非命令触发的自动回复在命中后、真正发出前掷一次骰子：
命中未掷中视为"这条规则这次保持沉默"，不产生任何回复。

概率取值顺序：规则级 ``probability`` > 限流桶级 ``probability``
（``[rate_limit_rules.<key>]`` 条目内）> 1.0（必回，行为与历史版本一致）。
桶级配置让内置自动路径（时区、被动 LLM 判定、复读、游戏、唤醒、llm_chat）
无需逐条改代码即可调密度；规则级配置覆盖桶级，用于在同一桶内区分冷热梗。

两个可选的方差驯化开关（桶级配置，默认关闭；关闭时不创建任何状态）：

- ``suppress_after_hit`` 防连发：同一（规则身份, 群）命中后，接下来 N 次
  命中强制沉默。专治"刚回完又回"的观感。
- ``pity_step`` 保底步进：连哑越多概率越高，
  ``p_eff = p × (1 + 连哑数 × pity_step)``，给连哑长度一个软上限。

掷骰状态按（规则身份, 群）隔离——身份在文字/语境规则上是规则名，在内置
路径上是桶名或规则名。状态只存内存，重启即重置；被防连发压制的命中不
计入保底连哑数。规则级 ``probability`` 只覆盖基础概率，两个开关始终跟桶。
"""

import logging
import random

from quickquip.chat import config as chat_config

logger = logging.getLogger(__name__)

# 匹配器内部已掷过骰的结果带此标记；resolve_reply 出口不再对同一结果二次掷骰。
PROBABILITY_CHECKED = "probability_checked"

# 连哑计数的存放上限：pity_step 之下 p_eff 早已封顶，只为防整数无界增长。
_MISS_STREAK_CAP = 100
# 状态表膨胀保护：身份 × 群的组合超出该规模时整体重置（均为建议性状态）。
_STATE_TABLE_HARD_CAP = 8192

# (identity, group_key) → {"miss_streak": int, "suppress": int}
_ROLL_STATE: dict[tuple[str, str], dict[str, int]] = {}


def reset_state() -> None:
    """清空掷骰状态（测试与运维用途；正常运行无需调用）。"""
    _ROLL_STATE.clear()


def resolve_probability(rate_limit_key: str, rule: dict | None = None) -> float:
    if rule is not None:
        rule_probability = rule.get("probability")
        if isinstance(rule_probability, (int, float)) and not isinstance(rule_probability, bool):
            return float(rule_probability)

    entry = chat_config.RATE_LIMIT_RULES.get(rate_limit_key) or {}
    key_probability = entry.get("probability")
    if isinstance(key_probability, (int, float)) and not isinstance(key_probability, bool):
        return float(key_probability)
    return 1.0


def _state_key(identity: str, group_id: int | str | None) -> tuple[str, str]:
    return (identity, str(group_id) if group_id is not None else "")


def roll_reply(
    rate_limit_key: str,
    rule: dict | None = None,
    *,
    identity: str | None = None,
    group_id: int | str | None = None,
) -> bool:
    entry = chat_config.RATE_LIMIT_RULES.get(rate_limit_key) or {}
    probability = resolve_probability(rate_limit_key, rule)

    suppress_after_hit = entry.get("suppress_after_hit", 0)
    pity_step = entry.get("pity_step", 0)
    suppress_after_hit = suppress_after_hit if isinstance(suppress_after_hit, int) and not isinstance(suppress_after_hit, bool) else 0
    pity_step = pity_step if isinstance(pity_step, (int, float)) and not isinstance(pity_step, bool) else 0
    tracks_state = suppress_after_hit > 0 or pity_step > 0

    state_key = _state_key(identity or rate_limit_key, group_id)
    state = _ROLL_STATE.get(state_key) if tracks_state else None

    if state and state["suppress"] > 0:
        state["suppress"] -= 1
        logger.debug(
            "防连发压制命中，保持沉默：key=%s probability=%.2f",
            state_key[0],
            probability,
        )
        return False

    effective = probability
    if state and pity_step > 0 and state["miss_streak"] > 0:
        effective = min(1.0, probability * (1.0 + state["miss_streak"] * float(pity_step)))

    if effective >= 1.0:
        hit = True
    elif effective <= 0.0:
        hit = False
    else:
        hit = random.random() < effective

    if tracks_state:
        if len(_ROLL_STATE) >= _STATE_TABLE_HARD_CAP:
            _ROLL_STATE.clear()
        if hit:
            _ROLL_STATE[state_key] = {"miss_streak": 0, "suppress": suppress_after_hit}
        else:
            current = _ROLL_STATE.get(state_key) or {"miss_streak": 0, "suppress": 0}
            current["miss_streak"] = min(current["miss_streak"] + 1, _MISS_STREAK_CAP)
            _ROLL_STATE[state_key] = current

    if not hit:
        logger.debug(
            "自动回复概率未掷中，保持沉默：key=%s probability=%.2f",
            state_key[0],
            effective,
        )
    return hit
