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
# 原生块内不透明加密载荷（Responses reasoning 密文 encrypted_content）的
# 固定档预留：密文字节数与回放时实际计入的 reasoning token 无线性关系，
# 字符折算会系统性高估请求输入；按生成档位的 per-effort 固定档 + 单条字节
# 下限保护（max(档位值, b64 字符数/4)）预留（循环内续接与跨轮历史回放同
# 口径）。档位初值为 2026-09-18 定调量级，梯度经 2026-10-03 实测画像确认
# （low 档单条 ~1.7KB、实付 ~100 tok；max 档单条 1.4-4.3KB、实付 ~500 tok、
# 单轮 11-17 条），随 usage 实付持续校准（juice 漂移风险由此对冲）。
NATIVE_ENCRYPTED_TOKENS_DEFAULT = 64
NATIVE_ENCRYPTED_TOKENS_BY_EFFORT = {
    "low": 64,
    "medium": 256,
    "high": 1024,
    "xhigh": 4096,
    "max": 8192,
    "ultra": 8192,
}
# 每个原生块的结构开销（块类型、id、字段名的 wire 折算下界）。
_NATIVE_BLOCK_STRUCTURE_TOKENS = 8
# 按字段名固定档计量的载荷（媒体 base64），避免全量字符折算；密文
# encrypted_content 走 encrypted_payload_flat_tokens 的 per-effort 口径。
_FLAT_FIELD_TOKENS = {
    "inlineData": NATIVE_MEDIA_FLAT_TOKENS,
    "fileData": NATIVE_MEDIA_FLAT_TOKENS,
}


def encrypted_payload_flat_tokens(effort: str | None, payload_chars: int) -> int:
    """单条不透明密文的估算：per-effort 固定档与字节下限（b64/4）取大。

    未知/留空档按默认档画像预留（对应模型默认档的实测分布）。
    """
    tier = NATIVE_ENCRYPTED_TOKENS_BY_EFFORT.get(
        (effort or "").strip().lower(), NATIVE_ENCRYPTED_TOKENS_DEFAULT
    )
    return max(tier, payload_chars // 4)


def estimate_tokens(text: str) -> int:
    """按字符类别加权的 token 粗估，向上取整；空串为 0。"""
    cjk = sum(1 for ch in text if ord(ch) >= _CJK_ORD_FLOOR)
    return math.ceil(cjk * CJK_TOKEN_RATIO + (len(text) - cjk) * ASCII_TOKEN_RATIO)


def _estimate_block_value(value: Any, effort: str | None) -> int:
    if isinstance(value, str):
        return estimate_tokens(value)
    if isinstance(value, dict):
        return estimate_native_block_tokens(value, effort=effort)
    if isinstance(value, bool) or value is None:
        return 1
    if isinstance(value, (int, float)):
        return 2
    if isinstance(value, list):
        return sum(_estimate_block_value(item, effort) for item in value)
    return estimate_tokens(str(value))


def estimate_native_block_tokens(block: Any, *, effort: str | None = None) -> int:
    """协议原生内容块的字段级估算：遍历字段取载荷，未知形态保底非零。

    字符串字段（thinking/text/signature/参数 JSON 串等）按字符类别估；
    dict 字段（tool_use.input、functionCall.args 等）递归；
    媒体载荷（inlineData/fileData）按固定档，避免 base64 全量高估；
    密文载荷（encrypted_content）按 effort 分档 + 字节下限（effort 为
    生成该密文的配置档位，回放下同一 owner 的密文与当前请求同档）。
    """
    if not isinstance(block, dict):
        return estimate_tokens(str(block)) + _NATIVE_BLOCK_STRUCTURE_TOKENS
    total = _NATIVE_BLOCK_STRUCTURE_TOKENS
    for key, value in block.items():
        if key == "encrypted_content":
            chars = len(value) if isinstance(value, str) else 0
            total += encrypted_payload_flat_tokens(effort, chars)
            continue
        if key in _FLAT_FIELD_TOKENS:
            total += _FLAT_FIELD_TOKENS[key]
            continue
        total += _estimate_block_value(value, effort)
    return total


def estimate_native_blocks_tokens(
    blocks: list[Any] | None, *, effort: str | None = None
) -> int:
    """一组原生/中间表示内容块的估算；None/空为 0。"""
    if not blocks:
        return 0
    return sum(estimate_native_block_tokens(block, effort=effort) for block in blocks)


