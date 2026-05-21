"""ProviderConfig proxy field: opener creation and _urlopen dispatch."""
from __future__ import annotations

from urllib import request

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


def test_no_proxy_opener_is_none():
    client = BaseProviderClient(_make_config(proxy=""))
    assert client._opener is None


def test_proxy_creates_opener():
    client = BaseProviderClient(_make_config(proxy="http://127.0.0.1:7890"))
    assert client._opener is not None
    assert isinstance(client._opener, request.OpenerDirector)


def test_proxy_opener_has_proxy_handler():
    client = BaseProviderClient(_make_config(proxy="http://proxy.local:8080"))
    handlers = [h for h in client._opener.handlers if isinstance(h, request.ProxyHandler)]
    assert len(handlers) == 1
    assert handlers[0].proxies == {"http": "http://proxy.local:8080", "https": "http://proxy.local:8080"}


def test_urlopen_without_proxy_uses_stdlib(monkeypatch):
    client = BaseProviderClient(_make_config(proxy=""))
    calls = []
    monkeypatch.setattr(request, "urlopen", lambda req, timeout=None: calls.append(("urlopen", timeout)))
    req = request.Request("http://example.com")
    client._urlopen(req, timeout=10)
    assert calls == [("urlopen", 10)]


def test_urlopen_with_proxy_uses_opener(monkeypatch):
    client = BaseProviderClient(_make_config(proxy="http://127.0.0.1:7890"))
    calls = []
    client._opener.open = lambda req, timeout=None: calls.append(("opener", timeout))  # type: ignore[assignment]
    req = request.Request("http://example.com")
    client._urlopen(req, timeout=15)
    assert calls == [("opener", 15)]
