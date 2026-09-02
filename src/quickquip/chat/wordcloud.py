from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from time import time
from zoneinfo import ZoneInfo

from quickquip.common.paths import WORDCLOUD_MESSAGES_DIR
from quickquip.chat.config import BEIJING_TIMEZONE

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo(BEIJING_TIMEZONE)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORDCLOUD_MIN_WORDS: int = 50
WORDCLOUD_FONT_PATH: str = "data/fonts/NotoSansSC-Regular.ttf"
WORDCLOUD_WIDTH: int = 900
WORDCLOUD_HEIGHT: int = 600
WORDCLOUD_MAX_WORDS: int = 150
WORDCLOUD_BACKGROUND_COLOR: str = "white"

# Common Chinese function words, particles, and QQ placeholder tokens to exclude.
WORDCLOUD_STOPWORDS: frozenset[str] = frozenset({
    # QQ message placeholders
    "[图片]", "[表情]", "[语音]", "[视频]", "[文件]", "[位置]", "[链接]",
    "[动画表情]", "[回复]", "[合并转发]",
    # Common Chinese particles and function words
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会",
    "着", "没有", "看", "好", "自己", "这", "那", "里", "后", "来",
    "对", "吧", "啊", "嗯", "哦", "哈", "呢", "吗", "呀", "哇", "哎",
    "但", "但是", "所以", "因为", "如果", "虽然", "然后", "还是", "或者",
    "这个", "那个", "什么", "怎么", "为什么", "可以", "应该", "已经",
    "还", "又", "再", "只", "就是", "真的", "感觉", "觉得", "知道",
    "没", "不是", "这样", "那样", "现在", "时候", "一下", "一点",
    "他", "她", "它", "我们", "你们", "他们", "大家",
})


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def _safe_group_id(group_id: int | str) -> str:
    s = str(group_id).strip()
    if not s.isdigit():
        raise ValueError(f"Invalid group_id (must be all digits): {group_id!r}")
    return s


class WordCloudCollector:
    """Appends chat messages to per-group per-date JSONL files for word cloud generation."""

    def __init__(self, base_dir: str | Path = WORDCLOUD_MESSAGES_DIR):
        self.base_dir = Path(base_dir)

    def _file_path(self, group_id: int | str, calendar_date: date) -> Path:
        return self.base_dir / _safe_group_id(group_id) / f"{calendar_date.isoformat()}.jsonl"

    def record(self, group_id: int | str, sender_name: str, text: str, ts: float | None = None) -> None:
        if not text.strip():
            return
        ts_val = ts if ts is not None else time()
        local_date = datetime.fromtimestamp(ts_val, tz=_LOCAL_TZ).date()
        path = self._file_path(group_id, local_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"sender": sender_name, "text": text, "ts": ts_val}, ensure_ascii=False)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            logger.warning("wordcloud: failed to write message for group %s", group_id)

    def read_window(self, group_id: int | str, start_ts: float, end_ts: float) -> list[dict]:
        """Return all messages in [start_ts, end_ts) sorted by timestamp."""
        start_dt = datetime.fromtimestamp(start_ts, tz=_LOCAL_TZ)
        end_dt = datetime.fromtimestamp(end_ts, tz=_LOCAL_TZ)

        dates_to_check: list[date] = []
        current = start_dt.date()
        while current <= end_dt.date():
            dates_to_check.append(current)
            current += timedelta(days=1)

        messages: list[dict] = []
        for d in dates_to_check:
            path = self._file_path(group_id, d)
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            entry = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue
                        ts_val = float(entry.get("ts", 0))
                        if start_ts <= ts_val < end_ts:
                            messages.append(entry)
            except OSError:
                logger.warning("wordcloud: failed to read messages for group %s date %s", group_id, d)

        messages.sort(key=lambda m: m.get("ts", 0))
        return messages


# ---------------------------------------------------------------------------
# Word frequency builder (CPU-bound, call via asyncio.to_thread)
# ---------------------------------------------------------------------------

def build_word_frequencies(messages: list[dict], stopwords: frozenset[str]) -> dict[str, int]:
    """Tokenize message texts with jieba and return word frequency counts."""
    import re
    import jieba  # lazy import — only needed when generating

    counter: Counter[str] = Counter()
    for msg in messages:
        text = msg.get("text", "")
        if not text:
            continue
        text = re.sub(r'\[.*?\]', '', text)
        # 未登记成员的 @ 提及渲染为 @QQ<digits> 占位符，明文 QQ 号不得进入词频统计
        text = re.sub(r'@QQ\d+', '', text)
        for word in jieba.cut(text):
            word = word.strip()
            if len(word) < 2:
                continue
            if word in stopwords:
                continue
            counter[word] += 1
    return dict(counter)


# ---------------------------------------------------------------------------
# Image renderer (CPU-bound, call via asyncio.to_thread)
# ---------------------------------------------------------------------------

def render_wordcloud_bytes(freq: dict[str, int]) -> bytes:
    """Render a word cloud image from frequency dict and return PNG bytes.

    Raises FileNotFoundError if the font file is missing.
    """
    from wordcloud import WordCloud  # lazy import

    font_path = Path(WORDCLOUD_FONT_PATH)
    if not font_path.exists():
        raise FileNotFoundError(
            f"词云字体文件不存在：{WORDCLOUD_FONT_PATH}\n"
            "请将 NotoSansSC-Regular.ttf 放置到 data/fonts/ 目录下。"
        )

    wc = WordCloud(
        font_path=str(font_path),
        width=WORDCLOUD_WIDTH,
        height=WORDCLOUD_HEIGHT,
        max_words=WORDCLOUD_MAX_WORDS,
        background_color=WORDCLOUD_BACKGROUND_COLOR,
        collocations=False,
    ).generate_from_frequencies(freq)

    from PIL import Image  # lazy import
    img: Image.Image = wc.to_image()
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
