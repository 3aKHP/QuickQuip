"""OpenAI-compatible chat completions provider client."""
from __future__ import annotations

from typing import Any

from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMRequest,
    LLMResponse,
    _json_string,
    _text_from_block_list,
    strip_leading_reasoning_content,
)


class OpenAIProviderClient(BaseProviderClient):
    @staticmethod
    def _extract_reasoning_content(thinking_blocks: list[dict[str, Any]]) -> str:
        for block in thinking_blocks:
            if isinstance(block, dict) and block.get("type") == "reasoning":
                return str(block.get("reasoning_content", ""))
        return ""

    async def _serialize_message(self, message: LLMConversationMessage) -> dict[str, Any]:
        if message.role == "assistant":
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content,
            }
            reasoning = self._extract_reasoning_content(message.thinking_blocks)
            if reasoning:
                payload["reasoning_content"] = reasoning
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments_json,
                        },
                    }
                    for call in message.tool_calls
                ]
            return payload

        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "name": message.tool_name,
                "content": message.content,
            }

        image_inputs = await self._prepare_image_inputs(message.image_urls)
        if image_inputs:
            content: list[dict[str, Any]] = [
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{item.media_type};base64,{item.data_base64}"},
                    }
                    for item in image_inputs
                ]
            ]
            if message.content:
                content.append({"type": "text", "text": message.content})
            return {"role": "user", "content": content}

        return {"role": "user", "content": message.content}

    async def _build_request_parts(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            **self.config.headers,
            "authorization": f"Bearer {self._get_api_key()}",
            "content-type": "application/json",
        }
        messages = [{"role": "system", "content": request.system_prompt}]
        for message in request.messages:
            messages.append(await self._serialize_message(message))

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if self.config.user_agent:
            headers["user-agent"] = self.config.user_agent
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        if request.allow_tool_calls and request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.input_schema,
                    },
                }
                for spec in request.tools
            ]
            payload["tool_choice"] = request.tool_choice
        return url, headers, payload

    @staticmethod
    def _parse_response(data: dict[str, Any], fallback_model: str) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        tool_calls = [
            LLMToolCall(
                id=str(item.get("id", "")).strip() or f"tool_{index}",
                name=str(item.get("function", {}).get("name", "")).strip(),
                arguments_json=_json_string(item.get("function", {}).get("arguments", "{}")),
            )
            for index, item in enumerate(message.get("tool_calls", []) or [], 1)
            if isinstance(item, dict)
        ]
        thinking_blocks: list[dict[str, Any]] = []
        reasoning_content = message.get("reasoning_content", "")
        if reasoning_content:
            thinking_blocks.append({"type": "reasoning", "reasoning_content": reasoning_content})
        usage = data.get("usage", {})
        return LLMResponse(
            text=strip_leading_reasoning_content(_text_from_block_list(message.get("content"))),
            model=str(data.get("model", fallback_model)),
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason", "")).strip() or None,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            thinking_blocks=thinking_blocks,
        )

    @staticmethod
    def _assemble_stream_response(chunks: list[dict[str, Any]], fallback_model: str) -> LLMResponse:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}  # index -> {id, name, arguments}
        finish_reason: str | None = None
        model = fallback_model
        input_tokens: int | None = None
        output_tokens: int | None = None

        for chunk in chunks:
            model = str(chunk.get("model", model))
            choices = chunk.get("choices") or []
            if choices:
                choice = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice.get("delta", {})
                if delta.get("content"):
                    text_parts.append(str(delta["content"]))
                if delta.get("reasoning_content"):
                    reasoning_parts.append(str(delta["reasoning_content"]))
                for tc in delta.get("tool_calls", []) or []:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.get("id"):
                        tool_calls_acc[idx]["id"] = str(tc["id"])
                    func = tc.get("function", {})
                    if func.get("name"):
                        tool_calls_acc[idx]["name"] = str(func["name"])
                    if func.get("arguments"):
                        tool_calls_acc[idx]["arguments"] += str(func["arguments"])
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
            usage = chunk.get("usage")
            if isinstance(usage, dict):
                if usage.get("prompt_tokens") is not None:
                    input_tokens = usage["prompt_tokens"]
                if usage.get("completion_tokens") is not None:
                    output_tokens = usage["completion_tokens"]

        tool_calls = [
            LLMToolCall(
                id=acc["id"] or f"tool_{idx + 1}",
                name=acc["name"],
                arguments_json=_json_string(acc["arguments"] or "{}"),
            )
            for idx, acc in sorted(tool_calls_acc.items())
        ]
        thinking_blocks: list[dict[str, Any]] = []
        if reasoning_parts:
            thinking_blocks.append({"type": "reasoning", "reasoning_content": "".join(reasoning_parts)})
        return LLMResponse(
            text=strip_leading_reasoning_content("".join(text_parts)),
            model=model,
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _combine_stream_trace(
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        top: dict[str, Any] = {
            "object": "chat.completion",
            "model": fallback_model,
        }
        choices: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None

        for chunk in chunks:
            for key in ("id", "created", "model", "system_fingerprint", "service_tier"):
                if chunk.get(key) is not None:
                    top[key] = chunk[key]
            if isinstance(chunk.get("object"), str):
                top["object"] = str(chunk["object"]).removesuffix(".chunk")
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]

            for raw_choice in chunk.get("choices") or []:
                if not isinstance(raw_choice, dict):
                    continue
                index = int(raw_choice.get("index", 0) or 0)
                acc = choices.setdefault(
                    index,
                    {
                        "role": "assistant",
                        "content": [],
                        "reasoning_content": [],
                        "refusal": [],
                        "tool_calls": {},
                        "finish_reason": None,
                        "logprobs": None,
                    },
                )
                delta = raw_choice.get("delta") or {}
                if not isinstance(delta, dict):
                    delta = {}
                if delta.get("role"):
                    acc["role"] = str(delta["role"])
                for key in ("content", "reasoning_content", "refusal"):
                    if delta.get(key) is not None:
                        acc[key].append(str(delta[key]))
                for raw_tool in delta.get("tool_calls") or []:
                    if not isinstance(raw_tool, dict):
                        continue
                    tool_index = int(raw_tool.get("index", 0) or 0)
                    tool = acc["tool_calls"].setdefault(
                        tool_index,
                        {"id": "", "type": "function", "name": "", "arguments": ""},
                    )
                    if raw_tool.get("id"):
                        tool["id"] = str(raw_tool["id"])
                    if raw_tool.get("type"):
                        tool["type"] = str(raw_tool["type"])
                    function = raw_tool.get("function") or {}
                    if isinstance(function, dict):
                        if function.get("name"):
                            tool["name"] = str(function["name"])
                        if function.get("arguments") is not None:
                            tool["arguments"] += str(function["arguments"])
                if raw_choice.get("finish_reason") is not None:
                    acc["finish_reason"] = raw_choice["finish_reason"]
                if raw_choice.get("logprobs") is not None:
                    acc["logprobs"] = raw_choice["logprobs"]

        combined_choices: list[dict[str, Any]] = []
        for index, acc in sorted(choices.items()):
            message: dict[str, Any] = {
                "role": acc["role"],
                "content": "".join(acc["content"]) if acc["content"] else None,
            }
            if acc["reasoning_content"]:
                message["reasoning_content"] = "".join(acc["reasoning_content"])
            if acc["refusal"]:
                message["refusal"] = "".join(acc["refusal"])
            if acc["tool_calls"]:
                message["tool_calls"] = [
                    {
                        "id": tool["id"] or f"tool_{tool_index + 1}",
                        "type": tool["type"],
                        "function": {
                            "name": tool["name"],
                            "arguments": tool["arguments"],
                        },
                    }
                    for tool_index, tool in sorted(acc["tool_calls"].items())
                ]
            combined_choices.append(
                {
                    "index": index,
                    "message": message,
                    "logprobs": acc["logprobs"],
                    "finish_reason": acc["finish_reason"],
                }
            )

        top["choices"] = combined_choices
        if usage is not None:
            top["usage"] = usage
        return top

    async def _complete_non_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        data = await self._post_json_with_fallback(url, headers, payload)
        return self._parse_response(data, request.model)

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        chunks = await self._post_stream_sse_with_fallback(url, headers, payload)
        return self._assemble_stream_response(chunks, request.model)
