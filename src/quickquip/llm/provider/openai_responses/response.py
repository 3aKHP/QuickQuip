"""Responses 终态 output items 的解析/校验与 usage 映射。

校验语义对齐移植源（prism-vesicle items.ts/response.ts）：

- 未知 item 类型 fail-closed（含 web_search_call——QuickQuip 的原生搜索
  仅 gemini 协议声明，Responses 侧未启用该工具族）。
- ``message`` 只接受 assistant 角色 + ``output_text``/``refusal`` content。
- ``reasoning`` 的 ``summary`` 仅供展示（thinking_blocks），密文
  ``encrypted_content`` 作为不透明字段保留在原 item 内供回放。
- ``function_call`` 必须带 call_id/name/arguments，重复 call_id 抛错。
"""
from __future__ import annotations

from typing import Any

from quickquip.llm.provider.base import LLMProviderError, LLMResponse
from quickquip.llm.tools import LLMToolCall


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


def parse_responses_body(
    body: Any, *, provider_id: str, fallback_model: str
) -> LLMResponse:
    """终态 response body → ``LLMResponse``。

    ``native_blocks`` 承载当前工具循环的有序原生结果（reasoning 密文 +
    function_call + message 原样保序），供下一轮原样回传（PR-A 循环内
    契约）与执行记录持久化；跨轮回放由 PR-B 启用。
    """
    if not isinstance(body, dict) or not isinstance(body.get("output"), list):
        raise _malformed("Provider 响应缺少有序 output items。", provider_id)
    status = body.get("status")
    if status != "completed":
        error = body.get("error")
        incomplete = body.get("incomplete_details")
        detail = (
            error.get("message")
            if isinstance(error, dict)
            else None
        ) or (
            incomplete.get("reason")
            if isinstance(incomplete, dict)
            else None
        ) or status
        raise LLMProviderError(
            f"[{provider_id}] Provider 响应未完成：{detail}", status_code=400
        )

    items = validate_output_items(body["output"], provider_id=provider_id)
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
    if not text and not tool_calls:
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
        finish_reason=str(status),
        native_blocks=list(items),
        thinking_blocks=thinking_blocks,
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
