"""Responses SSE 事件折叠状态机。

移植自 prism-vesicle stream.ts（HTTP 路径），防御性校验策略直译：

- 语义事件（delta/output_item.done/completed/failed/incomplete/error）
  显式处理；结构型事件显式容忍忽略；**未知事件 fail-closed 抛错**。
- ``sequence_number`` 连续性校验；个别事件被中转剥除序号后退化为
  单调递增校验（剥除事件消耗了全局序号位，严格等值会误报跳变）。
- 终态（response.completed）之后再收到任何事件即畸形。
- 流式累计（正文/reasoning/function arguments）与终态 body 逐项交叉
  验证，不一致判畸形——重试不得泄漏半截输出。
- ``codex-http-relay``：output_item.done 按到达顺序索引校验并与终态
  逐项子集核对（终态缺省可选字段时以流式完整 item 为准），并容忍
  ``codex.*`` 中转私有结构事件。

QuickQuip 基座（base._post_stream_sse）已在传输层把 SSE 文本折叠为事件
dict 列表并容忍无 ``[DONE]`` 终止（Responses 以 response.completed 收
尾），本模块只做事件语义折叠。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from quickquip.llm.provider.base import LLMProviderError, LLMResponse
from quickquip.llm.provider.openai_responses.profiles import ResponsesProfile
from quickquip.llm.provider.openai_responses.response import parse_responses_body

# 结构型事件：协议演进新增的转发形态，显式容忍忽略。
_TOLERATED_EVENTS = frozenset(
    {
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.content_part.done",
        "response.output_text.done",
        "response.refusal.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
        "response.reasoning_summary_text.done",
        "response.function_call_arguments.done",
    }
)

# codex-http-relay 的中转私有结构事件（profile 能力位放行）。
_RELAY_EVENTS = frozenset(
    {
        "codex.rate_limits",
        "codex.response.metadata",
        "responsesapi.websocket_timing",
    }
)

# response.failed 的致命错误码白名单：重试必然徒劳；表外的服务端错误
# 视为瞬态（经 status_code=500 走基座可重试分类）。
_FATAL_FAILURE_CODES = frozenset(
    {
        "context_length_exceeded",
        "insufficient_quota",
        "usage_not_included",
        "cyber_policy",
        "invalid_prompt",
        "bio_policy",
    }
)


def fold_stream_events(
    events: list[dict[str, Any]],
    *,
    provider_id: str,
    fallback_model: str,
    profile: ResponsesProfile,
) -> LLMResponse:
    """把一次 SSE 流的事件列表折叠为终态 ``LLMResponse``（含交叉验证）。"""
    streamed_content: list[str] = []
    streamed_reasoning: list[str] = []
    streamed_arguments: dict[int, str] = {}
    relay_done_items: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    expected_sequence = 0
    # 一旦出现无序号事件（中转剥除），序号校验退化为单调不减。
    saw_unnumbered = False

    def _malformed(detail: str) -> LLMProviderError:
        return LLMProviderError(f"[{provider_id}] Responses 流畸形：{detail}")

    for event in events:
        if not isinstance(event, dict):
            raise _malformed("事件不是 JSON 对象。")
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise _malformed("事件缺少 type。")
        if terminal is not None:
            raise _malformed(f"终态事件后又收到 {event_type}。")
        sequence = event.get("sequence_number")
        if sequence is None:
            saw_unnumbered = True
        elif not isinstance(sequence, int) or isinstance(sequence, bool):
            raise _malformed(
                f"事件序号从 {expected_sequence} 跳变到 {sequence}。"
            )
        elif saw_unnumbered:
            # 剥除事件消耗了全局序号位：只拒绝回跳，不要求严格等值。
            if sequence < expected_sequence:
                raise _malformed(
                    f"事件序号从 {expected_sequence} 回跳到 {sequence}。"
                )
            expected_sequence = sequence + 1
        elif sequence != expected_sequence:
            raise _malformed(
                f"事件序号从 {expected_sequence} 跳变到 {sequence}。"
            )
        else:
            expected_sequence += 1

        if event_type in ("response.output_text.delta", "response.refusal.delta"):
            delta = event.get("delta")
            if not isinstance(delta, str):
                raise _malformed("正文 delta 畸形。")
            streamed_content.append(delta)
        elif event_type == "response.reasoning_summary_text.delta":
            delta = event.get("delta")
            if not isinstance(delta, str):
                raise _malformed("reasoning delta 畸形。")
            streamed_reasoning.append(delta)
        elif event_type == "response.function_call_arguments.delta":
            output_index = event.get("output_index")
            delta = event.get("delta")
            if not isinstance(output_index, int) or not isinstance(delta, str):
                raise _malformed("function arguments delta 畸形。")
            streamed_arguments[output_index] = (
                streamed_arguments.get(output_index, "") + delta
            )
        elif event_type == "response.output_item.done":
            item = event.get("item")
            if profile.reconcile_relay_items:
                if not isinstance(item, dict):
                    raise _malformed("中转完成的 output item 缺失。")
                output_index = event.get(
                    "output_index", len(relay_done_items)
                )
                if (
                    not isinstance(output_index, int)
                    or isinstance(output_index, bool)
                    or output_index != len(relay_done_items)
                ):
                    raise _malformed(
                        f"中转完成的 output item 索引 {output_index} 与预期 "
                        f"{len(relay_done_items)} 不符。"
                    )
                relay_done_items.append(item)
        elif event_type == "response.completed":
            response_body = event.get("response")
            if not isinstance(response_body, dict):
                raise _malformed("completed 事件缺少终态 response。")
            terminal = response_body
        elif event_type == "response.incomplete":
            # incomplete 是正常截断终态（reasoning 计入输出上限时常见）：
            # 折叠进终态由 parse_responses_body 归一为 length/原因终值。
            response_body = event.get("response")
            if not isinstance(response_body, dict):
                raise _malformed("incomplete 事件缺少终态 response。")
            terminal = response_body
        elif event_type == "response.failed":
            # 载荷形状先守卫再取字段：畸形载荷以 malformed 终止，不允许
            # AttributeError 逃逸成 complete() 的非流式 fallback。
            response_body = event.get("response")
            error = response_body.get("error") if isinstance(response_body, dict) else None
            if not isinstance(error, dict):
                error = {}
                message = "unknown"
            else:
                message = error.get("message") or "unknown"
            code = error.get("code")
            # 有 error 对象且码不在致命表内才视为瞬态（对齐移植源
            # stream.ts：error != null && !fatal）；无 error 对象的 failed
            # 是终态失败，不做满额重发。
            fatal = not error or code in _FATAL_FAILURE_CODES
            raise LLMProviderError(
                f"[{provider_id}] Responses 流失败（{code or 'unknown'}）：{message}",
                status_code=400 if fatal else 500,
            )
        elif event_type == "error":
            error = event.get("error")
            if not isinstance(error, dict):
                raise _malformed("error 事件载荷畸形。")
            code = error.get("code")
            if code in _FATAL_FAILURE_CODES:
                # 与 response.failed 共用致命码判据：重试必然徒劳的码
                # 直接终态拒绝。
                raise LLMProviderError(
                    f"[{provider_id}] Responses 流错误"
                    f"（{code}）：{error.get('message') or 'unknown error'}",
                    status_code=400,
                )
            raise LLMProviderError(
                f"[{provider_id}] Responses 流错误"
                f"（{code or 'unknown'}）："
                f"{error.get('message') or 'unknown error'}",
                # 中转瞬断（连接重置、上游网关错误）按传输层失败归类，
                # 交给基座退避重试（对齐移植源 stream_error 的可重试分类）。
                transport=True,
            )
        elif event_type in _TOLERATED_EVENTS:
            continue
        elif profile.tolerate_relay_events and event_type in _RELAY_EVENTS:
            continue
        else:
            raise _malformed(f"未知的语义事件 {event_type}。")

    if terminal is None:
        raise LLMProviderError(
            f"[{provider_id}] Responses 流在 response.completed 前结束。",
            # 连接干净关闭导致的截断按传输层失败归类，交基座退避重试；
            # 撕裂的 TCP/帧错误已在 base._post_stream_sse 捕获为 transport。
            transport=True,
        )

    effective_terminal = _reconcile_relay_terminal(
        terminal, relay_done_items, profile=profile, fail=_malformed
    )
    response = parse_responses_body(
        effective_terminal, provider_id=provider_id, fallback_model=fallback_model
    )

    content = "".join(streamed_content)
    if content and content != response.text:
        raise _malformed("流式正文与终态 items 不一致。")
    reasoning = "".join(streamed_reasoning)
    if reasoning and reasoning != _response_reasoning(response):
        raise _malformed("流式 reasoning 与终态 items 不一致。")
    output_items = effective_terminal.get("output") or []
    for output_index, arguments_text in streamed_arguments.items():
        item = (
            output_items[output_index]
            if isinstance(output_index, int) and 0 <= output_index < len(output_items)
            else None
        )
        if not isinstance(item, dict) or item.get("type") != "function_call":
            raise _malformed(
                f"流式 function arguments（output index {output_index}）"
                "在终态没有对应的 function_call item。"
            )
        if item.get("arguments") != arguments_text:
            raise _malformed(
                f"流式 function arguments（output index {output_index}）"
                "与终态 item 不一致。"
            )
    return response


def _response_reasoning(response: LLMResponse) -> str:
    for block in response.thinking_blocks:
        if block.get("type") == "reasoning":
            return str(block.get("reasoning_content", ""))
    return ""


def _reconcile_relay_terminal(
    terminal: dict[str, Any],
    done_items: list[dict[str, Any]],
    *,
    profile: ResponsesProfile,
    fail: Callable[[str], LLMProviderError],
) -> dict[str, Any]:
    """codex-http-relay 终态核对：output 缺省/子集时以流式完整 items 为准。"""
    if not profile.reconcile_relay_items or not done_items:
        return terminal
    output = terminal.get("output")
    if not isinstance(output, list) or not output:
        return {**terminal, "output": done_items}
    if len(output) == len(done_items) and all(
        _is_relay_subset(partial, full) for partial, full in zip(output, done_items)
    ):
        return {**terminal, "output": done_items}
    raise fail("中转终态 output 与流式 output_item.done items 不一致。")


def _is_relay_subset(partial: Any, full: Any) -> bool:
    """partial 是否为 full 的递归子集（同语义载荷、更少可选字段）。"""
    if partial == full:
        return True
    if isinstance(partial, dict) and isinstance(full, dict):
        return all(
            key in full and _is_relay_subset(value, full[key])
            for key, value in partial.items()
        )
    if isinstance(partial, list) and isinstance(full, list):
        return len(partial) == len(full) and all(
            _is_relay_subset(p, f) for p, f in zip(partial, full)
        )
    return partial == full
