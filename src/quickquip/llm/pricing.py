"""Provider-neutral LLM cost estimation.

各家 cache 上报有 inclusive/exclusive 两种约定：Claude exclusive（input_tokens
不含 cache_read/cache_creation），OpenAI/Gemini inclusive（cached ⊆ prompt）。
归一化前置到 ``normalize_usage``（Claude 还原为 inclusive），cost 计算完全中立，
避免在朴素实现里写反互相掩盖。参照同机 agent-gateway 的 usage_from_mapping +
estimate_cost 切分。

价格全由 ``llm.toml`` 的 ``[pricing.models.<name>]`` 提供（不内置易过时的官方
价表）；未覆盖的模型 → ``priced=False``，由仪表盘"未定价"可见性提示补填。
"""
from __future__ import annotations

from dataclasses import dataclass

from quickquip.llm.config import PricingRates


@dataclass(slots=True)
class CanonicalUsage:
    """归一化后的用量：prompt 为 inclusive 口径（含 cached 的总输入）。"""

    prompt: int | None
    completion: int | None
    cache_read: int | None
    cache_write: int | None

    @property
    def fresh_input(self) -> int | None:
        if self.prompt is None:
            return None
        return max(0, self.prompt - (self.cache_read or 0) - (self.cache_write or 0))

    @property
    def total_tokens(self) -> int | None:
        if self.prompt is None and self.completion is None:
            return None
        return (self.prompt or 0) + (self.completion or 0)

    @property
    def input_token_semantics(self) -> str:
        return "inclusive"


def normalize_usage(
    protocol: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_creation_tokens: int | None,
    cache_read_tokens: int | None,
) -> CanonicalUsage:
    """基于 ``LLMResponse`` 已解析字段 + protocol 归一为 inclusive canonical。"""
    if protocol == "claude":
        # exclusive: input_tokens 不含 cache；还原为 inclusive 口径
        parts = [input_tokens, cache_read_tokens, cache_creation_tokens]
        prompt = sum(p or 0 for p in parts) if any(p is not None for p in parts) else None
        return CanonicalUsage(
            prompt=prompt,
            completion=output_tokens,
            cache_read=cache_read_tokens,
            cache_write=cache_creation_tokens,
        )
    # openai/gemini inclusive: input_tokens 已含 cached
    return CanonicalUsage(
        prompt=input_tokens,
        completion=output_tokens,
        cache_read=cache_read_tokens,
        cache_write=None,
    )


def estimate_cost(u: CanonicalUsage, rates: PricingRates | None) -> tuple[float, bool]:
    """中立计算；无 rates → (0.0, False)（未定价）。

    actual_input = prompt - cache_read（inclusive 减法，避免缓存按全价计的 2-4× 高估，
    即 litellm#19681 类 bug）。cache_read/write 无单独价时回退 input 价。
    thinking_tokens v1 不额外计（Claude/OpenAI 已含在 output；Gemini thoughts 量小
    且与 candidatesTokenCount 的包含关系不确定，保守不计避免双算）。
    """
    if rates is None:
        return 0.0, False
    # actual_input = prompt - cache_read - cache_write（三者都已含在 inclusive prompt 中，
    # 都减掉才剩"未缓存的新鲜输入"，否则 Claude 的 cache_write 会在 actual_input 和
    # cache_write 两处重复计费）
    actual_input = u.fresh_input or 0
    cache_read_rate = (
        rates.cache_read_per_mtok
        if rates.cache_read_per_mtok is not None
        else rates.input_per_mtok
    )
    cache_write_rate = (
        rates.cache_write_per_mtok
        if rates.cache_write_per_mtok is not None
        else rates.input_per_mtok
    )
    cost = (
        _mtok(actual_input, rates.input_per_mtok)
        + _mtok(u.cache_read, cache_read_rate)
        + _mtok(u.cache_write, cache_write_rate)
        + _mtok(u.completion, rates.output_per_mtok)
    )
    return cost, True


def estimate_cost_components(
    u: CanonicalUsage,
    rates: PricingRates | None,
) -> tuple[dict[str, float], bool]:
    """Return the four billable components plus total pricing state."""
    if rates is None:
        return {
            "input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_read_cost_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
        }, False
    cache_read_rate = (
        rates.cache_read_per_mtok
        if rates.cache_read_per_mtok is not None
        else rates.input_per_mtok
    )
    cache_write_rate = (
        rates.cache_write_per_mtok
        if rates.cache_write_per_mtok is not None
        else rates.input_per_mtok
    )
    components = {
        "input_cost_usd": _mtok(u.fresh_input, rates.input_per_mtok),
        "output_cost_usd": _mtok(u.completion, rates.output_per_mtok),
        "cache_read_cost_usd": _mtok(u.cache_read, cache_read_rate),
        "cache_creation_cost_usd": _mtok(u.cache_write, cache_write_rate),
    }
    return components, True


def match_pricing(
    provider_id: str, model: str, configured: dict[str, PricingRates]
) -> PricingRates | None:
    """先查 ``provider_id/model``（per-provider 中转实际价），miss 回退纯 ``model``
    （官方价默认），再 miss → None（未定价）。

    key 为 ``f"{provider_id}/{model}"`` 精确拼接——即使 model 名本身含 ``/``（如
    OpenRouter 的 ``google/gemma-4-31b-it``），拼接后 ``openrouter/google/gemma-4-31b-it``
    仍与 configured 同名 key 精确匹配，无歧义；``is not None`` 判断避免依赖 truthiness。"""
    specific = configured.get(f"{provider_id}/{model}")
    return specific if specific is not None else configured.get(model)


def _mtok(tokens: int | None, rate_per_mtok: float) -> float:
    if not tokens:
        return 0.0
    return tokens * rate_per_mtok / 1_000_000
