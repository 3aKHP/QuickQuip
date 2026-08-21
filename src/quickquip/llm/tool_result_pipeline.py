"""Tool result post-processing pipeline for the tool-call loop.

Owns every enforcement/degradation concern applied around a tool execution:
sensitive-word scans (arguments before execution, result content and image
descriptions after), the per-request tool image budget, and non-vision model
image preprocessing fallback. The loop itself only sequences calls; all
mutable state here (remaining image budget) has this single owner.
"""

from __future__ import annotations

from quickquip.common.sensitive_filter import (
    SCRUB_PLACEHOLDER,
    get_filter as _get_sensitive_filter,
    log_hits as _log_sensitive_hits,
)
from quickquip.llm.provider import LLMRequest
from quickquip.llm.tools import LLMToolResult

# Threshold above which a scrubbed tool result is judged too noisy to keep
# even with placeholders, and gets replaced wholesale. Picked empirically:
# >5 distinct block hits in one tool result almost always means a search
# returned a hot-topic page rather than scattered incidental matches, and
# scrubbing those gives a Swiss-cheese result the model can't reason over.
_TOOL_RESULT_SCRUB_HIT_LIMIT = 5
# Below this content length, even a single block hit makes the remaining
# fragment too thin to be useful — replace wholesale instead.
_TOOL_RESULT_MIN_USABLE_LEN = 200
_TOOL_RESULT_BLOCK_REPLACEMENT = (
    "工具返回内容包含违规内容，已整体丢弃。请尝试其他查询、来源或换个表述。"
)
_TOOL_ARGS_BLOCK_REPLACEMENT = (
    "工具调用参数包含违规内容，已拒绝执行。请用其他表述重新尝试。"
)
_TOOL_IMAGE_PREPROCESSING_UNAVAILABLE = (
    "工具返回了图片，但当前模型无法直接读取图片，且前置图片识别服务不可用；已省略图片。"
)
_TOOL_IMAGE_PREPROCESSING_FAILED = "工具图片转述失败，已省略图片。"


def _append_tool_notice(result: LLMToolResult, notice: str) -> LLMToolResult:
    content = "\n".join(part for part in (result.content, notice) if part)
    return LLMToolResult(
        call_id=result.call_id,
        name=result.name,
        content=content,
        images=list(result.images),
        is_error=result.is_error,
    )


def _request_image_budget(request: LLMRequest) -> int:
    existing_images = sum(
        len(message.image_urls) + len(message.inline_images)
        for message in request.messages
        if message.role == "user"
    )
    return max(0, 5 - existing_images)


class ToolResultPipeline:
    """Per-run post-processing pipeline for tool results.

    The sensitive filter is re-fetched at each round boundary
    (`begin_round`) so a filter reload between rounds takes effect at the
    same point as before this extraction.
    """

    def __init__(self, *, provider, request: LLMRequest, context, image_preprocessor=None):
        self._image_preprocessor = image_preprocessor
        self._non_vision_model = context.model in provider.non_vision_models
        self._scope_key = getattr(context, "chat_scope", None) or str(
            getattr(context, "group_id", "?")
        )
        self._remaining_image_budget = _request_image_budget(request)
        self._sensitive = None

    def begin_round(self) -> None:
        self._sensitive = _get_sensitive_filter()

    def check_call_arguments(self, call) -> LLMToolResult | None:
        """Pre-execution: scan the LLM-constructed arguments. The model
        can fold a user's borderline phrasing into a search query and
        turn an innocuous question into a payload that would trip the
        next provider request — block before we even call the tool."""
        sensitive = self._sensitive
        if sensitive is None or not sensitive.is_loaded:
            return None
        args_scan = sensitive.scan(call.arguments_json or "")
        if args_scan.hits:
            _log_sensitive_hits(
                f"tool_args:{call.name}", self._scope_key, args_scan,
            )
        if args_scan.blocked:
            return LLMToolResult(
                call_id=call.id,
                name=call.name,
                content=_TOOL_ARGS_BLOCK_REPLACEMENT,
                is_error=True,
            )
        return None

    async def process_result(self, call, result: LLMToolResult) -> LLMToolResult:
        result = self._enforce_sensitive_result(call, result)
        result = self._apply_image_budget(result)
        if result.images and self._non_vision_model:
            result = await self._preprocess_images(call, result)
        return result

    def _enforce_sensitive_result(self, call, result: LLMToolResult) -> LLMToolResult:
        """Post-execution: scan the tool result. This is the highest-risk
        entry point — search/fetch tools pull external content that
        the user can steer (via query) but we cannot pre-vet. A single
        tool_result rich in flagged terms then rides into the next
        provider request as part of `messages` and trips the gateway."""
        sensitive = self._sensitive
        if sensitive is None or not sensitive.is_loaded or not result.content:
            return result
        result_scan = sensitive.scan(result.content)
        if result_scan.hits:
            _log_sensitive_hits(
                f"tool_result:{call.name}", self._scope_key, result_scan,
            )
        if result_scan.blocked:
            block_count = sum(
                1 for h in result_scan.hits if h.severity == "block"
            )
            if (
                block_count > _TOOL_RESULT_SCRUB_HIT_LIMIT
                or len(result.content) < _TOOL_RESULT_MIN_USABLE_LEN
            ):
                return LLMToolResult(
                    call_id=result.call_id,
                    name=result.name,
                    content=_TOOL_RESULT_BLOCK_REPLACEMENT,
                    is_error=True,
                )
            scrubbed = sensitive.scrub(result.content, SCRUB_PLACEHOLDER)
            return LLMToolResult(
                call_id=result.call_id,
                name=result.name,
                content=scrubbed,
                is_error=True,
            )
        return result

    def _apply_image_budget(self, result: LLMToolResult) -> LLMToolResult:
        if result.is_error and result.images:
            result = LLMToolResult(
                call_id=result.call_id,
                name=result.name,
                content=result.content,
                is_error=True,
            )

        if result.images:
            accepted_images = result.images[:self._remaining_image_budget]
            omitted_images = len(result.images) - len(accepted_images)
            result = LLMToolResult(
                call_id=result.call_id,
                name=result.name,
                content=result.content,
                images=accepted_images,
                is_error=result.is_error,
            )
            self._remaining_image_budget -= len(accepted_images)
            if omitted_images:
                result = _append_tool_notice(
                    result,
                    f"MCP 工具省略了 {omitted_images} 个超出当前请求图片预算的图片项。",
                )
        return result

    async def _preprocess_images(self, call, result: LLMToolResult) -> LLMToolResult:
        if self._image_preprocessor is None:
            return LLMToolResult(
                call_id=result.call_id,
                name=result.name,
                content="\n".join(
                    part for part in (result.content, _TOOL_IMAGE_PREPROCESSING_UNAVAILABLE) if part
                ),
                is_error=result.is_error,
            )
        descriptions = await self._image_preprocessor.describe_inline_images(result.images)
        descriptions_by_label = {
            description.source_url: description
            for description in descriptions
        }
        description_parts: list[str] = []
        failed_count = 0
        for image in result.images:
            description = descriptions_by_label.get(image.source_label)
            if (
                description is None
                or not description.success
                or not description.text_description.strip()
            ):
                failed_count += 1
                continue
            description_parts.append(
                f"[{image.source_label}]\n{description.text_description.strip()}"
            )
        description_blob = "\n".join(description_parts)
        sensitive = self._sensitive
        if description_blob and sensitive is not None and sensitive.is_loaded:
            description_scan = sensitive.scan(description_blob)
            if description_scan.hits:
                _log_sensitive_hits(
                    f"tool_image_description:{call.name}", self._scope_key, description_scan,
                )
            if description_scan.blocked:
                result = LLMToolResult(
                    call_id=result.call_id,
                    name=result.name,
                    content=_TOOL_RESULT_BLOCK_REPLACEMENT,
                    is_error=True,
                )
                description_parts = []
                failed_count = 0
        if description_parts or failed_count:
            notices = list(description_parts)
            if failed_count:
                notices.append(f"{_TOOL_IMAGE_PREPROCESSING_FAILED}（{failed_count} 张）")
            result = LLMToolResult(
                call_id=result.call_id,
                name=result.name,
                content="\n".join(part for part in [result.content, *notices] if part),
                is_error=result.is_error,
            )
        return result
