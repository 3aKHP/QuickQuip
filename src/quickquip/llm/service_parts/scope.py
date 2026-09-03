"""Scope mixin: group/private differentiation policies.

Extracted from ``service.py`` as the shared base that every other mixin
(ToolMixin, StateMixin, HealthMixin) reaches into for scope-key construction,
human-readable scope labels, and history/memory limit resolution.

This mixin is deliberately placed first in the ``LLMService`` MRO so its
methods are available to all other mixins via ``self.`` It depends only on
``self.config.runtime`` (history limits) and the scope-limit constants from
``service_parts.constants`` — no other mixin's state.
"""
from __future__ import annotations

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

    def _context_scope_key(self, context: ToolExecutionContext) -> str:
        if context.chat_scope:
            return context.chat_scope
        return self.build_chat_scope_key(context.group_id, context.chat_type)
