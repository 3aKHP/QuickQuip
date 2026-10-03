import math

from quickquip.llm.token_estimate import (
    ASCII_TOKEN_RATIO,
    CJK_TOKEN_RATIO,
    NATIVE_ENCRYPTED_TOKENS_BY_EFFORT,
    NATIVE_MEDIA_FLAT_TOKENS,
    encrypted_payload_flat_tokens,
    estimate_native_block_tokens,
    estimate_native_blocks_tokens,
    estimate_tokens,
)


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
    assert estimate_tokens("ab中文") == math.ceil(2 * CJK_TOKEN_RATIO + 2 * ASCII_TOKEN_RATIO)


# ── 协议原生块估算 ───────────────────────────────────────────────

def test_estimate_native_block_tokens_claude_thinking_payload():
    block = {"type": "thinking", "thinking": "思" * 100, "signature": "sig-123"}
    assert estimate_native_block_tokens(block) >= math.ceil(100 * CJK_TOKEN_RATIO)


def test_estimate_native_block_tokens_tool_use_input_dict():
    block = {
        "type": "tool_use",
        "id": "call_1",
        "name": "search_web",
        "input": {"query": "镜子", "limit": 3},
    }
    assert estimate_native_block_tokens(block) > 0


def test_estimate_native_block_tokens_gemini_function_call():
    block = {"functionCall": {"name": "search_web", "args": {"query": "镜子"}}}
    assert estimate_native_block_tokens(block) > 0


def test_estimate_native_block_tokens_unknown_shape_nonzero():
    # 载荷长度下界：固定值兜底实现（如恒返 1）无法通过。
    assert estimate_native_block_tokens(
        {"type": "future_block", "payload": "x" * 100}
    ) >= math.ceil(100 * ASCII_TOKEN_RATIO)
    assert estimate_native_block_tokens("raw-string-block") > 0
    assert estimate_native_block_tokens(None) > 0


def test_estimate_native_block_tokens_media_flat_not_base64_inflated():
    # 媒体载荷按固定档计量，体积增长不改变估算。
    block = {"inlineData": {"mimeType": "image/png", "data": "A" * 200_000}}
    small = {"inlineData": {"mimeType": "image/png", "data": "A"}}
    assert estimate_native_block_tokens(block) == estimate_native_block_tokens(small)
    assert estimate_native_block_tokens(block) - estimate_native_block_tokens({}) == (
        NATIVE_MEDIA_FLAT_TOKENS
    )


def test_estimate_native_blocks_tokens_none_and_empty():
    assert estimate_native_blocks_tokens(None) == 0
    assert estimate_native_blocks_tokens([]) == 0


# ── 密文 per-effort 估算 ─────────────────────────────────────────


def test_encrypted_effort_mapping_covers_config_vocabulary():
    """密文档位表与 config 六档词表一一对应（防词表漂移漏档）。"""
    from quickquip.llm.config import REASONING_EFFORT_CHOICES

    assert set(NATIVE_ENCRYPTED_TOKENS_BY_EFFORT) == set(REASONING_EFFORT_CHOICES)


def test_encrypted_payload_flat_tokens_tier_ordering():
    """档位越高预留越大；留空档按默认档画像。"""
    efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    values = [encrypted_payload_flat_tokens(effort, 0) for effort in efforts]
    assert values == sorted(values)
    assert values[0] < values[-1]


def test_encrypted_payload_flat_tokens_byte_floor():
    """大条目按 b64/4 字节口径兜底（防档位表低估超大密文）。"""
    # 档位值之下：固定档生效
    assert encrypted_payload_flat_tokens("low", 100) == 64
    # 超出档位值：字节下限生效
    assert encrypted_payload_flat_tokens("low", 100_000) == 100_000 // 4
    assert encrypted_payload_flat_tokens("max", 100_000) == 100_000 // 4
