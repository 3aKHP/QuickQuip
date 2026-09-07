"""字符级 token 粗估：中文 ≈0.7 token/字、ASCII ≈0.35 token/字符。

账本（信封/现场补丁）与纪元预算共用的定标换算比（dev/research 口径，
由生产 usage 拟合验证），不引入 tokenizer 依赖；以 usage 实际值持续校准。
"""
from __future__ import annotations

import math
from typing import Any

CJK_TOKEN_RATIO = 0.7
ASCII_TOKEN_RATIO = 0.35

# 粗判 CJK 与全角符号的下界（⼀ U+2E80 起），之上的码位按中文比率计。
_CJK_ORD_FLOOR = 0x2E80

# 协议原生块内媒体载荷（inlineData/fileData）的固定档估算（与请求预算口径一致）。
NATIVE_MEDIA_FLAT_TOKENS = 1200
# 每个原生块的结构开销（块类型、id、字段名的 wire 折算下界）。
_NATIVE_BLOCK_STRUCTURE_TOKENS = 8


def estimate_tokens(text: str) -> int:
    """按字符类别加权的 token 粗估，向上取整；空串为 0。"""
    cjk = sum(1 for ch in text if ord(ch) >= _CJK_ORD_FLOOR)
    return math.ceil(cjk * CJK_TOKEN_RATIO + (len(text) - cjk) * ASCII_TOKEN_RATIO)


def _estimate_block_value(value: Any) -> int:
    if isinstance(value, str):
        return estimate_tokens(value)
    if isinstance(value, dict):
        return estimate_native_block_tokens(value)
    if isinstance(value, bool) or value is None:
        return 1
    if isinstance(value, (int, float)):
        return 2
    if isinstance(value, list):
        return sum(_estimate_block_value(item) for item in value)
    return estimate_tokens(str(value))


def estimate_native_block_tokens(block: Any) -> int:
    """协议原生内容块的字段级估算：遍历字段取载荷，未知形态保底非零。

    字符串字段（thinking/text/signature/参数 JSON 串等）按字符类别估；
    dict 字段（tool_use.input、functionCall.args 等）递归；
    媒体载荷（inlineData/fileData）按固定档，避免 base64 全量高估。
    """
    if not isinstance(block, dict):
        return estimate_tokens(str(block)) + _NATIVE_BLOCK_STRUCTURE_TOKENS
    total = _NATIVE_BLOCK_STRUCTURE_TOKENS
    for key, value in block.items():
        if key in ("inlineData", "fileData"):
            total += NATIVE_MEDIA_FLAT_TOKENS
            continue
        total += _estimate_block_value(value)
    return total


def estimate_native_blocks_tokens(blocks: list[Any] | None) -> int:
    """一组原生/中间表示内容块的估算；None/空为 0。"""
    if not blocks:
        return 0
    return sum(estimate_native_block_tokens(block) for block in blocks)


