import math

from quickquip.llm.token_estimate import ASCII_TOKEN_RATIO, CJK_TOKEN_RATIO, estimate_tokens


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_cjk_ratio():
    # 纯中文按 0.7 token/字
    assert estimate_tokens("中" * 10) == math.ceil(10 * CJK_TOKEN_RATIO)


def test_estimate_tokens_ascii_ratio():
    # 纯 ASCII 按 0.35 token/字符
    assert estimate_tokens("a" * 10) == math.ceil(10 * ASCII_TOKEN_RATIO)


def test_estimate_tokens_fullwidth_punctuation_counts_as_cjk():
    # 全角标点（：、【】）码位在 CJK 下界之上，按中文比率计
    assert estimate_tokens("：【】") == math.ceil(3 * CJK_TOKEN_RATIO)


def test_estimate_tokens_mixed_rounds_up():
    text = "当前时间：2026-03-16 星期一"
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    expected = math.ceil(cjk * CJK_TOKEN_RATIO + (len(text) - cjk) * ASCII_TOKEN_RATIO)
    assert estimate_tokens(text) == expected


# ── 协议原生块估算 ───────────────────────────────────────────────

def test_estimate_native_block_tokens_claude_thinking_payload():
    from quickquip.llm.token_estimate import estimate_native_block_tokens

    block = {"type": "thinking", "thinking": "思" * 100, "signature": "sig-123"}
    assert estimate_native_block_tokens(block) >= math.ceil(100 * CJK_TOKEN_RATIO)


def test_estimate_native_block_tokens_tool_use_input_dict():
    from quickquip.llm.token_estimate import estimate_native_block_tokens

    block = {
        "type": "tool_use",
        "id": "call_1",
        "name": "search_web",
        "input": {"query": "镜子", "limit": 3},
    }
    assert estimate_native_block_tokens(block) > 0


def test_estimate_native_block_tokens_gemini_function_call():
    from quickquip.llm.token_estimate import estimate_native_block_tokens

    block = {"functionCall": {"name": "search_web", "args": {"query": "镜子"}}}
    assert estimate_native_block_tokens(block) > 0


def test_estimate_native_block_tokens_unknown_shape_nonzero():
    from quickquip.llm.token_estimate import estimate_native_block_tokens

    assert estimate_native_block_tokens({"type": "future_block", "payload": "x" * 100}) > 0
    assert estimate_native_block_tokens("raw-string-block") > 0
    assert estimate_native_block_tokens(None) > 0


def test_estimate_native_block_tokens_media_flat_not_base64_inflated():
    from quickquip.llm.token_estimate import (
        NATIVE_MEDIA_FLAT_TOKENS,
        estimate_native_block_tokens,
    )

    block = {"inlineData": {"mimeType": "image/png", "data": "A" * 200_000}}
    assert estimate_native_block_tokens(block) <= NATIVE_MEDIA_FLAT_TOKENS + 128


def test_estimate_native_blocks_tokens_none_and_empty():
    from quickquip.llm.token_estimate import estimate_native_blocks_tokens

    assert estimate_native_blocks_tokens(None) == 0
    assert estimate_native_blocks_tokens([]) == 0
