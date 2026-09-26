"""Responses 终态 output items 的解析/校验与 usage 映射。

校验语义对齐移植源（prism-vesicle items.ts/response.ts）：

- 未知 item 类型 fail-closed（含 web_search_call——QuickQuip 的原生搜索
  仅 gemini 协议声明，Responses 侧未启用该工具族）。唯一例外是
  ``image_generation_call``：codex 类后端会在服务端注入该工具，条目
  剥除出 native_blocks 并提取为 ``generated_images``（见
  ``_extract_generated_images``），其余条目照旧走严格校验。
- ``message`` 只接受 assistant 角色 + ``output_text``/``refusal`` content。
- ``reasoning`` 的 ``summary`` 仅供展示（thinking_blocks），密文
  ``encrypted_content`` 作为不透明字段保留在原 item 内供回放。
- ``function_call`` 必须带 call_id/name/arguments，重复 call_id 抛错。
"""
from __future__ import annotations

from typing import Any

from quickquip.llm.provider.base import (
    LLMGeneratedImage,
    LLMProviderError,
    LLMResponse,
)
from quickquip.llm.tools import LLMToolCall

# image_generation_call.output_format → media_type（未知格式按 image/<fmt> 透传）
_IMAGE_OUTPUT_FORMATS = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _extract_generated_images(
    items: list[Any],
) -> tuple[list[LLMGeneratedImage], list[Any]]:
    """剥除内置 image_generation 工具条目并提取为归一图片附件。

    codex 类后端在服务端注入该工具（请求未声明也会出现）。条目无论
    提取成败都从 items 剥除：base64 不进 native_blocks（回放是纯成本
    无收益），解码失败按无图跳过（``LLMGeneratedImage.from_base64``
    共享策略）——图片丢失不应连累正文交付。
    """
    images: list[LLMGeneratedImage] = []
    remaining: list[Any] = []
    for item in items:
        if isinstance(item, dict) and item.get("type") == "image_generation_call":
            fmt = str(item.get("output_format") or "png").strip().lower() or "png"
            image = LLMGeneratedImage.from_base64(
                str(item.get("result") or ""),
                media_type=_IMAGE_OUTPUT_FORMATS.get(fmt, f"image/{fmt}"),
                source="responses.image_generation",
            )
            if image is not None:
                images.append(image)
            continue
        remaining.append(item)
    return images, remaining


def validate_output_items(
    items: Any, *, provider_id: str
) -> list[dict[str, Any]]:
    """终态/回放 output items 的逐类型结构校验；返回原列表（不拷贝）。"""
    if not isinstance(items, list):
        raise _malformed("Provider 响应缺少有序 output items。", provider_id)
    call_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise _malformed("Provider 响应包含畸形 output item。", provider_id)
        item_type = item.get("type")
        if item_type == "message":
            _validate_message_item(item, provider_id)
        elif item_type == "reasoning":
            _validate_reasoning_item(item, provider_id)
        elif item_type == "function_call":
            call_id = item.get("call_id")
            name = item.get("name")
            if not isinstance(call_id, str) or not call_id or not name:
                raise _malformed(
                    "Provider 响应包含畸形 function_call item。", provider_id
                )
            if not isinstance(item.get("arguments"), str):
                raise _malformed(
                    "Provider 响应包含畸形 function_call item。", provider_id
                )
            if call_id in call_ids:
                raise _malformed(
                    f"Provider 响应重复了 function call_id {call_id}。", provider_id
                )
            call_ids.add(call_id)
        else:
            raise _malformed(
                f"Provider 响应包含不支持的 output item "
                f"{item_type if isinstance(item_type, str) else 'unknown'}。",
                provider_id,
            )
    return items


def blocks_replay_valid(blocks: list) -> bool:
    """持久化原生批次的跨轮回放资格（历史投影调用，bool 语义）。

    结构校验复用终态校验；附加回放安全条件——``reasoning`` item 必须携带
    非空 ``encrypted_content``：store:false 手动上下文下缺密文的 reasoning
    不具备原生回放资格，投影层降级走通用重建。
    """
    for block in blocks:
        if not isinstance(block, dict):
            return False
        if block.get("type") == "reasoning" and not str(
            block.get("encrypted_content") or ""
        ).strip():
            return False
    try:
        validate_output_items(list(blocks), provider_id="history")
    except LLMProviderError:
        return False
    return True


def _validate_message_item(item: dict[str, Any], provider_id: str) -> None:
    if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
        raise _malformed("Provider 响应包含畸形 message item。", provider_id)
    for part in item["content"]:
        if not isinstance(part, dict):
            raise _malformed("Provider 响应包含畸形 message content。", provider_id)
        if part.get("type") == "output_text" and isinstance(part.get("text"), str):
            continue
        if part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
            continue
        part_type = part.get("type")
        raise _malformed(
            f"Provider 响应包含不支持的 message content "
            f"{part_type if isinstance(part_type, str) else 'unknown'}。",
            provider_id,
        )


def _validate_reasoning_item(item: dict[str, Any], provider_id: str) -> None:
    summary = item.get("summary")
    if summary is not None:
        if not isinstance(summary, list) or not all(
            isinstance(part, dict)
            and part.get("type") == "summary_text"
            and isinstance(part.get("text"), str)
            for part in summary
        ):
            raise _malformed(
                "Provider 响应包含畸形 reasoning summary。", provider_id
            )
    if item.get("encrypted_content") is not None and not isinstance(
        item.get("encrypted_content"), str
    ):
        raise _malformed(
            "Provider 响应包含畸形 encrypted reasoning。", provider_id
        )
    content = item.get("content")
    if content is not None and (not isinstance(content, list) or content):
        raise _malformed(
            "Provider 响应包含不支持的 reasoning content。", provider_id
        )


def failure_detail(body: dict[str, Any]) -> str:
    """终态失败/incomplete 的可读原因（error/incomplete_details 形状守卫）。"""
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    incomplete = body.get("incomplete_details")
    if isinstance(incomplete, dict) and incomplete.get("reason"):
        return str(incomplete["reason"])
    return str(body.get("status") or "unknown")


def parse_responses_body(
    body: Any, *, provider_id: str, fallback_model: str
) -> LLMResponse:
    """终态 response body → ``LLMResponse``。

    ``native_blocks`` 承载当前工具循环的有序原生结果（reasoning 密文 +
    function_call + message 原样保序），供下一轮原样回传（PR-A 循环内
    契约）与执行记录持久化；跨轮回放由 PR-B 启用。

    ``incomplete`` 是正常截断（reasoning token 计入 max_output_tokens，
    思考模型下常见）：max_output_tokens 归一为兄弟协议的 ``length`` 终值
    照常返回（可空正文——截断可能发生在可见输出之前），其余 reason 原样
    作为终值；仅 ``failed``/``cancelled`` 等形态抛错。
    """
    if not isinstance(body, dict) or not isinstance(body.get("output"), list):
        raise _malformed("Provider 响应缺少有序 output items。", provider_id)
    status = body.get("status")
    if status not in ("completed", "incomplete"):
        raise LLMProviderError(
            f"[{provider_id}] Provider 响应未完成：{failure_detail(body)}",
            status_code=400,
        )

    generated_images, stripped_items = _extract_generated_images(body["output"])
    items = validate_output_items(stripped_items, provider_id=provider_id)
    text = _message_text(items)
    tool_calls = [
        LLMToolCall(
            id=str(item["call_id"]),
            name=str(item["name"]),
            arguments_json=_arguments_json(item["arguments"]),
        )
        for item in items
        if item.get("type") == "function_call"
    ]
    finish_reason = str(status)
    if status == "incomplete":
        incomplete = body.get("incomplete_details")
        reason = (
            str(incomplete.get("reason"))
            if isinstance(incomplete, dict) and incomplete.get("reason")
            else "incomplete"
        )
        finish_reason = "length" if reason == "max_output_tokens" else reason
    elif not text and not tool_calls and not generated_images:
        raise _malformed(
            "Provider 响应不包含正文或 function calls。", provider_id
        )

    reasoning = _summary_text(items)
    thinking_blocks: list[dict[str, Any]] = []
    if reasoning:
        thinking_blocks.append(
            {"type": "reasoning", "reasoning_content": reasoning}
        )
    usage = parse_usage(body.get("usage"))
    return LLMResponse(
        text=text,
        model=str(body.get("model") or fallback_model),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        native_blocks=list(items),
        thinking_blocks=thinking_blocks,
        generated_images=generated_images,
        **usage,
    )


def parse_usage(usage: Any) -> dict[str, int | None]:
    """Responses usage → ``LLMResponse`` token 桶。

    ``input_tokens`` 为 inclusive 口径（含 ``cached_tokens``），与
    usage/pricing/usage_store 的默认分支一致；``reasoning_tokens`` 归
    thinking_tokens（观测口径，不参与计费加成）。
    """
    if not isinstance(usage, dict):
        return {}
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    return {
        "input_tokens": _optional_int(usage.get("input_tokens")),
        "output_tokens": _optional_int(usage.get("output_tokens")),
        "cache_read_tokens": (
            _optional_int(input_details.get("cached_tokens"))
            if isinstance(input_details, dict)
            else None
        ),
        "thinking_tokens": (
            _optional_int(output_details.get("reasoning_tokens"))
            if isinstance(output_details, dict)
            else None
        ),
    }


def _message_text(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                parts.append(str(part.get("text", "")))
            elif part.get("type") == "refusal":
                parts.append(str(part.get("refusal") or ""))
    return "".join(parts)


def _summary_text(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        if item.get("type") != "reasoning":
            continue
        for part in item.get("summary") or []:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
    return "".join(parts)


def _arguments_json(raw: Any) -> str:
    text = str(raw).strip()
    return text or "{}"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _malformed(message: str, provider_id: str) -> LLMProviderError:
    return LLMProviderError(f"[{provider_id}] {message}")
