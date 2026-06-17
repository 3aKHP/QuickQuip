"""Scope mixin: group/private differentiation policies.

Extracted from ``service.py`` as the shared base that every other mixin
(ToolMixin, StateMixin, HealthMixin) reaches into for scope-key construction,
human-readable scope labels, and history/memory limit resolution.

This mixin is deliberately placed first in the ``LLMService`` MRO so its
methods are available to all other mixins via ``self.`` It depends only on
``self.config.runtime`` (history limits) — no other mixin's state.
"""
from __future__ import annotations

from quickquip.llm.service_parts.constants import (
    DEFAULT_PRIVATE_HISTORY_LIMIT,
    MAX_GROUP_STORED_CONVERSATION_MESSAGES,
    MAX_PRIVATE_STORED_CONVERSATION_MESSAGES,
)
from quickquip.llm.tools import ToolExecutionContext


class ScopeMixin:
    """Group/private scope key construction, labels, and history limits.

    All methods take ``chat_type`` ("group" / "private") and return the
    appropriate variant. Other mixins call these via ``self.`` — this
    mixin must stay in the MRO.
    """

    def build_chat_scope_key(self, chat_id: int | str, chat_type: str = "group") -> str:
        if chat_type == "private":
            return f"private:{chat_id}"
        return str(chat_id)

    def _scope_label(self, chat_type: str) -> str:
        return "私聊" if chat_type == "private" else "群聊"

    def _scope_subject(self, chat_type: str) -> str:
        return "当前私聊" if chat_type == "private" else "本群"

    def _memory_label(self, chat_type: str) -> str:
        return "当前私聊记忆" if chat_type == "private" else "当前群记忆"

    def _model_label(self, chat_type: str) -> str:
        return "当前私聊模型配置" if chat_type == "private" else "当前群模型配置"

    def _default_history_limit(self, chat_type: str) -> int:
        if chat_type == "private":
            return max(self.config.runtime.history_limit, DEFAULT_PRIVATE_HISTORY_LIMIT)
        return self.config.runtime.history_limit

    def get_default_history_limit(self, chat_type: str = "group") -> int:
        return self._default_history_limit(chat_type)

    def _max_stored_conversation_messages(self, chat_type: str) -> int:
        if chat_type == "private":
            return MAX_PRIVATE_STORED_CONVERSATION_MESSAGES
        return MAX_GROUP_STORED_CONVERSATION_MESSAGES

    def _history_retention_limit(self, chat_type: str) -> int:
        if chat_type == "private":
            return max(self.config.runtime.history_max_messages_per_group, MAX_PRIVATE_STORED_CONVERSATION_MESSAGES)
        return min(self.config.runtime.history_max_messages_per_group, MAX_GROUP_STORED_CONVERSATION_MESSAGES)

    def _context_scope_key(self, context: ToolExecutionContext) -> str:
        if context.chat_scope:
            return context.chat_scope
        return self.build_chat_scope_key(context.group_id, context.chat_type)
