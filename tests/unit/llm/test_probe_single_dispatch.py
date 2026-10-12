"""A probe never replays a possibly billed request through another dispatch path."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from quickquip.llm.config import ProviderConfig
from quickquip.llm.config_runtime import ConfigRuntimeWorker
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.llm.provider_health import probe_provider


@pytest.fixture
def transport(monkeypatch):
    original_client = httpx.AsyncClient
    calls = []
    monkeypatch.setattr("quickquip.llm.provider.base.begin_http_trace", AsyncMock())
    monkeypatch.setattr("quickquip.llm.provider.base.finish_http_trace", AsyncMock())
    monkeypatch.setattr("quickquip.llm.provider.base._schedule_usage_record", lambda *args: None)

    def install(handler):
        def capture(request):
            calls.append((str(request.url), json.loads(request.content)))
            return handler(request)
        mock = httpx.MockTransport(capture)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
            transport=mock, **kwargs
        ))
    return calls, install


def provider():
    return ProviderConfig(
        id="test", protocol="openai", base_url="https://primary.test/v1",
        api_key_env="TEST_PROBE_KEY", default_model="model", models=["model"],
        fallback_urls=["https://secondary.test/v1"], retry_max_attempts=5,
    )


async def test_single_dispatch_blocks_retry_policy_and_endpoint_fallback(transport, monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "synthetic")
    calls, install = transport
    install(lambda request: httpx.Response(503, text="retryable service failure", request=request))
    # Keep the configured retries and fallback URL to exercise the transport policy itself.
    client = build_provider_client(provider(), single_dispatch=True)
    with pytest.raises(LLMProviderError):
        await client.complete(LLMRequest(
            model="model", system_prompt="", messages=[], temperature=0, max_output_tokens=1
        ))
    assert len(calls) == 1
    assert calls[0][0].startswith("https://primary.test/")


async def test_plain_probe_sends_one_nonstream_request(transport, monkeypatch):
    monkeypatch.setenv("TEST_PROBE_KEY", "synthetic")
    calls, install = transport
    install(lambda request: httpx.Response(503, text="retryable service failure", request=request))
    configuration = provider()
    configuration.stream_enabled = True
    result = await probe_provider(configuration)
    assert result.status == "error"
    assert len(calls) == 1
    assert calls[0][1].get("stream", False) is False


async def test_stream_diagnostic_does_not_replay_after_response_parse_failure(
    transport, llm_service, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    calls, install = transport
    install(lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content=b'data: {"choices":[{"delta":3}]}\n\ndata: [DONE]\n\n', request=request,
    ))
    service = llm_service.config_service
    draft = service.read()
    draft["document"]["providers"][0]["fallback_urls"] = ["https://secondary.test/v1"]
    service.replace(draft["document"], draft["revision"])
    operation = service.probe(
        "draft", "openai-main", "gpt-test", "stream-probe",
        payload={"user_prompt": "test", "stream": True},
    )
    await ConfigRuntimeWorker(service, llm_service).tick()
    assert service.tasks.get(operation["id"])["status"] == "failed"
    assert len(calls) == 1
    assert calls[0][1]["stream"] is True
    assert service.read("published")["revision"] != operation["target_revision"]
