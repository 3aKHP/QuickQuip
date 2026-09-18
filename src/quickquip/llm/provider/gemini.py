"""Google Gemini generateContent API provider client."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any
from urllib import parse

from quickquip.llm.tools import LLMConversationMessage, LLMToolCall
from quickquip.llm.provider.owner import build_response_owner
from quickquip.llm.provider.base import (
    BaseProviderClient,
    LLMGeneratedImage,
    LLMImageInput,
    LLMRequest,
    LLMResponse,
    LLMWebSearchReport,
    LLMWebSearchSource,
    _json_string,
    sanitize_gemini_schema,
)


def _inline_image_payload(part: dict[str, Any]) -> tuple[str, str] | None:
    """响应 part 的内联图片载荷（REST 驼峰 / 宽容蛇形两种键）。

    仅提取 ``image/*`` 媒体类型：其余 inlineData（如音频）保留在原生
    parts 中，不被误剥除误外发。
    """
    for key in ("inlineData", "inline_data"):
        payload = part.get(key)
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, str) and data.strip():
                media_type = str(
                    payload.get("mimeType") or payload.get("mime_type") or ""
                )
                if not media_type.startswith("image/"):
                    return None
                return data, media_type or "image/png"
    return None


def _extract_inline_images(
    parts: list[Any],
) -> tuple[list[LLMGeneratedImage], list[dict[str, Any]]]:
    """图片输出 parts（image 系模型的 inlineData）提取为归一附件并从
    parts 剥除：不进 native_blocks/thinking_blocks 的原生回放（base64
    回放是纯成本无收益），解码失败按无图跳过（from_base64 共享策略）。
    非图片 parts 原样保留（含非图片 inlineData）。"""
    images: list[LLMGeneratedImage] = []
    remaining: list[dict[str, Any]] = []
    for item in parts:
        if isinstance(item, dict):
            inline = _inline_image_payload(item)
            if inline is not None:
                data_b64, media_type = inline
                image = LLMGeneratedImage.from_base64(
                    data_b64, media_type=media_type, source="gemini.inline_data"
                )
                if image is not None:
                    images.append(image)
                continue
        remaining.append(item)
    return images, remaining


class GeminiProviderClient(BaseProviderClient):
    def _serialize_user_parts(
        self, message: LLMConversationMessage, image_inputs: list[LLMImageInput]
    ) -> list[dict[str, Any]]:
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

    async def _serialize_messages(
        self, messages: list[LLMConversationMessage]
    ) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        prepared_images = await self._prepare_request_images(messages)
        pending_tool_results: list[tuple[LLMConversationMessage, list[LLMImageInput]]] = []

        async def _flush_tool_results() -> None:
            nonlocal pending_tool_results
            if not pending_tool_results:
                return
            serialized.append(
                {
                    "role": "user",
                    "parts": self._serialize_function_response_parts(
                        [item for item, _ in pending_tool_results]
                    ),
                }
            )
            # Gemini requires the complete functionResponse batch to stay in one
            # Content. Ordinary multimodal parts follow as separate user turns.
            for _, image_inputs in pending_tool_results:
                image_parts = self._serialize_tool_result_image_parts(image_inputs)
                if image_parts:
                    serialized.append({"role": "user", "parts": image_parts})
            pending_tool_results = []

        for message, image_inputs in zip(messages, prepared_images, strict=True):
            if message.role == "tool":
                pending_tool_results.append((message, image_inputs))
                continue

            await _flush_tool_results()
            if message.role == "assistant":
                if message.native_content is not None:
                    # 原生路径（§7.2）：历史记录的原样 parts 深拷贝回放，
                    # 保留 functionCall 与 thoughtSignature 的原始位置。
                    serialized.append(
                        {
                            "role": "model",
                            "parts": [
                                deepcopy(part) for part in message.native_content
                            ],
                        }
                    )
                    continue
                parts = self._replay_parts(message.thinking_blocks)
                if not parts:
                    if message.content:
                        parts.append({"text": message.content})
                    for call in message.tool_calls:
                        try:
                            args = json.loads(call.arguments_json or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        parts.append({
                            "functionCall": {
                                "id": call.id,
                                "name": call.name,
                                "args": args,
                            }
                        })
                serialized.append({"role": "model", "parts": parts or [{"text": ""}]})
                continue

            serialized.append(
                {
                    "role": "user",
                    "parts": self._serialize_user_parts(message, image_inputs),
                }
            )

        await _flush_tool_results()
        return serialized

    @staticmethod
    def _replay_parts(thinking_blocks: list[Any]) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for block in thinking_blocks:
            if not isinstance(block, dict) or block.get("type") != "gemini_part":
                continue
            part = block.get("part")
            if isinstance(part, dict):
                parts.append(deepcopy(part))
        return parts

    @staticmethod
    def _serialize_function_response_parts(
        tool_results: list[LLMConversationMessage],
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for item in tool_results:
            function_response: dict[str, Any] = {
                "name": item.tool_name,
                "response": {
                    "content": item.content,
                    "is_error": item.is_tool_error,
                },
            }
            if item.tool_call_id:
                function_response["id"] = item.tool_call_id
            parts.append({"functionResponse": function_response})
        return parts

    def _serialize_tool_result_image_parts(
        self,
        image_inputs: list[LLMImageInput],
    ) -> list[dict[str, Any]]:
        return [
            {
                "inline_data": {
                    "mime_type": image.media_type,
                    "data": image.data_base64,
                }
            }
            for image in image_inputs
        ]

    async def _build_request_parts(
        self, request: LLMRequest, *, stream: bool = False
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        api_key = self._get_api_key()
        action = "streamGenerateContent" if stream else "generateContent"
        url = self.config.base_url.rstrip("/") + f"/models/{request.model}:{action}"
        headers = {"content-type": "application/json"}
        if self.config.auth_method == "bearer":
            headers["authorization"] = f"Bearer {api_key}"
        else:
            # Preserve the existing Gemini-compatible relay contract. Gateway
            # deployments should select bearer auth so credentials stay out of
            # URLs and Nginx access logs.
            url += f"?key={parse.quote(api_key)}"
        if stream:
            url += "&alt=sse" if "?" in url else "?alt=sse"
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
        if request.builtin_search:
            # google_search 是服务端执行的工具声明，与客户端 functionDeclarations
            # 并列成独立 tools 条目；不依赖 allow_tool_calls / 客户端工具列表。
            payload.setdefault("tools", []).append({"google_search": {}})
        headers.update(self.config.headers)
        if self.config.user_agent:
            headers["user-agent"] = self.config.user_agent
        if self.config.extra_body:
            payload.update(self.config.extra_body)
        return url, headers, payload

    @staticmethod
    def _parse_candidate(candidate: dict[str, Any], fallback_model: str) -> LLMResponse:
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        # 图片输出 parts 提取见 _extract_inline_images；剥除后 functionCall
        # 缺省 id 按剩余 parts 连续重编号。
        generated_images, kept_parts = _extract_inline_images(
            parts if isinstance(parts, list) else []
        )
        normalized_parts: list[dict[str, Any]] = [
            GeminiProviderClient._normalize_part(item, index)
            for index, item in enumerate(kept_parts, 1)
            if isinstance(item, dict)
        ]
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        replay_required = any(
            item.get("thought") is True or isinstance(item.get("thoughtSignature"), str)
            for item in normalized_parts
        )
        thinking_blocks: list[dict[str, Any]] = []
        for item in normalized_parts:
            if item.get("thought") is True:
                pass
            elif "text" in item:
                text_parts.append(str(item.get("text", "")))
            if "functionCall" in item:
                function_call = item.get("functionCall", {})
                call_id = str(function_call.get("id", "")).strip()
                tool_calls.append(
                    LLMToolCall(
                        id=call_id,
                        name=str(function_call.get("name", "")).strip(),
                        arguments_json=_json_string(function_call.get("args", {})),
                    )
                )
                if replay_required:
                    thinking_blocks.append({
                        "type": "gemini_part",
                        "part": deepcopy(item),
                    })
                continue
            if replay_required:
                thinking_blocks.append({"type": "gemini_part", "part": deepcopy(item)})
        grounding = candidate.get("groundingMetadata")
        web_search = (
            GeminiProviderClient._parse_grounding_metadata(grounding)
            if isinstance(grounding, dict)
            else None
        )
        return LLMResponse(
            text="".join(text_parts).strip(),
            model=fallback_model,
            tool_calls=tool_calls,
            finish_reason=str(candidate.get("finishReason", "")).strip() or None,
            thinking_blocks=thinking_blocks,
            native_blocks=[deepcopy(part) for part in normalized_parts] or None,
            web_search=web_search,
            generated_images=generated_images,
        )

    @staticmethod
    def _parse_grounding_metadata(grounding: dict[str, Any]) -> LLMWebSearchReport | None:
        queries = [
            str(item).strip()
            for item in grounding.get("webSearchQueries") or []
            if str(item).strip()
        ]
        sources: list[LLMWebSearchSource] = []
        seen_urls: set[str] = set()
        for chunk in grounding.get("groundingChunks") or []:
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            url = str(web.get("uri") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            # title 缺失时保持空串：grounding 链接是 provider 侧重定向长链，
            # 回填为 title 会在展示层变成「长链 — 域名」，由渲染层回退为仅域名。
            sources.append(
                LLMWebSearchSource(
                    title=str(web.get("title") or "").strip(),
                    url=url,
                )
            )
        if not queries and not sources:
            return None
        return LLMWebSearchReport(queries=queries, sources=sources)

    @staticmethod
    def _normalize_part(part: dict[str, Any], index: int) -> dict[str, Any]:
        normalized = deepcopy(part)
        function_call = normalized.get("functionCall")
        if isinstance(function_call, dict) and not str(function_call.get("id", "")).strip():
            function_call["id"] = f"gemini_tool_{index}"
        return normalized

    @staticmethod
    def _assemble_stream_response(chunks: list[dict[str, Any]], fallback_model: str) -> LLMResponse:
        combined = GeminiProviderClient._combine_stream_trace(chunks, fallback_model)
        candidates = combined.get("candidates", [])
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        response = GeminiProviderClient._parse_candidate(candidate, fallback_model)
        usage = combined.get("usageMetadata", {})
        if isinstance(usage, dict):
            response.input_tokens = usage.get("promptTokenCount")
            response.output_tokens = usage.get("candidatesTokenCount")
            response.cache_read_tokens = usage.get("cachedContentTokenCount")
            response.thinking_tokens = usage.get("thoughtsTokenCount")
        return response

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
                            parts[-1]["text"] = (
                                str(parts[-1]["text"]) + str(raw_part.get("text", ""))
                            )
                            for key, value in raw_part.items():
                                if key != "text":
                                    parts[-1][key] = deepcopy(value)
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
        data, final_url = await self._post_json_candidate(url, headers, payload)
        candidates = data.get("candidates", [])
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        response = self._parse_candidate(candidate, request.model)
        usage = data.get("usageMetadata", {})
        response.input_tokens = usage.get("promptTokenCount")
        response.output_tokens = usage.get("candidatesTokenCount")
        response.cache_read_tokens = usage.get("cachedContentTokenCount")
        response.thinking_tokens = usage.get("thoughtsTokenCount")
        response.owner = build_response_owner(self.config, final_url, request.model)
        return response

    async def _complete_stream(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = await self._build_request_parts(request, stream=True)
        chunks, final_url = await self._post_stream_sse_candidate(url, headers, payload)
        response = self._assemble_stream_response(chunks, request.model)
        response.owner = build_response_owner(self.config, final_url, request.model)
        return response
