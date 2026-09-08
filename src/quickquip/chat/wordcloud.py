from __future__ import annotations

import logging
from collections import Counter
from io import BytesIO
from pathlib import Path


logger = logging.getLogger(__name__)

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
        text = re.sub(r'@QQ\d*', '', text)
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
