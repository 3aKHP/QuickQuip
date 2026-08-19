from __future__ import annotations

import asyncio
import logging
import random
import re
import tomllib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from time import monotonic
from typing import Any
from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE, RECENT_CONTEXT_TTL_SECONDS
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.common.json_utils import extract_json_object
from quickquip.llm.usage import usage_scope
from quickquip.common.paths import CONFIG_AWAKENING_TOML

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AwakeningDefaults:
    extend_duration: int = 0
    fallback_probability: float = 0.0
    boredom_silence_seconds: int = 0
    boredom_probability: float = 0.0
    boredom_check_interval: int = 300
    # 全局 scheduler 扫描周期（秒）。None = 未设置，回退到 boredom_check_interval；
    # boredom_check_interval 固定为群级成功唤醒冷却时间。
    boredom_scan_interval: int | None = None
    boredom_dnd_start: str = ""
    boredom_dnd_end: str = ""
    interest_topics: list[str] = field(default_factory=list)
    relevance_threshold: float = 1.0
    qa_threshold: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AwakeningDefaults:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        filtered: dict[str, Any] = {}
        for k, v in data.items():
            if k in valid and v is not None:
                if k == "interest_topics" and isinstance(v, list):
                    filtered[k] = [str(item).strip() for item in v if str(item).strip()]
                else:
                    filtered[k] = v
        return cls(**filtered)


@dataclass(slots=True)
class AwakeningGroupOverride:
    group_id: str = ""
    extend_duration: int | None = None
    fallback_probability: float | None = None
    boredom_silence_seconds: int | None = None
    boredom_probability: float | None = None
    boredom_check_interval: int | None = None
    boredom_dnd_start: str | None = None
    boredom_dnd_end: str | None = None
    interest_topics: list[str] | None = None
    relevance_threshold: float | None = None
    qa_threshold: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AwakeningGroupOverride | None:
        if not data:
            return None
        group_id = str(data.get("group_id", "")).strip()
        if not group_id:
            return None
        valid = {f.name for f in fields(cls)} - {"group_id"}
        filtered: dict[str, Any] = {"group_id": group_id}
        for k, v in data.items():
            if k in valid and v is not None:
                if k == "interest_topics" and isinstance(v, list):
                    filtered[k] = [str(item).strip() for item in v if str(item).strip()]
                else:
                    filtered[k] = v
        return cls(**filtered)


@dataclass(slots=True)
class ResolvedAwakeningSettings:
    extend_duration: int = 0
    fallback_probability: float = 0.0
    boredom_silence_seconds: int = 0
    boredom_probability: float = 0.0
    boredom_check_interval: int = 300
    boredom_dnd_start: str = ""
    boredom_dnd_end: str = ""
    interest_topics: list[str] = field(default_factory=list)
    relevance_threshold: float = 1.0
    qa_threshold: float = 1.0


@dataclass(slots=True)
class AwakeningConfig:
    defaults: AwakeningDefaults = field(default_factory=AwakeningDefaults)
    group_overrides: dict[str, AwakeningGroupOverride] = field(default_factory=dict)
    load_error: str | None = None
    source_path: Path | None = None

    def resolve_group(self, group_id: int | str) -> ResolvedAwakeningSettings:
        override = self.group_overrides.get(str(group_id))
        d = self.defaults
        if override is None:
            return ResolvedAwakeningSettings(
                extend_duration=d.extend_duration,
                fallback_probability=d.fallback_probability,
                boredom_silence_seconds=d.boredom_silence_seconds,
                boredom_probability=d.boredom_probability,
                boredom_check_interval=d.boredom_check_interval,
                boredom_dnd_start=d.boredom_dnd_start,
                boredom_dnd_end=d.boredom_dnd_end,
                interest_topics=list(d.interest_topics),
                relevance_threshold=d.relevance_threshold,
                qa_threshold=d.qa_threshold,
            )
        return ResolvedAwakeningSettings(
            extend_duration=override.extend_duration if override.extend_duration is not None else d.extend_duration,
            fallback_probability=override.fallback_probability if override.fallback_probability is not None else d.fallback_probability,
            boredom_silence_seconds=override.boredom_silence_seconds if override.boredom_silence_seconds is not None else d.boredom_silence_seconds,
            boredom_probability=override.boredom_probability if override.boredom_probability is not None else d.boredom_probability,
            boredom_check_interval=override.boredom_check_interval if override.boredom_check_interval is not None else d.boredom_check_interval,
            boredom_dnd_start=override.boredom_dnd_start if override.boredom_dnd_start is not None else d.boredom_dnd_start,
            boredom_dnd_end=override.boredom_dnd_end if override.boredom_dnd_end is not None else d.boredom_dnd_end,
            interest_topics=list(override.interest_topics) if override.interest_topics is not None else list(d.interest_topics),
            relevance_threshold=override.relevance_threshold if override.relevance_threshold is not None else d.relevance_threshold,
            qa_threshold=override.qa_threshold if override.qa_threshold is not None else d.qa_threshold,
        )


@dataclass(slots=True)
class AwakeningTriggerResult:
    rule_name: str
    prompt: str
    trigger_reason: str
    trigger_instruction: str = ""
    opens_extend_window: bool = False
    matched_topic: str = ""


@dataclass(frozen=True, slots=True)
class AwakeningExtendSession:
    timestamp: float
    source: str = "explicit_llm"


_PASSIVE_IMAGE_LIMIT = 2


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_awakening_config(path: str | Path) -> AwakeningConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AwakeningConfig(source_path=config_path)

    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return AwakeningConfig(load_error=f"无法解析 {config_path}：{exc}", source_path=config_path)

    raw = data.get("awakening", data)
    defaults = AwakeningDefaults.from_dict(raw.get("defaults"))

    overrides: dict[str, AwakeningGroupOverride] = {}
    for entry in raw.get("group_overrides", []):
        if not isinstance(entry, dict):
            continue
        ov = AwakeningGroupOverride.from_dict(entry)
        if ov is not None:
            overrides[ov.group_id] = ov

    return AwakeningConfig(
        defaults=defaults,
        group_overrides=overrides,
        source_path=config_path,
    )


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_config: AwakeningConfig = load_awakening_config(CONFIG_AWAKENING_TOML)


def get_config() -> AwakeningConfig:
    return _config


def reload_config(path: str | Path | None = None) -> None:
    global _config
    _config = load_awakening_config(path or CONFIG_AWAKENING_TOML)


def effective_boredom_scan_interval(config: AwakeningConfig | None = None) -> int:
    """APScheduler 扫描周期：新字段优先；未设置时回退旧配置的
    ``defaults.boredom_check_interval``（兼容尚未写新键的私有部署）。"""
    cfg = config if config is not None else _config
    if cfg.defaults.boredom_scan_interval is not None and cfg.defaults.boredom_scan_interval > 0:
        return cfg.defaults.boredom_scan_interval
    interval = cfg.defaults.boredom_check_interval
    return interval if interval > 0 else 300


# ---------------------------------------------------------------------------
# Runtime state (in-memory, not persisted)
# ---------------------------------------------------------------------------


class BotMessageCache:
    """Per-group cache of recent bot reply texts for relevance checking.

    Entries older than the recent-context TTL (monotonic clock) are evicted
    lazily on read; the window is shared with ``RecentMessageBuffer``.
    """

    __slots__ = ("_messages", "_ttl_seconds")
    _MAX_PER_GROUP = 5

    def __init__(self, *, ttl_seconds: float = RECENT_CONTEXT_TTL_SECONDS) -> None:
        self._messages: dict[str, deque[tuple[str, float]]] = {}
        self._ttl_seconds = ttl_seconds

    def add(self, group_id: int | str, text: str, *, now: float | None = None) -> None:
        gid = str(group_id)
        if gid not in self._messages:
            self._messages[gid] = deque(maxlen=self._MAX_PER_GROUP)
        stripped = text.strip()
        if stripped:
            self._messages[gid].append((stripped, monotonic() if now is None else now))

    def get_recent(self, group_id: int | str, *, now: float | None = None) -> list[str]:
        gid = str(group_id)
        queue = self._messages.get(gid)
        if queue is None:
            return []
        current = monotonic() if now is None else now
        while queue and (current - queue[0][1]) > self._ttl_seconds:
            queue.popleft()
        if not queue:
            del self._messages[gid]
            return []
        return [text for text, _ in queue]

    def clear_group(self, group_id: int | str) -> None:
        self._messages.pop(str(group_id), None)


class AwakeningState:
    __slots__ = (
        "_extend_sessions", "_last_message_times", "_last_boredom_trigger",
        "bot_messages", "_llm_cache",
    )

    _LLM_CACHE_TTL = 60.0
    _LLM_CACHE_MAX = 256

    def __init__(self) -> None:
        self._extend_sessions: dict[str, dict[str, AwakeningExtendSession]] = {}
        self._last_message_times: dict[str, float] = {}
        self._last_boredom_trigger: dict[str, float] = {}
        self.bot_messages = BotMessageCache()
        self._llm_cache: dict[tuple[str, str, str], tuple[bool, float]] = {}

    def record_message(self, group_id: int | str, user_id: int | str) -> None:
        self._last_message_times[str(group_id)] = monotonic()

    def mark_awakened(self, group_id: int | str, user_id: int | str, source: str = "explicit_llm") -> None:
        gid = str(group_id)
        uid = str(user_id)
        if gid not in self._extend_sessions:
            self._extend_sessions[gid] = {}
        self._extend_sessions[gid][uid] = AwakeningExtendSession(
            timestamp=monotonic(),
            source=source.strip() or "explicit_llm",
        )

    def is_in_extend_window(self, group_id: int | str, user_id: int | str, duration: int) -> bool:
        if duration <= 0:
            return False
        gid = str(group_id)
        uid = str(user_id)
        sessions = self._extend_sessions.get(gid)
        if sessions is None:
            return False
        session = sessions.get(uid)
        if session is None:
            return False
        return session.source == "explicit_llm" and (monotonic() - session.timestamp) < duration

    def get_group_silence_seconds(self, group_id: int | str) -> float | None:
        """群沉寂秒数；本进程未观察到该群消息时返回 None（未知），
        未知状态不允许无聊唤醒。"""
        ts = self._last_message_times.get(str(group_id))
        if ts is None:
            return None
        return monotonic() - ts

    def can_trigger_boredom(self, group_id: int | str, check_interval: int) -> bool:
        ts = self._last_boredom_trigger.get(str(group_id))
        if ts is None:
            return True
        return (monotonic() - ts) >= check_interval

    def mark_boredom_triggered(self, group_id: int | str) -> None:
        self._last_boredom_trigger[str(group_id)] = monotonic()

    def clear_boredom_state(self, group_id: int | str) -> None:
        """清除群的沉寂与冷却状态（群取消无聊唤醒 opt-in 时调用）。"""
        gid = str(group_id)
        self._last_message_times.pop(gid, None)
        self._last_boredom_trigger.pop(gid, None)

    def llm_cache_get(self, rule: str, group_id: int | str, text: str) -> bool | None:
        key = (rule, str(group_id), text)
        entry = self._llm_cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if (monotonic() - ts) > self._LLM_CACHE_TTL:
            del self._llm_cache[key]
            return None
        return result

    def llm_cache_set(self, rule: str, group_id: int | str, text: str, result: bool) -> None:
        if len(self._llm_cache) >= self._LLM_CACHE_MAX:
            now = monotonic()
            expired = [k for k, (_, ts) in self._llm_cache.items() if (now - ts) > self._LLM_CACHE_TTL]
            for k in expired:
                del self._llm_cache[k]
            if len(self._llm_cache) >= self._LLM_CACHE_MAX:
                oldest_key = min(self._llm_cache, key=lambda k: self._llm_cache[k][1])
                del self._llm_cache[oldest_key]
        self._llm_cache[(rule, str(group_id), text)] = (result, monotonic())

    def prune_stale(self, max_age: float = 7200) -> None:
        """只清理延长会话。沉寂时间戳与群级冷却**不做固定时限淘汰**：
        较大的 boredom_silence_seconds 会被提前满足（旧实现两小时即丢状态，
        使沉寂回到未知），取消 opt-in 的清除由 clear_boredom_state 显式负责。
        每群仅各一个浮点条目，不淘汰无增长风险。"""
        now = monotonic()
        for sessions in self._extend_sessions.values():
            stale = [uid for uid, session in sessions.items() if (now - session.timestamp) > max_age]
            for uid in stale:
                del sessions[uid]
        stale_groups = [gid for gid, sessions in self._extend_sessions.items() if not sessions]
        for gid in stale_groups:
            del self._extend_sessions[gid]


_state = AwakeningState()


def get_state() -> AwakeningState:
    return _state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Common Chinese question markers for fast QA filtering
_QA_FAST_PATTERNS = re.compile(r"[？?]|(?:请问|求解|怎么[办样]?|如何|怎么回事|谁能帮|有没有人|有没[有谁]|求助|谁知道|为啥|为什么|什么原因|怎样|能不能|可不可以|可以吗|是什么|怎么办|该怎么)")
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
    "a an and are as at be been but by can com did do does for get go got had has have he her his how http "
    "https i if in io is it its just me my net no not ok of on or org our she so that the their them these "
    "they this those to use used was we were what when where which who why will with www you your".split()
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


def _get_effective_interest_topics(
    settings: ResolvedAwakeningSettings,
    persona_id: str,
    svc: Any,
) -> list[str]:
    topics = list(settings.interest_topics)
    try:
        persona = svc.config.personas.get(persona_id)
        if persona is not None:
            persona_cfg = persona.extras.get("awakening", {})
            persona_topics = persona_cfg.get("interest_topics", [])
            if isinstance(persona_topics, list):
                topics.extend(str(t).strip() for t in persona_topics if str(t).strip())
    except Exception:
        pass
    seen: set[str] = set()
    deduped: list[str] = []
    for t in topics:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    return deduped


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


def _passive_trigger_allows_images(rule_name: str) -> bool:
    return rule_name in {_RULE_EXTEND, _RULE_INTEREST, _RULE_RELEVANCE, _RULE_QA}


def allows_recent_images(rule_name: str) -> bool:
    """Whether an awakening trigger should carry recent-buffer images.

    Boredom and the passive triggers that already accept the current
    message's images also get recent-buffer images; explicit triggers and
    the low-signal fallback do not.
    """
    return rule_name == _RULE_BOREDOM or _passive_trigger_allows_images(rule_name)


def select_passive_trigger_image_urls(
    result: AwakeningTriggerResult,
    image_urls: list[str],
    *,
    limit: int = _PASSIVE_IMAGE_LIMIT,
) -> list[str]:
    if limit <= 0 or not image_urls or not _passive_trigger_allows_images(result.rule_name):
        return []
    selected: list[str] = []
    seen: set[str] = set()
    for raw_url in image_urls:
        url = raw_url.strip()
        if not url or url in seen:
            continue
        selected.append(url)
        seen.add(url)
        if len(selected) >= limit:
            break
    return selected


def build_passive_trigger_raw_user_text(result: AwakeningTriggerResult, image_urls: list[str]) -> str:
    text = _replace_voice_transcripts(result.prompt.strip())
    if image_urls:
        return text
    return _strip_structural_message_parts(text)


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


# ---------------------------------------------------------------------------
# LLM judge helpers
# ---------------------------------------------------------------------------

_RELEVANCE_SYSTEM = (
    "你是一个仅输出 JSON 的判定器。"
    "判断用户消息是否在延续或回应 bot 之前的对话。"
    '仅输出 {"score": 0.0} 到 {"score": 1.0}，score 越高越相关。'
)

_QA_SYSTEM = (
    "你是一个仅输出 JSON 的判定器。"
    "判断用户消息是否是一个需要专业性回答的问题（而非日常闲聊问候）。"
    '仅输出 {"score": 0.0} 到 {"score": 1.0}，score 越高越需要回答。'
)

# quick-judge 结果类别：业务 true/false 可缓存；其余为技术失败，
# fail-closed（不触发群聊回复）且不得写入判定缓存。
# timeout/provider_error/invalid_json 为 awakening 层类别；service 层
# 技术失败（empty/length/provider_error/no_provider）直接透传其 outcome，
# 技术失败判定统一经 QuickJudgeResult.is_technical，不在此枚举字符串。
_JUDGE_BUSINESS_TRUE = "business_true"
_JUDGE_BUSINESS_FALSE = "business_false"
_JUDGE_TIMEOUT = "timeout"
_JUDGE_PROVIDER_ERROR = "provider_error"
_JUDGE_INVALID_JSON = "invalid_json"


@dataclass(slots=True)
class QuickJudgeOutcome:
    """awakening 层的 quick-judge 判定结果。

    ``triggered`` 为 None 表示技术失败（fail-closed）；诊断字段与
    QuickJudgeResult.to_diagnostic() 同源，另含解析状态，禁止携带
    聊天正文、prompt、模型原始响应、凭据或 endpoint。
    """

    category: str
    triggered: bool | None
    diagnostic: dict


def _parse_judge_text(text: str, threshold: float) -> bool | None:
    """严格解析业务判定；无法解析返回 None（区别于业务 false）。

    只接受完整 JSON 对象；残缺 JSON 或散文中出现的 "trigger" 字样
    一律视为不可解析（fail-closed，不写缓存）。
    """
    try:
        data = extract_json_object(text)
    except (TypeError, ValueError):
        return None
    if "score" in data:
        return float(data["score"]) >= threshold
    if "trigger" in data:
        trigger = data["trigger"]
        if isinstance(trigger, bool):
            return trigger
        if isinstance(trigger, str):
            return trigger.strip().lower() == "true"
        return bool(trigger)
    return None


def _judge_target(svc: Any) -> dict:
    """解析判定目标的 provider/model（仅诊断字段，无敏感信息）。"""
    config = getattr(svc, "config", None)
    qj = getattr(config, "quick_judge", None)
    provider_id = ""
    if qj is not None and qj.provider_id:
        provider_id = str(qj.provider_id)
    else:
        runtime = getattr(config, "runtime", None)
        provider_id = str(getattr(runtime, "default_provider", "") or "")
    model = str(getattr(qj, "model", "") or "")
    return {"provider": provider_id, "model": model}


def _cache_business_outcome(
    st: AwakeningState, rule: str, group_id: int | str, cache_text: str, outcome: QuickJudgeOutcome
) -> None:
    """仅业务 true/false 写入判定缓存；技术失败不缓存。"""
    if outcome.category == _JUDGE_BUSINESS_TRUE:
        st.llm_cache_set(rule, group_id, cache_text, True)
    elif outcome.category == _JUDGE_BUSINESS_FALSE:
        st.llm_cache_set(rule, group_id, cache_text, False)


async def _llm_judge(
    svc: Any,
    system_prompt: str,
    user_prompt: str,
    threshold: float,
    timeout: float,
    max_tokens: int,
) -> QuickJudgeOutcome:
    """Call quick_judge with timeout; classify the outcome for cache/log policy."""
    # quick_judge uses its own system_prompt; we embed ours in the user prompt
    full_prompt = f"[系统指令] {system_prompt}\n\n[待判定内容] {user_prompt}"
    started = monotonic()
    try:
        with usage_scope("awakening_judge"):
            result = await asyncio.wait_for(
                svc.quick_judge_detailed(full_prompt, max_tokens=max_tokens),
                timeout=timeout,
            )
    except asyncio.TimeoutError:
        diagnostic = {
            "outcome": _JUDGE_TIMEOUT,
            "duration_ms": round((monotonic() - started) * 1000, 2),
            **_judge_target(svc),
        }
        logger.warning("awakening: quick_judge timed out after %.1fs: %s", timeout, diagnostic)
        return QuickJudgeOutcome(_JUDGE_TIMEOUT, None, diagnostic)
    except Exception:
        diagnostic = {
            "outcome": _JUDGE_PROVIDER_ERROR,
            "duration_ms": round((monotonic() - started) * 1000, 2),
            **_judge_target(svc),
        }
        logger.warning("awakening: quick_judge call failed: %s", diagnostic, exc_info=True)
        return QuickJudgeOutcome(_JUDGE_PROVIDER_ERROR, None, diagnostic)

    diagnostic = result.to_diagnostic()
    if result.is_technical:
        logger.warning("awakening: quick_judge technical failure: %s", diagnostic)
        return QuickJudgeOutcome(result.outcome, None, diagnostic)

    parsed = _parse_judge_text(result.text, threshold)
    if parsed is None:
        merged = {**diagnostic, "parsed": False}
        logger.warning("awakening: quick_judge unparsable output: %s", merged)
        return QuickJudgeOutcome(_JUDGE_INVALID_JSON, None, merged)

    merged = {**diagnostic, "parsed": True}
    logger.debug("awakening: quick_judge resolved: %s", merged)
    return QuickJudgeOutcome(
        _JUDGE_BUSINESS_TRUE if parsed else _JUDGE_BUSINESS_FALSE, parsed, merged
    )


def _llm_cache_text(message_text: str, threshold: float) -> str:
    return f"{threshold:.6g}\0{message_text}"


# ---------------------------------------------------------------------------
# Trigger check functions
# ---------------------------------------------------------------------------

_RULE_EXTEND = "awakening_extend"
_RULE_INTEREST = "awakening_interest"
_RULE_FALLBACK = "awakening_fallback"
_RULE_BOREDOM = "awakening_boredom"
_RULE_RELEVANCE = "awakening_relevance"
_RULE_QA = "awakening_qa"

_BOREDOM_INSTRUCTION = "群聊沉寂已久，你可以自然地冒个泡说点什么。不要说明自己是因为无聊唤醒或定时机制才发言。"
_EXTEND_INSTRUCTION = "这名群友刚刚显式召唤过你，现在仍在同一段短对话窗口内。只有能自然接上时才回应，保持简短，不要说明唤醒延长或触发机制。"
_INTEREST_INSTRUCTION_TEMPLATE = "这条群聊消息命中了你感兴趣的话题「{topic}」。请围绕这条消息自然接话，不要说明兴趣话题、关键词或唤醒机制。"
_FALLBACK_INSTRUCTION = "你低概率决定参与这条群聊。只有在能自然接上时才简短回应，不要强行扩展，不要说明兜底概率或唤醒机制。"
_RELEVANCE_INSTRUCTION = "判定结果显示用户在延续你之前的对话。请自然回应当前消息，不要说明相关性判定或唤醒机制。"
_QA_INSTRUCTION = "判定结果显示用户提出了可能需要你回答的问题。请直接回答当前问题，不要说明答疑判定或唤醒机制。"
_PASSIVE_IMAGE_INSTRUCTION = "这条触发消息包含图片，请结合图片与文字自然回应；如果图片不可见或信息不足，不要编造具体图像细节。"


def build_awakening_prompt(result: AwakeningTriggerResult, image_urls: list[str] | None = None) -> str:
    text = result.prompt.strip()
    instruction = result.trigger_instruction.strip()
    if select_passive_trigger_image_urls(result, image_urls or []):
        instruction = "\n".join(item for item in [instruction, _PASSIVE_IMAGE_INSTRUCTION] if item)
    if not instruction:
        return text
    if text:
        return f"【内部触发说明】{instruction}\n【群友消息】{text}"
    return f"【内部触发说明】{instruction}"


def check_extend(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    settings: ResolvedAwakeningSettings,
    state: AwakeningState | None = None,
) -> AwakeningTriggerResult | None:
    text = message_text.strip()
    if settings.extend_duration <= 0 or not text:
        return None
    if not _is_extend_eligible_message(text):
        return None
    st = state or _state
    if not st.is_in_extend_window(group_id, user_id, settings.extend_duration):
        return None
    return AwakeningTriggerResult(
        rule_name=_RULE_EXTEND,
        prompt=text,
        trigger_reason="唤醒延长：用户在活跃窗口内继续发言",
        trigger_instruction=_EXTEND_INSTRUCTION,
    )


def check_interest(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    settings: ResolvedAwakeningSettings,
    persona_id: str,
    svc: Any,
) -> AwakeningTriggerResult | None:
    topics = _get_effective_interest_topics(settings, persona_id, svc)
    text = message_text.strip()
    if not topics or not text:
        return None
    text_lower = text.lower()
    for topic in topics:
        if topic.lower() in text_lower:
            return AwakeningTriggerResult(
                rule_name=_RULE_INTEREST,
                prompt=text,
                trigger_reason=f"兴趣话题匹配：{topic}",
                trigger_instruction=_INTEREST_INSTRUCTION_TEMPLATE.format(topic=topic),
                matched_topic=topic,
            )
    return None


def check_fallback(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    settings: ResolvedAwakeningSettings,
) -> AwakeningTriggerResult | None:
    text = message_text.strip()
    if settings.fallback_probability <= 0 or not text:
        return None
    if random.random() >= settings.fallback_probability:
        return None
    return AwakeningTriggerResult(
        rule_name=_RULE_FALLBACK,
        prompt=text,
        trigger_reason="兜底概率触发",
        trigger_instruction=_FALLBACK_INSTRUCTION,
    )


def check_boredom(
    group_id: int | str,
    settings: ResolvedAwakeningSettings,
    state: AwakeningState | None = None,
) -> AwakeningTriggerResult | None:
    if settings.boredom_silence_seconds <= 0 or settings.boredom_probability <= 0:
        return None
    if _is_in_dnd_window(settings.boredom_dnd_start, settings.boredom_dnd_end):
        return None
    st = state or _state
    silence = st.get_group_silence_seconds(group_id)
    if silence is None:
        # 本进程未观察到该群消息：沉寂未知，不允许无聊唤醒
        return None
    if silence < settings.boredom_silence_seconds:
        return None
    if not st.can_trigger_boredom(group_id, settings.boredom_check_interval):
        return None
    if random.random() >= settings.boredom_probability:
        return None
    return AwakeningTriggerResult(
        rule_name=_RULE_BOREDOM,
        prompt="",
        trigger_reason=f"无聊唤醒：沉寂 {silence:.0f}s",
        trigger_instruction=_BOREDOM_INSTRUCTION,
    )


async def check_relevance(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    settings: ResolvedAwakeningSettings,
    svc: Any,
    state: AwakeningState | None = None,
    timeout: float = 2.0,
    max_tokens: int = 64,
) -> AwakeningTriggerResult | None:
    """Check if user message is continuing a conversation with the bot.

    Two-stage: fast word overlap filter -> LLM judge.
    Zero LLM calls if threshold <= 0 or >= 1.0 (disabled).
    """
    if settings.relevance_threshold <= 0 or settings.relevance_threshold >= 1.0 or not message_text.strip():
        return None

    st = state or _state
    bot_msgs = st.bot_messages.get_recent(group_id)
    if not bot_msgs:
        return None

    # Stage 1: fast word overlap filter
    overlap = _word_overlap_ratio(message_text, bot_msgs)
    if overlap < 0.1:
        return None

    # Check LLM cache
    cache_text = _llm_cache_text(message_text, settings.relevance_threshold)
    cached = st.llm_cache_get(_RULE_RELEVANCE, group_id, cache_text)
    if cached is not None:
        if not cached:
            return None
        return AwakeningTriggerResult(
            rule_name=_RULE_RELEVANCE,
            prompt=message_text.strip(),
            trigger_reason=f"相关性唤醒：overlap={overlap:.2f}",
            trigger_instruction=_RELEVANCE_INSTRUCTION,
        )

    # Stage 2: LLM judge（仅业务 true/false 写入判定缓存；技术失败 fail-closed 不缓存）
    context_lines = [f"[bot 回复 {i+1}] {msg}" for i, msg in enumerate(bot_msgs)]
    user_prompt = "\n".join(context_lines) + f"\n[用户消息] {message_text.strip()}"
    outcome = await _llm_judge(svc, _RELEVANCE_SYSTEM, user_prompt, settings.relevance_threshold, timeout, max_tokens)
    _cache_business_outcome(st, _RULE_RELEVANCE, group_id, cache_text, outcome)

    if outcome.triggered is not True:
        return None

    return AwakeningTriggerResult(
        rule_name=_RULE_RELEVANCE,
        prompt=message_text.strip(),
        trigger_reason=f"相关性唤醒：overlap={overlap:.2f}, LLM确认",
        trigger_instruction=_RELEVANCE_INSTRUCTION,
    )


async def check_qa(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    settings: ResolvedAwakeningSettings,
    svc: Any,
    state: AwakeningState | None = None,
    timeout: float = 2.0,
    max_tokens: int = 64,
) -> AwakeningTriggerResult | None:
    """Check if user message is a question needing a professional answer.

    Two-stage: fast regex filter -> LLM judge.
    Zero LLM calls if threshold <= 0 or >= 1.0 (disabled).
    """
    if settings.qa_threshold <= 0 or settings.qa_threshold >= 1.0 or not message_text.strip():
        return None

    # Stage 1: fast regex filter - must contain question markers
    if not _QA_FAST_PATTERNS.search(message_text):
        return None

    st = state or _state

    # Check LLM cache
    cache_text = _llm_cache_text(message_text, settings.qa_threshold)
    cached = st.llm_cache_get(_RULE_QA, group_id, cache_text)
    if cached is not None:
        if not cached:
            return None
        return AwakeningTriggerResult(
            rule_name=_RULE_QA,
            prompt=message_text.strip(),
            trigger_reason="答疑唤醒：LLM缓存命中",
            trigger_instruction=_QA_INSTRUCTION,
        )

    # Stage 2: LLM judge（仅业务 true/false 写入判定缓存；技术失败 fail-closed 不缓存）
    outcome = await _llm_judge(svc, _QA_SYSTEM, message_text.strip(), settings.qa_threshold, timeout, max_tokens)
    _cache_business_outcome(st, _RULE_QA, group_id, cache_text, outcome)

    if outcome.triggered is not True:
        return None

    return AwakeningTriggerResult(
        rule_name=_RULE_QA,
        prompt=message_text.strip(),
        trigger_reason="答疑唤醒：LLM确认",
        trigger_instruction=_QA_INSTRUCTION,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def check_awakening_triggers(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    llm_settings: Any,
    svc: Any,
    *,
    state: AwakeningState | None = None,
    rule_enabled: Callable[[str], bool] | None = None,
    rate_available: Callable[[str], bool] | None = None,
) -> AwakeningTriggerResult | None:
    if not bool(getattr(llm_settings, "enabled", True)):
        return None

    cfg = get_config()
    settings = cfg.resolve_group(group_id)
    st = state or _state

    def _rule_enabled(rule_name: str) -> bool:
        return True if rule_enabled is None else rule_enabled(rule_name)

    def _rate_available(rule_name: str) -> bool:
        return True if rate_available is None else rate_available(rule_name)

    # Stage 1: synchronous checks (no LLM)
    if _rule_enabled(_RULE_EXTEND) and _rate_available(_RULE_EXTEND):
        result = check_extend(group_id, user_id, message_text, settings, st)
        if result is not None:
            return result

    persona_id = getattr(llm_settings, "persona_id", "")
    if _rule_enabled(_RULE_INTEREST) and _rate_available(_RULE_INTEREST):
        result = check_interest(group_id, user_id, message_text, settings, persona_id, svc)
        if result is not None:
            return result

    # Stage 2: async checks (may call LLM, gated by threshold + fast filter)
    qj_cfg = svc.config.quick_judge if hasattr(svc, "config") else None
    timeout = qj_cfg.timeout if qj_cfg and qj_cfg.timeout > 0 else 2.0
    max_tokens = qj_cfg.max_tokens if qj_cfg and qj_cfg.max_tokens > 0 else 64

    if _rule_enabled(_RULE_RELEVANCE) and _rate_available(_RULE_RELEVANCE):
        result = await check_relevance(group_id, user_id, message_text, settings, svc, st, timeout, max_tokens)
        if result is not None:
            return result

    if _rule_enabled(_RULE_QA) and _rate_available(_RULE_QA):
        result = await check_qa(group_id, user_id, message_text, settings, svc, st, timeout, max_tokens)
        if result is not None:
            return result

    # Stage 3: fallback
    if _rule_enabled(_RULE_FALLBACK) and _rate_available(_RULE_FALLBACK):
        result = check_fallback(group_id, user_id, message_text, settings)
        if result is not None:
            return result

    return None


# ---------------------------------------------------------------------------
# Boredom check entry point (for scheduler)
# ---------------------------------------------------------------------------


def _is_group_llm_enabled(svc: Any, group_id: int | str) -> bool:
    config = getattr(svc, "config", None)
    if getattr(config, "load_error", None):
        return False
    try:
        settings = svc.get_group_settings(group_id)
    except Exception:
        logger.debug("awakening_boredom: failed to resolve LLM settings for group %s", group_id, exc_info=True)
        return False
    return bool(getattr(settings, "enabled", False))


async def run_boredom_check(
    bot: Any,
    boredom_enabled_groups: Any,
    rule_switch: Any,
    svc: Any,
    rate_limiter: Any | None = None,
    stats_tracker: Any | None = None,
    build_reply_message: Any | None = None,
) -> None:
    """无聊唤醒巡检。``build_reply_message`` 由适配层注入（把 generate_reply
    结果转为可发送内容，带图时拼 Message）；缺省只发纯文本。"""
    cfg = get_config()
    st = get_state()
    st.prune_stale()

    for gid in boredom_enabled_groups.all_groups():
        if not rule_switch.is_enabled(gid, _RULE_BOREDOM):
            continue
        if not _is_group_llm_enabled(svc, gid):
            continue
        settings = cfg.resolve_group(gid)
        result = check_boredom(gid, settings, st)
        if result is None:
            continue
        if rate_limiter is not None and not rate_limiter.allow(_RULE_BOREDOM, "boredom_timer", group_id=gid):
            continue
        try:
            trigger_context = svc.recent_message_buffer.list_recent(gid, limit=20) if hasattr(svc, "recent_message_buffer") else []
            reply_result = await svc.generate_reply(
                group_id=gid,
                user_id="boredom_timer",
                sender_name="系统",
                prompt=build_awakening_prompt(result),
                image_urls=[],
                recent_messages=trigger_context,
                include_recent_images=True,
                raw_user_text="",
                store_user_message=False,
                message_id=None,
            )
            with bot_action_trace(
                trigger_kind="awakening",
                reason_code=_RULE_BOREDOM,
                reason_detail=result.trigger_reason,
                rule_name=_RULE_BOREDOM,
                chat_type="group",
                group_id=gid,
                user_id="boredom_timer",
                reply_preview=reply_result["reply"],
                llm_used=bool(reply_result.get("llm_used")),
                provider_id=str(reply_result.get("provider_id", "")),
                model=str(reply_result.get("model", "")),
                source="awakening.boredom_timer",
            ):
                await bot.send_group_msg(
                    group_id=int(gid),
                    message=(
                        build_reply_message(reply_result)
                        if build_reply_message is not None
                        else reply_result["reply"]
                    ),
                )
            st.mark_boredom_triggered(gid)
            st.bot_messages.add(gid, reply_result["reply"])
            if stats_tracker is not None:
                stats_tracker.record_trigger(gid, _RULE_BOREDOM)
            logger.info("awakening_boredom: sent to group %s (%s)", gid, result.trigger_reason)
        except Exception:
            logger.warning("awakening_boredom: failed for group %s", gid, exc_info=True)
