"""Safety and compatibility contracts for MCP tool-result normalization."""
from __future__ import annotations

import pytest

from quickquip.llm.mcp.types import _format_tool_result


BASE64_SENTINEL = "MCP_IMAGE_BASE64_SECRET_5fd8e1"
RESOURCE_QUERY_SENTINEL = "mcp_resource_query_secret_3a29"
RESOURCE_BODY_SENTINEL = "mcp_resource_body_secret_0bb7"


def test_text_items_are_trimmed_joined_and_empty_items_ignored():
    result = _format_tool_result(
        {"content": [
            {"type": "text", "text": "  first  "},
            {"type": "text", "text": " \n "},
            {"type": "text", "text": "second"},
        ]}
    )

    assert result.text == ["first", "second"]
    assert result.content == "first\nsecond"
    assert result.images == []
    assert result.deferred == []


def test_structured_content_preserves_existing_text_fallback_behavior():
    structured_only = _format_tool_result({"structuredContent": {"answer": "ok"}})
    text_and_structured = _format_tool_result(
        {
            "content": [{"type": "text", "text": "visible text"}],
            "structuredContent": {"answer": "not included when text exists"},
        }
    )

    assert structured_only.content == '{"answer": "ok"}'
    assert text_and_structured.content == "visible text"


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        (
            {"content": [{"type": "image", "data": BASE64_SENTINEL, "mimeType": "image/png"}]},
            "1 个尚未交付的图片项",
        ),
        (
            {"content": [{"type": "resource", "resource": {
                "uri": f"https://example.test/data?token={RESOURCE_QUERY_SENTINEL}",
                "text": RESOURCE_BODY_SENTINEL,
                "mimeType": "text/plain",
            }}]},
            "1 个 resource 项",
        ),
        (
            {"content": [{"type": "audio", "data": BASE64_SENTINEL, "mimeType": "audio/ogg"}]},
            "1 个 audio 项",
        ),
        (
            {"content": [{"type": "resource_link", "uri":
                f"https://example.test/file?token={RESOURCE_QUERY_SENTINEL}", "mimeType": "text/plain"}]},
            "1 个 link 项",
        ),
        (
            {"content": [{"type": "unrecognized_payload", "data": BASE64_SENTINEL}]},
            "1 个格式错误或未知的内容项",
        ),
        (
            {"content": [BASE64_SENTINEL]},
            "1 个格式错误或未知的内容项",
        ),
    ],
)
def test_non_text_payloads_have_stable_notices_without_payload_leaks(payload, expected_fragment):
    result = _format_tool_result(payload)

    assert expected_fragment in result.content
    assert BASE64_SENTINEL not in result.content
    assert RESOURCE_QUERY_SENTINEL not in result.content
    assert RESOURCE_BODY_SENTINEL not in result.content


def test_text_and_image_keeps_safe_text_and_reports_undelivered_image():
    result = _format_tool_result(
        {"content": [
            {"type": "text", "text": "safe result"},
            {"type": "image", "data": BASE64_SENTINEL, "mimeType": "image/png"},
        ]}
    )

    assert result.content.startswith("safe result")
    assert "1 个尚未交付的图片项" in result.content
    assert BASE64_SENTINEL not in result.content
    assert len(result.images) == 1
    assert result.images[0].data == BASE64_SENTINEL


def test_malformed_resource_uri_is_not_rendered_or_allowed_to_break_normalization():
    result = _format_tool_result(
        {"content": [{"type": "resource_link", "uri": "https://[invalid"}]}
    )

    assert result.deferred[0].scheme == ""
    assert "link 项" in result.content


@pytest.mark.parametrize(
    "payload",
    [
        {"isError": True, "content": [{"type": "image", "data": BASE64_SENTINEL, "mimeType": "image/png"}]},
        {"isError": True, "content": [{"type": "resource", "resource": {
            "uri": f"https://example.test?token={RESOURCE_QUERY_SENTINEL}",
            "blob": RESOURCE_BODY_SENTINEL,
        }}]},
    ],
)
def test_error_results_use_the_same_safe_normalization(payload):
    result = _format_tool_result(payload)

    assert result.is_error is True
    assert BASE64_SENTINEL not in result.content
    assert RESOURCE_QUERY_SENTINEL not in result.content
    assert RESOURCE_BODY_SENTINEL not in result.content
