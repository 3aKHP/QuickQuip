"""实际请求预算检查（§8.3）：应用侧输入预算 + 模型上下文窗口。

每次 provider HTTP 尝试开始前对最终 payload 估算：system、tools、历史
正文/工具/原生块、当前 Loop、信封、现场和媒体均计入；媒体按已知协议
成本估算。预算不足的处置（容量 reset / 终止）由调用方按契约执行，本
模块只做检查与分类。

``capacity unknown``：未配置模型容量时只保证应用估算预算，不得宣称
不会触发上游 context-limit。
"""
from __future__ import annotations

from dataclasses import dataclass

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.provider import LLMRequest
from quickquip.llm.token_estimate import estimate_tokens

# 预留估算余量（§8.3：至少 1,024 token）。
_RESERVE_TOKENS = 1024
# wire 消息/part 数的应用兜底（不替代供应商真实限制）。
MAX_WIRE_ITEMS = 1024


class RequestBudgetExceeded(RuntimeError):
    """最终 payload 超出可执行预算（§8.3 request_budget_exceeded）。"""

    def __init__(self, message: str, *, capacity_unknown: bool = False):
        super().__init__(message)
        self.capacity_unknown = capacity_unknown


@dataclass(frozen=True, slots=True)
class RequestBudgetCheck:
    estimated_input_tokens: int
    budget_limit: int
    context_window: int | None
    wire_items: int
    capacity_unknown: bool

    @property
    def ok(self) -> bool:
        within_budget = self.estimated_input_tokens <= self.budget_limit
        within_window = (
            self.context_window is None
            or self.estimated_input_tokens + _RESERVE_TOKENS <= self.context_window
        )
        return within_budget and within_window and self.wire_items <= MAX_WIRE_ITEMS


def estimate_request_tokens(request: LLMRequest) -> int:
    """最终实际 payload 的输入估算：system/tools/messages 全量计入。"""
    total = estimate_tokens(request.system_prompt)
    for spec in request.tools:
        total += estimate_tokens(spec.name) + estimate_tokens(spec.description)
        total += estimate_tokens(str(spec.input_schema))
    for message in request.messages:
        total += estimate_tokens(message.content)
        for call in message.tool_calls:
            total += estimate_tokens(call.arguments_json)
        for block in message.thinking_blocks or []:
            total += estimate_tokens(str(block))
        # 媒体按已知协议成本粗估：每图固定档位（保守）。
        total += 1200 * len(message.image_urls)
    return total


def count_wire_items(request: LLMRequest) -> int:
    """wire 消息/part 数应用兜底（§8.3：统计最终 serializer 产物口径）。"""
    count = 0
    for message in request.messages:
        count += 1
        count += len(message.tool_calls)
        count += len(message.image_urls)
    count += len(request.tools)
    return count


def check_request_budget(
    config: LLMConfig,
    provider: ProviderConfig,
    request: LLMRequest,
    *,
    max_output_tokens: int | None = None,
) -> RequestBudgetCheck:
    budget_limit = provider.request_input_token_budget or config.runtime.request_input_token_budget
    wire_model = request.model
    context_window = provider.model_context_windows.get(wire_model)
    output_reserve = (max_output_tokens or provider.max_output_tokens) + _RESERVE_TOKENS
    estimated = estimate_request_tokens(request)
    effective_window = None if context_window is None else max(0, context_window - output_reserve)
    return RequestBudgetCheck(
        estimated_input_tokens=estimated,
        budget_limit=budget_limit,
        context_window=effective_window,
        wire_items=count_wire_items(request),
        capacity_unknown=context_window is None,
    )


def enforce_request_budget(
    config: LLMConfig,
    provider: ProviderConfig,
    request: LLMRequest,
    *,
    max_output_tokens: int | None = None,
) -> RequestBudgetCheck:
    check = check_request_budget(
        config, provider, request, max_output_tokens=max_output_tokens
    )
    if check.ok:
        return check
    if check.wire_items > MAX_WIRE_ITEMS:
        raise RequestBudgetExceeded(
            f"wire 消息/工具条目数 {check.wire_items} 超过应用兜底 {MAX_WIRE_ITEMS}",
            capacity_unknown=check.capacity_unknown,
        )
    if check.context_window is not None and check.estimated_input_tokens > check.context_window:
        raise RequestBudgetExceeded(
            f"估算输入 {check.estimated_input_tokens} token 超出模型上下文余量 "
            f"{check.context_window}",
            capacity_unknown=check.capacity_unknown,
        )
    raise RequestBudgetExceeded(
        f"估算输入 {check.estimated_input_tokens} token 超出应用输入预算 {check.budget_limit}",
        capacity_unknown=check.capacity_unknown,
    )
