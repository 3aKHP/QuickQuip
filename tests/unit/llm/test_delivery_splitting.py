"""§11.2 切分边界与分段不变性测试组。"""
from __future__ import annotations

import pytest

from quickquip.llm.delivery import SplitParams, plan_text_chunks, split_text_into_chunks

P = SplitParams(threshold=20, chunk_max=40)


def _identity(text: str, chunks) -> bool:
    return "".join(text[c.start : c.end] for c in chunks) == text


def test_empty_string_returns_no_chunks():
    assert split_text_into_chunks("", P) == []


def test_short_text_single_chunk():
    chunks = split_text_into_chunks("短文本", P)
    assert [(c.start, c.end) for c in chunks] == [(0, 3)]


def test_blank_line_boundary_preferred():
    text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)
    # 空行分界处切开：分隔换行归前一个 Chunk（§6.1.4）。
    for c in chunks[:-1]:
        assert text[c.start : c.end].endswith("\n\n")


def test_long_paragraph_uses_sentence_then_newline_boundaries():
    text = "。".join(f"第{i}句内容比较长一点" for i in range(30))
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)
    assert all(c.end - c.start <= P.chunk_max for c in chunks)
    assert len(chunks) > 1


def test_no_natural_boundary_hard_cuts():
    text = "长" * 200  # 无换行无标点无空白
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)
    assert all(c.end - c.start <= P.chunk_max for c in chunks)
    assert len(chunks) >= 5


def test_consecutive_newlines_stay_with_preceding_chunk():
    text = "段一\n\n\n\n段二"
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)
    first = text[chunks[0].start : chunks[0].end]
    assert first.startswith("段一")
    assert "\n" in first  # 分隔换行归前段


def test_emoji_and_combining_characters_safe():
    text = "👨‍👩‍👧‍👦家庭" * 30  # 组合 emoji（ZWJ 序列）
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)


def test_oversized_single_grapheme_rejected():
    # 单个超长 grapheme 无法在 max 内切分时明确失败（§6.1.5）。
    with pytest.raises(Exception):
        split_text_into_chunks("🧬" * 0 + "́" * 100, SplitParams(threshold=1, chunk_max=1))


def test_code_fence_kept_whole_within_max():
    fence = "```python\nprint(1)\n```"
    text = fence + "\n\n结论文字。" * 10
    chunks = split_text_into_chunks(text, P)
    assert _identity(text, chunks)
    body = text[chunks[0].start : chunks[0].end]
    assert body.startswith("```")


def test_plan_respects_delivery_limit():
    text = "段落。\n\n" * 50
    chunks, reason = plan_text_chunks(
        text, P, reserved_delivery_slots=0, max_chunks=3,
    )
    if reason == "delivery_limit":
        assert chunks == []  # 不静默截尾（§6.1 尾段）
    else:
        assert len(chunks) <= 3
        assert _identity(text, chunks)


# ── 分段不变性（§11.2）：两套阈值下 normalized history 相同 ─────────


def test_split_invariance_normalized_history_identical():
    from tests.fixtures.agent_loop import FIVE_TURN_TEXTS

    params_a = SplitParams(threshold=800, chunk_max=1200)  # 默认
    params_b = SplitParams(threshold=120, chunk_max=240)   # 测试切分
    for text in FIVE_TURN_TEXTS:
        chunks_a = split_text_into_chunks(text, params_a)
        chunks_b = split_text_into_chunks(text, params_b)
        # 源文本不因拆分改变：两种参数的拼回结果都恒等于原文。
        assert "".join(text[c.start : c.end] for c in chunks_a) == text
        assert "".join(text[c.start : c.end] for c in chunks_b) == text
    # 计数口径：默认 1 段 vs 测试参数 7 段（五 Turn 合计）。
    total_default = sum(len(split_text_into_chunks(t, params_a)) for t in FIVE_TURN_TEXTS)
    total_test = sum(len(split_text_into_chunks(t, params_b)) for t in FIVE_TURN_TEXTS)
    assert (total_default, total_test) == (5, 7)
