from __future__ import annotations

from dataclasses import replace

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


async def test_gemini_builtin_tool_array_schemas_declare_items(llm_service):
    client = FakeGeminiClient(
        _provider_config(),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )
    request = _tool_call_request()
    request.tools = llm_service.tool_registry.list_specs()

    _url, _headers, payload = await client._build_request_parts(request)

    declarations = payload["tools"][0]["functionDeclarations"]
    tool_list = next(item for item in declarations if item["name"] == "tool_list")
    assert tool_list["parameters"]["properties"]["names"] == {
        "type": "array",
        "items": {"type": "string"},
    }

    missing_items: list[str] = []

    def collect_missing_items(schema, path: str) -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "array" and "items" not in schema:
            missing_items.append(path)
        for name, subschema in schema.get("properties", {}).items():
            collect_missing_items(subschema, f"{path}.properties[{name}]")
        if "items" in schema:
            collect_missing_items(schema["items"], f"{path}.items")
        for index, subschema in enumerate(schema.get("anyOf", [])):
            collect_missing_items(subschema, f"{path}.anyOf[{index}]")

    for index, declaration in enumerate(declarations):
        collect_missing_items(
            declaration["parameters"],
            f"functionDeclarations[{index}].parameters",
        )
    assert missing_items == []


async def test_gemini_bearer_auth_keeps_gateway_token_out_of_url():
    client = FakeGeminiClient(
        replace(_provider_config(), auth_method="bearer"),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )

    await client.complete(_tool_call_request())

    assert client.last_url == (
        "https://example.test/v1beta/models/gemini-test:generateContent"
    )
    assert client.last_headers["authorization"] == "Bearer test-key"
    assert "test-key" not in client.last_url


async def test_gemini_stream_bearer_auth_preserves_sse_query_only():
    client = FakeGeminiClient(
        replace(_provider_config(), auth_method="bearer"),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )

    url, headers, _payload = await client._build_request_parts(
        _tool_call_request(),
        stream=True,
    )

    assert url == (
        "https://example.test/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
    )
    assert headers["authorization"] == "Bearer test-key"
    assert "test-key" not in url


async def test_gemini_replays_ordered_signed_parts_and_parallel_function_responses():
    signed_parts = [
        {"text": "Need both tools.", "thought": True, "thoughtSignature": "thought-sig"},
        {
            "functionCall": {"id": "call_1", "name": "get_identity", "args": {"query": "A"}},
            "thoughtSignature": "call-sig-1",
        },
        {
            "functionCall": {"name": "get_identity", "args": {"query": "B"}},
            "thoughtSignature": "call-sig-2",
        },
    ]
    response_data = {
        "candidates": [{"finishReason": "STOP", "content": {"parts": signed_parts}}]
    }
    client = FakeGeminiClient(_provider_config(), response_data)

    response = await client.complete(_tool_call_request())

    assert [call.id for call in response.tool_calls] == ["call_1", "gemini_tool_3"]
    assert [block["part"]["thoughtSignature"] for block in response.thinking_blocks] == [
        "thought-sig",
        "call-sig-1",
        "call-sig-2",
    ]
    replay_request = _tool_call_request()
    replay_request.messages = [
        LLMConversationMessage(
            role="assistant",
            tool_calls=response.tool_calls,
            thinking_blocks=response.thinking_blocks,
        ),
        LLMConversationMessage(
            role="tool",
            content="A result",
            tool_call_id="call_1",
            tool_name="get_identity",
        ),
        LLMConversationMessage(
            role="tool",
            content="B result",
            tool_call_id="gemini_tool_3",
            tool_name="get_identity",
        ),
    ]

    await client.complete(replay_request)

    model_turn, tool_turn = client.last_payload["contents"]
    assert model_turn["parts"] == [
        signed_parts[0],
        signed_parts[1],
        {
            "functionCall": {
                "id": "gemini_tool_3",
                "name": "get_identity",
                "args": {"query": "B"},
            },
            "thoughtSignature": "call-sig-2",
        },
    ]
    assert [part["functionResponse"]["id"] for part in tool_turn["parts"]] == [
        "call_1",
        "gemini_tool_3",
    ]


async def test_gemini_cache_thinking_tokens_parsed():
    """cachedContentTokenCount/thoughtsTokenCount 从 usageMetadata 解析。"""
    request = LLMRequest(
        model="gemini-test", system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2, max_output_tokens=128,
    )
    data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 40,
                              "cachedContentTokenCount": 250, "thoughtsTokenCount": 15}}
    resp = await FakeGeminiClient(_provider_config(), data).complete(request)
    assert resp.cache_read_tokens == 250
    assert resp.thinking_tokens == 15
    assert resp.cache_creation_tokens is None


async def test_gemini_stream_cache_thinking_tokens_parsed():
    """流式 usageMetadata 解析（stream_enabled 默认 True，生产主路径）。"""
    chunks = [
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 40,
                           "cachedContentTokenCount": 250, "thoughtsTokenCount": 15}},
    ]
    resp = FakeGeminiClient._assemble_stream_response(chunks, "gemini-test")
    assert resp.cache_read_tokens == 250
    assert resp.thinking_tokens == 15


def test_gemini_stream_preserves_signatures_from_thought_and_function_parts():
    chunks = [
        {
            "candidates": [{
                "content": {"parts": [{"text": "thinking", "thought": True}]}
            }]
        },
        {
            "candidates": [{
                "content": {"parts": [{
                    "text": " done",
                    "thought": True,
                    "thoughtSignature": "thought-sig",
                }]}
            }]
        },
        {
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {"name": "get_identity", "args": {"query": "A"}},
                    "thoughtSignature": "call-sig",
                }]},
                "finishReason": "STOP",
            }]
        },
    ]

    response = FakeGeminiClient._assemble_stream_response(chunks, "gemini-test")

    assert response.text == ""
    assert response.tool_calls[0].id == "gemini_tool_2"
    assert [block["part"]["thoughtSignature"] for block in response.thinking_blocks] == [
        "thought-sig",
        "call-sig",
    ]
    assert response.thinking_blocks[0]["part"]["text"] == "thinking done"
