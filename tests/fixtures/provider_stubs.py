"""Stub LLM provider clients.

These replace build_provider_client() in LLMService tests. Each stub exposes
last_request (for assertions) and requests (for multi-call loops), all
per-instance state only — no class-level mutables.
"""
from __future__ import annotations

from plugins.llm_provider import LLMRequest, LLMResponse
from plugins.llm_tools import LLMToolCall


class StubProviderClient:
    """Records the last request and echoes the prompt back."""

    def __init__(self) -> None:
        self.last_request: LLMRequest | None = None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        prompt = request.messages[-1].content if request.messages else ""
        return LLMResponse(
            text=f"stub::{request.model}::{prompt}",
            model=request.model,
            input_tokens=11,
            output_tokens=7,
        )


class StubToolCallingProviderClient:
    """Round 1 → tool call get_identity; round 2 → final text."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id="call_identity_1",
                        name="get_identity",
                        arguments_json='{"query":"哈基镜"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="哈基镜通常指镜子。",
            model=request.model,
            finish_reason="stop",
        )


class StubMCPToolCallingProviderClient:
    """Round 1 → tool call mcp_fake_echo_text; round 2 → final text."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id="call_mcp_1",
                        name="mcp_fake_echo_text",
                        arguments_json='{"text":"云端 DOOD"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="echo::云端 DOOD",
            model=request.model,
            finish_reason="stop",
        )


class StubSearchOnlyProviderClient:
    """Rounds 1..4 → search_web; round 5 → final answer."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) <= 4:
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id=f"call_search_{len(self.requests)}",
                        name="search_web",
                        arguments_json='{"query":"QuickQuip","topic":"general"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            text="QuickQuip 是一个 QQ 群聊机器人项目。",
            model=request.model,
            finish_reason="stop",
        )


class StubReasoningLeakProviderClient:
    """Emits reasoning content that LLMService should strip before sending."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text="<think>\n内部分析\n</think>\n\n给群友看的答案",
            model=request.model,
            finish_reason="stop",
        )
