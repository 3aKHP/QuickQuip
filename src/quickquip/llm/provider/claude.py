"""Anthropic Claude Messages API provider client.

Includes the Claude Code wire-format fingerprint defaults (captured from
a real claude-cli client) that let this client present itself as a
first-party Claude Code session.
"""
from __future__ import annotations

import json
import platform
from typing import Any

from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMRequest,
    LLMResponse,
    _json_string,
)

# Claude Code wire-format fingerprint defaults.
# Captured from a real claude-cli 2.1.150 (external, cli) client running on
# Linux, routed through a capturing proxy. Each value is overridable via
# ProviderConfig.headers (case-insensitive lookup). Header keys are lowercase
# to match the undici wire format that httpx preserves on the wire.
#
# Note: x-stainless-os is injected dynamically in _build_request_parts because
# the real client reports the host OS rather than a fixed value.
_CLAUDE_CODE_FINGERPRINT: dict[str, str] = {
    "accept": "application/json",
    # Real claude-cli advertises "gzip, deflate, br, zstd", but httpx can only
    # auto-decompress gzip/deflate without optional brotli/zstandard deps.
    # Advertising encodings we cannot decode would corrupt the response body,
    # so we claim only what httpx can handle. Relays fall back to gzip.
    "accept-encoding": "gzip, deflate",
    "anthropic-version": "2023-06-01",
    "anthropic-beta": (
        "claude-code-20250219,context-1m-2025-08-07,"
        "interleaved-thinking-2025-05-14,context-management-2025-06-27,"
        "prompt-caching-scope-2026-01-05,advanced-tool-use-2025-11-20,"
        "effort-2025-11-24"
    ),
    "anthropic-dangerous-direct-browser-access": "true",
    "x-app": "cli",
    "x-stainless-arch": "x64",
    "x-stainless-lang": "js",
    "x-stainless-package-version": "0.94.0",
    "x-stainless-retry-count": "0",
    "x-stainless-runtime": "node",
    "x-stainless-runtime-version": "v24.3.0",
    "x-stainless-timeout": "600",
}
_CLAUDE_CODE_USER_AGENT = "claude-cli/2.1.150 (external, cli)"


def _detect_stainless_os() -> str:
    """Map the host OS to the value claude-cli's Stainless SDK reports."""
    system = platform.system()
    if system == "Windows":
        return "Windows"
    if system == "Darwin":
        return "MacOS"
    return system or "Linux"


def _cache_creation_tokens(usage: dict[str, Any]) -> int | None:
    """缓存写 token：顶层 cache_creation_input_tokens 优先，否则 5m/1h 细分求和。"""
    total = usage.get("cache_creation_input_tokens")
    if total is not None:
        return int(total)
    detail = usage.get("cache_creation")
    if isinstance(detail, dict):
        return int(detail.get("ephemeral_5m_input_tokens") or 0) + int(
            detail.get("ephemeral_1h_input_tokens") or 0
        )
    return None


class ClaudeProviderClient(BaseProviderClient):
    async def _serialize_user_message(self, message: LLMConversationMessage) -> dict[str, Any]:
        if message.inline_images:
            image_inputs = await self._prepare_image_inputs(message.image_urls, message.inline_images)
        else:
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
                            "content": await self._serialize_tool_result_content(item),
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

    async def _serialize_tool_result_content(
        self,
        message: LLMConversationMessage,
    ) -> str | list[dict[str, Any]]:
        image_inputs = await self._prepare_image_inputs(
            [],
            [] if message.is_tool_error else message.inline_images,
        )
        if not image_inputs:
            return message.content
        return [
            {"type": "text", "text": message.content},
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
            ],
        ]

    async def _build_request_parts(self, request: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = self.config.base_url.rstrip("/") + "/messages?beta=true"
        api_key = self._get_api_key()
        auth_key = "authorization" if self.config.auth_method == "bearer" else "x-api-key"
        auth_value = f"Bearer {api_key}" if self.config.auth_method == "bearer" else api_key

        # User overrides, indexed case-insensitively so that any fingerprint
        # default can be overridden without worrying about header casing.
        overrides = {k.lower(): v for k, v in self.config.headers.items()}

        # Build headers in undici wire order: auth + content-type first, then
        # inject Claude Code fingerprint defaults (x-stainless-os is dynamic),
        # then apply user overrides on top (preserving original casing).
        headers: dict[str, str] = {
            auth_key: auth_value,
            "content-type": "application/json",
        }
        for key, value in _CLAUDE_CODE_FINGERPRINT.items():
            if key not in overrides:
                headers[key] = value
        # x-stainless-os reflects the host OS; inject unless user overrode it.
        if "x-stainless-os" not in overrides:
            headers["x-stainless-os"] = _detect_stainless_os()
        for key, value in self.config.headers.items():
            headers[key] = value
        # user_agent config field takes precedence over both the fingerprint
        # default and any user-agent header set via config.headers. Strip any
        # existing user-agent key (regardless of casing) first to avoid a
        # duplicate header on the wire when both are set.
        if self.config.user_agent:
            for existing in [k for k in headers if k.lower() == "user-agent"]:
                del headers[existing]
            headers["user-agent"] = self.config.user_agent
        elif "user-agent" not in overrides:
            headers["user-agent"] = _CLAUDE_CODE_USER_AGENT
        use_cache = self.config.prompt_caching
        # cache_control 块：默认 ephemeral=5min；cache_ttl="1h" 启用 1h 扩展缓存。
        # 1h write 2× input（vs 5min 1.25×），仅当请求间隔 >5min 才更划算（如群聊）。
        # 注意第三方中转对 1h TTL 的支持因上游而异，套餐制 provider 无意义——默认空（5min）。
        cache_control: dict[str, str] = {"type": "ephemeral"}
        if self.config.cache_ttl:
            cache_control["ttl"] = self.config.cache_ttl

        # System prompt: match Claude Code wire format — array of text blocks
        # with cache_control on the final block.
        system: list[dict[str, Any]] = [{"type": "text", "text": request.system_prompt}]
        if use_cache:
            system[-1]["cache_control"] = dict(cache_control)

        # Messages: match Claude Code — cache_control on the last content block
        # of the last message. Skips thinking/redacted_thinking blocks.
        # String content is promoted to [{type: "text", ...}] when caching is on.
        messages = await self._serialize_messages(request.messages)
        if use_cache and messages:
            last_msg = messages[-1]
            content = last_msg.get("content")
            if isinstance(content, list) and content:
                last_block = content[-1]
                if last_block.get("type") not in ("thinking", "redacted_thinking"):
                    last_block["cache_control"] = dict(cache_control)
            elif isinstance(content, str) and content:
                last_msg["content"] = [{"type": "text", "text": content, "cache_control": dict(cache_control)}]

        payload: dict[str, Any] = {
            "model": request.model,
            "system": system,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        if request.allow_tool_calls and request.tools:
            tools: list[dict[str, Any]] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                }
                for spec in request.tools
            ]
            # Match Claude Code: cache_control on the final tool definition.
            if use_cache and tools:
                tools[-1]["cache_control"] = dict(cache_control)
            payload["tools"] = tools
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
            cache_creation_tokens=_cache_creation_tokens(usage),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            thinking_blocks=thinking_blocks,
        )

    @staticmethod
    def _assemble_stream_response(chunks: list[dict[str, Any]], fallback_model: str) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, str]] = {}  # block_index -> {id, name, input_json}
        thinking_acc: dict[int, dict[str, str]] = {}    # block_index -> {type, thinking, signature} 或 redacted {type, data}
        finish_reason: str | None = None
        model = fallback_model
        input_tokens: int | None = None
        output_tokens: int | None = None
        cache_creation_tokens: int | None = None
        cache_read_tokens: int | None = None
        current_block_index = -1

        for chunk in chunks:
            event = chunk.get("_sse_event", "")

            if event == "message_start":
                msg = chunk.get("message", {})
                model = str(msg.get("model", model))
                usage = msg.get("usage", {})
                if usage.get("input_tokens") is not None:
                    input_tokens = usage["input_tokens"]
                cc = _cache_creation_tokens(usage)
                if cc is not None:
                    cache_creation_tokens = cc
                if usage.get("cache_read_input_tokens") is not None:
                    cache_read_tokens = usage["cache_read_input_tokens"]

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
                    thinking_acc[current_block_index] = {"type": "thinking", "thinking": "", "signature": ""}
                elif block.get("type") == "redacted_thinking":
                    # redacted_thinking 的完整 data 载荷只出现在 start 事件，无后续 delta
                    thinking_acc[current_block_index] = {
                        "type": "redacted_thinking",
                        "data": str(block.get("data", "")),
                    }

            elif event == "content_block_delta":
                delta = chunk.get("delta", {})
                idx = chunk.get("index", current_block_index)
                if delta.get("type") == "text_delta":
                    text_parts.append(str(delta.get("text", "")))
                elif delta.get("type") == "input_json_delta":
                    if idx in tool_calls_acc:
                        tool_calls_acc[idx]["input_json"] += str(delta.get("partial_json", ""))
                elif delta.get("type") == "thinking_delta":
                    if thinking_acc.get(idx, {}).get("type") == "thinking":
                        thinking_acc[idx]["thinking"] += str(delta.get("thinking", ""))
                elif delta.get("type") == "signature_delta":
                    if thinking_acc.get(idx, {}).get("type") == "thinking":
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
            (
                {"type": "redacted_thinking", "data": acc["data"]}
                if acc.get("type") == "redacted_thinking"
                else {"type": "thinking", "thinking": acc["thinking"], "signature": acc["signature"]}
            )
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
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )

    @staticmethod
    def _combine_stream_trace(
        chunks: list[dict[str, Any]],
        fallback_model: str,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "model": fallback_model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {},
        }
        blocks: dict[int, dict[str, Any]] = {}
        tool_json: dict[int, str] = {}

        for chunk in chunks:
            event = chunk.get("_sse_event", "")
            if event == "message_start":
                started = chunk.get("message") or {}
                if isinstance(started, dict):
                    for key, value in started.items():
                        if key not in {"content", "usage"}:
                            message[key] = value
                    if isinstance(started.get("usage"), dict):
                        message["usage"].update(started["usage"])
            elif event == "content_block_start":
                index = int(chunk.get("index", len(blocks)) or 0)
                block = chunk.get("content_block") or {}
                if isinstance(block, dict):
                    blocks[index] = dict(block)
                    if block.get("type") == "tool_use":
                        tool_json[index] = ""
            elif event == "content_block_delta":
                index = int(chunk.get("index", 0) or 0)
                delta = chunk.get("delta") or {}
                block = blocks.setdefault(index, {})
                if not isinstance(delta, dict):
                    continue
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    block["type"] = "text"
                    block["text"] = str(block.get("text", "")) + str(delta.get("text", ""))
                elif delta_type == "thinking_delta":
                    block["type"] = "thinking"
                    block["thinking"] = str(block.get("thinking", "")) + str(delta.get("thinking", ""))
                elif delta_type == "signature_delta":
                    block["signature"] = str(block.get("signature", "")) + str(delta.get("signature", ""))
                elif delta_type == "input_json_delta":
                    tool_json[index] = tool_json.get(index, "") + str(delta.get("partial_json", ""))
            elif event == "message_delta":
                delta = chunk.get("delta") or {}
                if isinstance(delta, dict):
                    message.update(delta)
                if isinstance(chunk.get("usage"), dict):
                    message["usage"].update(chunk["usage"])

        for index, raw_json in tool_json.items():
            try:
                blocks[index]["input"] = json.loads(raw_json or "{}")
            except json.JSONDecodeError:
                blocks[index]["input"] = raw_json
        message["content"] = [block for _, block in sorted(blocks.items())]
        return message

    async def _complete_non_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        data = await self._post_json_with_fallback(url, headers, payload)
        return self._parse_response(data, request.model)

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request)
        payload["stream"] = True
        chunks = await self._post_stream_sse_with_fallback(url, headers, payload)
        return self._assemble_stream_response(chunks, request.model)
