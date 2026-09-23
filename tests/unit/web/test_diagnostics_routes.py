from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

fastapi = pytest.importorskip("fastapi")
HTTPException = fastapi.HTTPException

from quickquip.app.web.routes import diagnostics  # noqa: E402
from quickquip.llm.provider_health import ProviderHealth  # noqa: E402
from quickquip.llm.provider_health import format_probe_results  # noqa: E402


async def test_probe_providers_returns_results_and_text(monkeypatch):
    """端点应并发探活并返回结构化 results + 后端统一格式化的 text。"""
    monkeypatch.setattr(
        diagnostics, "load_llm_config", lambda path: SimpleNamespace(load_error=None, providers={})
    )

    fake_results = [
        ProviderHealth("p1", "m1", "ok", latency_ms=100.0),
        ProviderHealth("p2", "m2", "error", latency_ms=5000.0, error="timeout"),
    ]

    async def _fake_probe(cfg, **kwargs):
        return fake_results

    monkeypatch.setattr(diagnostics, "probe_all_providers", _fake_probe)

    resp = await diagnostics.probe_providers()

    assert len(resp["results"]) == 2
    assert resp["results"][0]["provider_id"] == "p1"
    assert resp["results"][0]["status"] == "ok"
    assert resp["results"][1]["status"] == "error"
    # 独立期望：合计行由 ok/error 计数直接决定，不用生产格式化函数自证
    assert "合计：1/2 正常" in resp["text"]
    assert resp["text"] == format_probe_results(fake_results)


async def test_probe_providers_raises_on_config_error(monkeypatch):
    """config 加载失败时应抛 400，不触发探活（不白花钱）。"""
    monkeypatch.setattr(
        diagnostics,
        "load_llm_config",
        lambda path: SimpleNamespace(load_error="TOML 语法错误"),
    )

    probe = AsyncMock()
    monkeypatch.setattr(diagnostics, "probe_all_providers", probe)
    with pytest.raises(HTTPException) as exc:
        await diagnostics.probe_providers()

    assert exc.value.status_code == 400
    probe.assert_not_awaited()
