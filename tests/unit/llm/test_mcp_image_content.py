"""MCP ImageContent validation and provider-wire contracts."""
from __future__ import annotations

import base64
from io import BytesIO

import pytest
from PIL import Image

from plugins.llm_config import ProviderConfig
from quickquip.llm.mcp.types import (
    MCPInlineImageCandidate,
    _decode_image_candidate,
    _format_tool_result,
    deliver_mcp_tool_result,
)
from quickquip.llm.provider import BaseProviderClient, LLMRequest
from quickquip.llm.tools import LLMConversationMessage, LLMInlineImage, LLMToolCall, LLMToolSpec
from tests.fixtures.provider_fakes import (
    FakeClaudeClient,
    FakeGeminiClient,
    FakeOpenAIClient,
)


def _encoded_image(image_format: str) -> str:
    image = Image.new("RGB", (2, 2), color=(12, 34, 56))
    data = BytesIO()
    image.save(data, format=image_format)
    return base64.b64encode(data.getvalue()).decode("ascii")


@pytest.mark.parametrize(
    ("image_format", "mime_type"),
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("GIF", "image/gif"),
        ("WEBP", "image/webp"),
    ],
)
def test_delivery_accepts_supported_verified_image_types(image_format, mime_type):
    encoded = _encoded_image(image_format)
    result = _format_tool_result({"content": [{
        "type": "image", "data": encoded, "mimeType": mime_type,
    }]})

    delivered = deliver_mcp_tool_result(result, server_id="prts", tool_name="operator_artwork")

    assert len(delivered.images) == 1
    assert delivered.images[0].media_type == mime_type
    assert delivered.images[0].data
    assert encoded not in delivered.content
    assert "图片项" not in delivered.content


@pytest.mark.parametrize(
    ("data", "mime_type"),
    [
        ("not canonical base64", "image/png"),
        ("AAAA=", "image/png"),
        (_encoded_image("PNG"), "image/jpeg"),
        (_encoded_image("PNG"), "image/svg+xml"),
    ],
)
def test_delivery_omits_invalid_or_mismatched_images_without_data_leak(data, mime_type):
    result = _format_tool_result({"content": [{
        "type": "image", "data": data, "mimeType": mime_type,
    }]})

    delivered = deliver_mcp_tool_result(result, server_id="prts", tool_name="operator_artwork")

    assert delivered.images == []
    assert "1 个无效或超出限制的图片项" in delivered.content
    assert data not in delivered.content


def test_delivery_caps_at_five_and_error_results_never_deliver_images():
    encoded = _encoded_image("PNG")
    items = [{"type": "image", "data": encoded, "mimeType": "image/png"} for _ in range(6)]

    delivered = deliver_mcp_tool_result(
        _format_tool_result({"content": items}), server_id="prts", tool_name="operator_artwork"
    )
    error_delivered = deliver_mcp_tool_result(
        _format_tool_result({"isError": True, "content": items[:1]}),
        server_id="prts",
        tool_name="operator_artwork",
    )

    assert len(delivered.images) == 5
    assert "1 个无效或超出限制的图片项" in delivered.content
    assert error_delivered.is_error is True
    assert error_delivered.images == []
    assert encoded not in error_delivered.content


def test_strict_decoder_enforces_five_mib_before_decoding():
    maximum = 5 * 1024 * 1024
    at_limit = base64.b64encode(b"x" * maximum).decode("ascii")
    above_limit = base64.b64encode(b"x" * (maximum + 1)).decode("ascii")

    assert len(_decode_image_candidate(MCPInlineImageCandidate(0, at_limit, "image/png"))) == maximum
    assert _decode_image_candidate(MCPInlineImageCandidate(0, above_limit, "image/png")) is None


def _config(protocol: str) -> ProviderConfig:
    return ProviderConfig(
        id=f"fake-{protocol}",
        protocol=protocol,
        base_url="https://example.test/v1",
        api_key_env="TEST_KEY",
        default_model="test-model",
        models=["test-model"],
    )


class _InlineOpenAIClient(FakeOpenAIClient):
    async def _prepare_image_inputs(self, image_urls, inline_images=None):
        return await BaseProviderClient._prepare_image_inputs(self, image_urls, inline_images)


class _InlineClaudeClient(FakeClaudeClient):
    async def _prepare_image_inputs(self, image_urls, inline_images=None):
        return await BaseProviderClient._prepare_image_inputs(self, image_urls, inline_images)


class _InlineGeminiClient(FakeGeminiClient):
    async def _prepare_image_inputs(self, image_urls, inline_images=None):
        return await BaseProviderClient._prepare_image_inputs(self, image_urls, inline_images)


def _tool_request(*, is_error: bool = False) -> LLMRequest:
    image = LLMInlineImage(
        data=base64.b64decode(_encoded_image("PNG")),
        media_type="image/png",
        source_label="MCP/prts/operator_artwork image 1",
    )
    return LLMRequest(
        model="test-model",
        system_prompt="system",
        messages=[
            LLMConversationMessage(
                role="assistant",
                tool_calls=[LLMToolCall(id="call_1", name="operator_artwork", arguments_json="{}")],
            ),
            LLMConversationMessage(
                role="tool",
                content="safe tool text",
                tool_call_id="call_1",
                tool_name="operator_artwork",
                is_tool_error=is_error,
                inline_images=[image],
            ),
        ],
        temperature=0.2,
        max_output_tokens=128,
        tools=[
            LLMToolSpec(
                name="operator_artwork",
                description="artwork",
                input_schema={"type": "object", "properties": {}},
            )
        ],
        allow_tool_calls=True,
    )


_OPENAI_RESPONSE = {"choices": [{"message": {"content": "ok"}}]}
_CLAUDE_RESPONSE = {"content": [{"type": "text", "text": "ok"}]}
_GEMINI_RESPONSE = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


async def test_openai_tool_image_uses_text_tool_pair_then_controlled_user_turn():
    client = _InlineOpenAIClient(_config("openai"), _OPENAI_RESPONSE)
    await client.complete(_tool_request())

    messages = client.last_payload["messages"]
    assert [item["role"] for item in messages[-3:]] == ["assistant", "tool", "user"]
    assert messages[-2]["content"] == "safe tool text"
    assert messages[-1]["content"][0]["type"] == "image_url"
    assert messages[-1]["content"][-1]["type"] == "text"
    assert "tools" in client.last_payload


async def test_openai_multiple_tool_results_finish_pairs_before_image_user_turn():
    client = _InlineOpenAIClient(_config("openai"), _OPENAI_RESPONSE)
    request = _tool_request()
    request.messages[0].tool_calls.append(
        LLMToolCall(id="call_2", name="other_tool", arguments_json="{}")
    )
    request.messages.append(LLMConversationMessage(
        role="tool",
        content="other safe text",
        tool_call_id="call_2",
        tool_name="other_tool",
    ))
    await client.complete(request)

    messages = client.last_payload["messages"]
    assert [item["role"] for item in messages[-4:]] == ["assistant", "tool", "tool", "user"]
    assert messages[-3]["tool_call_id"] == "call_1"
    assert messages[-2]["tool_call_id"] == "call_2"
    assert messages[-1]["content"][0]["type"] == "image_url"


async def test_claude_tool_image_uses_tool_result_content_blocks():
    client = _InlineClaudeClient(_config("claude"), _CLAUDE_RESPONSE)
    await client.complete(_tool_request())

    tool_result = client.last_payload["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["content"][0] == {"type": "text", "text": "safe tool text"}
    assert tool_result["content"][1]["source"]["media_type"] == "image/png"


async def test_gemini_tool_image_follows_complete_function_response_batch():
    client = _InlineGeminiClient(_config("gemini"), _GEMINI_RESPONSE)
    await client.complete(_tool_request())

    function_turn, image_turn = client.last_payload["contents"][-2:]
    assert function_turn["role"] == "user"
    assert function_turn["parts"] == [{
        "functionResponse": {
            "id": "call_1",
            "name": "operator_artwork",
            "response": {"content": "safe tool text", "is_error": False},
        }
    }]
    assert image_turn["role"] == "user"
    assert image_turn["parts"][0]["inline_data"]["mime_type"] == "image/png"


@pytest.mark.parametrize(
    ("client_type", "response"),
    [
        (_InlineOpenAIClient, _OPENAI_RESPONSE),
        (_InlineClaudeClient, _CLAUDE_RESPONSE),
        (_InlineGeminiClient, _GEMINI_RESPONSE),
    ],
)
async def test_provider_never_serializes_images_for_tool_error(client_type, response):
    protocol = {"_InlineOpenAIClient": "openai", "_InlineClaudeClient": "claude", "_InlineGeminiClient": "gemini"}[client_type.__name__]
    client = client_type(_config(protocol), response)
    await client.complete(_tool_request(is_error=True))

    rendered = str(client.last_payload)
    assert "safe tool text" in rendered
    assert "iVBOR" not in rendered
