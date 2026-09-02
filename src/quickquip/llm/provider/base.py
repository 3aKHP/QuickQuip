"""Base provider client, data classes, and shared utilities.

Extracted from the former monolithic ``provider.py``. Holds the protocol-
agnostic ``BaseProviderClient`` (HTTP transport, fallback, image download,
trace integration) plus the request/response data classes and text/schema
helpers used across all three provider implementations.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider.retry import RetryPolicy, backoff_delay
from quickquip.llm.sanitize import MAX_SAFE_ERROR_LENGTH, sanitize_error_message
from quickquip.llm.tools import (
    LLMConversationMessage,
    LLMInlineImage,
    LLMToolCall,
    LLMToolSpec,
)
from quickquip.llm.provider.trace import (
    begin_http_trace,
    finish_http_trace,
)
from quickquip.llm.usage import _schedule_usage_record

logger = logging.getLogger(__name__)

# Max images attached to a single provider request. Caps multimodal token
# cost; also bounds how many recent-buffer images a passive trigger carries.
MAX_IMAGES_PER_REQUEST = 5


class LLMProviderError(RuntimeError):
    """Provider 调用失败。

    ``status_code`` 为上游 HTTP 状态码（非 HTTP 错误为 None）；``transport``
    标记连接失败/超时等传输层错误。两者供重试分类（``_is_retryable``）使用，
    消息文本保持原有格式（会被直接内插到用户可见回复中）。
    """

    def __init__(self, message: str, *, status_code: int | None = None, transport: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.transport = transport


def _is_retryable(exc: LLMProviderError) -> bool:
    if exc.transport:
        return True
    return exc.status_code is not None and (exc.status_code == 429 or exc.status_code >= 500)


def _headers_to_text(headers: Any) -> str:
    raw = getattr(headers, "raw", None)
    if isinstance(raw, (list, tuple)):
        return "\r\n".join(
            f"{bytes(name).decode('latin-1')}: {bytes(value).decode('latin-1')}"
            for name, value in raw
        )
    items = headers.items() if hasattr(headers, "items") else []
    return "\r\n".join(f"{name}: {value}" for name, value in items)


def _trace_model(url: str, payload: dict[str, Any]) -> str:
    model = payload.get("model")
    if model:
        return str(model)
    match = re.search(r"/models/([^/:?]+):", url)
    return match.group(1) if match else ""


def _parse_sse_text(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_event = ""
    current_data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_event, current_data_lines
        if current_data_lines:
            joined = " ".join(current_data_lines)
            try:
                data = json.loads(joined)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                if current_event:
                    data["_sse_event"] = current_event
                events.append(data)
        current_event = ""
        current_data_lines = []

    for raw_line in raw.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                flush()
                break
            current_data_lines.append(data_str)
        elif line == "":
            flush()
    else:
        flush()
    return events


def _take_sse_line(buffer: str) -> tuple[str, str] | None:
    """Take one complete SSE line while preserving its original line ending."""

    for index, char in enumerate(buffer):
        if char == "\n":
            return buffer[: index + 1], buffer[index + 1 :]
        if char != "\r":
            continue
        if index + 1 == len(buffer):
            return None
        end = index + 2 if buffer[index + 1] == "\n" else index + 1
        return buffer[:end], buffer[end:]
    return None


def _is_sse_done_line(line: str) -> bool:
    content = line.rstrip("\r\n")
    return content.startswith("data:") and content[5:].strip() == "[DONE]"


class _SSETextCapture:
    """Accumulate exact SSE text while recognizing its terminal data line."""

    def __init__(self) -> None:
        self._raw_parts: list[str] = []
        self._pending = ""
        self._done = False

    def feed(self, chunk: str) -> bool:
        self._pending += chunk
        while line_parts := _take_sse_line(self._pending):
            line, self._pending = line_parts
            self._raw_parts.append(line)
            if _is_sse_done_line(line):
                blank_parts = _take_sse_line(self._pending)
                if blank_parts is not None and not blank_parts[0].rstrip("\r\n"):
                    self._raw_parts.append(blank_parts[0])
                self._pending = ""
                self._done = True
                return True
        return False

    def text(self) -> str:
        pending = "" if self._done else self._pending
        return "".join(self._raw_parts) + pending


@dataclass(slots=True)
class LLMImageInput:
    source_url: str
    media_type: str
    data_base64: str


@dataclass(slots=True)
class LLMWebSearchSource:
    title: str
    url: str


@dataclass(slots=True)
class LLMWebSearchReport:
    """Provider 原生搜索（grounding）的响应侧统一载体。"""

    queries: list[str] = field(default_factory=list)
    sources: list[LLMWebSearchSource] = field(default_factory=list)


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
    builtin_search: bool = False


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    thinking_tokens: int | None = None
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)
    web_search: LLMWebSearchReport | None = None


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

    Arrays without ``items`` are valid JSON Schema (and common in
    MCP-transmitted tool schemas) but rejected by the proto, so a permissive
    ``items: {}`` is injected. List-valued ``type`` and pre-existing invalid
    ``items`` are out of scope — those remain the schema author's responsibility.
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
    if cleaned.get("type") == "array" and "items" not in cleaned:
        cleaned["items"] = {}
    return cleaned


class BaseProviderClient:
    def __init__(self, config: ProviderConfig, retry_policy: RetryPolicy | None = None):
        self.config = config
        self.retry_policy = retry_policy or RetryPolicy(
            max_attempts=config.retry_max_attempts,
            base_delay=config.retry_base_delay,
            jitter=config.retry_jitter,
        )
        self._proxy: str | None = config.proxy or None
        if self._proxy:
            logger.info("provider %s 启用代理：%s", config.id, self._proxy)

    def _client_kwargs(self, *, stream_read: bool = False) -> dict[str, Any]:
        """Build httpx.AsyncClient kwargs honoring proxy and timeout config.

        ``stream_read=True`` disables the read timeout so SSE long-lived
        streams are not killed mid-response (mirrors the mcp.py pattern).
        """
        timeout: httpx.Timeout | float
        if stream_read:
            timeout = httpx.Timeout(self.config.timeout_seconds, read=None)
        else:
            timeout = self.config.timeout_seconds
        kwargs: dict[str, Any] = {"timeout": timeout}
        if self._proxy:
            kwargs["proxy"] = self._proxy
        return kwargs

    def _get_api_key(self) -> str:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise LLMProviderError(
                f"环境变量 {self.config.api_key_env} 未设置，provider {self.config.id} 无法调用"
            )
        return api_key

    async def _dispatch_with_retry(self, dispatch, request: LLMRequest) -> LLMResponse:
        """执行一次 dispatch 调用，对可重试失败按 retry_policy 指数退避重试。

        每次尝试内部已含 fallback_urls 链，退避等待发生在链与链之间；
        被重试吸收的失败不产生额外 usage 记录（明细见 HTTP trace）。
        """
        policy = self.retry_policy
        attempt = 0
        while True:
            try:
                return await dispatch(request)
            except LLMProviderError as exc:
                attempt += 1
                if attempt >= policy.max_attempts or not _is_retryable(exc):
                    raise
                delay = backoff_delay(attempt - 1, policy)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, policy.max_attempts, delay, exc,
                )
                await asyncio.sleep(delay)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Stream-then-fallback dispatch + retry + usage metering.

        When ``config.stream_enabled`` is set, try the streaming endpoint
        first; on a non-LLMProviderError failure, fall back to the non-
        streaming endpoint. LLMProviderError is re-raised unchanged. Both
        dispatch paths retry retryable failures (HTTP 429/5xx, transport
        errors) with jittered exponential backoff per ``retry_policy``.

        Every complete() (success/error/cancelled) is metered once via
        ``_record_usage``; metering failure never affects the main path.
        """
        started = time.monotonic()
        stream_used = self.config.stream_enabled
        response: LLMResponse | None = None
        try:
            if self.config.stream_enabled:
                try:
                    response = await self._dispatch_with_retry(self._complete_stream, request)
                except LLMProviderError:
                    raise
                except Exception:
                    stream_used = False
                    response = await self._dispatch_with_retry(self._complete_non_stream, request)
            else:
                response = await self._dispatch_with_retry(self._complete_non_stream, request)
        except asyncio.CancelledError:
            _schedule_usage_record(self, request, None, started, stream_used, "cancelled")
            raise
        except Exception as exc:
            _schedule_usage_record(
                self, request, None, started, stream_used, "error",
                f"{type(exc).__name__}: {sanitize_error_message(str(exc))}"[:MAX_SAFE_ERROR_LENGTH],
            )
            raise
        _schedule_usage_record(self, request, response, started, stream_used, "ok")
        return response

    async def _download_image(self, image_url: str) -> LLMImageInput:
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(
                    image_url, headers={"User-Agent": "QuickQuip/1.0"}
                )
                response.raise_for_status()
                media_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                if not media_type.startswith("image/"):
                    raise LLMProviderError(f"图片 URL 不是受支持的图片类型：{image_url}")
                raw = response.content
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            raise LLMProviderError(
                f"图片下载失败：HTTP {exc.response.status_code} {detail[:160]}",
                status_code=exc.response.status_code,
            ) from exc
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            raise LLMProviderError(f"图片下载网络错误：{exc}", transport=True) from exc

        if not raw:
            raise LLMProviderError(f"图片内容为空：{image_url}")
        if len(raw) > 5 * 1024 * 1024:
            raise LLMProviderError(f"图片过大，当前限制为 5MB：{image_url}")

        return LLMImageInput(
            source_url=image_url,
            media_type=media_type,
            data_base64=base64.b64encode(raw).decode("ascii"),
        )

    async def _prepare_image_inputs(
        self,
        image_urls: list[str],
        inline_images: list[LLMInlineImage] | None = None,
    ) -> list[LLMImageInput]:
        if not image_urls and not inline_images:
            return []
        prepared: list[LLMImageInput] = []
        for image_url in image_urls[:MAX_IMAGES_PER_REQUEST]:
            try:
                prepared.append(await self._download_image(image_url))
            except LLMProviderError:
                # A single stale/forbidden URL (common for QQ CDN links pulled
                # from the recent buffer) must not sink the whole request;
                # skip it so the remaining images and text still go through.
                logger.warning("provider: 跳过无法下载的图片 %s", image_url)
        remaining = MAX_IMAGES_PER_REQUEST - len(prepared)
        for image in (inline_images or [])[:remaining]:
            if (
                image.media_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}
                or not image.data
                or len(image.data) > 5 * 1024 * 1024
            ):
                logger.warning("provider: 跳过无效的内联图片 %s", image.source_label)
                continue
            prepared.append(
                LLMImageInput(
                    source_url=image.source_label,
                    media_type=image.media_type,
                    data_base64=base64.b64encode(image.data).decode("ascii"),
                )
            )
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

    def _combine_stream_trace(
        self,
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__} must reconstruct its streamed response"
        )

    async def _post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = _headers_to_text(headers)
        started = time.monotonic()
        call_id = await begin_http_trace(
            provider_id=self.config.id,
            protocol=self.config.protocol,
            model=_trace_model(url, payload),
            stream=False,
            method="POST",
            url=url,
            request_headers=request_headers,
            request_text=body.decode("utf-8"),
            request_bytes=len(body),
        )
        response_status: int | None = None
        response_headers = ""
        raw = ""

        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.post(url, content=body, headers=headers)
                response_status = response.status_code
                response_headers = _headers_to_text(response.headers)
                raw = response.text
                response.raise_for_status()
            try:
                result = json.loads(raw)
            except json.JSONDecodeError as exc:
                await finish_http_trace(
                    call_id,
                    state="error",
                    response_status=response_status,
                    response_headers=response_headers,
                    response_text=raw,
                    response_bytes=len(raw.encode("utf-8")),
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type=type(exc).__name__,
                    error_message=f"响应非 JSON：{raw[:120]}",
                )
                raise LLMProviderError(f"响应非 JSON：{raw[:120]}") from exc
        except asyncio.CancelledError:
            await asyncio.shield(
                finish_http_trace(
                    call_id,
                    state="error",
                    response_status=response_status,
                    response_headers=response_headers,
                    response_text=raw,
                    response_bytes=len(raw.encode("utf-8")),
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type="CancelledError",
                    error_message="HTTP request was cancelled",
                )
            )
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            await finish_http_trace(
                call_id,
                state="error",
                response_status=exc.response.status_code,
                response_headers=_headers_to_text(exc.response.headers),
                response_text=detail,
                response_bytes=len(detail.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=f"HTTP {exc.response.status_code} {detail[:240]}",
            )
            raise LLMProviderError(
                f"HTTP {exc.response.status_code} {detail[:240]}",
                status_code=exc.response.status_code,
            ) from exc
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            await finish_http_trace(
                call_id,
                state="error",
                response_status=response_status,
                response_headers=response_headers,
                response_text=raw,
                response_bytes=len(raw.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise LLMProviderError(f"网络错误：{exc}", transport=True) from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            await finish_http_trace(
                call_id,
                state="error",
                response_status=response_status,
                response_headers=response_headers,
                response_text=raw,
                response_bytes=len(raw.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise

        await finish_http_trace(
            call_id,
            state="success",
            response_status=response_status,
            response_headers=response_headers,
            response_text=raw,
            response_bytes=len(raw.encode("utf-8")),
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return result

    async def _post_stream_sse(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> list[dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {**headers, "accept": "text/event-stream"}
        started = time.monotonic()
        call_id = await begin_http_trace(
            provider_id=self.config.id,
            protocol=self.config.protocol,
            model=_trace_model(url, payload),
            stream=True,
            method="POST",
            url=url,
            request_headers=_headers_to_text(headers),
            request_text=body.decode("utf-8"),
            request_bytes=len(body),
        )

        raw = ""
        response_status: int | None = None
        response_headers = ""
        try:
            async with httpx.AsyncClient(**self._client_kwargs(stream_read=True)) as client:
                async with client.stream("POST", url, content=body, headers=headers) as response:
                    response_status = response.status_code
                    response_headers = _headers_to_text(response.headers)
                    # Read the error body before raise_for_status so the HTTPStatusError
                    # handler can access exc.response.text (streamed responses are not
                    # pre-read; accessing .text on an unread stream raises ResponseNotRead).
                    if response.status_code >= 400:
                        await response.aread()
                        raw = response.text
                    response.raise_for_status()
                    capture = _SSETextCapture()
                    try:
                        async for chunk in response.aiter_text():
                            if capture.feed(chunk):
                                break
                    finally:
                        raw = capture.text()
        except asyncio.CancelledError:
            await asyncio.shield(
                finish_http_trace(
                    call_id,
                    state="error",
                    response_status=response_status,
                    response_headers=response_headers,
                    response_text="",
                    response_bytes=0,
                    response_raw_text=raw,
                    response_raw_bytes=len(raw.encode("utf-8")),
                    duration_ms=(time.monotonic() - started) * 1000,
                    error_type="CancelledError",
                    error_message="HTTP stream was cancelled",
                )
            )
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            await finish_http_trace(
                call_id,
                state="error",
                response_status=exc.response.status_code,
                response_headers=_headers_to_text(exc.response.headers),
                response_text=detail,
                response_bytes=len(detail.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=f"HTTP {exc.response.status_code} {detail[:240]}",
            )
            raise LLMProviderError(
                f"HTTP {exc.response.status_code} {detail[:240]}",
                status_code=exc.response.status_code,
            ) from exc
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            await finish_http_trace(
                call_id,
                state="error",
                response_status=response_status,
                response_headers=response_headers,
                response_text=raw,
                response_bytes=len(raw.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise LLMProviderError(f"网络错误：{exc}", transport=True) from exc
        except Exception as exc:
            await finish_http_trace(
                call_id,
                state="error",
                response_status=response_status,
                response_headers=response_headers,
                response_text=raw,
                response_bytes=len(raw.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise

        events = _parse_sse_text(raw)
        try:
            combined = self._combine_stream_trace(events, _trace_model(url, payload))
            combined_response = json.dumps(combined, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.exception("LLM HTTP trace response reconstruction failed")
            await finish_http_trace(
                call_id,
                state="success",
                response_status=response_status,
                response_headers=response_headers,
                response_text="",
                response_bytes=0,
                response_raw_text=raw,
                response_raw_bytes=len(raw.encode("utf-8")),
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return events
        await finish_http_trace(
            call_id,
            state="success",
            response_status=response_status,
            response_headers=response_headers,
            response_text=combined_response,
            response_bytes=len(combined_response.encode("utf-8")),
            response_raw_text=raw,
            response_raw_bytes=len(raw.encode("utf-8")),
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return events
