from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional

from quickquip.chat.config import CONTEXT_REPLY_RULES
from quickquip.chat.text_rules import build_rule_context, render_rule_reply, select_reply_template

logger = logging.getLogger(__name__)

# (rule_name, group_id, text) → (trigger_bool, expires_at_ts)
_LLM_JUDGE_CACHE: dict[tuple[str, str, str], tuple[bool, float]] = {}
_LLM_JUDGE_CACHE_TTL_SECONDS = 60.0
_LLM_JUDGE_CACHE_MAX = 512


def _llm_cache_get(key: tuple[str, str, str]) -> Optional[bool]:
    entry = _LLM_JUDGE_CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() >= expires_at:
        _LLM_JUDGE_CACHE.pop(key, None)
        return None
    return value


def _llm_cache_set(key: tuple[str, str, str], value: bool, ttl: float) -> None:
    if len(_LLM_JUDGE_CACHE) >= _LLM_JUDGE_CACHE_MAX:
        now_ts = time.time()
        for k, (_, exp) in list(_LLM_JUDGE_CACHE.items()):
            if exp <= now_ts:
                _LLM_JUDGE_CACHE.pop(k, None)
        if len(_LLM_JUDGE_CACHE) >= _LLM_JUDGE_CACHE_MAX:
            _LLM_JUDGE_CACHE.pop(next(iter(_LLM_JUDGE_CACHE)), None)
    _LLM_JUDGE_CACHE[key] = (value, time.time() + ttl)

# ═══════════════════════════════════════════════════════════════════
# 预编译正则（模块加载时一次完成）
# ═══════════════════════════════════════════════════════════════════
_COMPILED_CONTEXT_PATTERNS: list[list[re.Pattern[str]]] = [
    [re.compile(p) for p in rule.get("patterns", [])]
    for rule in CONTEXT_REPLY_RULES
]

_COMPILED_CONTEXT_CONDITIONS: list[list[re.Pattern[str]]] = [
    [re.compile(c) for c in rule.get("context_conditions", [])]
    for rule in CONTEXT_REPLY_RULES
]

for _idx, _rule in enumerate(CONTEXT_REPLY_RULES):
    if _rule.get("type", "regex_context") == "regex_context" and not _COMPILED_CONTEXT_CONDITIONS[_idx]:
        logger.warning(
            "context rule %s 是 regex_context 但未配置 context_conditions，该规则将不会触发",
            _rule.get("name", f"#{_idx}"),
        )


def _match_any(patterns: list[re.Pattern[str]], text: str) -> re.Match | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


def _check_regex_context(
    conditions: list[re.Pattern[str]],
    recent_messages: list[dict[str, str]],
    context_window: int,
) -> bool:
    """本地历史判定：在最近 N 条消息中搜索 context_conditions。空条件视为不放行。"""
    if not conditions:
        return False
    window = recent_messages[-context_window:] if len(recent_messages) > context_window else recent_messages
    for msg in window:
        if _match_any(conditions, msg.get("text", "")):
            return True
    return False


async def _check_llm_context(
    rule: dict,
    current_text: str,
    recent_messages: list[dict[str, str]],
    llm_service: Any,
    timeout: float = 2.0,
    group_id: int | str | None = None,
) -> bool:
    """
    微型 LLM 判定：用超短 prompt 做 yes/no。
    全程带 asyncio.wait_for 超时保护，防止阻塞。
    结果按 (rule_name, group_id, text) 短期缓存，降低 "好啊" 这类常见触发词的重复调用。
    """
    if llm_service is None:
        return False

    rule_name = str(rule.get("name", ""))
    cache_ttl = float(rule.get("llm_cache_ttl", _LLM_JUDGE_CACHE_TTL_SECONDS))
    cache_key = (rule_name, str(group_id) if group_id is not None else "", current_text)
    cached = _llm_cache_get(cache_key)
    if cached is not None:
        return cached

    judge_prompt = rule.get("llm_judge_prompt", "").strip()
    if not judge_prompt:
        judge_prompt = (
            "请根据最近群聊记录判断：当前消息是否在玩《新三国》电视剧的梗，"
            "或是否适合用新三国台词回复？只输出 JSON：{\"trigger\": true/false}"
        )

    history_lines = [
        f"{msg.get('sender_name', '某人')}: {msg.get('text', '')}"
        for msg in recent_messages[-10:]
    ]
    history_text = "\n".join(history_lines)

    full_prompt = (
        f"{judge_prompt}\n\n"
        f"最近群聊记录：\n{history_text}\n\n"
        f"当前消息：{current_text}\n\n"
        '请只回复一个 JSON 对象：{"trigger": true} 或 {"trigger": false}'
    )

    try:
        raw = await asyncio.wait_for(
            llm_service.quick_judge(full_prompt, max_tokens=64),
            timeout=timeout,
        )
        data = json.loads(raw.strip())
        result = bool(data.get("trigger", False))
    except asyncio.TimeoutError:
        logger.warning("LLM context judge timeout for rule %s", rule.get("name"))
        return False
    except Exception:
        logger.exception("LLM context judge failed for rule %s", rule.get("name"))
        return False

    _llm_cache_set(cache_key, result, cache_ttl)
    return result


async def match_context_rule(
    text: str,
    user_id: int | str,
    sender_name: str,
    recent_messages: list[dict[str, str]],
    now: Optional[datetime] = None,
    llm_service: Any = None,
    group_id: int | str | None = None,
) -> Optional[dict]:
    """
    语境感知规则匹配入口。
    流程：快筛(patterns) → 语境判定(regex/llm) → 渲染回复。
    """
    if not CONTEXT_REPLY_RULES:
        return None

    base_context = build_rule_context(user_id, sender_name, now=now)
    matched_rules: list[dict] = []

    for rule_index, rule in enumerate(CONTEXT_REPLY_RULES):
        compiled_patterns = _COMPILED_CONTEXT_PATTERNS[rule_index]
        current_match = _match_any(compiled_patterns, text)
        if not current_match:
            continue

        context_window = int(rule.get("context_window", 5))
        rule_type = rule.get("type", "regex_context")
        context_ok = False

        if rule_type == "llm_context":
            timeout = float(rule.get("llm_timeout", 2.0))
            context_ok = await _check_llm_context(
                rule, text, recent_messages, llm_service, timeout=timeout, group_id=group_id
            )
        else:
            conditions = _COMPILED_CONTEXT_CONDITIONS[rule_index]
            context_ok = _check_regex_context(conditions, recent_messages, context_window)

        if not context_ok:
            continue

        context = {**base_context, **current_match.groupdict()}
        template = select_reply_template(rule)
        matched_rules.append(
            {
                "rule_name": rule["name"],
                "rate_limit_key": rule.get("rate_limit_key", rule["name"]),
                "reply": render_rule_reply(template, context, current_match),
                "context": context,
                "priority": int(rule.get("priority", 0)),
                "rule_index": rule_index,
            }
        )

    if not matched_rules:
        return None

    matched_rules.sort(key=lambda item: (-item["priority"], item["rule_index"]))
    best_match = matched_rules[0]
    best_match.pop("rule_index", None)
    return best_match
