from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.wordcloud import (
    WORDCLOUD_MIN_WORDS,
    WORDCLOUD_STOPWORDS,
    build_word_frequencies,
    render_wordcloud_bytes,
)
from quickquip.app.message_pipeline import is_admin, wordcloud_collector

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)

_SUBCOMMANDS = {"today", "week", "month", "year"}
_LABELS = {
    "today": "今日",
    "week": "近 7 天",
    "month": "近 30 天",
    "year": "近一年",
}


def _time_window(subcommand: str, now: datetime) -> tuple[float, float, str]:
    end_ts = now.timestamp()
    if subcommand == "week":
        from datetime import timedelta
        start_ts = (now - timedelta(days=7)).timestamp()
    elif subcommand == "month":
        from datetime import timedelta
        start_ts = (now - timedelta(days=30)).timestamp()
    elif subcommand == "year":
        from datetime import timedelta
        start_ts = (now - timedelta(days=365)).timestamp()
    else:  # today (default)
        subcommand = "today"
        start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return start_ts, end_ts, _LABELS[subcommand]


def setup(on_command) -> None:
    cmd = on_command("wordcloud", aliases=frozenset({"词云"}), priority=10, block=True)

    @cmd.handle()
    async def _(event):
        group_id = getattr(event, "group_id", None)
        if group_id is None:
            await cmd.finish("词云功能仅在群聊中可用。")
            return

        if not is_admin(event):
            await cmd.finish("词云功能仅管理员可用。")
            return

        # Parse subcommand from message text
        raw = str(event.get_message()).strip()
        parts = raw.split()
        # parts[0] is the command itself (/wordcloud or /词云), parts[1] is optional subcommand
        subcommand = parts[1].lower() if len(parts) > 1 else "today"
        if subcommand not in _SUBCOMMANDS:
            await cmd.finish(
                "用法：/wordcloud [today|week|month|year]\n"
                "例：/wordcloud week"
            )
            return

        now = datetime.now(tz=_LOCAL_TZ)
        start_ts, end_ts, label = _time_window(subcommand, now)

        messages = wordcloud_collector.read_window(group_id, start_ts, end_ts)
        if not messages:
            await cmd.finish(f"{label}暂无消息记录，无法生成词云。")
            return

        try:
            freq = await asyncio.to_thread(build_word_frequencies, messages, WORDCLOUD_STOPWORDS)
        except Exception:
            logger.exception("wordcloud: build_word_frequencies failed for group %s", group_id)
            await cmd.finish("词频统计失败，请稍后再试。")
            return

        if sum(freq.values()) < WORDCLOUD_MIN_WORDS:
            await cmd.finish(f"{label}有效词汇不足（需至少 {WORDCLOUD_MIN_WORDS} 个词），无法生成词云。")
            return

        try:
            png_bytes = await asyncio.to_thread(render_wordcloud_bytes, freq)
        except FileNotFoundError as e:
            await cmd.finish(str(e))
            return
        except Exception:
            logger.exception("wordcloud: render failed for group %s", group_id)
            await cmd.finish("词云图片生成失败，请稍后再试。")
            return

        b64 = base64.b64encode(png_bytes).decode()
        from nonebot.adapters.onebot.v11 import MessageSegment
        await cmd.finish(MessageSegment.image(f"base64://{b64}"))
