"""唤醒触发域：六条触发规则、指令文本、图片选取与编排入口。"""
from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from quickquip.chat.awakening.config import (
    AwakeningConfig,
    ResolvedAwakeningSettings,
    get_config,
)
from quickquip.chat.awakening.judge import (
    _QA_SYSTEM,
    _RELEVANCE_SYSTEM,
    AwakeningJudgeChannel,
    _cache_business_outcome,
    _llm_cache_text,
    _llm_judge,
    resolve_judge_settings,
)
from quickquip.chat.awakening.state import AwakeningState, get_state
from quickquip.chat.awakening.text_signals import (
    _QA_FAST_PATTERNS,
    _is_extend_eligible_message,
    _is_in_dnd_window,
    _replace_voice_transcripts,
    _strip_structural_message_parts,
    _word_overlap_ratio,
)

logger = logging.getLogger(__name__)


class LLMSettingsLike(Protocol):
    """群级 LLM 设置在唤醒域内的最小读取面。"""

    enabled: bool
    persona_id: str


class PersonaTopicsSource(Protocol):
    def persona_interest_topics(self, persona_id: str) -> list[str]: ...


@dataclass(slots=True)
class AwakeningTriggerResult:
    rule_name: str
    prompt: str
    trigger_reason: str
    trigger_instruction: str = ""
    opens_extend_window: bool = False
    matched_topic: str = ""


_PASSIVE_IMAGE_LIMIT = 2

_RULE_EXTEND = "awakening_extend"
_RULE_INTEREST = "awakening_interest"
_RULE_FALLBACK = "awakening_fallback"
_RULE_BOREDOM = "awakening_boredom"
_RULE_RELEVANCE = "awakening_relevance"
_RULE_QA = "awakening_qa"

# 唤醒规则唯一目录：(规则名, 中文标签)。adapter 命令的 status 展示与
# on/off 校验、Web Admin 的规则列表都从这里取，不再各自维护副本。
# 顺序即 /awakening status 的展示顺序。
AWAKENING_RULES: tuple[tuple[str, str], ...] = (
    (_RULE_EXTEND, "唤醒延长"),
    (_RULE_INTEREST, "兴趣话题"),
    (_RULE_FALLBACK, "兜底概率"),
    (_RULE_BOREDOM, "无聊唤醒"),
    (_RULE_RELEVANCE, "相关性唤醒"),
    (_RULE_QA, "答疑唤醒"),
)
AWAKENING_RULE_NAMES: frozenset[str] = frozenset(name for name, _label in AWAKENING_RULES)

_BOREDOM_INSTRUCTION = "群聊沉寂已久，你可以自然地冒个泡说点什么。不要说明自己是因为无聊唤醒或定时机制才发言。"
_EXTEND_INSTRUCTION = "这名群友刚刚显式召唤过你，现在仍在同一段短对话窗口内。只有能自然接上时才回应，保持简短，不要说明唤醒延长或触发机制。"
_INTEREST_INSTRUCTION_TEMPLATE = "这条群聊消息命中了你感兴趣的话题「{topic}」。请围绕这条消息自然接话，不要说明兴趣话题、关键词或唤醒机制。"
_FALLBACK_INSTRUCTION = "你低概率决定参与这条群聊。只有在能自然接上时才简短回应，不要强行扩展，不要说明兜底概率或唤醒机制。"
_RELEVANCE_INSTRUCTION = "判定结果显示用户在延续你之前的对话。请自然回应当前消息，不要说明相关性判定或唤醒机制。"
_QA_INSTRUCTION = "判定结果显示用户提出了可能需要你回答的问题。请直接回答当前问题，不要说明答疑判定或唤醒机制。"
_PASSIVE_IMAGE_INSTRUCTION = "这条触发消息包含图片，请结合图片与文字自然回应；如果图片不可见或信息不足，不要编造具体图像细节。"


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


def build_passive_trigger_raw_user_text(
    result: AwakeningTriggerResult, image_urls: list[str]
) -> str:
    text = _replace_voice_transcripts(result.prompt.strip())
    if image_urls:
        return text
    return _strip_structural_message_parts(text)


def build_awakening_prompt(
    result: AwakeningTriggerResult, image_urls: list[str] | None = None
) -> str:
    text = result.prompt.strip()
    instruction = result.trigger_instruction.strip()
    if select_passive_trigger_image_urls(result, image_urls or []):
        instruction = "\n".join(item for item in [instruction, _PASSIVE_IMAGE_INSTRUCTION] if item)
    if not instruction:
        return text
    if text:
        return f"【内部触发说明】{instruction}\n【群友消息】{text}"
    return f"【内部触发说明】{instruction}"


def _get_effective_interest_topics(
    settings: ResolvedAwakeningSettings,
    persona_id: str,
    topics_source: PersonaTopicsSource,
) -> list[str]:
    """合并配置话题与 persona 话题（去重、保序、大小写不敏感）。"""
    topics = list(settings.interest_topics)
    try:
        persona_topics = topics_source.persona_interest_topics(persona_id)
        if isinstance(persona_topics, list):
            topics.extend(str(t).strip() for t in persona_topics if str(t).strip())
    except Exception:
        # fail-soft：persona 话题读取失败时降级为仅用配置话题，不阻断触发判定
        logger.debug(
            "awakening: persona interest_topics unavailable for %s", persona_id, exc_info=True
        )
    seen: set[str] = set()
    deduped: list[str] = []
    for t in topics:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    return deduped


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
    st = state or get_state()
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
    message_text: str,
    settings: ResolvedAwakeningSettings,
    persona_id: str,
    topics_source: PersonaTopicsSource,
) -> AwakeningTriggerResult | None:
    topics = _get_effective_interest_topics(settings, persona_id, topics_source)
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
    st = state or get_state()
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
    message_text: str,
    settings: ResolvedAwakeningSettings,
    svc: AwakeningJudgeChannel | None,
    state: AwakeningState | None = None,
    timeout: float = 2.0,
    max_tokens: int = 64,
) -> AwakeningTriggerResult | None:
    """Check if user message is continuing a conversation with the bot.

    Two-stage: fast word overlap filter -> LLM judge.
    Zero LLM calls if threshold <= 0 or >= 1.0 (disabled).
    """
    if (
        settings.relevance_threshold <= 0
        or settings.relevance_threshold >= 1.0
        or not message_text.strip()
    ):
        return None

    st = state or get_state()
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
    outcome = await _llm_judge(
        svc, _RELEVANCE_SYSTEM, user_prompt, settings.relevance_threshold, timeout, max_tokens
    )
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
    message_text: str,
    settings: ResolvedAwakeningSettings,
    svc: AwakeningJudgeChannel | None,
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

    st = state or get_state()

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
    outcome = await _llm_judge(
        svc, _QA_SYSTEM, message_text.strip(), settings.qa_threshold, timeout, max_tokens
    )
    _cache_business_outcome(st, _RULE_QA, group_id, cache_text, outcome)

    if outcome.triggered is not True:
        return None

    return AwakeningTriggerResult(
        rule_name=_RULE_QA,
        prompt=message_text.strip(),
        trigger_reason="答疑唤醒：LLM确认",
        trigger_instruction=_QA_INSTRUCTION,
    )


async def check_awakening_triggers(
    group_id: int | str,
    user_id: int | str,
    message_text: str,
    llm_settings: LLMSettingsLike,
    svc: AwakeningJudgeChannel,
    *,
    state: AwakeningState | None = None,
    rule_enabled: Callable[[str], bool] | None = None,
    rate_available: Callable[[str], bool] | None = None,
    config: AwakeningConfig | None = None,
) -> AwakeningTriggerResult | None:
    if not bool(llm_settings.enabled):
        return None

    cfg = config if config is not None else get_config()
    settings = cfg.resolve_group(group_id)
    st = state or get_state()

    def _rule_enabled(rule_name: str) -> bool:
        return True if rule_enabled is None else rule_enabled(rule_name)

    def _rate_available(rule_name: str) -> bool:
        return True if rate_available is None else rate_available(rule_name)

    # Stage 1: synchronous checks (no LLM)
    if _rule_enabled(_RULE_EXTEND) and _rate_available(_RULE_EXTEND):
        result = check_extend(group_id, user_id, message_text, settings, st)
        if result is not None:
            return result

    persona_id = llm_settings.persona_id
    if _rule_enabled(_RULE_INTEREST) and _rate_available(_RULE_INTEREST):
        result = check_interest(group_id, message_text, settings, persona_id, svc)
        if result is not None:
            return result

    # Stage 2: async checks (may call LLM, gated by threshold + fast filter)
    judge = resolve_judge_settings(svc.config)

    if _rule_enabled(_RULE_RELEVANCE) and _rate_available(_RULE_RELEVANCE):
        result = await check_relevance(
            group_id, message_text, settings, svc, st, judge.timeout, judge.max_tokens
        )
        if result is not None:
            return result

    if _rule_enabled(_RULE_QA) and _rate_available(_RULE_QA):
        result = await check_qa(
            group_id, message_text, settings, svc, st, judge.timeout, judge.max_tokens
        )
        if result is not None:
            return result

    # Stage 3: fallback
    if _rule_enabled(_RULE_FALLBACK) and _rate_available(_RULE_FALLBACK):
        result = check_fallback(group_id, message_text, settings)
        if result is not None:
            return result

    return None
