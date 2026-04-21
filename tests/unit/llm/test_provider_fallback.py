"""When stream_enabled=True but _post_stream_sse fails non-terminally,
the client must transparently fall back to _post_json.
"""
from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest, OpenAIProviderClient
from plugins.llm_tools import LLMConversationMessage


class FakeStreamFallbackClient(OpenAIProviderClient):
    def __init__(self, config: ProviderConfig, response_data: dict):
        super().__init__(config)
        self.response_data = response_data
        self.stream_attempted = False

    async def _prepare_image_inputs(self, image_urls):
        return []

    def _get_api_key(self) -> str:
        return "test-key"

    async def _post_stream_sse(self, url, headers, payload):
        self.stream_attempted = True
        raise ValueError("simulated stream parse failure")

    async def _post_json(self, url, headers, payload):
        return self.response_data


async def test_stream_failure_falls_back_to_json():
    config = ProviderConfig(
        id="test",
        protocol="openai",
        base_url="http://test",
        api_key_env="TEST_KEY",
        default_model="gpt-test",
        models=["gpt-test"],
        stream_enabled=True,
    )
    client = FakeStreamFallbackClient(
        config,
        {
            "choices": [{"message": {"content": "fallback reply"}, "finish_reason": "stop"}],
            "model": "gpt-test",
        },
    )
    request = LLMRequest(
        model="gpt-test",
        system_prompt="",
        messages=[LLMConversationMessage(role="user", content="查一下", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
        tools=[],
        allow_tool_calls=False,
    )
    response = await client.complete(request)

    assert client.stream_attempted is True
    assert response.text == "fallback reply"
