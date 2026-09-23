"""finalize_reply_text 的空正文语义：占位文本与 allow_empty 开关。"""
from __future__ import annotations

from quickquip.common.sensitive_filter import SensitiveFilter
from quickquip.llm.provider import LLMResponse
from quickquip.llm.reply_chain import finalize_reply_text


def _finalize(response: LLMResponse, *, allow_empty: bool = False) -> str:
    return finalize_reply_text(
        response,
        provider_id="fake",
        model="m",
        sensitive=SensitiveFilter(),
        scope_key="scope",
        allow_empty=allow_empty,
    )


def test_empty_text_gets_placeholder_by_default():
    text = _finalize(LLMResponse(text="", model="m"))
    assert text.strip()


def test_allow_empty_preserves_empty_text():
    response = LLMResponse(text="", model="m", generated_images=[])
    assert _finalize(response, allow_empty=True) == ""
