"""OpenAI Responses 协议后端包。

模块边界对齐移植源（prism-vesicle openai-responses/）：profiles（能力位）、
request（序列化与 call_id 记账）、response（终态解析与 usage 映射）、
stream（SSE 事件折叠状态机）、client（传输钩子与编排）。
"""
from quickquip.llm.provider.openai_responses.client import (
    OpenAIResponsesProviderClient,
)

__all__ = ["OpenAIResponsesProviderClient"]
