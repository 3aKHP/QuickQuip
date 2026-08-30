from __future__ import annotations

import asyncio
import time

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.provider_health import (
    ProviderHealth,
    format_probe_results,
    probe_all_providers,
    probe_provider,
)


def _make_provider(
    *,
    id: str = "p1",
    api_key_env: str = "TEST_PROBE_KEY",
    default_model: str = "gpt-test",
) -> ProviderConfig:
    return ProviderConfig(
        id=id,
        protocol="openai",
        base_url="https://example.test",
        api_key_env=api_key_env,
        default_model=default_model,
        models=[default_model],
    )


class _FakeClient:
    """假 provider client：根据 side_effect 决定 complete 的行为。

    probe_provider 只关心 complete 是否抛异常，返回值不读取。
    """

    def __init__(self, *, complete_side_effect: BaseException | None = None) -> None:
        self._side_effect = complete_side_effect

    async def complete(self, request):
        if self._side_effect is not None:
            raise self._side_effect
        return object()  # probe 不读返回值


def _patch_client(monkeypatch, factory):
    monkeypatch.setattr("quickquip.llm.provider.build_provider_client", factory)


async def test_probe_provider_ok(monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")
    _patch_client(monkeypatch, lambda provider: _FakeClient())

    result = await probe_provider(_make_provider())

    assert result.status == "ok"
    assert result.provider_id == "p1"
    assert result.model == "gpt-test"
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.error == ""


async def test_probe_provider_timeout(monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")
    _patch_client(
        monkeypatch,
        lambda provider: _FakeClient(complete_side_effect=asyncio.TimeoutError()),
    )

    result = await probe_provider(_make_provider())

    assert result.status == "error"
    assert result.error == "timeout"
    assert result.latency_ms is not None


async def test_probe_provider_error_captures_type_name(monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")

    class _ConnError(Exception):
        pass

    _patch_client(
        monkeypatch,
        lambda provider: _FakeClient(complete_side_effect=_ConnError("boom")),
    )

    result = await probe_provider(_make_provider())

    assert result.status == "error"
    assert result.error == "_ConnError"


async def test_probe_provider_skipped_when_api_key_unset(monkeypatch):
    """api_key_env 已配置但环境变量未设：应跳过且不构造 client（不计费）。"""
    monkeypatch.delenv("TEST_PROBE_KEY", raising=False)

    built = {"count": 0}

    def _factory(provider):
        built["count"] += 1
        return _FakeClient()

    _patch_client(monkeypatch, _factory)

    result = await probe_provider(_make_provider())

    assert result.status == "skipped"
    assert result.error == "api_key_missing"
    assert built["count"] == 0  # 没发请求 = 没扣费


async def test_probe_provider_skipped_when_no_env_name(monkeypatch):
    result = await probe_provider(_make_provider(api_key_env=""))

    assert result.status == "skipped"
    assert result.error == "api_key_missing"


async def test_probe_provider_explicit_model_used(monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")
    captured = {}

    class _CaptureClient:
        async def complete(self, request):
            captured["model"] = request.model
            return object()

    _patch_client(monkeypatch, lambda provider: _CaptureClient())

    result = await probe_provider(_make_provider(), model="custom-model")

    assert result.model == "custom-model"
    assert captured["model"] == "custom-model"


async def test_probe_all_providers_runs_concurrently(monkeypatch):
    """3 个各 sleep 0.2s 的 provider 并发探活，总耗时应 ≈ 0.2s 而非 0.6s。"""
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")

    class _SlowClient:
        async def complete(self, request):
            await asyncio.sleep(0.2)
            return object()

    _patch_client(monkeypatch, lambda provider: _SlowClient())

    config = LLMConfig()
    config.providers = {f"p{i}": _make_provider(id=f"p{i}") for i in range(3)}

    t0 = time.monotonic()
    results = await probe_all_providers(config)
    elapsed = time.monotonic() - t0

    assert len(results) == 3
    assert all(r.status == "ok" for r in results)
    # 串行会是 0.6s；并发 ~0.2s。0.5s 阈值留余量，超过即说明并发失效。
    assert elapsed < 0.5, f"并发失效，耗时 {elapsed:.2f}s"


async def test_probe_all_providers_empty_config():
    assert await probe_all_providers(LLMConfig()) == []


async def test_probe_all_providers_skips_disabled(monkeypatch):
    """enabled = false 的 provider 不参与探活（不出结果、不建 client）。"""
    monkeypatch.setenv("TEST_PROBE_KEY", "fake-key")

    built_for: list[str] = []

    def factory(provider):
        built_for.append(provider.id)
        return _FakeClient()

    _patch_client(monkeypatch, factory)

    config = LLMConfig()
    config.providers = {
        "p-on": _make_provider(id="p-on"),
        "p-off": _make_provider(id="p-off", api_key_env="OFF_KEY"),
    }
    config.providers["p-off"].enabled = False

    results = await probe_all_providers(config)

    assert [r.provider_id for r in results] == ["p-on"]
    assert built_for == ["p-on"]


def test_format_probe_results_mixed_statuses():
    results = [
        ProviderHealth("p1", "m1", "ok", latency_ms=120.5),
        ProviderHealth("p2", "m2", "skipped", error="api_key_missing"),
        ProviderHealth("p3", "m3", "error", latency_ms=5000.0, error="timeout"),
        ProviderHealth("p4", "m4", "error", latency_ms=88.0, error="ConnectionError"),
    ]
    text = format_probe_results(results)

    assert "Provider 探活（4 个，并发）" in text
    assert "p1" in text and "正常" in text
    assert "p2" in text and "api_key 未设置" in text
    assert "p3" in text and "超时" in text
    assert "p4" in text and "ConnectionError" in text
    assert "合计：1/4 正常" in text


def test_format_probe_results_empty():
    assert format_probe_results([]) == "没有已配置的 provider。"


def test_provider_health_as_dict():
    h = ProviderHealth("p1", "m1", "ok", latency_ms=50.0)
    assert h.as_dict() == {
        "provider_id": "p1",
        "model": "m1",
        "status": "ok",
        "latency_ms": 50.0,
        "error": "",
    }
