from __future__ import annotations

import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
import datetime
import json
import logging
import os
import re
from typing import Any
from urllib import error, parse, request

from quickquip.llm.config import ProviderConfig
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall, LLMToolSpec

logger = logging.getLogger(__name__)

try:
    from loguru import logger as _loguru_logger
    def _trace_log(msg: str) -> None:
        _loguru_logger.opt(depth=1).info(msg)
except ImportError:
    def _trace_log(msg: str) -> None:  # type: ignore[misc]
        print(msg, flush=True)

# Optional path to a flag file that enables LLM request/response tracing.
# Set via LLM_TRACE_FLAG_FILE env var. When the file exists, full payloads
# and raw responses are logged at DEBUG level.
_TRACE_FLAG_FILE: str = os.getenv("LLM_TRACE_FLAG_FILE", "")


def _trace_active() -> bool:
    return bool(_TRACE_FLAG_FILE and os.path.exists(_TRACE_FLAG_FILE))


_TRACE_LOG_LINES: deque[dict[str, object]] = deque(maxlen=200)


def _record_trace(direction: str, provider_id: str, stream: bool, payload: str) -> None:
    _TRACE_LOG_LINES.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "direction": direction,
        "provider_id": provider_id,
        "stream": stream,
        "payload": payload,
    })


def get_trace_entries(n: int = 50) -> list[dict[str, object]]:
    items = list(_TRACE_LOG_LINES)
    return items[-n:]


def clear_trace_entries() -> int:
    count = len(_TRACE_LOG_LINES)
    _TRACE_LOG_LINES.clear()
    return count


class LLMProviderError(RuntimeError):
    pass


_RETRYABLE_HTTP_PREFIXES = ("HTTP 429", "HTTP 5", "网络错误")


def _is_retryable(exc: LLMProviderError) -> bool:
    msg = str(exc)
    return any(msg.startswith(prefix) for prefix in _RETRYABLE_HTTP_PREFIXES)


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
    thinking_budget: int | None = None
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
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)


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


_LEADING_REASONING_BLOCK_PATTERN = re.compile(
    r"^\s*<(?P<tag>think|thinking|reasoning)>\s*.*?</(?P=tag)>\s*",
    re.IGNORECASE | re.DOTALL,
)
_LEADING_REASONING_FENCE_PATTERN = re.compile(
    r"^\s*```(?:think|thinking|reasoning)[^\n]*\n.*?\n```\s*",
    re.IGNORECASE | re.DOTALL,
)


def strip_leading_reasoning_content(text: str) -> str:
    cleaned = text.strip()
    while cleaned:
        next_cleaned = _LEADING_REASONING_BLOCK_PATTERN.sub("", cleaned, count=1)
        if next_cleaned != cleaned:
            cleaned = next_cleaned.strip()
            continue
        next_cleaned = _LEADING_REASONING_FENCE_PATTERN.sub("", cleaned, count=1)
        if next_cleaned != cleaned:
            cleaned = next_cleaned.strip()
            continue
        break
    return cleaned


_GEMINI_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "title",
        "description",
        "nullable",
        "enum",
        "default",
        "items",
        "properties",
        "required",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minProperties",
        "maxProperties",
        "pattern",
        "example",
        "anyOf",
        "propertyOrdering",
        "minimum",
        "maximum",
    }
)


def sanitize_gemini_schema(schema: Any) -> Any:
    """Restrict a JSON Schema subtree to keys Gemini's Schema proto accepts.

    Gemini's ``function_declarations.parameters`` follows the OpenAPI 3.0
    Schema proto and 400s on any unknown field name. Rather than chase the
    long tail of JSON Schema keywords we don't know about, keep only the
    exact set the proto declares; property names under ``properties`` are
    user-defined and pass through untouched.
    """
    if not isinstance(schema, dict):
        if isinstance(schema, list):
            return [sanitize_gemini_schema(item) for item in schema]
        return schema

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_ALLOWED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                name: sanitize_gemini_schema(sub) for name, sub in value.items()
            }
        elif key == "items":
            cleaned[key] = sanitize_gemini_schema(value)
        elif key == "anyOf" and isinstance(value, list):
            cleaned[key] = [sanitize_gemini_schema(item) for item in value]
        else:
            cleaned[key] = value
    return cleaned


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

    def _swap_base_url(self, url: str, new_base: str) -> str:
        prefix = self.config.base_url.rstrip("/")
        if url.startswith(prefix):
            return new_base.rstrip("/") + url[len(prefix):]
        logger.warning("LLM fallback: URL %s does not start with base_url %s", url, prefix)
        return url

    def _candidate_urls(self, url: str):
        yield url
        for fb in self.config.fallback_urls:
            yield self._swap_base_url(url, fb)

    async def _execute_with_fallback(self, fn, url: str, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        if not self.config.fallback_urls:
            return await fn(url, headers, payload)
        last_exc: LLMProviderError | None = None
        for candidate in self._candidate_urls(url):
            try:
                return await fn(candidate, headers, payload)
            except LLMProviderError as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    async def _post_json_with_fallback(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return await self._execute_with_fallback(self._post_json, url, headers, payload)

    async def _post_stream_sse_with_fallback(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._execute_with_fallback(self._post_stream_sse, url, headers, payload)

    async def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url=url, data=body, headers=headers, method="POST")
        trace = _trace_active()
        if trace:
            _trace_log(
                f">>> REQUEST [{self.config.id}]\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            )
            _record_trace("request", self.config.id, False, json.dumps(payload, ensure_ascii=False, indent=2))

        def _send() -> dict[str, Any]:
            try:
                with request.urlopen(http_request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise LLMProviderError(f"响应非 JSON：{raw[:120]}") from exc
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
            except error.URLError as exc:
                raise LLMProviderError(f"网络错误：{exc.reason}") from exc
            except OSError as exc:
                raise LLMProviderError(f"网络错误：{exc}") from exc

        result = await asyncio.to_thread(_send)
        if trace:
            _trace_log(
                f"<<< RESPONSE [{self.config.id}]\n"
                + json.dumps(result, ensure_ascii=False, indent=2)
            )
            _record_trace("response", self.config.id, False, json.dumps(result, ensure_ascii=False, indent=2))
        return result

    async def _post_stream_sse(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        headers = {**headers, "Accept": "text/event-stream"}
        http_request = request.Request(url=url, data=body, headers=headers, method="POST")
        trace = _trace_active()
        if trace:
            _trace_log(
                f">>> REQUEST (stream) [{self.config.id}]\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
            )
            _record_trace("request", self.config.id, True, json.dumps(payload, ensure_ascii=False, indent=2))

        def _stream() -> list[dict[str, Any]]:
            try:
                response = request.urlopen(http_request, timeout=self.config.timeout_seconds)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise LLMProviderError(f"HTTP {exc.code} {detail[:240]}") from exc
            except error.URLError as exc:
                raise LLMProviderError(f"网络错误：{exc.reason}") from exc

            events: list[dict[str, Any]] = []
            current_event = ""
            current_data_lines: list[str] = []
            try:
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        current_data_lines.append(data_str)
                    elif line == "":
                        if current_data_lines:
                            joined = " ".join(current_data_lines)
                            try:
                                data = json.loads(joined)
                                if current_event:
                                    data["_sse_event"] = current_event
                                events.append(data)
                            except json.JSONDecodeError:
                                pass
                        current_event = ""
                        current_data_lines = []
            finally:
                response.close()
            return events

        result = await asyncio.to_thread(_stream)
        if trace:
            _trace_log(
                f"<<< RESPONSE (stream) [{self.config.id}]\n"
                + json.dumps(result, ensure_ascii=False, indent=2)
            )
            _record_trace("response", self.config.id, True, json.dumps(result, ensure_ascii=False, indent=2))
        return result


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
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
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
            headers["User-Agent"] = self.config.user_agent
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

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self.config.stream_enabled:
            try:
                return await self._complete_stream(request)
            except LLMProviderError:
                raise
            except Exception:
                return await self._complete_non_stream(request)
        return await self._complete_non_stream(request)


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
                content: list[dict[str, Any]] = [*message.thinking_blocks]
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

    async def _build_request_parts(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
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
        if self.config.user_agent:
            headers["User-Agent"] = self.config.user_agent
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        if request.allow_tool_calls and request.tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for spec in request.tools
            ]
        return url, headers, payload

    @staticmethod
    def _parse_response(data: dict[str, Any], fallback_model: str) -> LLMResponse:
        content = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        thinking_blocks: list[dict[str, Any]] = []
        for index, item in enumerate(content if isinstance(content, list) else [], 1):
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "thinking":
                thinking_blocks.append({"type": "thinking", "thinking": item.get("thinking", ""), "signature": item.get("signature", "")})
            elif t == "redacted_thinking":
                thinking_blocks.append({"type": "redacted_thinking", "data": item.get("data", "")})
            elif t == "text":
                text_parts.append(str(item.get("text", "")))
            elif t == "tool_use":
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
            model=str(data.get("model", fallback_model)),
            tool_calls=tool_calls,
            finish_reason=str(data.get("stop_reason", "")).strip() or None,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            thinking_blocks=thinking_blocks,
        )

    @staticmethod
    def _assemble_stream_response(chunks: list[dict[str, Any]], fallback_model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}  # block_index -> {id, name, input_json}
        thinking_acc: dict[int, dict[str, str]] = {}    # block_index -> {thinking, signature}
        finish_reason: str | None = None
        model = fallback_model
        input_tokens: int | None = None
        output_tokens: int | None = None
        current_block_index = -1

        for chunk in chunks:
            event = chunk.get("_sse_event", "")

            if event == "message_start":
                msg = chunk.get("message", {})
                model = str(msg.get("model", model))
                usage = msg.get("usage", {})
                if usage.get("input_tokens") is not None:
                    input_tokens = usage["input_tokens"]

            elif event == "content_block_start":
                current_block_index = chunk.get("index", current_block_index + 1)
                block = chunk.get("content_block", {})
                if block.get("type") == "tool_use":
                    tool_calls_acc[current_block_index] = {
                        "id": str(block.get("id", "")),
                        "name": str(block.get("name", "")),
                        "input_json": "",
                    }
                elif block.get("type") == "thinking":
                    thinking_acc[current_block_index] = {"thinking": "", "signature": ""}

            elif event == "content_block_delta":
                delta = chunk.get("delta", {})
                idx = chunk.get("index", current_block_index)
                if delta.get("type") == "text_delta":
                    text_parts.append(str(delta.get("text", "")))
                elif delta.get("type") == "input_json_delta":
                    if idx in tool_calls_acc:
                        tool_calls_acc[idx]["input_json"] += str(delta.get("partial_json", ""))
                elif delta.get("type") == "thinking_delta":
                    if idx in thinking_acc:
                        thinking_acc[idx]["thinking"] += str(delta.get("thinking", ""))
                elif delta.get("type") == "signature_delta":
                    if idx in thinking_acc:
                        thinking_acc[idx]["signature"] = str(delta.get("signature", ""))

            elif event == "message_delta":
                delta = chunk.get("delta", {})
                if delta.get("stop_reason"):
                    finish_reason = str(delta["stop_reason"])
                usage = chunk.get("usage", {})
                if usage.get("output_tokens") is not None:
                    output_tokens = usage["output_tokens"]

        tool_calls = [
            LLMToolCall(
                id=acc["id"] or f"tool_{idx + 1}",
                name=acc["name"],
                arguments_json=_json_string(acc["input_json"] or "{}"),
            )
            for idx, acc in sorted(tool_calls_acc.items())
        ]
        thinking_blocks = [
            {"type": "thinking", "thinking": acc["thinking"], "signature": acc["signature"]}
            for _, acc in sorted(thinking_acc.items())
        ]
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=model,
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _complete_non_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        data = await self._post_json_with_fallback(url, headers, payload)
        return self._parse_response(data, request.model)

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        payload["stream"] = True
        chunks = await self._post_stream_sse_with_fallback(url, headers, payload)
        return self._assemble_stream_response(chunks, request.model)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self.config.stream_enabled:
            try:
                return await self._complete_stream(request)
            except LLMProviderError:
                raise
            except Exception:
                return await self._complete_non_stream(request)
        return await self._complete_non_stream(request)


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
            "Content-Type": "application/json",
            **self.config.headers,
        }
        if self.config.user_agent:
            headers["User-Agent"] = self.config.user_agent
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

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self.config.stream_enabled:
            try:
                return await self._complete_stream(request)
            except LLMProviderError:
                raise
            except Exception:
                return await self._complete_non_stream(request)
        return await self._complete_non_stream(request)


def build_provider_client(config: ProviderConfig) -> BaseProviderClient:
    if config.protocol == "openai":
        return OpenAIProviderClient(config)
    if config.protocol == "claude":
        return ClaudeProviderClient(config)
    if config.protocol == "gemini":
        return GeminiProviderClient(config)
    raise LLMProviderError(f"未知 provider 协议：{config.protocol}")
