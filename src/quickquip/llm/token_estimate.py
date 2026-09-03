"""字符级 token 粗估：中文 ≈0.7 token/字、ASCII ≈0.35 token/字符。

账本（信封/现场补丁）与纪元预算共用的定标换算比（dev/research 口径，
由生产 usage 拟合验证），不引入 tokenizer 依赖；以 usage 实际值持续校准。
"""
from __future__ import annotations

import math

CJK_TOKEN_RATIO = 0.7
ASCII_TOKEN_RATIO = 0.35

# 粗判 CJK 与全角符号的下界（⼀ U+2E80 起），之上的码位按中文比率计。
_CJK_ORD_FLOOR = 0x2E80


def estimate_tokens(text: str) -> int:
    """按字符类别加权的 token 粗估，向上取整；空串为 0。"""
    cjk = sum(1 for ch in text if ord(ch) >= _CJK_ORD_FLOOR)
    return math.ceil(cjk * CJK_TOKEN_RATIO + (len(text) - cjk) * ASCII_TOKEN_RATIO)
