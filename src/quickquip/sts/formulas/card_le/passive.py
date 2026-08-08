"""「xxx了」被动匹配：群友发言里整句「X了」。

流程：整句锚定正则命中 → X 是合法卡牌/遗物名则静默（别人已在玩梗，无需插话）→
否则交给 LLM 从词表里找语义/字面最近的真名，回复「Y了」。

按捕获词缓存最近匹配结果，降低同一「X了」的重复 LLM 调用（参考 context_rules
的 judge 缓存）。回复频率由框架在 resolve_reply 之后按 rate_limit_key 施加。
"""

from __future__ import annotations

import logging
import re
import time

from quickquip.sts import lexicon
from quickquip.sts.config import CARD_LE_PATTERN, CARD_LE_RATE_LIMIT_KEY, CARD_LE_RULE_NAME

logger = logging.getLogger(__name__)

_CARD_LE_RE = re.compile(CARD_LE_PATTERN)

# 捕获词 → (回复 or None, 过期时间戳)。None 也缓存，避免对失败词反复重试。
_NEAREST_CACHE: dict[str, tuple[str | None, float]] = {}
_NEAREST_CACHE_TTL = 300.0
_NEAREST_CACHE_MAX = 256
_MISSING = object()  # 与缓存的 None 区分的"未命中"哨兵


def _cache_get(word: str):
    entry = _NEAREST_CACHE.get(word)
    if entry is None:
        return _MISSING
    reply, expires_at = entry
    if time.time() >= expires_at:
        _NEAREST_CACHE.pop(word, None)
        return _MISSING
    return reply


def _cache_set(word: str, reply: str | None) -> None:
    if len(_NEAREST_CACHE) >= _NEAREST_CACHE_MAX:
        now_ts = time.time()
        for k, (_, exp) in list(_NEAREST_CACHE.items()):
            if exp <= now_ts:
                _NEAREST_CACHE.pop(k, None)
        if len(_NEAREST_CACHE) >= _NEAREST_CACHE_MAX:
            _NEAREST_CACHE.pop(next(iter(_NEAREST_CACHE)), None)
    _NEAREST_CACHE[word] = (reply, time.time() + _NEAREST_CACHE_TTL)


async def match_card_le(
    text: str,
    *,
    llm_service,
    group_id: int | str | None,
    chat_type: str = "group",
) -> dict | None:
    """整句「X了」命中且 X 非合法名时，返回「最近真名了」的规则回复；否则 None。"""
    m = _CARD_LE_RE.match(text)
    if not m:
        return None
    captured = m.group(1)
    if lexicon.is_card_name(captured):
        return None  # 命中真名：别人已在玩梗，静默

    cached = _cache_get(captured)
    if cached is _MISSING:
        result = await llm_service.generate_card_le_nearest(
            captured=captured,
            chat_id=group_id if group_id is not None else 0,
            chat_type=chat_type,
        )
        reply = result["reply"] if result else None
        _cache_set(captured, reply)
    else:
        reply = cached  # type: ignore[assignment]

    if not reply:
        return None
    return {
        "rule_name": CARD_LE_RULE_NAME,
        "rate_limit_key": CARD_LE_RATE_LIMIT_KEY,
        "reply": reply,
        "trigger_kind": "rule",
        "trigger_reason": f"STS「xxx了」：{captured}了 → {reply}",
    }
