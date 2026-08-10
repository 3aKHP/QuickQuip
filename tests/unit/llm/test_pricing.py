from quickquip.llm.config import PricingRates
from quickquip.llm.pricing import (
    CanonicalUsage,
    estimate_cost,
    match_pricing,
    normalize_usage,
    estimate_cost_components,
)


def test_normalize_claude_exclusive_restores_inclusive():
    # Claude: input_tokens 不含 cache；还原为 inclusive（prompt = input + read + write）
    u = normalize_usage(
        "claude", input_tokens=100, output_tokens=50,
        cache_creation_tokens=80, cache_read_tokens=200,
    )
    assert u.prompt == 380  # 100 + 200 + 80
    assert u.completion == 50
    assert u.cache_read == 200
    assert u.cache_write == 80


def test_normalize_openai_inclusive():
    u = normalize_usage(
        "openai", input_tokens=300, output_tokens=40,
        cache_creation_tokens=None, cache_read_tokens=250,
    )
    assert u.prompt == 300  # inclusive 直接取
    assert u.cache_read == 250
    assert u.cache_write is None


def test_normalize_gemini_inclusive():
    u = normalize_usage(
        "gemini", input_tokens=300, output_tokens=40,
        cache_creation_tokens=None, cache_read_tokens=250,
    )
    assert u.prompt == 300
    assert u.cache_write is None


def test_estimate_cost_openai_cache_subtraction():
    """回归 litellm#19681：inclusive 下 actual_input = prompt - cached，避免缓存全价计。"""
    rates = PricingRates(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_read_per_mtok=0.3, cache_write_per_mtok=None,
    )
    u = CanonicalUsage(prompt=300, completion=40, cache_read=250, cache_write=None)
    cost, priced = estimate_cost(u, rates)
    expected = 50 * 3 / 1e6 + 250 * 0.3 / 1e6 + 40 * 15 / 1e6
    assert priced is True
    assert abs(cost - expected) < 1e-12


def test_estimate_cost_claude_exclusive():
    rates = PricingRates(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_read_per_mtok=0.3, cache_write_per_mtok=3.75,
    )
    u = CanonicalUsage(prompt=380, completion=50, cache_read=200, cache_write=80)
    cost, _ = estimate_cost(u, rates)
    # actual_input = 380 - 200 - 80 = 100（减 cache_write 避免双算）
    expected = 100 * 3 / 1e6 + 200 * 0.3 / 1e6 + 80 * 3.75 / 1e6 + 50 * 15 / 1e6
    assert abs(cost - expected) < 1e-12


def test_estimate_cost_no_rates_unpriced():
    u = CanonicalUsage(prompt=100, completion=10, cache_read=0, cache_write=None)
    cost, priced = estimate_cost(u, None)
    assert cost == 0.0
    assert priced is False


def test_estimate_cost_none_tokens_not_counted():
    rates = PricingRates(input_per_mtok=3.0, output_per_mtok=15.0)
    u = CanonicalUsage(prompt=None, completion=None, cache_read=None, cache_write=None)
    cost, priced = estimate_cost(u, rates)
    assert cost == 0.0
    assert priced is True


def test_match_pricing_provider_overrides_model_fallback():
    configured = {
        "gpt-test": PricingRates(input_per_mtok=1.0),
        "p1/gpt-test": PricingRates(input_per_mtok=2.0),
    }
    assert match_pricing("p1", "gpt-test", configured).input_per_mtok == 2.0
    assert match_pricing("p2", "gpt-test", configured).input_per_mtok == 1.0
    assert match_pricing("p1", "unknown", configured) is None


def test_cache_rate_falls_back_to_input():
    rates = PricingRates(input_per_mtok=3.0, output_per_mtok=15.0)  # cache_* 为 None
    u = CanonicalUsage(prompt=100, completion=10, cache_read=50, cache_write=20)
    cost, _ = estimate_cost(u, rates)
    # actual_input=100-50-20=30；cache_read 50 + cache_write 20 均回退 input 3.0
    expected = 30 * 3 / 1e6 + 50 * 3 / 1e6 + 20 * 3 / 1e6 + 10 * 15 / 1e6
    assert abs(cost - expected) < 1e-12


def test_cost_components_expose_canonical_buckets():
    rates = PricingRates(input_per_mtok=2.0, output_per_mtok=8.0, cache_read_per_mtok=0.2)
    usage = normalize_usage("claude", 100, 50, 80, 200)
    components, priced = estimate_cost_components(usage, rates)
    assert priced is True
    assert usage.fresh_input == 100
    assert usage.total_tokens == 430
    assert usage.input_token_semantics == "inclusive"
    assert components["input_cost_usd"] == 100 * 2 / 1e6
    assert components["cache_read_cost_usd"] == 200 * 0.2 / 1e6
