"""Fake provider clients that inherit from the real ones.

Unlike Stub clients (which replace build_provider_client wholesale), these
subclass the real OpenAI/Claude/Gemini clients and override only the network
seam (_post_json) and image prep, so tests exercise the real request/response
serialization logic.
"""
from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import (
    ClaudeProviderClient,
    GeminiProviderClient,
    OpenAIProviderClient,
)


def _force_non_streaming(config: ProviderConfig) -> ProviderConfig:
    return ProviderConfig(
        **{
            **{f.name: getattr(config, f.name) for f in config.__dataclass_fields__.values()},
            "stream_enabled": False,
        }
    )


class FakeOpenAIClient(OpenAIProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        super().__init__(_force_non_streaming(config))
        self.response_data = response_data
        self.last_payload: dict | None = None
        self.last_headers: dict | None = None
        self.last_url: str | None = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        self.last_headers = headers
        self.last_url = url
        return self.response_data


class FakeClaudeClient(ClaudeProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        super().__init__(_force_non_streaming(config))
        self.response_data = response_data
        self.last_payload: dict | None = None
        self.last_headers: dict | None = None
        self.last_url: str | None = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        self.last_headers = headers
        self.last_url = url
        return self.response_data


class FakeGeminiClient(GeminiProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        super().__init__(_force_non_streaming(config))
        self.response_data = response_data
        self.last_payload: dict | None = None
        self.last_headers: dict | None = None
        self.last_url: str | None = None

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_json(self, url, headers, payload):
        self.last_payload = payload
        self.last_headers = headers
        self.last_url = url
        return self.response_data
