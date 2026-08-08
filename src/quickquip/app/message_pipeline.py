from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.llm.service import get_llm_service
from quickquip.common.event_utils import (  # noqa: F401 — re-exported for adapter layer
    get_sender_name as get_sender_name,
    is_admin as is_admin,
    is_self_message as is_self_message,
    strip_command_name as strip_command_name,
)
from quickquip.chat import config as chat_config
from quickquip.chat import context_rules as context_rules_module
from quickquip.chat import rule_switch as rule_switch_module
from quickquip.chat import text_rules as text_rules_module
from quickquip.chat.chain_game import ChainGameDef, ChainGameManager
from quickquip.games import BlackjackGame, GameEconomyStore, GameRegistry, NiuNiuStore, NumberBombGame, RussianRouletteGame, game_scores

from quickquip.games.config import load_games_config
from quickquip.chat.good_girl_chain import GoodGirlChainManager
from quickquip.chat.message_stats import GroupStatsTracker
from quickquip.chat.repeat_detector import GroupRepeatDetector
from quickquip.chat.rule_switch import GroupRuleSwitch
from quickquip.chat.text_rules import match_text_rule
from quickquip.chat.timezones import find_best_timezones
from quickquip.chat.config import (
    BEIJING_TIMEZONE,
    CHAIN_GAME_CONFIGS,
    RATE_LIMIT_RULES,
    RATE_LIMIT_WINDOW_SECONDS,
    SLEEP_TARGET,
    SLEEP_WORDS,
    WAKE_TARGET,
    WAKE_WORDS,
)
from quickquip.chat.daily_summary import (
    DailyMessageCollector,
    DailySummaryEnabledGroups,
    DailySummaryStore,
)
from quickquip.chat.daily_briefing import DailyBriefingEnabledGroups
from quickquip.chat.period_report import (
    PERIOD_MONTHLY,
    PERIOD_WEEKLY,
    PeriodReportEnabledGroups,
    PeriodReportStore,
)
from quickquip.chat.wordcloud import WordCloudCollector
from quickquip.chat.context_rules import match_context_rule
from quickquip.sts.config import CARD_LE_RATE_LIMIT_KEY, CARD_LE_RULE_NAME
from quickquip.sts.formulas.card_le.passive import match_card_le
from quickquip.chat.awakening import (
    get_config as _get_awakening_config,
    get_state as _get_awakening_state,
    reload_config as _reload_awakening_config,
)
from quickquip.chat.offline_messages import OfflineMessageStore
from quickquip.chat.group_quotes import GroupQuoteStore
from quickquip.common.message_deduper import RecentMessageDeduper
from quickquip.common.paths import (
    CONFIG_GAMES_TOML,
    DATA_DIR,
    OFFLINE_MESSAGES_DB_PATH,
    PERIOD_REPORTS_DB_PATH,
    QUOTES_DB_PATH,
    RULE_SWITCH_JSON_PATH,
    STATS_JSON_PATH,
    WEEKLY_REPORT_GROUPS_PATH,
    MONTHLY_REPORT_GROUPS_PATH,
)
from quickquip.common.rate_limit import KeyedRateLimiter
from quickquip.common.recent_message_buffer import RecentMessageBuffer


class _LazyStoreProxy:
    """Delay SQLite-backed store creation until the first real use."""

    def __init__(self, factory):
        self._factory = factory
        self._store = None

    def _get_store(self):
        if self._store is None:
            self._store = self._factory()
        return self._store

    def __getattr__(self, name):
        return getattr(self._get_store(), name)

    def close(self) -> None:
        if self._store is not None:
            self._store.close()


STATS_PATH = STATS_JSON_PATH
RULE_SWITCH_PATH = RULE_SWITCH_JSON_PATH
OFFLINE_MESSAGES_PATH = OFFLINE_MESSAGES_DB_PATH
QUOTES_PATH = QUOTES_DB_PATH

rate_limiter = KeyedRateLimiter(
    rule_limits=RATE_LIMIT_RULES,
    window_seconds=RATE_LIMIT_WINDOW_SECONDS,
)
repeat_detector = GroupRepeatDetector()
good_girl_chain = GoodGirlChainManager()
custom_chain_games = ChainGameManager([ChainGameDef.from_dict(d) for d in CHAIN_GAME_CONFIGS])
stats_tracker = GroupStatsTracker()
rule_switch = GroupRuleSwitch()
recent_messages = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=1800)
message_deduper = RecentMessageDeduper()
awakening_state = _get_awakening_state()

daily_collector = DailyMessageCollector()
daily_store = DailySummaryStore()
daily_enabled_groups = DailySummaryEnabledGroups()
daily_briefing_enabled_groups = DailyBriefingEnabledGroups()
wordcloud_collector = WordCloudCollector()
# 群周报 / 群月报（数据源复用 wordcloud_collector，独立 store 与 enabled 集合）
period_store = PeriodReportStore(PERIOD_REPORTS_DB_PATH)
weekly_enabled_groups = PeriodReportEnabledGroups(PERIOD_WEEKLY, WEEKLY_REPORT_GROUPS_PATH)
monthly_enabled_groups = PeriodReportEnabledGroups(PERIOD_MONTHLY, MONTHLY_REPORT_GROUPS_PATH)
offline_message_store = _LazyStoreProxy(
    lambda: OfflineMessageStore(OFFLINE_MESSAGES_PATH),
)
group_quote_store = _LazyStoreProxy(
    lambda: GroupQuoteStore(QUOTES_PATH),
)

games_config = load_games_config(CONFIG_GAMES_TOML)

game_registry = GameRegistry(max_sessions=1024)
game_registry.register(NumberBombGame(config=games_config.number_bomb))
game_economy = GameEconomyStore(config=games_config.economy)
game_registry.register(BlackjackGame(economy=game_economy, config=games_config.blackjack))
game_registry.register(RussianRouletteGame(economy=game_economy, config=games_config.russian_roulette))
niuniu_store = NiuNiuStore(config=games_config.niuniu)

DATA_DIR.mkdir(exist_ok=True)
stats_tracker.load(STATS_PATH)
rule_switch.load(RULE_SWITCH_PATH)
_llm_bindings_done = False


def _ensure_llm_bindings() -> None:
    """Wire the pipeline singletons into LLMService once, lazily.

    Called at the top of every adapter entry point that needs llm_service,
    so bindings are guaranteed to be in place before first use but never
    executed at import time.
    """
    global _llm_bindings_done
    if _llm_bindings_done:
        return
    svc = get_llm_service()
    svc.bind_group_stats_tracker(stats_tracker)
    svc.bind_rule_switch(rule_switch)
    svc.bind_recent_message_buffer(recent_messages)
    _llm_bindings_done = True


def record_group_message(
    group_id: int | str,
    user_id: int | str,
    sender_name: str,
    rendered_text: str,
) -> None:
    """Record a message for daily summary / briefing collection when either feature is enabled."""
    if not (
        daily_enabled_groups.contains(group_id)
        or daily_briefing_enabled_groups.contains(group_id)
    ):
        return
    daily_collector.record(group_id, sender_name, rendered_text, user_id=user_id)


def record_wordcloud_message(group_id: int | str, sender_name: str, rendered_text: str) -> None:
    """Always-on word cloud collection for all groups."""
    wordcloud_collector.record(group_id, sender_name, rendered_text)


def save_all() -> None:
    stats_tracker.save(STATS_PATH)
    rule_switch.save(RULE_SWITCH_PATH)


def close_persistent_stores() -> None:
    offline_message_store.close()
    group_quote_store.close()


def reload_chat_rules_pipeline() -> dict[str, int]:
    """Reload chat_rules.toml and rebuild every derived cache in-place.

    Returns a summary count dict so callers (e.g. the ``/reload_rules`` command)
    can report how many rules landed after the refresh.
    """
    chat_config.reload_chat_rules()
    text_rules_module.recompile_patterns()
    context_rules_module.recompile_patterns()
    rule_switch_module.rebuild_switchable_rules()
    rate_limiter.reload_rules(chat_config.RATE_LIMIT_RULES)
    custom_chain_games.replace_defs(
        [ChainGameDef.from_dict(d) for d in chat_config.CHAIN_GAME_CONFIGS]
    )
    _reload_awakening_config()
    return {
        "text_rules": len(chat_config.TEXT_REPLY_RULES),
        "context_rules": len(chat_config.CONTEXT_REPLY_RULES),
        "chain_games": len(chat_config.CHAIN_GAME_CONFIGS),
        "rate_limit_rules": len(chat_config.RATE_LIMIT_RULES),
        "awakening_config_error": 1 if _get_awakening_config().load_error else 0,
    }


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


async def resolve_reply(
    text: str,
    user_id: int | str,
    sender_name: str = "这位朋友",
    group_id: int | str | None = None,
    now: datetime | None = None,
    recent_context: list[dict[str, str]] | None = None,
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

    if group_id is not None:
        chain_game_reply = custom_chain_games.process(group_id=group_id, text=text)
        if chain_game_reply:
            rule_name = chain_game_reply.get("rule_name", "")
            if rule_switch.is_enabled(group_id, rule_name):
                return chain_game_reply

    if group_id is not None:
        game_reply = game_registry.process(
            group_id=str(group_id),
            user_id=str(user_id),
            text=text,
        )
        if game_reply:
            # Record win if the game result has both an @mention target and a game name
            if game_reply.get("at_user_id") and game_reply.get("game_name"):
                game_scores.record_win(
                    str(group_id),
                    str(game_reply["at_user_id"]),
                    game_reply["game_name"],
                )
            rule_name = game_reply.get("rule_name", "")
            if rule_switch.is_enabled(group_id, rule_name):
                return game_reply

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

    if recent_context and group_id is not None:
        ctx_reply = await match_context_rule(
            text=text,
            user_id=user_id,
            sender_name=sender_name,
            recent_messages=recent_context,
            now=now_cst,
            llm_service=get_llm_service(),
            group_id=group_id,
        )
        if ctx_reply:
            rule_name = ctx_reply.get("rule_name", "")
            if rule_switch.is_enabled(group_id, rule_name):
                return ctx_reply

    tz_reply = build_timezone_reply(text, sender_name=sender_name, now=now_cst)
    if tz_reply:
        rule_name = tz_reply.get("rule_name", "")
        if group_id is None or rule_switch.is_enabled(group_id, rule_name):
            return tz_reply

    # STS「xxx了」置于链尾：广覆盖的梗规则，不得抢占时区（起床了/睡醒了）等具体规则
    if (
        group_id is not None
        and rule_switch.is_enabled(group_id, CARD_LE_RULE_NAME)
        and rate_limiter.can_allow(CARD_LE_RATE_LIMIT_KEY, user_id, group_id=group_id)
    ):
        sts_reply = await match_card_le(
            text=text,
            llm_service=get_llm_service(),
            group_id=group_id,
        )
        if sts_reply:
            return sts_reply

    return None


async def build_reply(
    text: str,
    user_id: int | str,
    sender_name: str = "这位朋友",
    group_id: int | str | None = None,
    now: datetime | None = None,
    recent_context: list[dict[str, str]] | None = None,
):
    result = await resolve_reply(
        text,
        user_id=user_id,
        sender_name=sender_name,
        group_id=group_id,
        now=now,
        recent_context=recent_context,
    )
    if not result:
        return None
    return result["reply"]
