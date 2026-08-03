"""Google Gemini generateContent API provider client."""
from __future__ import annotations

import json
from typing import Any
from urllib import parse

from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMRequest,
    LLMResponse,
    _json_string,
    sanitize_gemini_schema,
)


class GeminiProviderClient(BaseProviderClient):
    async def _serialize_user_parts(self, message: LLMConversationMessage) -> list[dict[str, Any]]:
        image_inputs = await self._prepare_image_inputs(message.image_urls)
        parts: list[dict[str, Any]] = [
            *[
                {
                    "inline_data": {
                        "mime_type": item.media_type,
                        "data": item.data_base64,
                    }
                }
                for item in image_inputs
            ]
        ]
        if message.content:
            parts.append({"text": message.content})
        return parts or [{"text": ""}]

    async def _serialize_messages(self, messages: list[LLMConversationMessage]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        pending_tool_results: list[LLMConversationMessage] = []

        def _flush_tool_results() -> None:
            nonlocal pending_tool_results
            if not pending_tool_results:
                return
            serialized.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": item.tool_name,
                                "response": {
                                    "content": item.content,
                                    "is_error": item.is_tool_error,
                                },
                            }
                        }
                        for item in pending_tool_results
                    ],
                }
            )
            pending_tool_results = []

        for message in messages:
            if message.role == "tool":
                pending_tool_results.append(message)
                continue

            _flush_tool_results()
            if message.role == "assistant":
                parts: list[dict[str, Any]] = []
                if message.content:
                    parts.append({"text": message.content})
                for call in message.tool_calls:
                    try:
                        args = json.loads(call.arguments_json or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({"functionCall": {"name": call.name, "args": args}})
                serialized.append({"role": "model", "parts": parts or [{"text": ""}]})
                continue

            serialized.append({"role": "user", "parts": await self._serialize_user_parts(message)})

        _flush_tool_results()
        return serialized

    async def _build_request_parts(self, request: LLMRequest, *, stream: bool = False) -> tuple[str, dict[str, str], dict[str, Any]]:
        api_key = self._get_api_key()
        action = "streamGenerateContent" if stream else "generateContent"
        url = self.config.base_url.rstrip("/") + f"/models/{request.model}:{action}?key={parse.quote(api_key)}"
        if stream:
            url += "&alt=sse"
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": await self._serialize_messages(request.messages),
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        if request.thinking_budget is not None:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": request.thinking_budget,
            }
        if request.allow_tool_calls and request.tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": spec.name,
                            "description": spec.description,
                            "parameters": sanitize_gemini_schema(spec.input_schema),
                        }
                        for spec in request.tools
                    ]
                }
            ]
        headers = {
            "content-type": "application/json",
            **self.config.headers,
        }
        if self.config.user_agent:
            headers["user-agent"] = self.config.user_agent
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        return url, headers, payload

    @staticmethod
    def _parse_candidate(candidate: dict[str, Any], fallback_model: str) -> LLMResponse:
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for index, item in enumerate(parts if isinstance(parts, list) else [], 1):
            if not isinstance(item, dict):
                continue
            if item.get("thought") is True:
                continue
            if "text" in item:
                text_parts.append(str(item.get("text", "")))
            if "functionCall" in item:
                function_call = item.get("functionCall", {})
                tool_calls.append(
                    LLMToolCall(
                        id=f"tool_{index}",
                        name=str(function_call.get("name", "")).strip(),
                        arguments_json=_json_string(function_call.get("args", {})),
                    )
                )
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=fallback_model,
            tool_calls=tool_calls,
            finish_reason=str(candidate.get("finishReason", "")).strip() or None,
        )

    @staticmethod
    def _assemble_stream_response(chunks: list[dict[str, Any]], fallback_model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        finish_reason: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        tool_counter = 0

        for chunk in chunks:
            candidates = chunk.get("candidates", [])
            if isinstance(candidates, list) and candidates:
                candidate = candidates[0] if isinstance(candidates[0], dict) else {}
                content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
                parts = content.get("parts", []) if isinstance(content, dict) else []
                for item in parts if isinstance(parts, list) else []:
                    if not isinstance(item, dict):
                        continue
                    if item.get("thought") is True:
                        continue
                    if "text" in item:
                        text_parts.append(str(item.get("text", "")))
                    if "functionCall" in item:
                        tool_counter += 1
                        function_call = item.get("functionCall", {})
                        tool_calls.append(
                            LLMToolCall(
                                id=f"tool_{tool_counter}",
                                name=str(function_call.get("name", "")).strip(),
                                arguments_json=_json_string(function_call.get("args", {})),
                            )
                        )
                if candidate.get("finishReason"):
                    finish_reason = str(candidate["finishReason"])
            usage = chunk.get("usageMetadata", {})
            if isinstance(usage, dict):
                if usage.get("promptTokenCount") is not None:
                    input_tokens = usage["promptTokenCount"]
                if usage.get("candidatesTokenCount") is not None:
                    output_tokens = usage["candidatesTokenCount"]

        return LLMResponse(
            text="".join(text_parts).strip(),
            model=fallback_model,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _combine_stream_trace(
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        combined: dict[str, Any] = {"candidates": []}
        candidates: dict[int, dict[str, Any]] = {}

        for chunk in chunks:
            for key, value in chunk.items():
                if key not in {"candidates", "usageMetadata", "_sse_event"}:
                    combined[key] = value
            if isinstance(chunk.get("usageMetadata"), dict):
                combined["usageMetadata"] = chunk["usageMetadata"]
            for raw_candidate in chunk.get("candidates") or []:
                if not isinstance(raw_candidate, dict):
                    continue
                index = int(raw_candidate.get("index", 0) or 0)
                candidate = candidates.setdefault(
                    index,
                    {"index": index, "content": {"role": "model", "parts": []}},
                )
                for key, value in raw_candidate.items():
                    if key not in {"content", "index"}:
                        candidate[key] = value
                content = raw_candidate.get("content") or {}
                if not isinstance(content, dict):
                    continue
                if content.get("role"):
                    candidate["content"]["role"] = content["role"]
                for raw_part in content.get("parts") or []:
                    if not isinstance(raw_part, dict):
                        continue
                    parts = candidate["content"]["parts"]
                    if "text" in raw_part:
                        thought = bool(raw_part.get("thought"))
                        if (
                            parts
                            and "text" in parts[-1]
                            and bool(parts[-1].get("thought")) == thought
                        ):
                            parts[-1]["text"] = str(parts[-1]["text"]) + str(raw_part.get("text", ""))
                        else:
                            parts.append(dict(raw_part))
                    else:
                        parts.append(dict(raw_part))

        combined["candidates"] = [candidate for _, candidate in sorted(candidates.items())]
        if "modelVersion" not in combined:
            combined["modelVersion"] = fallback_model
        return combined

    async def _complete_non_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        data = await self._post_json_with_fallback(url, headers, payload)
        candidates = data.get("candidates", [])
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        response = self._parse_candidate(candidate, request.model)
        usage = data.get("usageMetadata", {})
        response.input_tokens = usage.get("promptTokenCount")
        response.output_tokens = usage.get("candidatesTokenCount")
        return response

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request, stream=True)
        chunks = await self._post_stream_sse_with_fallback(url, headers, payload)
        return self._assemble_stream_response(chunks, request.model)
