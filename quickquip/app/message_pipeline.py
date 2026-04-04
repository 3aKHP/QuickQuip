from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quickquip.llm.service import llm_service
from quickquip.chat.good_girl_chain import GoodGirlChainManager
from quickquip.chat.message_stats import GroupStatsTracker
from quickquip.chat.repeat_detector import GroupRepeatDetector
from quickquip.chat.rule_switch import GroupRuleSwitch
from quickquip.chat.text_rules import match_text_rule
from quickquip.chat.timezones import find_best_timezones
from quickquip.chat.config import (
    BEIJING_TIMEZONE,
    RATE_LIMIT_RULES,
    RATE_LIMIT_WINDOW_SECONDS,
    SLEEP_TARGET,
    SLEEP_WORDS,
    WAKE_TARGET,
    WAKE_WORDS,
)
from quickquip.common.message_deduper import RecentMessageDeduper
from quickquip.common.rate_limit import KeyedRateLimiter
from quickquip.common.recent_message_buffer import RecentMessageBuffer


DATA_DIR = Path("data")
STATS_PATH = DATA_DIR / "stats.json"
RULE_SWITCH_PATH = DATA_DIR / "rule_switch.json"

rate_limiter = KeyedRateLimiter(
    rule_limits=RATE_LIMIT_RULES,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
repeat_detector = GroupRepeatDetector()
good_girl_chain = GoodGirlChainManager()
stats_tracker = GroupStatsTracker()
rule_switch = GroupRuleSwitch()
recent_messages = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=1800)
message_deduper = RecentMessageDeduper()

DATA_DIR.mkdir(exist_ok=True)
stats_tracker.load(STATS_PATH)
rule_switch.load(RULE_SWITCH_PATH)
llm_service.bind_group_stats_tracker(stats_tracker)
llm_service.bind_rule_switch(rule_switch)
llm_service.bind_recent_message_buffer(recent_messages)


def save_all() -> None:
    stats_tracker.save(STATS_PATH)
    rule_switch.save(RULE_SWITCH_PATH)


def detect_kind(text: str):
    if any(word in text for word in WAKE_WORDS):
        return "wake"
    if any(word in text for word in SLEEP_WORDS):
        return "sleep"
    return None


def get_sender_name(event) -> str:
    sender = getattr(event, "sender", None)
    if sender:
        if getattr(sender, "card", None):
            return sender.card
        if getattr(sender, "nickname", None):
            return sender.nickname
    return str(event.user_id)


def is_admin(event) -> bool:
    sender = getattr(event, "sender", None)
    if sender:
        role = getattr(sender, "role", None)
        if role in ("admin", "owner"):
            return True
    return False


def is_self_message(event) -> bool:
    return str(getattr(event, "user_id", "")) == str(getattr(event, "self_id", ""))


def strip_command_name(text: str, command_name: str) -> str:
    normalized = text.strip()
    prefixes = (f"/{command_name}", f"!{command_name}", command_name)
    for prefix in prefixes:
        if normalized.startswith(prefix):
            return normalized[len(prefix):].strip()
    return normalized


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
    }


def resolve_repeat_reply(
    text: str,
    user_id: int | str,
    group_id: int | str | None,
):
    if group_id is None:
        return None
    return repeat_detector.process(group_id=group_id, user_id=user_id, text=text)


def resolve_good_girl_chain_reply(
    text: str,
    group_id: int | str | None,
):
    if group_id is None:
        return None
    return good_girl_chain.process(group_id=group_id, text=text)


def resolve_reply(
    text: str,
    user_id: int | str,
    sender_name: str = "这位朋友",
    group_id: int | str | None = None,
    now: datetime | None = None,
):
    repeat_reply = resolve_repeat_reply(text=text, user_id=user_id, group_id=group_id)
    if repeat_reply:
        rule_name = repeat_reply.get("rule_name", "")
        if group_id is None or rule_switch.is_enabled(group_id, rule_name):
            return repeat_reply

    good_girl_reply = resolve_good_girl_chain_reply(text=text, group_id=group_id)
    if good_girl_reply:
        rule_name = good_girl_reply.get("rule_name", "")
        if group_id is None or rule_switch.is_enabled(group_id, rule_name):
            return good_girl_reply

    now_cst = now or datetime.now(ZoneInfo(BEIJING_TIMEZONE))

    special_reply = match_text_rule(
        text=text,
        user_id=user_id,
        sender_name=sender_name,
        now=now_cst,
    )
    if special_reply:
        rule_name = special_reply.get("rule_name", "")
        if group_id is None or rule_switch.is_enabled(group_id, rule_name):
            return special_reply

    tz_reply = build_timezone_reply(text, sender_name=sender_name, now=now_cst)
    if tz_reply:
        rule_name = tz_reply.get("rule_name", "")
        if group_id is None or rule_switch.is_enabled(group_id, rule_name):
            return tz_reply

    return None


def build_reply(
    text: str,
    user_id: int | str,
    sender_name: str = "这位朋友",
    group_id: int | str | None = None,
    now: datetime | None = None,
):
    result = resolve_reply(
        text,
        user_id=user_id,
        sender_name=sender_name,
        group_id=group_id,
        now=now,
    )
    if not result:
        return None
    return result["reply"]
