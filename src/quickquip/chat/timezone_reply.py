"""时区猜测回复决策：关键词识别、目标时刻选择与文案模板。

该模块拥有规则链兜底环节「时区作息」的全部领域决策（触发词分类、
rate_limit_key、trigger_reason、回复文案模板）。返回 dict 的键集合与文案
措辞是规则链契约，改动需同步检查消费方（message_pipeline.resolve_reply、
rate_limit 规则配置）。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.chat.config import (
    BEIJING_TIMEZONE,
    SLEEP_TARGET,
    SLEEP_WORDS,
    WAKE_TARGET,
    WAKE_WORDS,
)
from quickquip.chat.timezones import find_best_timezones


def detect_kind(text: str):
    if any(word in text for word in WAKE_WORDS):
        return "wake"
    if any(word in text for word in SLEEP_WORDS):
        return "sleep"
    return None


def build_timezone_reply(
    text: str,
    sender_name: str = "这位朋友",
    now: datetime | None = None,
):
    kind = detect_kind(text)
    if not kind:
        return None

    now_cst = now or datetime.now(ZoneInfo(BEIJING_TIMEZONE))

    if kind == "wake":
        target = WAKE_TARGET
        action = "起床"
        rate_limit_key = "timezone_wake"
    else:
        target = SLEEP_TARGET
        action = "睡觉"
        rate_limit_key = "timezone_sleep"

    candidates = find_best_timezones(now_cst, target, limit=3)
    if len(candidates) < 3:
        return None

    primary = candidates[0]["city_zh"]
    second = candidates[1]["city_zh"]
    third = candidates[2]["city_zh"]

    return {
        "reply": (
            f"现在是北京时间{now_cst:%Y-%m-%d %H:%M}，"
            f"位于{primary}的@{sender_name} 要{action}了。"
            f"TA也有可能在{second}或{third}。"
        ),
        "rate_limit_key": rate_limit_key,
        "kind": kind,
        "rule_name": rate_limit_key,
        "trigger_kind": "rule",
        "trigger_reason": f"时区作息关键词触发：{action}",
    }
