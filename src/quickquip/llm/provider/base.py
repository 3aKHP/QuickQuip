"""Base provider client, data classes, and shared utilities.

Extracted from the former monolithic ``provider.py``. Holds the protocol-
agnostic ``BaseProviderClient`` (HTTP transport, fallback, image download,
trace integration) plus the request/response data classes and text/schema
helpers used across all three provider implementations.
"""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from quickquip.llm.config import ProviderConfig
from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.provider.media_guard import (
    MAX_IMAGE_BYTES,
    InlineMediaBudget,
)
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

# 工具产出图片回灌模型时的合成 user 消息提示文案（openai 与
# openai_responses 两个序列化端共用，用户可见文案单源）。
TOOL_IMAGE_FLUSH_NOTICE = "以下图片来自刚才工具调用，仅用于继续推理。"

# 图片下载实例级缓存：一轮对话内工具循环重建请求与 429/5xx 退避重试会反复
# 序列化同一批图片 URL；TTL 与容量双重兜底内存占用（QQ CDN 链接本身短时效）。
_IMAGE_CACHE_TTL_SECONDS = 600
_IMAGE_CACHE_MAX_ENTRIES = 32


class LLMProviderError(RuntimeError):
    """Provider 调用失败。

    ``status_code`` 为上游 HTTP 状态码（非 HTTP 错误为 None）；``transport``
    标记连接失败/超时等传输层错误。两者供重试分类（``_is_retryable``）使用，
    消息文本保持原有格式（会被直接内插到用户可见回复中）。``http_reject``
    区分"上游 HTTP 层拒绝请求"与协议层把畸形/失败终态归一出的同码错误
    （如 Responses 的 failed/cancelled 终态）——降级重试类调用方只应响应
    前者（协议层 400 重试必然徒劳）。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        transport: bool = False,
        http_reject: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.transport = transport
        self.http_reject = http_reject


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


def _parse_sse_and_measure(raw: str) -> tuple[list[dict[str, Any]], int]:
    """SSE 解析 + 原文字节测量，供线程池执行（生图流可达数 MB）。"""
    return _parse_sse_text(raw), len(raw.encode("utf-8"))


def _is_sse_done_line(line: str) -> bool:
    content = line.rstrip("\r\n")
    return content.startswith("data:") and content[5:].strip() == "[DONE]"


class _SSETextCapture:
    """Accumulate exact SSE text while recognizing its terminal data line.

    行边界检测用带扫描偏移的 ``str.find``（C 速度）且只扫描新到字节；
    不含行结尾的 chunk 暂存进 ``_tail``，仅在出现行结尾时合并。生图等
    内置工具会把多 MB 的 base64 放进单个 SSE data 行——逐字符扫描或逐
    chunk 全量重扫都是 O(n²) 纯 Python CPU，足以把事件循环卡死分钟级。
    """

    def __init__(self) -> None:
        self._raw_parts: list[str] = []
        self._pending = ""
        self._scanned = 0
        self._tail: list[str] = []
        self._done = False

    def feed(self, chunk: str) -> bool:
        if (
            "\n" not in chunk
            and "\r" not in chunk
            and self._scanned == len(self._pending)
        ):
            self._tail.append(chunk)
            return False
        self._pending += "".join(self._tail) + chunk
        self._tail.clear()
        while line := self._take_line():
            self._raw_parts.append(line)
            if _is_sse_done_line(line):
                blank = self._take_line()
                if blank is not None and not blank.rstrip("\r\n"):
                    self._raw_parts.append(blank)
                self._pending = ""
                self._scanned = 0
                self._done = True
                return True
        return False

    def text(self) -> str:
        pending = "" if self._done else self._pending + "".join(self._tail)
        return "".join(self._raw_parts) + pending

    def _take_line(self) -> str | None:
        pending = self._pending
        newline = pending.find("\n", self._scanned)
        carriage = pending.find("\r", self._scanned)
        if carriage != -1 and (newline == -1 or carriage < newline):
            if carriage + 1 == len(pending):
                # 缓冲以 \r 结尾：可能还有未到达的 \n 配对，等下一块。
                self._scanned = carriage
                return None
            end = carriage + 2 if pending[carriage + 1] == "\n" else carriage + 1
        elif newline != -1:
            end = newline + 1
        else:
            self._scanned = len(pending)
            return None
        line = pending[:end]
        self._pending = pending[end:]
        self._scanned = 0
        return line


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
class LLMGeneratedImage:
    """模型在对话响应中产出的图片（协议中立，与输入侧媒体归一对称）。

    源自 Responses 内置 image_generation 工具条目或 Gemini 响应的
    inlineData 图片 parts；由送达层按外发图片统一投递，不进入
    native_blocks 原生回放（base64 回放是纯成本无收益）。
    """

    data: bytes = field(repr=False)
    media_type: str = ""
    # 产出来源标签（如 "responses.image_generation" / "gemini.inline_data"），
    # 供观测与限流口径区分。
    source: str = ""

    @classmethod
    def from_base64(
        cls, data_b64: str, *, media_type: str, source: str
    ) -> "LLMGeneratedImage | None":
        """各协议适配器共用的解码策略：非法 base64 返回 None（按无图跳过，
        图片丢失不连累正文交付）。"""
        if not isinstance(data_b64, str) or not data_b64.strip():
            return None
        try:
            data = base64.b64decode(data_b64, validate=True)
        except ValueError:
            return None
        if not data:
            return None
        return cls(data=data, media_type=media_type, source=source)


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
    # 模型产出的图片附件（见 LLMGeneratedImage）：与 web_search 同级的
    # 响应侧归一能力，由各协议适配器按自身能力提取。
    generated_images: list[LLMGeneratedImage] = field(default_factory=list)
    # 实际成功请求的归属（§7.1）：由 client 在成功路径按最终端点填充。
    owner: "ResponseOwner | None" = None
    # 协议原生的有序内容块（§4.4 保序表示）：Claude 的 content 序列 /
    # Gemini 的 parts 序列 / OpenAI Responses 的有序 output items（含
    # reasoning 密文），白名单深拷贝。Chat Completions 无此结构（reasoning
    # 单块已由 thinking_blocks 承载）。供执行记录的 native_state 持久化。
    native_blocks: list[dict[str, Any]] | None = None


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
        self._image_cache: OrderedDict[str, tuple[float, LLMImageInput]] = OrderedDict()

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

    async def _dispatch_with_retry(
        self,
        dispatch: Callable[[LLMRequest], Awaitable[LLMResponse]],
        request: LLMRequest,
    ) -> LLMResponse:
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
        """下载并缓存图片：实例级 LRU（TTL 600s、容量 32，仅缓存成功结果）。

        同一 provider client 实例在一轮对话内被工具循环逐轮重建请求、退避重试
        多次序列化同一批图片 URL；缓存把重复下载压成一次。失败不进门，下一轮
        重试仍能拿到真实错误。并发不加锁：两个协程同时 miss 同一 URL 的代价
        至多一次重复下载；缓存读写均为同步字典操作、中间无 await，不会撕裂。
        """
        now = time.monotonic()
        cached = self._image_cache.get(image_url)
        if cached is not None:
            cached_at, cached_input = cached
            if now - cached_at < _IMAGE_CACHE_TTL_SECONDS:
                self._image_cache.move_to_end(image_url)
                return cached_input
            del self._image_cache[image_url]
        image_input = await self._download_image_uncached(image_url)
        self._image_cache[image_url] = (now, image_input)
        if len(self._image_cache) > _IMAGE_CACHE_MAX_ENTRIES:
            self._image_cache.popitem(last=False)
        return image_input

    async def _download_image_uncached(self, image_url: str) -> LLMImageInput:
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(
                    image_url, headers={"User-Agent": "QuickQuip/1.0"}
                )
                response.raise_for_status()
                media_type = (
                    response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                )
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
        if len(raw) > MAX_IMAGE_BYTES:
            raise LLMProviderError(
                f"图片过大，当前限制为 {MAX_IMAGE_BYTES // (1024 * 1024)}MB：{image_url}"
            )

        return LLMImageInput(
            source_url=image_url,
            media_type=media_type,
            data_base64=base64.b64encode(raw).decode("ascii"),
        )

    async def _prepare_image_inputs(
        self,
        image_urls: list[str],
        inline_images: list[LLMInlineImage] | None = None,
        *,
        budget: InlineMediaBudget | None = None,
    ) -> list[LLMImageInput]:
        if budget is not None and budget.exhausted:
            return []
        if not image_urls and not inline_images:
            return []
        # 收口顺序：URL 图先入列（下载失败不占名额），内联图补足剩余名额，
        # 全部经 media_guard 做 GIF 首帧化、MIME 归一、内容去重与字节预算。
        candidates: list[tuple[str, bytes, str]] = []
        for image_url in image_urls[:MAX_IMAGES_PER_REQUEST]:
            try:
                downloaded = await self._download_image(image_url)
            except LLMProviderError:
                # A single stale/forbidden URL (common for QQ CDN links pulled
                # from the recent buffer) must not sink the whole request;
                # skip it so the remaining images and text still go through.
                logger.warning("provider: 跳过无法下载的图片 %s", image_url)
                continue
            candidates.append(
                (
                    downloaded.source_url,
                    base64.b64decode(downloaded.data_base64),
                    downloaded.media_type,
                )
            )
        remaining = MAX_IMAGES_PER_REQUEST - len(candidates)
        for image in (inline_images or [])[:remaining]:
            candidates.append((image.source_label, image.data, image.media_type))
        budget = (
            budget if budget is not None else InlineMediaBudget(self.config.max_inline_media_bytes)
        )
        # guard 内含 Pillow 解码/转码/降采样重编码（病态图可达秒级），下沉
        # 工作线程执行，不占事件循环；模块级缓存的跨线程安全由 media_guard
        # 的缓存锁保证。
        kept, _dropped = await asyncio.to_thread(budget.guard, candidates)
        return [
            LLMImageInput(
                source_url=item.label,
                media_type=item.media_type,
                data_base64=base64.b64encode(item.data).decode("ascii"),
            )
            for item in kept
        ]

    async def _prepare_request_images(
        self, messages: list[LLMConversationMessage],
    ) -> list[list[LLMImageInput]]:
        """预备整次请求的图片，返回与原消息逐项对齐的结果。

        最新用户消息优先（其内部保留当前/引用/近期的候选顺序），随后按
        新到旧处理工具结果及历史用户图片。序列化仍保留原消息和工具批次顺序。
        每次组装独立创建预算，取消、重试和并发请求均不共享可变状态。
        """
        images: list[list[LLMImageInput]] = [[] for _ in messages]
        order = [i for i in reversed(range(len(messages))) if messages[i].role in {"user", "tool"}]
        current_user = next((i for i in order if messages[i].role == "user"), None)
        if current_user is not None:
            order.remove(current_user)
            order.insert(0, current_user)
        budget = InlineMediaBudget(self.config.max_inline_media_bytes)
        for index in order:
            if budget.exhausted:
                break
            message = messages[index]
            if message.role == "tool" and message.is_tool_error:
                continue
            urls = message.image_urls if message.role == "user" else []
            if not urls and not message.inline_images:
                continue
            images[index] = await self._prepare_image_inputs(
                urls, message.inline_images, budget=budget
            )
        return images

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

    async def _execute_with_fallback(
        self, fn, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[Any, str]:
        """按候选端点链执行，返回 ``(结果, 实际成功的 URL)``（§7.3）。

        失败的可重试错误切换下一候选；不可重试立即抛。调用方用返回的
        URL 构造实际 owner，不共享可变"最后成功端点"字段。
        """
        if not self.config.fallback_urls:
            return await fn(url, headers, payload), url
        last_exc: LLMProviderError | None = None
        for candidate in self._candidate_urls(url):
            try:
                return await fn(candidate, headers, payload), candidate
            except LLMProviderError as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    async def _post_json_with_fallback(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        data, _ = await self._execute_with_fallback(self._post_json, url, headers, payload)
        return data

    async def _post_stream_sse_with_fallback(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        events, _ = await self._execute_with_fallback(self._post_stream_sse, url, headers, payload)
        return events

    async def _post_json_candidate(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        """``_post_json_with_fallback`` 的候选可观测变体：带回实际端点。"""
        return await self._execute_with_fallback(self._post_json, url, headers, payload)

    async def _post_stream_sse_candidate(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str]:
        return await self._execute_with_fallback(self._post_stream_sse, url, headers, payload)

    def _combine_stream_trace(
        self,
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__} must reconstruct its streamed response"
        )

    def _dump_stream_trace(
        self, events: list[dict[str, Any]], fallback_model: str
    ) -> tuple[str, int]:
        """终态重建 + 序列化 + 字节测量，供线程池执行（秒级 CPU）。"""
        combined = self._combine_stream_trace(events, fallback_model)
        combined_response = json.dumps(combined, ensure_ascii=False, indent=2)
        return combined_response, len(combined_response.encode("utf-8"))

    async def _post_json(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
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
                http_reject=True,
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

    async def _post_stream_sse(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
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
                http_reject=True,
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

        # 生图等调用会产生数 MB 的 SSE 原文与终态事件：解析、终态重建
        # 与序列化都是秒级 CPU，放线程池执行，避免同步阻塞事件循环。
        events, raw_bytes = await asyncio.to_thread(_parse_sse_and_measure, raw)
        try:
            combined_response, combined_bytes = await asyncio.to_thread(
                self._dump_stream_trace, events, _trace_model(url, payload)
            )
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
                response_raw_bytes=raw_bytes,
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error_message="stream trace reconstruction failed",
            )
            return events
        await finish_http_trace(
            call_id,
            state="success",
            response_status=response_status,
            response_headers=response_headers,
            response_text=combined_response,
            response_bytes=combined_bytes,
            response_raw_text=raw,
            response_raw_bytes=raw_bytes,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return events
