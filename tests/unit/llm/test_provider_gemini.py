from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import LLMRequest
from plugins.llm_tools import LLMConversationMessage, LLMToolSpec

from tests.fixtures.provider_fakes import FakeGeminiClient


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id="fake-gemini",
        protocol="gemini",
        base_url="https://example.test/v1beta",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-test",
        models=["gemini-test"],
    )


def _tool_call_request() -> LLMRequest:
    return LLMRequest(
        model="gemini-test",
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


async def test_gemini_function_call_payload_and_response():
    response_data = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_identity",
                                "args": {"query": "哈基镜"},
                            }
                        }
                    ]
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    client = FakeGeminiClient(_provider_config(), response_data)
    response = await client.complete(_tool_call_request())

    # Gemini nests tools under functionDeclarations
    assert client.last_payload["tools"][0]["functionDeclarations"][0]["name"] == "get_identity"
    assert response.tool_calls[0].name == "get_identity"
    assert response.tool_calls[0].arguments_json == '{"query": "哈基镜"}'
