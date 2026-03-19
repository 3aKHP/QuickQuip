from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from nonebot import on_message, on_command
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
except ModuleNotFoundError:
    on_message = None
    on_command = None
    GroupMessageEvent = object
    Message = None
    MessageSegment = None

from plugins.good_girl_chain import GoodGirlChainManager
from plugins.message_stats import GroupStatsTracker
from plugins.rate_limit import KeyedRateLimiter
from plugins.repeat_detector import GroupRepeatDetector
from plugins.rule_switch import GroupRuleSwitch
from plugins.text_reply_rules import match_text_rule
from plugins.tz_config import (
    BEIJING_TIMEZONE,
    RATE_LIMIT_RULES,
    RATE_LIMIT_WINDOW_SECONDS,
    SLEEP_TARGET,
    SLEEP_WORDS,
    WAKE_TARGET,
    WAKE_WORDS,
)
from plugins.tz_utils import find_best_timezones

rate_limiter = KeyedRateLimiter(
    rule_limits=RATE_LIMIT_RULES,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
repeat_detector = GroupRepeatDetector()
good_girl_chain = GoodGirlChainManager()
stats_tracker = GroupStatsTracker()
rule_switch = GroupRuleSwitch()


def detect_kind(text: str):
    if any(word in text for word in WAKE_WORDS):
        return "wake"
    if any(word in text for word in SLEEP_WORDS):
        return "sleep"
    return None


def get_sender_name(event: GroupMessageEvent) -> str:
    sender = getattr(event, "sender", None)
    if sender:
        if getattr(sender, "card", None):
            return sender.card
        if getattr(sender, "nickname", None):
            return sender.nickname
    return str(event.user_id)


def _is_admin(event: GroupMessageEvent) -> bool:
    sender = getattr(event, "sender", None)
    if sender:
        role = getattr(sender, "role", None)
        if role in ("admin", "owner"):
            return True
    return False


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


matcher = None

if on_message is not None:
    matcher = on_message(priority=60, block=False)

    @matcher.handle()
    async def _(event: GroupMessageEvent):
        text = str(event.get_message()).strip()
        sender_name = get_sender_name(event)
        user_id = event.user_id
        group_id = event.group_id

        stats_tracker.record_message(group_id, user_id)

        result = resolve_reply(
            text,
            user_id=user_id,
            sender_name=sender_name,
            group_id=group_id,
        )
        if not result:
            return
        if not rate_limiter.allow(result["rate_limit_key"], user_id):
            return

        stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))

        if "at_user_id" in result:
            message = Message([
                MessageSegment.at(result["at_user_id"]),
                MessageSegment.text(f" {result['reply']}"),
            ])
            await matcher.finish(message)

        await matcher.finish(result["reply"])


if on_command is not None:
    stats_cmd = on_command("stats", priority=10, block=True)

    @stats_cmd.handle()
    async def _(event: GroupMessageEvent):
        group_id = event.group_id
        reply = stats_tracker.format_stats(group_id)
        await stats_cmd.finish(reply)

    reset_stats_cmd = on_command("reset_stats", priority=10, block=True)

    @reset_stats_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        await reset_stats_cmd.finish("统计数据已重置")

    disable_cmd = on_command("disable", priority=10, block=True)

    @disable_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await disable_cmd.finish("仅管理员可执行此操作")
        text = str(event.get_message()).strip()
        rule_name = text.replace("/disable", "").strip()
        if not rule_name:
            await disable_cmd.finish("用法：/disable <rule_name>")
        if rule_switch.disable(event.group_id, rule_name):
            await disable_cmd.finish(f"已禁用规则：{rule_name}")
        else:
            await disable_cmd.finish(f"未知规则：{rule_name}")

    enable_cmd = on_command("enable", priority=10, block=True)

    @enable_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await enable_cmd.finish("仅管理员可执行此操作")
        text = str(event.get_message()).strip()
        rule_name = text.replace("/enable", "").strip()
        if not rule_name:
            await enable_cmd.finish("用法：/enable <rule_name>")
        if rule_switch.enable(event.group_id, rule_name):
            await enable_cmd.finish(f"已启用规则：{rule_name}")
        else:
            await enable_cmd.finish(f"未知规则：{rule_name}")

    rules_cmd = on_command("rules", priority=10, block=True)

    @rules_cmd.handle()
    async def _(event: GroupMessageEvent):
        reply = rule_switch.format_rules(event.group_id)
        await rules_cmd.finish(reply)
