"""``generate_reply`` 族返回形状的单一类型定义。

纯 typing 模块（无运行时依赖）：``llm/service.py`` 的返回契约与其消费者
（chat/awakening 等）共用同一份键集定义，不再各自建模宽 dict。键集按
路径漂移是既有契约——短路/错误路径只含基础四键（reply / rate_limit_key
/ rule_name / llm_used），成功路径携带 provider_id / model / images /
scope_key，agent 记录路径另含 agent_turn_row_id；「reply 为空字符串」
表示正文已由逐 Turn 交付 sink 送出（docs/dev/llm-module.md §5.1）。
"""
from __future__ import annotations

from typing import TypedDict


class ReplyResult(TypedDict, total=False):
    """``LLMService.generate_reply`` / ``generate_private_reply`` 的返回契约。"""

    reply: str
    rate_limit_key: str
    rule_name: str
    llm_used: bool
    provider_id: str
    model: str
    images: list[str]
    scope_key: str
    agent_turn_row_id: int
