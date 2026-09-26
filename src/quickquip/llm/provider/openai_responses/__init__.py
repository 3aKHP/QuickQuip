"""OpenAI Responses 协议后端包。

模块边界对齐移植源（prism-vesicle openai-responses/）：profiles（能力位）、
request（序列化与 call_id 记账）、response（终态解析与 usage 映射）、
stream（SSE 事件折叠状态机）、client（传输钩子与编排）、replay_guard
（历史原生回放的发送前守门）。跨协议消费的契约（历史投影层）只经本
facade 导出，不直接触碰包内实现模块。
"""
from quickquip.llm.provider.openai_responses.client import (
    OpenAIResponsesProviderClient,
)
from quickquip.llm.provider.openai_responses.replay_guard import (
    replay_guard_violations,
)
from quickquip.llm.provider.openai_responses.response import blocks_replay_valid

__all__ = [
    "OpenAIResponsesProviderClient",
    "blocks_replay_valid",
    "replay_guard_violations",
]
