from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

try:
    from nonebot import on_message
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
except ModuleNotFoundError:
    on_message = None
    GroupMessageEvent = object
    Message = None
    MessageSegment = None

from plugins.good_girl_chain import GoodGirlChainManager
from plugins.rate_limit import KeyedRateLimiter
from plugins.repeat_detector import GroupRepeatDetector
from plugins.text_reply_rules import match_text_rule
from plugins.tz_config import (
    BEIJING_TIMEZONE,
    RATE_LIMIT_RULES,
    RATE_LIMIT_WINDOW_SECONDS,
    REGION_ZH,
    SLEEP_TARGET,
    SLEEP_WORDS,
    TZ_PART_ZH,
    WAKE_TARGET,
    WAKE_WORDS,
)

rate_limiter = KeyedRateLimiter(
    rule_limits=RATE_LIMIT_RULES,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
repeat_detector = GroupRepeatDetector()
good_girl_chain = GoodGirlChainManager()


def circular_diff_minutes(a: int, b: int) -> int:
    return abs((a - b + 720) % 1440 - 720)


def format_location_zh(tz_name: str) -> str:
    parts = tz_name.split("/")
    region = REGION_ZH.get(parts[0], parts[0])
    local_parts = [TZ_PART_ZH.get(part, part.replace("_", "·")) for part in parts[1:]]
    if not local_parts:
        return region
    return f"{region}/{'/'.join(local_parts)}"


def format_city_zh(tz_name: str) -> str:
    parts = tz_name.split("/")
    if len(parts) <= 1:
        return REGION_ZH.get(parts[0], parts[0])

    local_parts = [TZ_PART_ZH.get(part, part.replace("_", "·")) for part in parts[1:]]
    return "/".join(local_parts)


def find_best_timezones(now_cst: datetime, target, limit: int = 3):
    target_min = target.hour * 60 + target.minute
    candidates = []

    for tz_name in available_timezones():
        if tz_name.startswith(("Etc/", "GMT", "UTC", "Factory", "SystemV/")):
            continue
        if "/" not in tz_name:
            continue

        local_dt = now_cst.astimezone(ZoneInfo(tz_name))
        local_min = local_dt.hour * 60 + local_dt.minute
        diff = circular_diff_minutes(local_min, target_min)

        candidates.append(
            {
                "tz_name": tz_name,
                "location_zh": format_location_zh(tz_name),
                "city_zh": format_city_zh(tz_name),
                "local_dt": local_dt,
                "diff": diff,
            }
        )

    candidates.sort(key=lambda item: (item["diff"], item["tz_name"]))

    unique_candidates = []
    seen_cities = set()
    for item in candidates:
        city_zh = item["city_zh"]
        if city_zh in seen_cities:
            continue
        seen_cities.add(city_zh)
        unique_candidates.append(item)
        if len(unique_candidates) >= limit:
            break

    return unique_candidates


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
        return repeat_reply

    good_girl_reply = resolve_good_girl_chain_reply(text=text, group_id=group_id)
    if good_girl_reply:
        return good_girl_reply

    now_cst = now or datetime.now(ZoneInfo(BEIJING_TIMEZONE))

    special_reply = match_text_rule(
        text=text,
        user_id=user_id,
        sender_name=sender_name,
        now=now_cst,
    )
    if special_reply:
        return special_reply

    return build_timezone_reply(text, sender_name=sender_name, now=now_cst)


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

        if "at_user_id" in result:
            message = Message([
                MessageSegment.at(result["at_user_id"]),
                MessageSegment.text(f" {result['reply']}"),
            ])
            await matcher.finish(message)

        await matcher.finish(result["reply"])
