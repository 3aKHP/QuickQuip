"""群聊唤醒域（facade）。

包内按职责分层，依赖单向（后者依赖前者）：
``config``（TOML 形状与单例）→ ``state``（运行时状态）→ ``text_signals``
（纯文本信号）→ ``judge``（LLM 判定通道）→ ``triggers``（六条触发规则与
编排）→ ``boredom``（无聊唤醒巡检）。本 facade 只 re-export 真实公共契约
（adapter / pipeline / Web 路由消费的名字），子模块不回导 facade。
"""
from __future__ import annotations

from quickquip.chat.awakening.boredom import (
    BoredomEnabledGroups,
    BoredomSendPlan,
    confirm_boredom_sent,
    is_group_llm_enabled,
    iter_boredom_send_plans,
)
from quickquip.chat.awakening.config import (
    AwakeningConfig,
    AwakeningDefaults,
    AwakeningGroupOverride,
    ResolvedAwakeningSettings,
    effective_boredom_scan_interval,
    get_config,
    load_awakening_config,
    reload_config,
)
from quickquip.chat.awakening.state import (
    AwakeningExtendSession,
    AwakeningState,
    BotMessageCache,
    get_state,
)
from quickquip.chat.awakening.triggers import (
    AWAKENING_RULE_NAMES,
    AWAKENING_RULES,
    AwakeningTriggerResult,
    allows_recent_images,
    build_awakening_prompt,
    build_passive_trigger_raw_user_text,
    check_awakening_triggers,
    check_boredom,
    check_extend,
    check_fallback,
    check_interest,
    check_qa,
    check_relevance,
    select_passive_trigger_image_urls,
)

__all__ = [
    "AWAKENING_RULE_NAMES",
    "AWAKENING_RULES",
    "AwakeningConfig",
    "AwakeningDefaults",
    "AwakeningExtendSession",
    "AwakeningGroupOverride",
    "AwakeningState",
    "AwakeningTriggerResult",
    "BotMessageCache",
    "BoredomEnabledGroups",
    "BoredomSendPlan",
    "ResolvedAwakeningSettings",
    "allows_recent_images",
    "build_awakening_prompt",
    "build_passive_trigger_raw_user_text",
    "check_awakening_triggers",
    "check_boredom",
    "check_extend",
    "check_fallback",
    "check_interest",
    "check_qa",
    "check_relevance",
    "confirm_boredom_sent",
    "effective_boredom_scan_interval",
    "get_config",
    "get_state",
    "is_group_llm_enabled",
    "iter_boredom_send_plans",
    "load_awakening_config",
    "reload_config",
    "select_passive_trigger_image_urls",
]
