from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest
from plugins.llm_tools import LLMConversationMessage, LLMToolSpec

from tests.fixtures.provider_fakes import FakeOpenAIClient


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id="fake",
        protocol="openai",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-test",
        models=["gpt-test"],
    )


def _tool_call_request() -> LLMRequest:
    return LLMRequest(
        model="gpt-test",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="查一下", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
        tools=[
            LLMToolSpec(
                name="get_identity",
                description="身份查询",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ],
        allow_tool_calls=True,
    )


async def test_openai_tool_call_payload_and_response():
    response_data = {
        "model": "gpt-test",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tool_openai_1",
                            "type": "function",
                            "function": {
                                "name": "get_identity",
                                "arguments": '{"query":"哈基镜"}',
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    client = FakeOpenAIClient(_provider_config(), response_data)
    response = await client.complete(_tool_call_request())

    assert client.last_payload["tools"][0]["function"]["name"] == "get_identity"
    assert response.tool_calls[0].name == "get_identity"
    assert response.tool_calls[0].arguments_json == '{"query":"哈基镜"}'


async def test_openai_cache_thinking_tokens_parsed():
    """cached_tokens/reasoning_tokens 从 usage.details 解析（inclusive：cached ⊆ prompt）。"""
    request = LLMRequest(
        model="gpt-test", system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2, max_output_tokens=128,
    )
    data = {"model": "gpt-test",
            "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40,
                      "prompt_tokens_details": {"cached_tokens": 250},
                      "completion_tokens_details": {"reasoning_tokens": 15}}}
    resp = await FakeOpenAIClient(_provider_config(), data).complete(request)
    assert resp.cache_read_tokens == 250
    assert resp.thinking_tokens == 15
    assert resp.cache_creation_tokens is None
