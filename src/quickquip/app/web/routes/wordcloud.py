import asyncio
import base64
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from quickquip.common.paths import WORDCLOUD_MESSAGES_DIR
from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.chat.wordcloud import (
    WORDCLOUD_MIN_WORDS,
    WORDCLOUD_STOPWORDS,
    build_word_frequencies,
    render_wordcloud_bytes,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)
_GROUP_RE = re.compile(r"^\d{5,12}$")
_WINDOWS = {"today", "week", "month", "year"}


def _validate_group(group: str) -> None:
    if not _GROUP_RE.match(group):
        raise HTTPException(status_code=422, detail="group must be 5-12 digits")


def _time_window(window: str, now: datetime) -> tuple[float, float]:
    end_ts = now.timestamp()
    if window == "week":
        start_ts = (now - timedelta(days=7)).timestamp()
    elif window == "month":
        start_ts = (now - timedelta(days=30)).timestamp()
    elif window == "year":
        start_ts = (now - timedelta(days=365)).timestamp()
    else:
        start_ts = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return start_ts, end_ts


@router.get("/wordcloud/groups")
def list_wordcloud_groups():
    base = WORDCLOUD_MESSAGES_DIR
    if not base.exists():
        return {"groups": []}
    groups = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not _GROUP_RE.match(entry.name):
            continue
        files = [f for f in entry.iterdir() if f.is_file() and f.suffix == ".jsonl"]
        if not files:
            continue
        latest_mtime = max(f.stat().st_mtime for f in files)
        total_bytes = sum(f.stat().st_size for f in files)
        groups.append({
            "group_id": entry.name,
            "days": len(files),
            "total_bytes": total_bytes,
            "latest_mtime": int(latest_mtime),
        })
    groups.sort(key=lambda g: g["latest_mtime"], reverse=True)
    return {"groups": groups}


@router.get("/wordcloud/render")
async def render_wordcloud(
    group: str = Query(..., min_length=5, max_length=12),
    window: str = Query(default="today"),
    top_k: int = Query(default=50, ge=1, le=200),
):
    _validate_group(group)
    if window not in _WINDOWS:
        raise HTTPException(status_code=422, detail=f"window must be one of {sorted(_WINDOWS)}")

    now = datetime.now(tz=_LOCAL_TZ)
    start_ts, end_ts = _time_window(window, now)

    from quickquip.app.message_pipeline import wordcloud_collector

    messages = wordcloud_collector.read_window(group, start_ts, end_ts)
    if not messages:
        raise HTTPException(status_code=404, detail="窗口内无消息记录")

    try:
        freq = await asyncio.to_thread(build_word_frequencies, messages, WORDCLOUD_STOPWORDS)
    except Exception as e:
        logger.exception("wordcloud: build_word_frequencies failed for group %s", group)
        raise HTTPException(status_code=500, detail=f"词频统计失败：{e}")

    word_count = sum(freq.values())
    if word_count < WORDCLOUD_MIN_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"有效词汇不足（{word_count} < {WORDCLOUD_MIN_WORDS}），无法生成词云",
        )

    try:
        png_bytes = await asyncio.to_thread(render_wordcloud_bytes, freq)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("wordcloud: render failed for group %s", group)
        raise HTTPException(status_code=500, detail=f"渲染失败：{e}")

    top_words = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return {
        "image_base64": base64.b64encode(png_bytes).decode("ascii"),
        "message_count": len(messages),
        "word_count": word_count,
        "unique_words": len(freq),
        "top_words": [{"word": w, "count": c} for w, c in top_words],
        "window": window,
        "group": group,
    }
