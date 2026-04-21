"""Sample SSE chunk sequences for each provider's streaming decoder.

These are real-shape fixtures captured from production traffic, used to
exercise ProviderClient._assemble_stream_response. Do not hand-edit fields
without cross-checking the provider's wire format.
"""
from __future__ import annotations


# ── OpenAI ────────────────────────────────────────────────────────────────

OPENAI_TEXT_CHUNKS: list[dict] = [
    {
        "model": "gpt-5.4",
        "choices": [{"delta": {"content": "你好"}, "finish_reason": None}],
    },
    {
        "model": "gpt-5.4",
        "choices": [{"delta": {"content": "世界"}, "finish_reason": None}],
    },
    {
        "model": "gpt-5.4",
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    },
]


OPENAI_TOOL_CHUNKS: list[dict] = [
    {
        "model": "gpt-5.4",
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {"name": "search_web", "arguments": '{"qu'},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    },
    {
        "model": "gpt-5.4",
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": 'ery": "test"}'}}
                    ]
                },
                "finish_reason": None,
            }
        ],
    },
    {
        "model": "gpt-5.4",
        "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
    },
]


OPENAI_REASONING_CHUNKS: list[dict] = [
    {
        "model": "gpt-5.4",
        "choices": [
            {"delta": {"content": "<think>\n先想一想\n</think>\n"}, "finish_reason": None}
        ],
    },
    {
        "model": "gpt-5.4",
        "choices": [{"delta": {"content": "最终答复"}, "finish_reason": "stop"}],
    },
]


# ── Claude ────────────────────────────────────────────────────────────────

CLAUDE_TEXT_CHUNKS: list[dict] = [
    {
        "_sse_event": "message_start",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 15}},
    },
    {
        "_sse_event": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "_sse_event": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "你好"},
    },
    {
        "_sse_event": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "世界"},
    },
    {"_sse_event": "content_block_stop", "index": 0},
    {
        "_sse_event": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 8},
    },
]


CLAUDE_TOOL_CHUNKS: list[dict] = [
    {
        "_sse_event": "message_start",
        "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 20}},
    },
    {
        "_sse_event": "content_block_start",
        "index": 0,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search_web"},
    },
    {
        "_sse_event": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"quer'},
    },
    {
        "_sse_event": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": 'y": "test"}'},
    },
    {"_sse_event": "content_block_stop", "index": 0},
    {
        "_sse_event": "message_delta",
        "delta": {"stop_reason": "tool_use"},
        "usage": {"output_tokens": 12},
    },
]


# ── Gemini ────────────────────────────────────────────────────────────────

GEMINI_TEXT_CHUNKS: list[dict] = [
    {"candidates": [{"content": {"parts": [{"text": "你好"}]}}]},
    {
        "candidates": [
            {
                "content": {"parts": [{"text": "世界"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4},
    },
]


GEMINI_TOOL_CHUNKS: list[dict] = [
    {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {
                                "name": "search_web",
                                "args": {"query": "test"},
                            }
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    },
]


# Shape captured from a real Gemini stream where `thought: true` parts
# (Gemini native thought summaries) appeared interleaved with real reply
# parts. Used to exercise the filter in _assemble_stream_response.
GEMINI_THOUGHT_LEAK_CHUNKS: list[dict] = [
    {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "**Analyzing the Input**\n\nI'm currently dissecting",
                            "thought": True,
                        }
                    ],
                    "role": "model",
                }
            }
        ],
    },
    {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "**Interpreting the Nuance**\n\nI'm now focusing on",
                            "thought": True,
                        }
                    ],
                    "role": "model",
                }
            }
        ],
    },
    {"candidates": [{"content": {"parts": [{"text": "月曦，"}], "role": "model"}}]},
    {
        "candidates": [
            {
                "content": {"parts": [{"text": "小四这是不小心啃到蘑菇了吗？"}], "role": "model"},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 79, "candidatesTokenCount": 12},
    },
]
