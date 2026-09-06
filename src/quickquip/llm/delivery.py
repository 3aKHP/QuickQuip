"""文本切分与交付计划（§6）：纯计算、版本固定。

对整个 Turn 完成敏感扫描与清理后冻结的字符串 ``S`` 做确定性切分：
同输入同输出；源范围连续、无重叠、无遗漏，满足
``''.join(S[a:b] for a, b in ranges) == S``。参数只影响新建计划；重试、
重放与撤回使用已存范围。

wrappers 只属于显示（超长代码块的闭合/重开围栏），不进入模型正文。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# 切分算法版本（§6.1：版本固定；变更即行为变更，需评审）。
SPLIT_ALGORITHM_VERSION = 1

# 句末标点边界（。！？.!? 后）。
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？.!?])\s*")


class SplitLimitError(ValueError):
    """单个 grapheme 超过单 Chunk 上限（§6.1.5）：拒绝该交付计划并明确终止。"""


def _is_combining(index: int, text: str) -> bool:
    return index < len(text) and unicodedata.combining(text[index]) != 0


@dataclass(frozen=True, slots=True)
class SplitParams:
    threshold: int  # 超过才自然分段
    chunk_max: int  # 单 Chunk 源文本上限

    def validate(self) -> None:
        if self.threshold <= 0 or self.chunk_max <= 0:
            raise ValueError("切分参数必须为正数")
        if self.threshold > self.chunk_max:
            raise ValueError("split_threshold 不能超过 chunk_max")


@dataclass(frozen=True, slots=True)
class ChunkRange:
    chunk_index: int
    start: int
    end: int
    prefix: str = ""
    suffix: str = ""


def _blank_line_boundaries(text: str) -> list[int]:
    """空白行边界位置（切在 ``\n\n`` 的两个换行之间，分隔换行归前段）。"""
    positions: list[int] = []
    index = 0
    while index < len(text):
        if text[index] == "\n":
            end = index
            while end < len(text) and text[end] == "\n":
                end += 1
            if end - index >= 2:
                positions.append(end)
            index = end
        else:
            index += 1
    return positions


def _merge_short_segments(
    text: str, segments: list[tuple[int, int]], threshold: int
) -> list[tuple[int, int]]:
    """连续短段按源顺序合并：选择不超过 threshold 的最后一个自然边界。"""
    merged: list[tuple[int, int]] = []
    for start, end in segments:
        if merged:
            prev_start, prev_end = merged[-1]
            if end - prev_start <= threshold:
                merged[-1] = (prev_start, end)
                continue
        merged.append((start, end))
    return merged


def _split_long_segment(text: str, start: int, end: int, chunk_max: int) -> list[tuple[int, int]]:
    """超 max 段落：换行 → 句末标点 → 空白的优先级找不超过 max 的最后边界。"""
    segments: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > chunk_max:
        window = text[cursor : cursor + chunk_max]
        candidates: list[int] = []
        newline = window.rfind("\n")
        if newline >= 0:
            candidates.append(newline + 1)
        sentence_matches = list(_SENTENCE_BOUNDARY.finditer(window))
        if sentence_matches:
            boundary = sentence_matches[-1].end()
            if boundary > 0:
                candidates.append(boundary)
        space = max(window.rfind(" "), window.rfind("　"))
        if space >= 0:
            candidates.append(space + 1)
        positive = [c for c in candidates if 0 < c <= chunk_max]
        cut = cursor + (max(positive) if positive else chunk_max)
        # 硬切尽量避开 grapheme cluster（§6.1.5）：组合标记不作为新 Chunk 的
        # 开头；调整后超出 max 说明单个 grapheme 本身超限，明确拒绝。
        while _is_combining(cut, text) and cut < end:
            cut += 1
        if cut - cursor > chunk_max:
            raise SplitLimitError(
                f"单个 grapheme 超过单 Chunk 上限（{chunk_max} code point），拒绝该交付计划"
            )
        segments.append((cursor, cut))
        cursor = cut
    if end > cursor:
        segments.append((cursor, end))
    return segments


def split_text_into_chunks(text: str, params: SplitParams) -> list[ChunkRange]:
    """确定性切分（§6.1）。空串返回空列表；还原恒等式必须成立。"""
    params.validate()
    if not text:
        return []
    if len(text) <= params.threshold and len(text) <= params.chunk_max:
        return [ChunkRange(chunk_index=0, start=0, end=len(text))]

    boundaries = _blank_line_boundaries(text)
    segments: list[tuple[int, int]] = []
    cursor = 0
    for boundary in boundaries:
        if boundary > cursor:
            segments.append((cursor, boundary))
            cursor = boundary
    if cursor < len(text):
        segments.append((cursor, len(text)))

    merged = _merge_short_segments(text, segments, params.threshold)

    final: list[tuple[int, int]] = []
    for start, end in merged:
        if end - start > params.chunk_max:
            final.extend(_split_long_segment(text, start, end, params.chunk_max))
        else:
            final.append((start, end))

    chunks = [
        ChunkRange(chunk_index=index, start=start, end=end)
        for index, (start, end) in enumerate(final)
    ]
    # 还原恒等式（§6.1.4）：任何输出都必须满足。
    reconstructed = "".join(text[c.start : c.end] for c in chunks)
    if reconstructed != text:
        raise RuntimeError("切分算法破坏源范围还原恒等式")
    return chunks


def plan_text_chunks(
    text: str,
    params: SplitParams,
    *,
    reserved_delivery_slots: int = 0,
    max_chunks: int = 64,
) -> tuple[list[ChunkRange], str | None]:
    """整个 Turn 先规划，预检剩余 Loop 交付条数（§6.1 尾段）。

    自然分段超过可用条数时合并未提交短段到 max；仍超出返回
    ``delivery_limit`` 原因（保存完整正文，不静默截尾）。
    """
    chunks = split_text_into_chunks(text, params)
    available = max_chunks - reserved_delivery_slots
    if len(chunks) <= available:
        return chunks, None
    if available <= 0:
        return [], "delivery_limit"
    # 收缩重切：把整段按可用条数均分上限收紧到 max。
    tight_max = max(params.chunk_max // available, 1)
    tight = SplitParams(threshold=min(params.threshold, tight_max), chunk_max=tight_max)
    try:
        squeezed = split_text_into_chunks(text, tight)
    except RuntimeError:
        return [], "delivery_limit"
    if len(squeezed) <= available:
        return [
            ChunkRange(chunk_index=index, start=c.start, end=c.end)
            for index, c in enumerate(squeezed)
        ], None
    return [], "delivery_limit"
