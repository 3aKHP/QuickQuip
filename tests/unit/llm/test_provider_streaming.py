from __future__ import annotations

import json

from plugins.llm_provider import (
    ClaudeProviderClient,
    GeminiProviderClient,
    OpenAIProviderClient,
    strip_leading_reasoning_content,
)

from tests.fixtures.stream_chunks import (
    CLAUDE_TEXT_CHUNKS,
    CLAUDE_TOOL_CHUNKS,
    GEMINI_TEXT_CHUNKS,
    GEMINI_THOUGHT_LEAK_CHUNKS,
    GEMINI_TOOL_CHUNKS,
    OPENAI_REASONING_CHUNKS,
    OPENAI_TEXT_CHUNKS,
    OPENAI_TOOL_CHUNKS,
)


class TestOpenAIStreaming:
    def test_text_only(self):
        resp = OpenAIProviderClient._assemble_stream_response(OPENAI_TEXT_CHUNKS, "gpt-5.4")
        assert resp.text == "你好世界"
        assert resp.finish_reason == "stop"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 2
        assert resp.tool_calls == []

    def test_tool_calls_with_incremental_arguments(self):
        resp = OpenAIProviderClient._assemble_stream_response(OPENAI_TOOL_CHUNKS, "gpt-5.4")
        assert resp.text == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "call_1"
        assert resp.tool_calls[0].name == "search_web"
        assert json.loads(resp.tool_calls[0].arguments_json) == {"query": "test"}
        assert resp.finish_reason == "tool_calls"

    def test_reasoning_content_is_stripped(self):
        resp = OpenAIProviderClient._assemble_stream_response(OPENAI_REASONING_CHUNKS, "gpt-5.4")
        assert resp.text == "最终答复"


class TestStripLeadingReasoningContent:
    def test_think_block(self):
        assert strip_leading_reasoning_content("<think>\n先想一想\n</think>\n最终答复") == "最终答复"

    def test_thinking_fence(self):
        assert strip_leading_reasoning_content("```thinking\n分析\n```\n最终答复") == "最终答复"


class TestClaudeStreaming:
    def test_text_only(self):
        resp = ClaudeProviderClient._assemble_stream_response(CLAUDE_TEXT_CHUNKS, "claude-sonnet-4-6")
        assert resp.text == "你好世界"
        assert resp.finish_reason == "end_turn"
        assert resp.input_tokens == 15
        assert resp.output_tokens == 8
        assert resp.tool_calls == []

    def test_tool_use(self):
        resp = ClaudeProviderClient._assemble_stream_response(CLAUDE_TOOL_CHUNKS, "claude-sonnet-4-6")
        assert resp.text == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "toolu_1"
        assert resp.tool_calls[0].name == "search_web"
        assert json.loads(resp.tool_calls[0].arguments_json) == {"query": "test"}


class TestGeminiStreaming:
    def test_text_only(self):
        resp = GeminiProviderClient._assemble_stream_response(GEMINI_TEXT_CHUNKS, "gemini-pro")
        assert resp.text == "你好世界"
        assert resp.finish_reason == "STOP"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 4
        assert resp.tool_calls == []

    def test_function_call(self):
        resp = GeminiProviderClient._assemble_stream_response(GEMINI_TOOL_CHUNKS, "gemini-pro")
        assert resp.text == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search_web"
        assert json.loads(resp.tool_calls[0].arguments_json) == {"query": "test"}

    def test_thought_parts_are_filtered(self):
        resp = GeminiProviderClient._assemble_stream_response(
            GEMINI_THOUGHT_LEAK_CHUNKS, "gemini-3.1-pro-preview"
        )
        assert resp.text == "月曦，小四这是不小心啃到蘑菇了吗？"
        assert "Analyzing" not in resp.text
        assert "thought" not in resp.text.lower()

    def test_thought_parts_are_filtered_non_stream(self):
        candidate = {
            "content": {
                "parts": [
                    {"text": "**Analyzing**\n\nI'm thinking hard.", "thought": True},
                    {"text": "真正的回复"},
                ]
            },
            "finishReason": "STOP",
        }
        resp = GeminiProviderClient._parse_candidate(candidate, "gemini-3.1-pro-preview")
        assert resp.text == "真正的回复"
