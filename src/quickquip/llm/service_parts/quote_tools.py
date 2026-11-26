"""query_group_quotes 工具 Mixin（#343）。

从 tools.py 拆出的独立 mixin，遵循 draw_svg / schedule_messages_tool 模式。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from quickquip.llm.quote_tools import (
    QUERY_GROUP_QUOTES_SPEC,
    QuoteToolDeps,
    redact_quote_arguments,
    run_group_quote_query,
)
from quickquip.llm.tools import LLMToolOutput, ToolExecutionContext

if TYPE_CHECKING:
    from quickquip.chat.group_quotes import GroupQuoteStore


class QuoteToolMixin:
    def bind_group_quote_store(self, store: "GroupQuoteStore | None") -> None:
        self.group_quote_store = store

    def register_quote_tools(self) -> None:
        self.tool_registry.register(
            QUERY_GROUP_QUOTES_SPEC,
            self._tool_query_group_quotes,
            category="group",
            keywords=["语录", "群语录", "名言", "金句", "黑历史", "quote", "收藏"],
            result_retention="ephemeral",
            redact_arguments=redact_quote_arguments,
        )

    def _quote_deps(self) -> QuoteToolDeps | None:
        store = getattr(self, "group_quote_store", None)
        if store is None:
            return None
        return QuoteToolDeps(
            quote_store=store,
            resolve_speaker=lambda gid, query: sorted(
                self._identity_repository.snapshot(str(gid)).candidates(query)
            ),
            get_identity_snapshot=lambda gid: self._identity_repository.snapshot(str(gid)),
        )

    async def _tool_query_group_quotes(
        self,
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> LLMToolOutput:
        return await run_group_quote_query(arguments, context, self._quote_deps())
