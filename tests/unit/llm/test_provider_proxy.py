"""ProviderConfig proxy field: httpx client kwargs construction."""
from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import BaseProviderClient


def _make_config(**overrides) -> ProviderConfig:
    defaults = dict(
        id="test",
        protocol="openai",
        base_url="http://test",
        api_key_env="TEST_KEY",
        default_model="m",
        models=["m"],
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def test_client_kwargs_no_proxy():
    client = BaseProviderClient(_make_config(proxy="", timeout_seconds=30.0))
    kwargs = client._client_kwargs()
    assert "proxy" not in kwargs
    assert kwargs["timeout"] == 30.0


def test_client_kwargs_with_proxy():
    client = BaseProviderClient(_make_config(proxy="http://proxy.local:8080"))
    kwargs = client._client_kwargs()
    assert kwargs["proxy"] == "http://proxy.local:8080"


def test_client_kwargs_stream_read_disables_read_timeout():
    import httpx

    client = BaseProviderClient(_make_config(timeout_seconds=45.0))
    kwargs = client._client_kwargs(stream_read=True)
    timeout = kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    # read=None lets SSE long-lived streams survive between chunks
    assert timeout.read is None
