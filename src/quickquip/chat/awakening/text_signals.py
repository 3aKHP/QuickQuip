"""唤醒文本信号域：纯函数层（结构清洗、分词、词重叠、extend 资格、DND 窗口）。"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE

# Common Chinese question markers for fast QA filtering
_QA_FAST_PATTERNS = re.compile(
    r"[？?]|(?:请问|求解|怎么[办样]?|如何|怎么回事|谁能帮|有没有人|有没[有谁]|求助|谁知道"
    r"|为啥|为什么|什么原因|怎样|能不能|可不可以|可以吗|是什么|怎么办|该怎么)"
)
_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\[(?:图片|语音|合并转发消息|文件|表情|视频)(?:[^\]]*)\]")
_MEANINGFUL_TEXT_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
_EXTEND_REJECT_TEXTS = {
    "?",
    "？",
    "??",
    "？？",
    "!",
    "！",
    "...",
    "…",
    "草",
    "艹",
    "好",
    "行",
    "嗯",
    "恩",
    "哦",
    "噢",
    "啊",
    "诶",
    "额",
    "呃",
    "哈",
    "哈哈",
    "哈哈哈",
    "乐",
    "笑死",
}

# Stopwords for word overlap calculation
_STOPWORDS = frozenset("的了是在我你他她它们吗呢啊吧呀哦嘛嗯么这那就也都还不")

# English stopwords filtered from latin token overlap (mirrors the Chinese set)
_LATIN_STOPWORDS = frozenset(
    "a an and are as at be been but by can com did do does for get go got had has have he her his "
    "how http https i if in io is it its just me my net no not ok of on or org our she so that "
    "the their them these they this those to use used was we were what when where which who why "
    "will with www you your".split()
)


def _is_in_dnd_window(dnd_start: str, dnd_end: str, now: datetime | None = None) -> bool:
    if not dnd_start or not dnd_end:
        return False
    try:
        sh, sm = int(dnd_start.split(":")[0]), int(dnd_start.split(":")[1])
        eh, em = int(dnd_end.split(":")[0]), int(dnd_end.split(":")[1])
    except (ValueError, IndexError):
        return False

    now_cst = now or datetime.now(ZoneInfo(BEIJING_TIMEZONE))
    current_minutes = now_cst.hour * 60 + now_cst.minute
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        return current_minutes >= start_minutes or current_minutes < end_minutes


def _strip_structural_message_parts(text: str) -> str:
    cleaned = _CQ_CODE_RE.sub(" ", text)
    cleaned = _URL_RE.sub(" ", cleaned)
    cleaned = _PLACEHOLDER_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


_VOICE_TRANSCRIPT_RE = re.compile(r"\[语音(?:\d+)?转文字：([^\]]+)\]")


def _replace_voice_transcripts(text: str) -> str:
    """把语音转写标记替换为其中的转写文本：转写是用户内容，不是结构占位符。"""
    return _VOICE_TRANSCRIPT_RE.sub(lambda m: m.group(1).strip(), text)


def _is_extend_eligible_message(message_text: str) -> bool:
    cleaned = _strip_structural_message_parts(message_text)
    if not cleaned or not _MEANINGFUL_TEXT_RE.search(cleaned):
        return False

    compact = re.sub(r"\s+", "", cleaned).lower()
    punctuationless = re.sub(r"[^\w\u4e00-\u9fff]+", "", compact, flags=re.UNICODE)
    if compact in _EXTEND_REJECT_TEXTS or punctuationless in _EXTEND_REJECT_TEXTS:
        return False
    is_short_question = (
        bool(_QA_FAST_PATTERNS.search(cleaned))
        or any(mark in cleaned for mark in "?？")
        or cleaned.rstrip().endswith(("吗", "嘛", "么"))
    )
    if len(punctuationless) < 3 and not is_short_question:
        return False
    return True


# Normalized latin/digit runs: english words, numbers and code identifiers
# (snake_case, camelCase, __dunder__) all stay intact as single tokens.
_LATIN_TOKEN_RE = re.compile(r"[a-z_][a-z0-9_]*|\d+", re.IGNORECASE)


def _extract_words(text: str) -> set[str]:
    """Extract meaningful tokens from text: Chinese unigram/bigram plus
    normalized english words, numbers and code identifiers. URLs, CQ codes
    and structural placeholders are stripped first; voice transcript markers
    are replaced by their content so spoken words still participate."""
    cleaned = _strip_structural_message_parts(_replace_voice_transcripts(text))
    words: set[str] = {
        token
        for token in _LATIN_TOKEN_RE.findall(cleaned.lower())
        if token not in _LATIN_STOPWORDS
    }
    # Keep only CJK characters, then extract bigrams + unigrams
    chars = [c for c in cleaned if "一" <= c <= "鿿"]
    for c in chars:
        if c not in _STOPWORDS:
            words.add(c)
    for i in range(len(chars) - 1):
        bigram = chars[i] + chars[i + 1]
        if chars[i] not in _STOPWORDS or chars[i + 1] not in _STOPWORDS:
            words.add(bigram)
    return words


def _word_overlap_ratio(user_text: str, bot_texts: list[str]) -> float:
    """Fast word overlap between user message and bot messages. Returns max ratio."""
    user_words = _extract_words(user_text)
    if not user_words:
        return 0.0
    max_ratio = 0.0
    for bt in bot_texts:
        bot_words = _extract_words(bt)
        if not bot_words:
            continue
        overlap = len(user_words & bot_words)
        ratio = overlap / min(len(user_words), len(bot_words))
        if ratio > max_ratio:
            max_ratio = ratio
    return max_ratio
