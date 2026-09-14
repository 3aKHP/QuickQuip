"""OpenAI Responses 协议 client：传输钩子与编排。

复用基座 ``BaseProviderClient`` 的 HTTP 传输、fallback 链、退避重试、
trace 与 usage 计量（``_post_json`` / ``_post_stream_sse`` / complete()
模板方法）。序列化、终态解析与流折叠分别委托 request/response/stream
模块；响应折叠与交叉验证完成后才向工具循环返回结果。

历史降级重试（移植 vesicle portable checkpoint 思想）：请求以 400 失败
且携带历史原生 reasoning（密文）时，剥去历史批次 reasoning item 重试
一次——旧轮 reasoning 非协议必需，message/function_call 保留即工具事实
不丢；当前循环批次（最后一条 user 消息之后）一律不动。二次失败如实
上抛。鉴权/限流/5xx 不触发（基座已有对应处置）。

WS 路径与 attempt-commit barrier 不随本协议后端引入（1.16.1 候选专项）。
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
)
from quickquip.llm.provider.owner import build_response_owner
from quickquip.llm.provider.openai_responses.profiles import (
    DEFAULT_PROFILE_ID,
    resolve_profile,
)
from quickquip.llm.provider.openai_responses.request import build_responses_payload
from quickquip.llm.provider.openai_responses.response import parse_responses_body
from quickquip.llm.provider.openai_responses.stream import fold_stream_events

logger = logging.getLogger(__name__)


class OpenAIResponsesProviderClient(BaseProviderClient):
    def _profile(self):
        return resolve_profile(self.config.responses_profile or DEFAULT_PROFILE_ID)

    async def _build_request_parts(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = self.config.base_url.rstrip("/") + "/responses"
        headers = {
            **self.config.headers,
            "authorization": f"Bearer {self._get_api_key()}",
            "content-type": "application/json",
        }
        if self.config.user_agent:
            headers["user-agent"] = self.config.user_agent
        prepared_images = await self._prepare_request_images(request.messages)
        payload = build_responses_payload(
            request,
            self.config,
            stream=False,
            prepared_images=prepared_images,
        )
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        return url, headers, payload

    def _parse_response(self, data: dict[str, Any], fallback_model: str) -> LLMResponse:
        return parse_responses_body(
            data, provider_id=self.config.id, fallback_model=fallback_model
        )

    def _assemble_stream_response(
        self, chunks: list[dict[str, Any]], fallback_model: str
    ) -> LLMResponse:
        return fold_stream_events(
            chunks,
            provider_id=self.config.id,
            fallback_model=fallback_model,
            profile=self._profile(),
        )

    @staticmethod
    def _combine_stream_trace(
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        """流式 trace 的可读重建：有终态直接采用，失败流如实标注失败形态。

        仅服务 trace 展示；真正的语义错误由 ``_assemble_stream_response``
        抛出（此处抛错只会被基座捕获并把 trace 记为重建失败，掩盖真实
        的失败原因）。
        """
        for chunk in reversed(chunks):
            if not isinstance(chunk, dict):
                continue
            chunk_type = chunk.get("type")
            if (
                chunk_type == "response.completed"
                and isinstance(chunk.get("response"), dict)
            ):
                return chunk["response"]
            if chunk_type == "response.failed":
                return {
                    "object": "response",
                    "model": fallback_model,
                    "status": "failed",
                    "error": (chunk.get("response") or {}).get("error")
                    if isinstance(chunk.get("response"), dict)
                    else None,
                }
            if chunk_type in ("response.incomplete", "error"):
                return {
                    "object": "response",
                    "model": fallback_model,
                    "status": str(chunk_type),
                }
        return {
            "object": "response",
            "model": fallback_model,
            "status": "stream_ended_without_terminal",
            "output": [],
        }

    async def _complete_non_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        data, final_url = await self._post_json_candidate(url, headers, payload)
        response = self._parse_response(data, request.model)
        response.owner = build_response_owner(self.config, final_url, request.model)
        return response

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        payload["stream"] = True
        chunks, final_url = await self._post_stream_sse_candidate(url, headers, payload)
        response = self._assemble_stream_response(chunks, request.model)
        response.owner = build_response_owner(self.config, final_url, request.model)
        return response

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            return await super().complete(request)
        except LLMProviderError as exc:
            degraded = self._portable_history_request(request)
            if degraded is None or exc.transport or exc.status_code != 400:
                raise
            logger.warning(
                "%s responses request rejected with 400; retrying once without "
                "history reasoning items",
                self.config.id,
            )
            return await super().complete(degraded)

    def _portable_history_request(self, request: LLMRequest) -> LLMRequest | None:
        """剥历史原生 reasoning 的可重试请求；无历史密文可剥时返回 None。

        边界：最后一条 user 消息之后的 assistant/tool 消息属当前工具循环
        （协议要求原样回传，不动）；之前的 native 批次是已关闭 Loop 的
        历史，reasoning item 非必需，剥除后 message/function_call 照旧。
        """
        last_user = max(
            (index for index, m in enumerate(request.messages) if m.role == "user"),
            default=-1,
        )
        stripped_messages = []
        stripped_items = 0
        for index, message in enumerate(request.messages):
            blocks = message.native_content
            if index >= last_user or blocks is None:
                stripped_messages.append(message)
                continue
            kept = [
                block for block in blocks
                if not (isinstance(block, dict) and block.get("type") == "reasoning")
            ]
            stripped_items += len(blocks) - len(kept)
            stripped_messages.append(replace(message, native_content=kept or None))
        if not stripped_items:
            return None
        return replace(request, messages=stripped_messages)
