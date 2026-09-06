from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.llm.identity import IdentityIndex
from quickquip.llm.service import get_llm_service
from quickquip.llm.usage import drain_usage_tasks
from quickquip.llm.usage_store import usage_store
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
from quickquip.chat.repeat_detector import GroupRepeatDetector, RepeatAction
from quickquip.chat.rule_switch import GroupRuleSwitch
from quickquip.chat.reply_probability import PROBABILITY_CHECKED, roll_reply
from quickquip.chat.text_rules import match_text_rule
from quickquip.chat.timezone_reply import (  # noqa: F401 — re-exported for plugin shim
    build_timezone_reply as build_timezone_reply,
    detect_kind as detect_kind,
)
from quickquip.chat.config import (
    BEIJING_TIMEZONE,
    CHAIN_GAME_CONFIGS,
    RATE_LIMIT_RULES,
    RATE_LIMIT_WINDOW_SECONDS,
    RECENT_CONTEXT_TTL_SECONDS,
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
from quickquip.sts.formulas.card_le.passive import match_card_le, matches_card_le_pattern
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
from quickquip.tieba.service import TiebaService


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
recent_messages = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=RECENT_CONTEXT_TTL_SECONDS)
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

# 贴吧服务：构造不做磁盘 IO，帖子池由 startup()/web 装配显式 load()
tieba_service = TiebaService()

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


logger = logging.getLogger(__name__)


def get_sender_identity_sources(
    group_id: int | str,
) -> tuple[dict[str, str] | None, IdentityIndex | None]:
    """发言人展示名的两个来源：群内最新名片表与群级身份索引。

    身份索引依赖 LLM 服务，不可用时降级为 None，由调用方回退快照名。
    """
    gs = stats_tracker.get_stats(group_id)
    identity_index = None
    try:
        _ensure_llm_bindings()
        identity_index = get_llm_service().group_identities(str(group_id))
    except Exception:
        logger.debug("语录发言人解析：身份索引不可用，回退快照名", exc_info=True)
    return (gs.user_names if gs else None), identity_index


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


async def close_persistent_stores() -> None:
    """关停收尾：先排空在途 fire-and-forget 计量任务，再关闭各持久化 store。"""
    await drain_usage_tasks()
    offline_message_store.close()
    group_quote_store.close()
    usage_store.close()


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


def resolve_repeat_reply(
    text: str,
    user_id: int | str,
    group_id: int | str | None,
    repeat_fingerprint: str | None = None,
):
    if group_id is None:
        return None
    result = repeat_detector.process(
        group_id=group_id,
        user_id=user_id,
        text=repeat_fingerprint if repeat_fingerprint is not None else text,
    )
    if result is None:
        return None
    action = result.get("repeat_action")
    if action == RepeatAction.COPY_ORIGINAL:
        result["reply"] = text
    elif action == RepeatAction.TRIM_LAST:
        result["reply"] = text[:-1]
    return result


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
    repeat_fingerprint: str | None = None,
):
    """_resolve_reply_chain 的概率闸口：所有自动回复在返回前掷一次桶级概率。

    匹配器内部已按规则级概率掷过骰的结果带 PROBABILITY_CHECKED 标记，
    这里只兜底其余路径（复读、链游戏、内置游戏、时区等）。
    """
    result = await _resolve_reply_chain(
        text,
        user_id=user_id,
        sender_name=sender_name,
        group_id=group_id,
        now=now,
        recent_context=recent_context,
        repeat_fingerprint=repeat_fingerprint,
    )
    if not result or result.get(PROBABILITY_CHECKED):
        return result
    exit_key = str(result.get("rate_limit_key") or result.get("rule_name", ""))
    if not roll_reply(
        exit_key,
        identity=str(result.get("rule_name") or exit_key),
        group_id=group_id,
    ):
        return None
    return result


async def _resolve_reply_chain(
    text: str,
    user_id: int | str,
    sender_name: str = "这位朋友",
    group_id: int | str | None = None,
    now: datetime | None = None,
    recent_context: list[dict[str, str]] | None = None,
    repeat_fingerprint: str | None = None,
):
    repeat_reply = resolve_repeat_reply(
        text=text,
        user_id=user_id,
        group_id=group_id,
        repeat_fingerprint=repeat_fingerprint,
    )
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
        group_id=group_id,
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
    # 概率掷骰放在「X了」正则快筛之后、LLM 判定之前：非候选消息不消耗掷骰状态，
    # 未掷中时连判定成本也不花费
    if (
        group_id is not None
        and matches_card_le_pattern(text) is not None
        and rule_switch.is_enabled(group_id, CARD_LE_RULE_NAME)
        and rate_limiter.can_allow(CARD_LE_RATE_LIMIT_KEY, user_id, group_id=group_id)
        and roll_reply(
            CARD_LE_RATE_LIMIT_KEY, identity=CARD_LE_RULE_NAME, group_id=group_id
        )
    ):
        sts_reply = await match_card_le(
            text=text,
            llm_service=get_llm_service(),
            group_id=group_id,
        )
        if sts_reply:
            sts_reply[PROBABILITY_CHECKED] = True
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
