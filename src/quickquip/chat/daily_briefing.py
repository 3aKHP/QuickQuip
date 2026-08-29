from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.wordcloud import WORDCLOUD_STOPWORDS, WordCloudCollector, build_word_frequencies
from quickquip.common.opt_in_groups import OptInGroupSet, normalize_digit_group_id
from quickquip.llm.config import DailyBriefingConfig

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
# 群名片/昵称里的 CQ 码会被剔除：播报文本与 LLM prompt 都不应携带可激活的段语法。
# 只剥 [CQ:...]（对齐 awakening.py），保留普通方括号昵称。
_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]")
_PERIOD_LABELS: dict[str, str] = {
    "morning": "早报",
    "noon": "午报",
    "evening": "晚报",
}

BriefingPeriod = Literal["morning", "noon", "evening"]


@dataclass(slots=True)
class BriefingNewsItem:
    title: str
    source: str = ""
    url: str = ""


class BriefingNewsProvider(Protocol):
    async def fetch_news(
        self,
        period: BriefingPeriod,
        now: datetime,
        limit: int,
    ) -> list[BriefingNewsItem]: ...


class NullBriefingNewsProvider:
    async def fetch_news(
        self,
        period: BriefingPeriod,
        now: datetime,
        limit: int,
    ) -> list[BriefingNewsItem]:
        _ = period, now, limit
        return []


@dataclass(slots=True)
class BriefingTopUser:
    user_id: str
    display_name: str
    message_count: int


@dataclass(slots=True)
class DailyBriefingContext:
    period: BriefingPeriod
    period_label: str
    now: datetime
    date_label: str
    weekday_label: str
    current_time_label: str
    window_label: str
    message_count: int
    active_users: list[BriefingTopUser] = field(default_factory=list)
    hot_words: list[str] = field(default_factory=list)
    sample_messages: list[dict] = field(default_factory=list)
    news_items: list[BriefingNewsItem] = field(default_factory=list)

    @property
    def has_enough_messages_for_llm(self) -> bool:
        return self.message_count > 0


def _weekday_label(dt: datetime) -> str:
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return weekdays[dt.weekday()]


def default_period_for_now(now: datetime) -> BriefingPeriod:
    """按时刻选择默认时段：[0,11)=morning，[11,18)=noon，[18,24)=evening。"""
    if now.hour < 11:
        return "morning"
    if now.hour < 18:
        return "noon"
    return "evening"


def normalize_period(raw: str) -> BriefingPeriod | None:
    normalized = raw.strip().lower()
    aliases = {
        "morning": "morning",
        "早": "morning",
        "早报": "morning",
        "早餐": "morning",
        "noon": "noon",
        "midday": "noon",
        "午": "noon",
        "午报": "noon",
        "中午": "noon",
        "evening": "evening",
        "night": "evening",
        "晚": "evening",
        "晚报": "evening",
        "晚上": "evening",
    }
    resolved = aliases.get(normalized)
    if resolved in {"morning", "noon", "evening"}:
        return resolved
    return None


def get_briefing_window(period: BriefingPeriod, now: datetime) -> tuple[datetime, datetime, str]:
    if period == "morning":
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = f"{start:%Y-%m-%d 00:00} 至 {end:%m-%d 00:00}"
        return start, end, label

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now
    label = f"{start:%Y-%m-%d 00:00} 至 {end:%m-%d %H:%M}"
    return start, end, label


def _sample_messages(messages: list[dict], limit: int) -> list[dict]:
    if len(messages) <= limit:
        selected = messages
    else:
        head_count = max(1, limit // 4)
        mid_count = max(1, limit // 4)
        tail_count = max(1, limit - head_count - mid_count)
        head = messages[:head_count]
        mid_start = max(head_count, (len(messages) - mid_count) // 2)
        mid = messages[mid_start:mid_start + mid_count]
        tail = messages[-tail_count:]

        selected = []
        seen_ids: set[int] = set()
        for item in [*head, *mid, *tail]:
            marker = id(item)
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
            selected.append(item)

    sampled: list[dict] = []
    for item in selected:
        ts = float(item.get("ts", 0))
        sampled.append(
            {
                **item,
                "time_label": datetime.fromtimestamp(ts, tz=_LOCAL_TZ).strftime("%H:%M") if ts else "",
            }
        )
    return sampled


def _build_active_users(messages: list[dict], limit: int) -> list[BriefingTopUser]:
    counts: Counter[str] = Counter()
    display_names: dict[str, str] = {}
    for entry in messages:
        user_id = str(entry.get("user_id", "")).strip()
        sender = _CQ_CODE_RE.sub("", str(entry.get("sender", ""))).strip() or "未知"
        key = user_id or sender
        counts[key] += 1
        display_names[key] = sender

    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [
        BriefingTopUser(
            user_id=key if key.isdigit() else "",
            display_name=display_names.get(key, key),
            message_count=count,
        )
        for key, count in top
    ]


def build_fallback_briefing(context: DailyBriefingContext) -> str:
    lines = [
        f"{context.period_label} | {context.date_label} 星期{context.weekday_label}",
        f"现在是北京时间 {context.current_time_label}。",
    ]

    if context.period == "morning":
        lines.append("新的一天开始了，先来简单回顾一下昨天群里的动静。")
    elif context.period == "noon":
        lines.append("今天已经过半，来看看群里的午间进度。")
    else:
        lines.append("今天差不多要收尾了，来做个轻量收官。")

    lines.append(f"统计窗口：{context.window_label}")
    lines.append(f"消息总数：{context.message_count}")

    if context.active_users:
        top_users = "，".join(
            f"{item.display_name} {item.message_count}条" for item in context.active_users[:3]
        )
        lines.append(f"活跃用户：{top_users}")

    if context.hot_words:
        lines.append(f"热词：{' / '.join(context.hot_words[:3])}")

    if context.news_items:
        lines.append(f"预留新闻位：{context.news_items[0].title}")

    return "\n".join(lines)


async def build_briefing_context(
    *,
    group_id: int | str,
    period: BriefingPeriod,
    now: datetime,
    daily_collector,
    wordcloud_collector: WordCloudCollector,
    briefing_config: DailyBriefingConfig,
    news_provider: BriefingNewsProvider | None = None,
) -> DailyBriefingContext:
    start_dt, end_dt, window_label = get_briefing_window(period, now)
    messages = daily_collector.read_window(group_id, start_dt.timestamp(), end_dt.timestamp())
    active_users = _build_active_users(messages, briefing_config.active_users_limit)
    sampled_messages = _sample_messages(messages, briefing_config.sample_messages_limit)

    wordcloud_messages = wordcloud_collector.read_window(
        group_id, start_dt.timestamp(), end_dt.timestamp()
    )
    hot_words: list[str] = []
    if wordcloud_messages:
        try:
            freq = await asyncio.to_thread(
                build_word_frequencies,
                wordcloud_messages,
                WORDCLOUD_STOPWORDS,
            )
            hot_words = [
                word
                for word, _count in sorted(freq.items(), key=lambda item: (-item[1], item[0]))
            ][:briefing_config.hot_words_limit]
        except Exception:
            logger.exception("daily_briefing: build_word_frequencies failed for group %s", group_id)

    provider = news_provider or NullBriefingNewsProvider()
    try:
        news_items = await provider.fetch_news(period, now, limit=3)
    except Exception:
        logger.exception("daily_briefing: fetch_news failed for group %s", group_id)
        news_items = []

    return DailyBriefingContext(
        period=period,
        period_label=_PERIOD_LABELS[period],
        now=now,
        date_label=now.strftime("%Y-%m-%d"),
        weekday_label=_weekday_label(now),
        current_time_label=now.strftime("%H:%M"),
        window_label=window_label,
        message_count=len(messages),
        active_users=active_users,
        hot_words=hot_words,
        sample_messages=sampled_messages,
        news_items=news_items,
    )


class DailyBriefingEnabledGroups(OptInGroupSet):
    """Manages the opt-in set of groups with daily_briefing enabled (default: off)."""

    log_label = "daily_briefing"

    def __init__(self, path: str | Path = "data/daily_briefing_groups.json"):
        super().__init__(path)

    def _normalize_group_id(self, group_id: int | str) -> str:
        return normalize_digit_group_id(group_id)
