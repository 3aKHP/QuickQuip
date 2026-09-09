"""总结族模型响应的统一接受策略。"""
from __future__ import annotations

from typing import Protocol


class _Response(Protocol):
    text: str
    finish_reason: str | None


NORMAL_FINISH_REASONS: frozenset[str] = frozenset(
    {"stop", "end_turn", "stop_sequence", "eos"}
)


def classify_response(response: _Response, *, feature: str = "summary") -> str:
    """返回总结生成器使用的持久化响应结果。"""
    text = response.text.strip()
    if feature == "briefing":
        from quickquip.llm.provider import strip_leading_reasoning_content
        text = strip_leading_reasoning_content(text).strip()
    if not text:
        return "discarded_empty"
    finish = (response.finish_reason or "").strip().lower()
    if finish and finish not in NORMAL_FINISH_REASONS:
        return "discarded_finish"
    return "accepted"


def is_response_accepted(response: _Response, *, feature: str = "summary") -> bool:
    return classify_response(response, feature=feature) == "accepted"
