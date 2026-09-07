"""实际请求预算检查（§8.3）：应用侧输入预算 + 模型上下文窗口。

每次 provider HTTP 尝试开始前对最终 payload 估算：system、tools、历史
正文/工具/原生块、当前 Loop、信封、现场和媒体均计入；媒体按已知协议
成本估算。预算不足的处置（容量 reset / 终止）由调用方按契约执行，本
模块只做检查与分类。

预算解析优先级：provider 显式 ``request_input_token_budget`` > 模型窗口
推导（窗口 − 输出预留）> ``runtime.request_input_token_budget`` 缺省。
重放投影预算由 ``derive_replay_budget`` 从同一仲裁者推导。

``capacity unknown``：未解析到模型容量（显式配置与内置策展表均未命中）
时只保证应用估算预算，不得宣称不会触发上游 context-limit。
"""
from __future__ import annotations

from dataclasses import dataclass

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.context_windows import resolve_context_window
from quickquip.llm.provider import LLMRequest
from quickquip.llm.token_estimate import (
    NATIVE_MEDIA_FLAT_TOKENS,
    estimate_native_blocks_tokens,
    estimate_tokens,
)

# 预留估算余量下界（§8.3：至少 1,024 token）。
_RESERVE_TOKENS = 1024
# 估算误差随 payload 放大：按估算值比例追加余量。
_ESTIMATE_MARGIN_RATIO = 0.10
# wire 消息/part 数的应用兜底（不替代供应商真实限制）。
MAX_WIRE_ITEMS = 1024
# 窗口推导输入预算的下界（防极小窗口 + 大输出预留产生无意义预算）。
_MIN_INPUT_BUDGET_TOKENS = 4096
# 重放推导中 system/工具 schema 的固定开销预留（token 估算）。
_SYSTEM_TOOLS_ALLOWANCE_TOKENS = 16_000
# 重放推导中当前进行中 Loop（thinking/正文/工具结果）的比例预留。
_LOOP_HEADROOM_FRACTION = 0.15
# 重放预算绝对下界（与配置钳制下界一致）。
_MIN_REPLAY_BUDGET_TOKENS = 512


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


def resolve_input_budget(
    config: LLMConfig,
    provider: ProviderConfig,
    model: str,
    *,
    max_output_tokens: int | None = None,
) -> int:
    """请求输入预算（仲裁者）解析：显式覆盖 > 窗口推导 > runtime 缺省。"""
    if provider.request_input_token_budget is not None:
        return provider.request_input_token_budget
    window = resolve_context_window(provider.model_context_windows, model)
    if window is not None:
        output_reserve = (max_output_tokens or provider.max_output_tokens) + _RESERVE_TOKENS
        return max(_MIN_INPUT_BUDGET_TOKENS, window - output_reserve)
    return config.runtime.request_input_token_budget


def derive_replay_budget(
    config: LLMConfig,
    provider: ProviderConfig,
    model: str,
    *,
    max_output_tokens: int | None = None,
) -> int:
    """重放投影预算推导：provider 覆盖 > 仲裁者减固定开销（runtime 值为下限）。

    仲裁者减去纪元可见窗上限、system/工具预留与当前 Loop 比例预留；
    ``runtime.agent_replay_loop_tokens`` 作为推导下限保留（调高即放宽，
    capacity unknown 时即实际值）。
    """
    if provider.agent_replay_loop_tokens is not None:
        return provider.agent_replay_loop_tokens
    arbiter = resolve_input_budget(
        config, provider, model, max_output_tokens=max_output_tokens
    )
    epoch_cap = config.resolve_epoch_params(provider).cap_tokens
    derived = (
        arbiter
        - epoch_cap
        - _SYSTEM_TOOLS_ALLOWANCE_TOKENS
        - int(arbiter * _LOOP_HEADROOM_FRACTION)
    )
    return max(
        _MIN_REPLAY_BUDGET_TOKENS,
        config.runtime.agent_replay_loop_tokens,
        derived,
    )


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
        total += estimate_native_blocks_tokens(message.thinking_blocks)
        total += estimate_native_blocks_tokens(message.native_content)
        # 媒体按已知协议成本粗估：每图固定档位（保守）。
        total += NATIVE_MEDIA_FLAT_TOKENS * len(message.image_urls)
    return total


def count_wire_items(request: LLMRequest) -> int:
    """wire 消息/part 数应用兜底（§8.3：统计最终 serializer 产物口径）。"""
    count = 0
    for message in request.messages:
        count += 1
        count += len(message.tool_calls)
        count += len(message.image_urls)
        count += len(message.thinking_blocks or [])
        count += len(message.native_content or [])
    count += len(request.tools)
    return count


def check_request_budget(
    config: LLMConfig,
    provider: ProviderConfig,
    request: LLMRequest,
    *,
    max_output_tokens: int | None = None,
) -> RequestBudgetCheck:
    budget_limit = resolve_input_budget(
        config, provider, request.model, max_output_tokens=max_output_tokens
    )
    wire_model = request.model
    context_window = resolve_context_window(provider.model_context_windows, wire_model)
    output_reserve = (max_output_tokens or provider.max_output_tokens) + _RESERVE_TOKENS
    estimated = estimate_request_tokens(request)
    if context_window is None:
        effective_window = None
    else:
        margin = max(_RESERVE_TOKENS, int(estimated * _ESTIMATE_MARGIN_RATIO))
        effective_window = max(0, context_window - output_reserve - margin)
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
