"""
NoneBot2 plugin adapter for LLMService.

This module re-exports ``LLMService`` / ``llm_service`` / ``ResolvedGroupSettings``
from ``quickquip.llm.service`` for backward compatibility.  The NoneBot2 command
handlers that use llm_service live in ``quickquip/adapters/nonebot/commands.py``.
"""
from __future__ import annotations

from quickquip.llm.service import (
    LLMService,
    llm_service,
    LLM_RULE_NAME,
    MAX_TRIGGER_CONTEXT_MESSAGES,
    MAX_GROUP_STORED_CONVERSATION_MESSAGES,
    MAX_PRIVATE_STORED_CONVERSATION_MESSAGES,
    MAX_MEMORY_RETRIEVAL_ITEMS,
    MAX_STORED_MEMORY_ITEMS,
    MAX_QUOTED_MESSAGE_CHARS,
    SEARCH_TOOL_NAME,
    SEARCH_TOOL_FAILSAFE_MAX_ROUNDS,
    SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND,
    DEFAULT_PRIVATE_HISTORY_LIMIT,
    PRIVATE_UNAVAILABLE_TOOLS,
    DEFAULT_ENABLED_TOOLS,
)
from quickquip.llm.settings import ResolvedGroupSettings

__all__ = [
    "LLMService",
    "llm_service",
    "LLM_RULE_NAME",
    "MAX_TRIGGER_CONTEXT_MESSAGES",
    "MAX_GROUP_STORED_CONVERSATION_MESSAGES",
    "MAX_PRIVATE_STORED_CONVERSATION_MESSAGES",
    "MAX_MEMORY_RETRIEVAL_ITEMS",
    "MAX_STORED_MEMORY_ITEMS",
    "MAX_QUOTED_MESSAGE_CHARS",
    "SEARCH_TOOL_NAME",
    "SEARCH_TOOL_FAILSAFE_MAX_ROUNDS",
    "SEARCH_TOOL_FAILSAFE_MAX_CALLS_PER_ROUND",
    "DEFAULT_PRIVATE_HISTORY_LIMIT",
    "PRIVATE_UNAVAILABLE_TOOLS",
    "DEFAULT_ENABLED_TOOLS",
    "ResolvedGroupSettings",
]
