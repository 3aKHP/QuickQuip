"""钉住 provider 层自动重试的语义。

重试循环内建于 ``BaseProviderClient.complete()``：上游 429/5xx/传输层错误按
``RetryPolicy`` 指数退避（带随机抖动）重试，所有 LLM 调用路径统一继承；
探活/诊断经 ``RetryPolicy.disabled()`` 显式豁免。可重试判定基于结构化属性
（``status_code`` / ``transport``），异常消息文本仅用于展示。
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import ClaudeProviderClient, LLMProviderError, LLMRequest
from plugins.llm_tools import LLMConversationMessage

from quickquip.llm.config import load_llm_config
from quickquip.llm.provider import RetryPolicy, build_provider_client
from quickquip.llm.provider.base import LLMResponse, _is_retryable
from quickquip.llm.provider.retry import backoff_delay
from quickquip.llm.usage import drain_usage_tasks
from tests.fixtures.provider_fakes import FakeClaudeClient


def _config(**overrides) -> ProviderConfig:
    return ProviderConfig(
        id="fake", protocol="claude", base_url="https://x/v1",
        api_key_env="K", default_model="m", models=["m"],
        **overrides,
    )


def _req() -> LLMRequest:
    return LLMRequest(
        model="m", system_prompt="s",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2, max_output_tokens=64,
    )


class FlakyFakeClient(FakeClaudeClient):
    """按脚本依次抛错；脚本耗尽后走 FakeClaudeClient 的成功 _post_json。"""

    def __init__(self, config: ProviderConfig, failures: list[Exception]):
        super().__init__(config, {"content": [], "usage": {"input_tokens": 1, "output_tokens": 1}})
        self.failures = list(failures)
        self.calls = 0

    async def _post_json(self, url, headers, payload):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.response_data


class StreamScriptedClient(ClaudeProviderClient):
    """stream_enabled=True；_complete_stream 按脚本抛错，验证 complete() 分支语义。"""

    def __init__(self, config: ProviderConfig, stream_failures: list[Exception]):
        super().__init__(config)
        self.stream_failures = list(stream_failures)
        self.stream_calls = 0
        self.post_json_calls = 0
        self._response_data = {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    def _get_api_key(self) -> str:
        return "test-key"

    async def _prepare_image_inputs(self, image_urls, inline_images=None):
        return []

    async def _complete_stream(self, request):
        self.stream_calls += 1
        if self.stream_failures:
            raise self.stream_failures.pop(0)
        return LLMResponse(text="ok", model=request.model)

    async def _post_json(self, url, headers, payload):
        self.post_json_calls += 1
        return self._response_data


@pytest.fixture
def captured_delays(monkeypatch) -> list[float]:
    """把 asyncio.sleep 换成记录器：断言退避序列且测试不真实等待。"""
    delays: list[float] = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return delays


# ---------- backoff_delay 纯函数 ----------


def test_backoff_delay_exponential_without_jitter():
    policy = RetryPolicy(max_attempts=4, base_delay=2.0, jitter=0.0)
    assert backoff_delay(0, policy, uniform=lambda lo, hi: lo) == 2.0
    assert backoff_delay(1, policy, uniform=lambda lo, hi: lo) == 4.0
    assert backoff_delay(2, policy, uniform=lambda lo, hi: lo) == 8.0


def test_backoff_delay_jitter_bounds():
    policy = RetryPolicy(max_attempts=4, base_delay=2.0, jitter=0.5)
    assert backoff_delay(1, policy, uniform=lambda lo, hi: lo) == 4.0
    assert backoff_delay(1, policy, uniform=lambda lo, hi: hi) == 6.0


# ---------- _is_retryable 结构化分类 ----------


def test_is_retryable_classification():
    assert _is_retryable(LLMProviderError("HTTP 429 too many requests", status_code=429))
    assert _is_retryable(LLMProviderError("HTTP 500 oops", status_code=500))
    assert _is_retryable(LLMProviderError("HTTP 503 upstream", status_code=503))
    assert _is_retryable(LLMProviderError("网络错误：connection reset", transport=True))
    assert not _is_retryable(LLMProviderError("HTTP 400 bad request", status_code=400))
    assert not _is_retryable(LLMProviderError("HTTP 401 unauthorized", status_code=401))
    # 消息前缀不再参与判定：无结构化属性的普通错误一律不可重试
    assert not _is_retryable(LLMProviderError("HTTP 429 too many requests"))
    assert not _is_retryable(LLMProviderError("环境变量 K 未设置"))


# ---------- complete() 内建重试 ----------


async def test_retry_on_429_then_success(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [LLMProviderError("HTTP 429 rate limited", status_code=429)])
    response = await client.complete(_req())
    assert response.text is not None
    assert client.calls == 2
    assert captured_delays == [0.25]


async def test_retry_on_5xx_and_transport_with_exponential_delays(captured_delays):
    config = _config(retry_max_attempts=4, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [
        LLMProviderError("HTTP 500 oops", status_code=500),
        LLMProviderError("网络错误：timeout", transport=True),
    ])
    await client.complete(_req())
    assert client.calls == 3
    assert captured_delays == [0.25, 0.5]


async def test_no_retry_on_other_4xx(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [LLMProviderError("HTTP 401 unauthorized", status_code=401)])
    with pytest.raises(LLMProviderError):
        await client.complete(_req())
    assert client.calls == 1
    assert captured_delays == []


async def test_exhaustion_raises_last_error(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    exc = LLMProviderError("HTTP 429 rate limited", status_code=429)
    client = FlakyFakeClient(config, [exc, exc, exc])
    with pytest.raises(LLMProviderError):
        await client.complete(_req())
    assert client.calls == 3
    assert captured_delays == [0.25, 0.5]


async def test_disabled_policy_single_attempt(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [LLMProviderError("HTTP 429 rate limited", status_code=429)])
    client.retry_policy = RetryPolicy.disabled()
    with pytest.raises(LLMProviderError):
        await client.complete(_req())
    assert client.calls == 1
    assert captured_delays == []


# ---------- 流式分支与重试/回退的交互 ----------


async def test_stream_retryable_error_retries_without_non_stream_fallback(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = StreamScriptedClient(config, [
        LLMProviderError("HTTP 429 rate limited", status_code=429),
        LLMProviderError("HTTP 429 rate limited", status_code=429),
    ])
    response = await client.complete(_req())
    assert response.text == "ok"
    assert client.stream_calls == 3
    assert client.post_json_calls == 0


async def test_stream_generic_failure_falls_back_to_non_stream(captured_delays):
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = StreamScriptedClient(config, [ValueError("boom")])
    response = await client.complete(_req())
    assert response.text == "ok"
    assert client.stream_calls == 1
    assert client.post_json_calls == 1


# ---------- usage 计量：重试不产生额外记录 ----------


async def test_absorbed_failures_record_single_ok_usage(monkeypatch, captured_delays):
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response is not None))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    config = _config(retry_max_attempts=3, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [LLMProviderError("HTTP 429 rate limited", status_code=429)])
    await client.complete(_req())
    await drain_usage_tasks()
    assert calls == [("ok", True)]


async def test_exhausted_retries_record_single_error_usage(monkeypatch, captured_delays):
    calls = []

    async def spy(client, request, response, started, stream_used, state, error_msg=""):
        calls.append((state, response is not None))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    config = _config(retry_max_attempts=2, retry_base_delay=0.25, retry_jitter=0.0)
    client = FlakyFakeClient(config, [
        LLMProviderError("HTTP 429 rate limited", status_code=429),
        LLMProviderError("HTTP 429 rate limited", status_code=429),
    ])
    with pytest.raises(LLMProviderError):
        await client.complete(_req())
    await drain_usage_tasks()
    assert calls == [("error", False)]


# ---------- 工厂与配置盖章 ----------


def test_factory_default_policy_from_config():
    config = _config(retry_max_attempts=5, retry_base_delay=2.5, retry_jitter=0.8)
    client = build_provider_client(config)
    assert client.retry_policy.max_attempts == 5
    assert client.retry_policy.base_delay == 2.5
    assert client.retry_policy.jitter == 0.8


def test_factory_explicit_policy_override():
    client = build_provider_client(_config(), retry_policy=RetryPolicy.disabled())
    assert client.retry_policy.max_attempts == 1
    assert client.retry_policy.base_delay == 0.0


_TOML_TEMPLATE = """
[runtime]
enabled = true
default_provider = "p1"
default_persona = "default"
{retry_lines}

[triggers]
default_prefix = "/ai"

[[personas]]
id = "default"
display_name = "默认"
system_prompt = "hi"

[[providers]]
id = "p1"
protocol = "openai"
base_url = "https://p1.example.test/v1"
api_key_env = "P1_KEY"
default_model = "m1"
models = ["m1"]
"""


def _load_toml(tmp_path: Path, retry_lines: str):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        textwrap.dedent(_TOML_TEMPLATE).format(retry_lines=retry_lines).strip(),
        encoding="utf-8",
    )
    return load_llm_config(config_path)


def test_runtime_retry_config_stamped_to_providers(tmp_path: Path):
    cfg = _load_toml(
        tmp_path,
        '\nretry_max_attempts = 5\nretry_base_delay = 2.5\nretry_jitter = 0.8',
    )
    provider = cfg.providers["p1"]
    assert provider.retry_max_attempts == 5
    assert provider.retry_base_delay == 2.5
    assert provider.retry_jitter == 0.8
    assert cfg.runtime.retry_jitter == 0.8


def test_runtime_retry_defaults_without_keys(tmp_path: Path):
    cfg = _load_toml(tmp_path, "")
    provider = cfg.providers["p1"]
    assert provider.retry_max_attempts == 3
    assert provider.retry_base_delay == 1.0
    assert provider.retry_jitter == 0.5


def test_retry_jitter_clamped_to_unit_range(tmp_path: Path):
    cfg = _load_toml(tmp_path, "\nretry_jitter = 3.0")
    assert cfg.runtime.retry_jitter == 1.0
    assert cfg.providers["p1"].retry_jitter == 1.0
