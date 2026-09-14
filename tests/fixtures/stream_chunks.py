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


# ── OpenAI Responses ───────────────────────────────────────────────────────
# 事件形状按官方 /v1/responses SSE 语义构造（sequence_number 连续递增，
# 终态 response.completed 携带完整 output items 与 usage）。语义事件与
# 结构型事件（response.created/output_item.added 等）按真实顺序穿插。

RESPONSES_TEXT_CHUNKS: list[dict] = [
    {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_1"}},
    {"type": "response.in_progress", "sequence_number": 1},
    {
        "type": "response.output_text.delta",
        "sequence_number": 2,
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "delta": "你好",
    },
    {
        "type": "response.output_text.delta",
        "sequence_number": 3,
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "delta": "，世界",
    },
    {"type": "response.output_text.done", "sequence_number": 4, "text": "你好，世界"},
    {
        "type": "response.completed",
        "sequence_number": 5,
        "response": {
            "id": "resp_1",
            "model": "gpt-5.2",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "你好，世界", "annotations": []}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 300,
                "output_tokens": 40,
                "input_tokens_details": {"cached_tokens": 250},
                "output_tokens_details": {"reasoning_tokens": 15},
            },
        },
    },
]

# 工具调用轮：reasoning（含密文）→ function_call（连续两次调用）→ 终态。
RESPONSES_TOOL_CHUNKS: list[dict] = [
    {"type": "response.created", "sequence_number": 0},
    {
        "type": "response.reasoning_summary_text.delta",
        "sequence_number": 1,
        "item_id": "rs_1",
        "output_index": 0,
        "delta": "需要先查询身份。",
    },
    {"type": "response.reasoning_summary_text.done", "sequence_number": 2},
    {
        "type": "response.output_item.added",
        "sequence_number": 3,
        "output_index": 1,
        "item": {"type": "function_call", "call_id": "call_1", "name": "get_identity"},
    },
    {
        "type": "response.function_call_arguments.delta",
        "sequence_number": 4,
        "item_id": "fc_1",
        "output_index": 1,
        "delta": '{"qu',
    },
    {
        "type": "response.function_call_arguments.delta",
        "sequence_number": 5,
        "item_id": "fc_1",
        "output_index": 1,
        "delta": 'ery":"哈基镜"}',
    },
    {"type": "response.function_call_arguments.done", "sequence_number": 6},
    {
        "type": "response.output_item.added",
        "sequence_number": 7,
        "output_index": 2,
        "item": {"type": "function_call", "call_id": "call_2", "name": "search_web"},
    },
    {
        "type": "response.function_call_arguments.delta",
        "sequence_number": 8,
        "item_id": "fc_2",
        "output_index": 2,
        "delta": '{"query":"今日新闻"}',
    },
    {
        "type": "response.completed",
        "sequence_number": 9,
        "response": {
            "id": "resp_2",
            "model": "gpt-5.2",
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [
                        {"type": "summary_text", "text": "需要先查询身份。"}
                    ],
                    "encrypted_content": "gAAAAABoGogL0EiS",
                },
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "get_identity",
                    "arguments": '{"query":"哈基镜"}',
                },
                {
                    "type": "function_call",
                    "id": "fc_2",
                    "call_id": "call_2",
                    "name": "search_web",
                    "arguments": '{"query":"今日新闻"}',
                },
            ],
            "usage": {"input_tokens": 120, "output_tokens": 66},
        },
    },
]

# codex-http-relay 形状：codex.* 私有结构事件 + 终态 output 省略可选字段
# （完整 item 只在流式 output_item.done 里出现）。
RESPONSES_RELAY_TOOL_CHUNKS: list[dict] = [
    {"type": "codex.rate_limits", "sequence_number": 0},
    {
        "type": "response.output_item.done",
        "sequence_number": 1,
        "output_index": 0,
        "item": {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [],
            "encrypted_content": "gAAAAABrelay",
        },
    },
    {
        "type": "response.output_item.done",
        "sequence_number": 2,
        "output_index": 1,
        "item": {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "get_identity",
            "arguments": '{"query":"哈基镜"}',
        },
    },
    {"type": "codex.response.metadata", "sequence_number": 3},
    {
        "type": "response.completed",
        "sequence_number": 4,
        "response": {
            "id": "resp_3",
            "model": "gpt-5.2",
            "status": "completed",
            # 终态省略 status/summary 等可选字段：流式完整 item 为回放基准
            "output": [
                {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAAAABrelay"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "get_identity",
                    "arguments": '{"query":"哈基镜"}',
                },
            ],
            "usage": {"input_tokens": 88, "output_tokens": 30},
        },
    },
]
