from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import json
from typing import Any
import os
from urllib import error, parse, request

from quickquip.llm.config import ProviderConfig
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall, LLMToolSpec


class LLMProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMImageInput:
    source_url: str
    media_type: str
    data_base64: str


@dataclass(slots=True)
class LLMRequest:
    model: str
    system_prompt: str
    messages: list[LLMConversationMessage]
    temperature: float
    max_output_tokens: int
    tools: list[LLMToolSpec] = field(default_factory=list)
    allow_tool_calls: bool = False
    tool_choice: str = "auto"


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


def _text_from_block_list(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "".join(parts).strip()


def _json_string(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or "{}"
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)
    except TypeError:
        return "{}"


class BaseProviderClient:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def _get_api_key(self) -> str:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise LLMProviderError(
                f"环境变量 {self.config.api_key_env} 未设置，provider {self.config.id} 无法调用"
            )
        return api_key

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def _download_image(self, image_url: str) -> LLMImageInput:
        http_request = request.Request(image_url, headers={"User-Agent": "QuickQuip/1.0"})

        def _fetch() -> LLMImageInput:
            try:
                with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                    media_type = response.headers.get_content_type() or "image/jpeg"
                    if not media_type.startswith("image/"):
                        raise LLMProviderError(f"图片 URL 不是受支持的图片类型：{image_url}")
                    raw = response.read()
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(f"图片下载失败：HTTP {exc.code} {detail[:160]}") from exc
            except error.URLError as exc:
                raise LLMProviderError(f"图片下载网络错误：{exc.reason}") from exc

            if not raw:
                raise LLMProviderError(f"图片内容为空：{image_url}")
            if len(raw) > 5 * 1024 * 1024:
                raise LLMProviderError(f"图片过大，当前限制为 5MB：{image_url}")

            return LLMImageInput(
                source_url=image_url,
                media_type=media_type,
                data_base64=base64.b64encode(raw).decode("ascii"),
            )

        return await asyncio.to_thread(_fetch)

    async def _prepare_image_inputs(self, image_urls: list[str]) -> list[LLMImageInput]:
        if not image_urls:
            return []
        prepared: list[LLMImageInput] = []
        for image_url in image_urls[:3]:
            prepared.append(await self._download_image(image_url))
        return prepared

    async def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url=url, data=body, headers=headers, method="POST")

        def _send() -> dict[str, Any]:
            try:
                with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
            except error.URLError as exc:
                raise LLMProviderError(f"网络错误：{exc.reason}") from exc

        return await asyncio.to_thread(_send)


class OpenAIProviderClient(BaseProviderClient):
    async def _serialize_message(self, message: LLMConversationMessage) -> dict[str, Any]:
        if message.role == "assistant":
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content,
            }
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

    async def complete(self, request: LLMRequest) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
            **self.config.headers,
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

        data = await self._post_json(url, headers, payload)
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
        usage = data.get("usage", {})
        return LLMResponse(
            text=_text_from_block_list(message.get("content")),
            model=str(data.get("model", request.model)),
            tool_calls=tool_calls,
            finish_reason=str(choice.get("finish_reason", "")).strip() or None,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class ClaudeProviderClient(BaseProviderClient):
    async def _serialize_user_message(self, message: LLMConversationMessage) -> dict[str, Any]:
        image_inputs = await self._prepare_image_inputs(message.image_urls)
        if image_inputs:
            content: list[dict[str, Any]] = [
                *[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": item.media_type,
                            "data": item.data_base64,
                        },
                    }
                    for item in image_inputs
                ]
            ]
            if message.content:
                content.append({"type": "text", "text": message.content})
            return {"role": "user", "content": content}
        return {"role": "user", "content": message.content}

    async def _serialize_messages(self, messages: list[LLMConversationMessage]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        pending_tool_results: list[LLMConversationMessage] = []

        async def _flush_tool_results() -> None:
            nonlocal pending_tool_results
            if not pending_tool_results:
                return
            serialized.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": item.tool_call_id,
                            "content": item.content,
                            "is_error": item.is_tool_error,
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

            await _flush_tool_results()
            if message.role == "assistant":
                content: list[dict[str, Any]] = []
                if message.content:
                    content.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    try:
                        tool_input = json.loads(call.arguments_json or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": tool_input,
                        }
                    )
                serialized.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
                continue

            serialized.append(await self._serialize_user_message(message))

        await _flush_tool_results()
        return serialized

    async def complete(self, request: LLMRequest) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": self._get_api_key(),
            "anthropic-version": self.config.headers.get("anthropic-version", "2023-06-01"),
            "Content-Type": "application/json",
            **{k: v for k, v in self.config.headers.items() if k != "anthropic-version"},
        }
        payload: dict[str, Any] = {
            "model": request.model,
            "system": request.system_prompt,
            "messages": await self._serialize_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.allow_tool_calls and request.tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for spec in request.tools
            ]

        data = await self._post_json(url, headers, payload)
        content = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for index, item in enumerate(content if isinstance(content, list) else [], 1):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            if item.get("type") == "tool_use":
                tool_calls.append(
                    LLMToolCall(
                        id=str(item.get("id", "")).strip() or f"tool_{index}",
                        name=str(item.get("name", "")).strip(),
                        arguments_json=_json_string(item.get("input", {})),
                    )
                )

        usage = data.get("usage", {})
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=str(data.get("model", request.model)),
            tool_calls=tool_calls,
            finish_reason=str(data.get("stop_reason", "")).strip() or None,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
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

    async def complete(self, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key()
        url = self.config.base_url.rstrip("/") + f"/models/{request.model}:generateContent?key={parse.quote(api_key)}"
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": await self._serialize_messages(request.messages),
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        if request.allow_tool_calls and request.tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": spec.name,
                            "description": spec.description,
                            "parameters": spec.input_schema,
                        }
                        for spec in request.tools
                    ]
                }
            ]

        headers = {
            "Content-Type": "application/json",
            **self.config.headers,
        }
        data = await self._post_json(url, headers, payload)
        candidates = data.get("candidates", [])
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for index, item in enumerate(parts if isinstance(parts, list) else [], 1):
            if not isinstance(item, dict):
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

        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=request.model,
            tool_calls=tool_calls,
            finish_reason=str(candidate.get("finishReason", "")).strip() or None,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )


def build_provider_client(config: ProviderConfig) -> BaseProviderClient:
    if config.protocol == "openai":
        return OpenAIProviderClient(config)
    if config.protocol == "claude":
        return ClaudeProviderClient(config)
    if config.protocol == "gemini":
        return GeminiProviderClient(config)
    raise LLMProviderError(f"未知 provider 协议：{config.protocol}")
