from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import nonebot
    from nonebot import on_message, on_command
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
except ModuleNotFoundError:
    nonebot = None
    on_message = None
    on_command = None
    GroupMessageEvent = object
    Message = None
    MessageSegment = None

from plugins.good_girl_chain import GoodGirlChainManager
from plugins.llm_inputs import extract_llm_input
from plugins.llm_runtime import llm_service
from plugins.message_rendering import render_message_for_llm
from plugins.message_deduper import RecentMessageDeduper
from plugins.message_stats import GroupStatsTracker
from plugins.rate_limit import KeyedRateLimiter
from plugins.recent_message_buffer import RecentMessageBuffer
from plugins.repeat_detector import GroupRepeatDetector
from plugins.rule_switch import GroupRuleSwitch
from plugins.web_search import WebSearchError, build_search_client, format_search_response
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


def _is_self_message(event: GroupMessageEvent) -> bool:
    return str(getattr(event, "user_id", "")) == str(getattr(event, "self_id", ""))


def _strip_command_name(text: str, command_name: str) -> str:
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


matcher = None

if nonebot is not None:
    driver = nonebot.get_driver()

    @driver.on_startup
    async def _startup_llm_runtime():
        await llm_service.startup(background=True)

    @driver.on_shutdown
    async def _save_on_shutdown():
        await llm_service.shutdown()
        save_all()

    try:
        from nonebot_plugin_apscheduler import scheduler

        scheduler.add_job(
            save_all,
            "interval",
            minutes=5,
            id="persistence_auto_save",
            replace_existing=True,
        )
    except ModuleNotFoundError:
        pass

if on_message is not None:
    matcher = on_message(priority=60, block=False)

    @matcher.handle()
    async def _(event: GroupMessageEvent):
        if _is_self_message(event):
            return

        message = event.get_message()
        text = str(message).strip()
        rendered_message = render_message_for_llm(
            message,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            include_image_placeholder=True,
        )
        rendered_text = rendered_message.text
        sender_name = get_sender_name(event)
        user_id = event.user_id
        group_id = event.group_id
        message_id = getattr(event, "message_id", None)
        identity = llm_service.identities.resolve_user(user_id, sender_name)
        canonical_name = identity.canonical_name

        if message_deduper.is_duplicate(group_id, message_id):
            return

        stats_tracker.record_message(group_id, user_id, sender_name)
        trigger_context = recent_messages.list_recent(group_id, limit=20)

        llm_settings = llm_service.get_group_settings(group_id)
        llm_input = extract_llm_input(
            message,
            event.self_id,
            llm_settings,
            identity_index=llm_service.identities,
        )
        if llm_input is not None and rule_switch.is_enabled(group_id, "llm_chat"):
            recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            if not rate_limiter.allow("llm_chat", user_id):
                return
            result = await llm_service.generate_reply(
                group_id=group_id,
                user_id=user_id,
                sender_name=sender_name,
                prompt=llm_input.prompt,
                image_urls=llm_input.image_urls,
                recent_messages=trigger_context,
            )
            stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))
            await matcher.finish(result["reply"])

        result = resolve_reply(
            text,
            user_id=user_id,
            sender_name=sender_name,
            group_id=group_id,
        )
        if not result:
            recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            return
        if not rate_limiter.allow(result["rate_limit_key"], user_id):
            recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            return

        stats_tracker.record_trigger(group_id, result.get("rule_name", "unknown"))

        if "at_user_id" in result:
            recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)
            message = Message([
                MessageSegment.at(result["at_user_id"]),
                MessageSegment.text(f" {result['reply']}"),
            ])
            await matcher.finish(message)

        recent_messages.add_message(group_id, user_id, sender_name, canonical_name, rendered_text)
        await matcher.finish(result["reply"])


if on_command is not None:
    stats_cmd = on_command("stats", priority=10, block=True)

    @stats_cmd.handle()
    async def _(event: GroupMessageEvent):
        group_id = event.group_id
        reply = stats_tracker.format_stats(group_id)
        await stats_cmd.finish(reply)

    llm_cmd = on_command("llm", priority=10, block=True)

    @llm_cmd.handle()
    async def _(event: GroupMessageEvent):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "llm")
        group_id = event.group_id
        tokens = args.split()

        if not args or args == "status":
            await llm_cmd.finish(llm_service.format_status(group_id))

        if args == "current":
            await llm_cmd.finish(llm_service.format_current(group_id))

        if args in {"mcp", "mcp status"}:
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "providers":
            await llm_cmd.finish(llm_service.format_providers())

        if args == "personas":
            await llm_cmd.finish(llm_service.format_personas())

        if tokens[:1] == ["models"]:
            provider_id = tokens[1] if len(tokens) > 1 else None
            await llm_cmd.finish(llm_service.format_models(provider_id))

        if tokens[:2] == ["memory", "status"]:
            await llm_cmd.finish(llm_service.format_memory_status(group_id))

        if not _is_admin(event):
            await llm_cmd.finish("仅管理员可执行此操作")

        if args == "on":
            llm_service.set_group_enabled(group_id, True)
            await llm_cmd.finish("本群 LLM 已开启")

        if args == "off":
            llm_service.set_group_enabled(group_id, False)
            await llm_cmd.finish("本群 LLM 已关闭")

        if args == "reload":
            config = await llm_service.reload_runtime(background=True)
            if config.load_error:
                await llm_cmd.finish(f"LLM 配置重载失败：{config.load_error}")
            await llm_cmd.finish("LLM 配置已重载")

        if args == "clear_context":
            deleted = llm_service.clear_group_context(group_id)
            await llm_cmd.finish(f"已清空当前群的短期上下文，共删除 {deleted} 条记录")

        if tokens[:1] == ["use"] and len(tokens) >= 3:
            provider_id = tokens[1]
            model = tokens[2]
            try:
                llm_service.set_group_model(group_id, provider_id, model)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群 LLM 已切换到 {provider_id} / {model}")

        if tokens[:2] == ["persona", "use"] and len(tokens) >= 3:
            persona_id = tokens[2]
            try:
                llm_service.set_group_persona(group_id, persona_id)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群人格已切换到 {persona_id}")

        if tokens[:2] == ["trigger", "prefix"] and len(tokens) >= 3:
            try:
                llm_service.set_group_trigger_prefix(group_id, tokens[2])
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群触发前缀已改为 {tokens[2]}")

        if tokens[:2] == ["trigger", "prefix_mode"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger prefix_mode on|off")
            llm_service.set_group_allow_prefix(group_id, value == "on")
            await llm_cmd.finish(f"本群前缀触发已设为 {value}")

        if tokens[:2] == ["trigger", "at"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger at on|off")
            llm_service.set_group_allow_at(group_id, value == "on")
            await llm_cmd.finish(f"本群艾特触发已设为 {value}")

        if tokens[:2] == ["memory", "on"]:
            llm_service.set_group_memory_enabled(group_id, True)
            await llm_cmd.finish("本群记忆注入已开启")

        if tokens[:2] == ["memory", "off"]:
            llm_service.set_group_memory_enabled(group_id, False)
            await llm_cmd.finish("本群记忆注入已关闭")

        await llm_cmd.finish(
            "LLM 命令用法：/llm status|current|on|off|providers|models [provider]|use <provider> <model>|"
            "personas|persona use <id>|trigger prefix <value>|trigger prefix_mode on|off|trigger at on|off|"
            "memory status|memory on|memory off|clear_context|reload|mcp status"
        )

    search_cmd = on_command("search", priority=10, block=True)

    @search_cmd.handle()
    async def _(event: GroupMessageEvent):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "search")
        if not args:
            await search_cmd.finish("用法：/search <query> 或 /search news <query>")
        if not rate_limiter.allow("web_search", event.user_id):
            await search_cmd.finish("搜索过于频繁，请稍后再试")

        tokens = args.split()
        topic = "general"
        query = args
        if tokens and tokens[0].lower() in {"general", "news", "finance"}:
            topic = tokens[0].lower()
            query = args[len(tokens[0]):].strip()
        if not query:
            await search_cmd.finish("搜索词不能为空")

        try:
            response = await build_search_client().search(query, topic=topic, max_results=5)
        except WebSearchError as exc:
            await search_cmd.finish(f"联网搜索失败：{exc}")
        await search_cmd.finish(format_search_response(response))

    reset_stats_cmd = on_command("reset_stats", priority=10, block=True)

    @reset_stats_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        stats_tracker.save(STATS_PATH)
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
            rule_switch.save(RULE_SWITCH_PATH)
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
            rule_switch.save(RULE_SWITCH_PATH)
            await enable_cmd.finish(f"已启用规则：{rule_name}")
        else:
            await enable_cmd.finish(f"未知规则：{rule_name}")

    rules_cmd = on_command("rules", priority=10, block=True)

    @rules_cmd.handle()
    async def _(event: GroupMessageEvent):
        reply = rule_switch.format_rules(event.group_id)
        await rules_cmd.finish(reply)

    remember_cmd = on_command("remember", priority=10, block=True)

    @remember_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await remember_cmd.finish("仅管理员可执行此操作")
        content = _strip_command_name(str(event.get_message()).strip(), "remember")
        if not content:
            await remember_cmd.finish("用法：/remember <要保存的群记忆>")
        memory_id = llm_service.remember_group_memory(event.group_id, content)
        await remember_cmd.finish(f"已写入群记忆 #{memory_id}")

    memories_cmd = on_command("memories", priority=10, block=True)

    @memories_cmd.handle()
    async def _(event: GroupMessageEvent):
        keyword = _strip_command_name(str(event.get_message()).strip(), "memories")
        reply = llm_service.format_memories(event.group_id, keyword=keyword or None)
        await memories_cmd.finish(reply)

    forget_cmd = on_command("forget", priority=10, block=True)

    @forget_cmd.handle()
    async def _(event: GroupMessageEvent):
        if not _is_admin(event):
            await forget_cmd.finish("仅管理员可执行此操作")
        keyword = _strip_command_name(str(event.get_message()).strip(), "forget")
        if not keyword:
            await forget_cmd.finish("用法：/forget <关键词>")
        deleted = llm_service.forget_group_memories(event.group_id, keyword)
        await forget_cmd.finish(f"已删除 {deleted} 条群记忆")
