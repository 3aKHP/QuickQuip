from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import replace

import pytest

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import GeminiProviderClient, LLMRequest
from plugins.llm_tools import LLMConversationMessage, LLMToolSpec

from tests.fixtures.provider_fakes import FakeGeminiClient


def test_stream_preserves_independent_signed_parts_and_text_deltas():
    def chunk(parts):
        return {"candidates": [{"content": {"parts": parts}}]}

    response = GeminiProviderClient._assemble_stream_response([
        chunk([{"text": "a"}, {"text": "b", "thoughtSignature": "sig-b"}]),
        chunk([{"text": "c"}]),
        chunk([{"text": "d"}]),
        chunk([{"text": "", "thoughtSignature": "sig-cd"}]),
        chunk([{"text": "e", "thoughtSignature": "sig-e"}]),
    ], "m")
    assert response.native_blocks == [
        {"text": "a"}, {"text": "b", "thoughtSignature": "sig-b"},
        {"text": "cd"},
        {"text": "", "thoughtSignature": "sig-cd"},
        {"text": "e", "thoughtSignature": "sig-e"},
    ]
    assert response.text == "abcde"
    assert GeminiProviderClient._replay_parts(response.thinking_blocks) == response.native_blocks


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


async def test_gemini_builtin_tool_schemas_match_parameters_contract(llm_service):
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
    invalid_enums: list[str] = []

    def check_schema(schema, path: str) -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "array" and "items" not in schema:
            missing_items.append(path)
        # Gemini's parameters Schema proto declares enum as repeated string.
        if "enum" in schema and any(not isinstance(v, str) for v in schema["enum"]):
            invalid_enums.append(path)
        for name, subschema in schema.get("properties", {}).items():
            check_schema(subschema, f"{path}.properties[{name}]")
        if "items" in schema:
            check_schema(schema["items"], f"{path}.items")
        for index, subschema in enumerate(schema.get("anyOf", [])):
            check_schema(subschema, f"{path}.anyOf[{index}]")

    for index, declaration in enumerate(declarations):
        check_schema(
            declaration["parameters"],
            f"functionDeclarations[{index}].parameters",
        )
    assert missing_items == []
    assert invalid_enums == []

    memory = next(item for item in declarations if item["name"] == "write_memory")
    version = memory["parameters"]["properties"]["content_parts"]["properties"]["version"]
    assert version["type"] == "integer"
    assert version["minimum"] == version["maximum"] == 1


async def test_gemini_mcp_style_array_schema_gets_default_items():
    # MCP 服务器透传的 schema 常声明 {"type": "array"} 而省略 items（合法 JSON Schema），
    # 修复前会被 Gemini proto 以 400 拒绝（同 #137 内建工具缺陷）。
    request = _tool_call_request()
    request.tools = [
        LLMToolSpec(
            name="mcp_fake_list_things",
            description="[MCP/fake] 列举事物",
            input_schema={"type": "object", "properties": {"tags": {"type": "array"}}},
        )
    ]
    client = FakeGeminiClient(
        _provider_config(), {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    )

    await client.complete(request)

    declaration = client.last_payload["tools"][0]["functionDeclarations"][0]
    assert declaration["parameters"]["properties"]["tags"] == {"type": "array", "items": {}}


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


# ---------------------------------------------------------------------------
# builtin_search（google_search grounding）
# ---------------------------------------------------------------------------

_GROUNDING_RESPONSE = {
    "candidates": [
        {
            "finishReason": "STOP",
            "content": {"parts": [{"text": "有来源的回答"}]},
            "groundingMetadata": {
                "webSearchQueries": ["quickquip 是什么", ""],
                "groundingChunks": [
                    {"web": {"uri": "https://example.test/a", "title": "来源甲"}},
                    {"web": {"uri": "https://example.test/a", "title": "重复来源"}},
                    "不是字典的条目",
                    {"web": {"uri": "", "title": "缺 uri"}},
                    {"web": {"uri": "https://example.test/b"}},
                    {"不是 web chunk": 1},
                ],
            },
        }
    ],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
}


async def test_gemini_builtin_search_declared_alongside_function_tools():
    client = FakeGeminiClient(
        _provider_config(),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )
    request = _tool_call_request()
    request.builtin_search = True

    await client.complete(request)

    assert client.last_payload["tools"][0]["functionDeclarations"][0]["name"] == "get_identity"
    assert client.last_payload["tools"][1] == {"google_search": {}}
    assert client.last_payload["toolConfig"] == {"includeServerSideToolInvocations": True}


async def test_gemini_builtin_search_declared_without_client_tools():
    client = FakeGeminiClient(
        _provider_config(),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )
    request = _tool_call_request()
    request.tools = []
    request.allow_tool_calls = False
    request.builtin_search = True

    await client.complete(request)

    # 声明独立于客户端工具：即使工具调用整体关闭也生效
    assert client.last_payload["tools"] == [{"google_search": {}}]
    assert "toolConfig" not in client.last_payload


async def test_gemini_builtin_search_off_keeps_payload_unchanged():
    client = FakeGeminiClient(
        _provider_config(),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )

    await client.complete(_tool_call_request())

    assert "google_search" not in str(client.last_payload)
    assert "toolConfig" not in client.last_payload


async def test_gemini_extra_body_merges_tool_config_without_mutating():
    extra = {"toolConfig": {"functionCallingConfig": {"mode": "AUTO"}}}
    cfg = replace(_provider_config(), extra_body=extra)
    client = FakeGeminiClient(cfg, _text_body())
    request = _tool_call_request()
    request.builtin_search = True

    await client.complete(request)

    assert client.last_payload["toolConfig"] == {
        "includeServerSideToolInvocations": True,
        "functionCallingConfig": {"mode": "AUTO"},
    }
    assert extra == {"toolConfig": {"functionCallingConfig": {"mode": "AUTO"}}}

    # Explicit camelCase override wins
    override_cfg = replace(
        _provider_config(),
        extra_body={"toolConfig": {"includeServerSideToolInvocations": False}},
    )
    override_client = FakeGeminiClient(override_cfg, _text_body())
    await override_client.complete(deepcopy(request))
    assert override_client.last_payload["toolConfig"] == {
        "includeServerSideToolInvocations": False,
    }

    # Explicit snake_case override removes auto camelCase spelling
    snake_cfg = replace(
        _provider_config(),
        extra_body={"toolConfig": {"include_server_side_tool_invocations": False}},
    )
    snake_client = FakeGeminiClient(snake_cfg, _text_body())
    await snake_client.complete(deepcopy(request))
    assert snake_client.last_payload["toolConfig"] == {
        "include_server_side_tool_invocations": False,
    }
    assert "includeServerSideToolInvocations" not in snake_client.last_payload["toolConfig"]

    # Top-level tool_config alias merges into toolConfig cleanly
    alias_cfg = replace(
        _provider_config(),
        extra_body={"tool_config": {"functionCallingConfig": {"mode": "ANY"}}},
    )
    alias_client = FakeGeminiClient(alias_cfg, _text_body())
    await alias_client.complete(deepcopy(request))
    assert alias_client.last_payload["toolConfig"] == {
        "includeServerSideToolInvocations": True,
        "functionCallingConfig": {"mode": "ANY"},
    }
    assert "tool_config" not in alias_client.last_payload


async def test_gemini_parses_grounding_metadata_non_stream():
    client = FakeGeminiClient(_provider_config(), _GROUNDING_RESPONSE)

    response = await client.complete(_tool_call_request())

    assert response.web_search is not None
    assert response.web_search.queries == ["quickquip 是什么"]
    assert [source.url for source in response.web_search.sources] == [
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert response.web_search.sources[0].title == "来源甲"
    # title 缺失时保持空串，展示层回退为仅域名（不回填 provider 侧长链）
    assert response.web_search.sources[1].title == ""


async def test_gemini_parses_grounding_metadata_from_stream():
    # 流式路径：groundingMetadata 挂在某个 chunk 的 candidate 上，
    # 经 _combine_stream_trace 合并后仍须到达 _parse_candidate。
    chunks = [
        {
            "candidates": [
                {
                    "index": 0,
                    "content": {"role": "model", "parts": [{"text": "流式"}]},
                }
            ]
        },
        {
            "candidates": [
                {
                    "index": 0,
                    "content": {"parts": [{"text": "回答"}]},
                    "groundingMetadata": {
                        "webSearchQueries": ["流式查询"],
                        "groundingChunks": [
                            {"web": {"uri": "https://example.test/s", "title": "流式来源"}},
                        ],
                    },
                }
            ]
        },
    ]

    response = GeminiProviderClient._assemble_stream_response(chunks, "gemini-test")

    assert response.text == "流式回答"
    assert response.web_search is not None
    assert response.web_search.queries == ["流式查询"]
    assert response.web_search.sources[0].url == "https://example.test/s"


async def test_gemini_without_grounding_metadata_yields_none():
    client = FakeGeminiClient(
        _provider_config(),
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )

    response = await client.complete(_tool_call_request())

    assert response.web_search is None


async def test_gemini_empty_grounding_metadata_yields_none():
    client = FakeGeminiClient(
        _provider_config(),
        {
            "candidates": [
                {"content": {"parts": [{"text": "ok"}]}, "groundingMetadata": {}}
            ]
        },
    )

    response = await client.complete(_tool_call_request())

    assert response.web_search is None


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
    assert response.tool_calls[0].id == "gemini_tool_3"
    assert [
        block["part"].get("thoughtSignature")
        for block in response.thinking_blocks
        if block["part"].get("thoughtSignature")
    ] == [
        "thought-sig",
        "call-sig",
    ]
    assert response.thinking_blocks[0]["part"] == {"text": "thinking", "thought": True}
    assert response.thinking_blocks[1]["part"] == {
        "text": " done",
        "thought": True,
        "thoughtSignature": "thought-sig",
    }


# ---------------------------------------------------------------------------
# 响应侧 inlineData 图片 parts（image 系模型输出）
# ---------------------------------------------------------------------------

_IMAGE_PNG_BASE64 = base64.b64encode(b"\x89PNG-gemini-bytes").decode()

_INLINE_IMAGE_RESPONSE = {
    "candidates": [
        {
            "finishReason": "STOP",
            "content": {
                "parts": [
                    {"text": "给你画好了"},
                    {"inlineData": {"mimeType": "image/png", "data": _IMAGE_PNG_BASE64}},
                    {
                        "functionCall": {
                            "name": "report_status",
                            "args": {"ok": True},
                        }
                    },
                ]
            },
        }
    ],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
}


async def test_gemini_extracts_inline_image_parts():
    client = FakeGeminiClient(_provider_config(), _INLINE_IMAGE_RESPONSE)

    response = await client.complete(_tool_call_request())

    assert response.text == "给你画好了"
    assert len(response.generated_images) == 1
    image = response.generated_images[0]
    assert image.data == b"\x89PNG-gemini-bytes"
    assert image.media_type == "image/png"
    assert image.source == "gemini.inline_data"
    # 图片 part 剥除出原生批次；functionCall 缺省 id 按剩余 parts 连续编号
    block_types = [
        "functionCall" if "functionCall" in part else "text"
        for part in (response.native_blocks or [])
    ]
    assert block_types == ["text", "functionCall"]
    assert response.tool_calls[0].id == "gemini_tool_2"


async def test_gemini_non_image_inline_data_kept_in_parts():
    audio_b64 = base64.b64encode(b"fake-audio").decode()
    response_body = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "听写如下"},
                        {"inlineData": {"mimeType": "audio/wav", "data": audio_b64}},
                    ]
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    client = FakeGeminiClient(_provider_config(), response_body)

    response = await client.complete(_tool_call_request())

    assert response.generated_images == []
    # 非图片 inlineData 不被误剥除，原样留在原生批次
    assert any("inlineData" in part for part in (response.native_blocks or []))


# ── 思考档位（resolve_thinking 接线） ────────────────────────────


def _simple_request(
    model: str, *, effort: str | None = None, thinking_budget: int | None = None
) -> LLMRequest:
    return LLMRequest(
        model=model,
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi", image_urls=[])],
        temperature=0.2,
        max_output_tokens=128,
        thinking_budget=thinking_budget,
        reasoning_effort=effort,
    )


def _text_body() -> dict:
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": "ok"}]}}
        ]
    }


async def test_gemini_3x_thinking_level():
    config = _provider_config()
    config.reasoning_effort = "xhigh"
    client = FakeGeminiClient(config, _text_body())
    await client.complete(_simple_request("gemini-3.7-flash"))
    assert client.last_payload["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "HIGH"
    }


async def test_gemini_25_thinking_budget_table():
    config = _provider_config()
    config.reasoning_effort = "medium"
    client = FakeGeminiClient(config, _text_body())
    await client.complete(_simple_request("gemini-2.5-flash"))
    assert client.last_payload["generationConfig"]["thinkingConfig"] == {
        "thinkingBudget": 2000
    }


async def test_gemini_explicit_thinking_budget_wins_over_tier():
    """已废弃的显式 thinking_budget 优先于档位映射（兼容读取）。"""
    config = _provider_config()
    config.reasoning_effort = "high"
    client = FakeGeminiClient(config, _text_body())
    await client.complete(_simple_request("gemini-3.7-flash", thinking_budget=1234))
    assert client.last_payload["generationConfig"]["thinkingConfig"] == {
        "thinkingBudget": 1234
    }


async def test_gemini_no_effort_sends_no_thinking_config():
    client = FakeGeminiClient(_provider_config(), _text_body())
    await client.complete(_simple_request("gemini-3.7-flash"))
    assert "thinkingConfig" not in client.last_payload["generationConfig"]


def test_stream_drops_trailing_empty_text_part_but_keeps_signed_empty_carrier():
    response = GeminiProviderClient._assemble_stream_response(
        [
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "id": "call_1",
                                        "name": "tool_search",
                                        "args": {"query": "q"},
                                    },
                                    "thoughtSignature": "sig-call",
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "", "thoughtSignature": "sig-carrier"}],
                        }
                    }
                ]
            },
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [{"text": ""}],
                        },
                    }
                ]
            },
        ],
        "gemini-4-argon",
    )
    assert response.native_blocks == [
        {
            "functionCall": {
                "id": "call_1",
                "name": "tool_search",
                "args": {"query": "q"},
            },
            "thoughtSignature": "sig-call",
        },
        {"text": "", "thoughtSignature": "sig-carrier"},
    ]


async def test_gemini_serializes_missing_signatures_and_strips_empty_native_parts():
    from plugins.llm_tools import LLMToolCall
    from quickquip.llm.provider.gemini_compat import SKIP_THOUGHT_SIGNATURE

    client = FakeGeminiClient(_provider_config(), _text_body())
    request = LLMRequest(
        model="gemini-4-argon",
        system_prompt="系统提示",
        messages=[
            LLMConversationMessage(role="user", content="查一下"),
            # Cross-model fallback assistant turn (no native_content, no thoughtSignature)
            LLMConversationMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_cross",
                        name="tool_search",
                        arguments_json='{"query":"x"}',
                    )
                ],
            ),
            LLMConversationMessage(
                role="tool",
                content="ok",
                tool_call_id="call_cross",
                tool_name="tool_search",
            ),
            # Native history turn containing stale {"text": ""} and unsigned functionCall
            LLMConversationMessage(
                role="assistant",
                content="",
                native_content=[
                    {
                        "functionCall": {
                            "id": "call_native_signed",
                            "name": "search_web",
                            "args": {"q": "a"},
                        },
                        "thoughtSignature": "real-sig",
                    },
                    {
                        "functionCall": {
                            "id": "call_native_unsigned",
                            "name": "search_web",
                            "args": {"q": "b"},
                        }
                    },
                    {"text": ""},
                    {"text": "", "thought": True},
                ],
            ),
            LLMConversationMessage(
                role="tool",
                content="done",
                tool_call_id="call_native_signed",
                tool_name="search_web",
            ),
            LLMConversationMessage(role="user", content=""),
        ],
        temperature=0.2,
        max_output_tokens=128,
    )
    _url, _headers, payload = await client._build_request_parts(request)
    contents = payload["contents"]
    assert contents[1] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call_cross",
                    "name": "tool_search",
                    "args": {"query": "x"},
                },
                "thoughtSignature": SKIP_THOUGHT_SIGNATURE,
            }
        ],
    }
    assert contents[3] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call_native_signed",
                    "name": "search_web",
                    "args": {"q": "a"},
                },
                "thoughtSignature": "real-sig",
            },
            {
                "functionCall": {
                    "id": "call_native_unsigned",
                    "name": "search_web",
                    "args": {"q": "b"},
                },
            },
        ],
    }
    # Empty user message falls back to non-empty space rather than ""
    assert contents[-1] == {"role": "user", "parts": [{"text": " "}]}


async def test_gemini_retries_once_with_downgraded_signatures_on_400_rejection():
    import pytest
    from quickquip.llm.provider.base import LLMProviderError
    from quickquip.llm.provider.gemini_compat import SKIP_THOUGHT_SIGNATURE

    class _RetryingGeminiClient(GeminiProviderClient):
        def __init__(
            self,
            config: ProviderConfig,
            outcomes: list[object],
            *,
            single_dispatch: bool = False,
        ):
            super().__init__(config, single_dispatch=single_dispatch)
            self._outcomes = list(outcomes)
            self.seen_payloads: list[dict] = []

        def _get_api_key(self) -> str:
            return "test-key"

        async def _post_json_candidate(self, url, headers, payload):
            self.seen_payloads.append(payload)
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, url

        async def _post_stream_sse_candidate(self, url, headers, payload):
            self.seen_payloads.append(payload)
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome, url

    def _signed_history_request() -> LLMRequest:
        return LLMRequest(
            model="gemini-4-argon",
            system_prompt="系统提示",
            messages=[
                LLMConversationMessage(role="user", content="hello"),
                LLMConversationMessage(
                    role="assistant",
                    content="",
                    native_content=[
                        {"text": "plan", "thought": True, "thoughtSignature": "vertex-sig-1"},
                        {
                            "functionCall": {"id": "c1", "name": "tool_a", "args": {}},
                            "thoughtSignature": "vertex-sig-2",
                        },
                    ],
                ),
                LLMConversationMessage(
                    role="tool",
                    content="res",
                    tool_call_id="c1",
                    tool_name="tool_a",
                ),
            ],
            temperature=0.2,
            max_output_tokens=128,
        )

    sig_400 = LLMProviderError(
        'HTTP 400 {"error":{"code":400,"message":"Invalid thought signature.",'
        '"status":"INVALID_ARGUMENT"}}',
        status_code=400,
        http_reject=True,
    )

    # 1. Non-stream succeeds on downgraded retry
    cfg = replace(_provider_config(), client_fingerprint="legacy-gemini", stream_enabled=False)
    client = _RetryingGeminiClient(cfg, [sig_400, _text_body()])
    resp = await client.complete(_signed_history_request())
    assert resp.text == "ok"
    assert len(client.seen_payloads) == 2
    assert client.seen_payloads[0]["contents"][1]["parts"][1]["thoughtSignature"] == "vertex-sig-2"
    assert client.seen_payloads[1]["contents"][1]["parts"] == [
        {"text": "plan", "thought": True},
        {
            "functionCall": {"id": "c1", "name": "tool_a", "args": {}},
            "thoughtSignature": SKIP_THOUGHT_SIGNATURE,
        },
    ]

    # 2. Stream succeeds on downgraded retry
    stream_cfg = replace(
        _provider_config(),
        client_fingerprint="legacy-gemini",
        stream_enabled=True,
    )
    stream_client = _RetryingGeminiClient(stream_cfg, [sig_400, [_text_body()]])
    stream_resp = await stream_client.complete(_signed_history_request())
    assert stream_resp.text == "ok"
    assert len(stream_client.seen_payloads) == 2
    retry_sig = stream_client.seen_payloads[1]["contents"][1]["parts"][1]["thoughtSignature"]
    assert retry_sig == SKIP_THOUGHT_SIGNATURE

    # 3. single_dispatch must never retry
    single_client = _RetryingGeminiClient(cfg, [sig_400, _text_body()], single_dispatch=True)
    with pytest.raises(LLMProviderError):
        await single_client.complete(_signed_history_request())
    assert len(single_client.seen_payloads) == 1

    # 4. Unrelated 400 must not retry
    other_400 = LLMProviderError(
        'HTTP 400 {"error":{"code":400,"message":"Invalid schema","status":"INVALID_ARGUMENT"}}',
        status_code=400,
        http_reject=True,
    )
    other_client = _RetryingGeminiClient(cfg, [other_400, _text_body()])
    with pytest.raises(LLMProviderError):
        await other_client.complete(_signed_history_request())
    assert len(other_client.seen_payloads) == 1

    # 5. Persistent signature 400 after downgrade stops after exactly one retry
    persistent_client = _RetryingGeminiClient(cfg, [sig_400, sig_400, _text_body()])
    with pytest.raises(LLMProviderError):
        await persistent_client.complete(_signed_history_request())
    assert len(persistent_client.seen_payloads) == 2

    # 6. No downgradable signatures in payload (changed == 0) must not retry
    unsigned_req = LLMRequest(
        model="gemini-4-argon",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hello")],
        temperature=0.2,
        max_output_tokens=128,
    )
    noop_client = _RetryingGeminiClient(cfg, [sig_400, _text_body()])
    with pytest.raises(LLMProviderError):
        await noop_client.complete(unsigned_req)
    assert len(noop_client.seen_payloads) == 1


async def test_gemini_optional_temperature_omitted_when_none():
    client = FakeGeminiClient(_provider_config(), _text_body())
    req = LLMRequest(
        model="gemini-3.7-flash",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi")],
        temperature=None,
        max_output_tokens=128,
    )
    await client.complete(req)
    assert "temperature" not in client.last_payload["generationConfig"]

    client_zero = FakeGeminiClient(_provider_config(), _text_body())
    req_zero = LLMRequest(
        model="gemini-3.7-flash",
        system_prompt="系统提示",
        messages=[LLMConversationMessage(role="user", content="hi")],
        temperature=0.0,
        max_output_tokens=128,
    )
    await client_zero.complete(req_zero)
    assert client_zero.last_payload["generationConfig"]["temperature"] == 0.0


@pytest.mark.parametrize("stream", [False, True])
def test_gemini_parses_and_replays_server_side_tool_parts(stream):
    parts = [
        {"thought": True, "text": "先联网查一下"},
        {
            "thoughtSignature": "sig-tc-1",
            "toolCall": {
                "id": "call_srv_1",
                "toolType": "GOOGLE_SEARCH_WEB",
                "args": {"queries": ["quickquip"]},
            },
        },
        {
            "thoughtSignature": "sig-tr-1",
            "toolResponse": {
                "id": "call_srv_1",
                "toolType": "GOOGLE_SEARCH_WEB",
            },
        },
        {"text": "搜索后总结"},
        {"text": "", "thoughtSignature": "sig-tail"},
    ]
    if stream:
        chunks = [
            {"candidates": [{"content": {"role": "model", "parts": [part]}}]}
            for part in parts
        ]
        response = GeminiProviderClient._assemble_stream_response(chunks, "gemini-3.7-flash")
    else:
        body = {
            "candidates": [
                {"finishReason": "STOP", "content": {"role": "model", "parts": parts}}
            ]
        }
        response = GeminiProviderClient._parse_response(body, "gemini-3.7-flash")

    assert response.tool_calls == []
    assert response.text == "搜索后总结"
    assert response.native_blocks == parts
    assert GeminiProviderClient._replay_parts(response.thinking_blocks) == parts


async def test_gemini_unsigned_server_tool_plus_client_call_roundtrips_via_thinking_blocks():
    from quickquip.llm.provider.gemini_compat import SKIP_THOUGHT_SIGNATURE

    parts = [
        {
            "toolCall": {
                "id": "call_srv_1",
                "toolType": "GOOGLE_SEARCH_WEB",
                "args": {"queries": ["weather"]},
            }
        },
        {
            "toolResponse": {
                "id": "call_srv_1",
                "toolType": "GOOGLE_SEARCH_WEB",
            }
        },
        {
            "functionCall": {
                "id": "fc_1",
                "name": "get_identity",
                "args": {"query": "镜子"},
            }
        },
    ]
    response = GeminiProviderClient._parse_response(
        {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": parts}}]},
        "gemini-2.5-flash",
    )
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_identity"
    assert GeminiProviderClient._replay_parts(response.thinking_blocks) == parts

    client = FakeGeminiClient(_provider_config(), _text_body())
    turn2_req = _tool_call_request()
    turn2_req.builtin_search = True
    turn2_req.messages = [
        LLMConversationMessage(role="user", content="查一下"),
        LLMConversationMessage(
            role="assistant",
            content=response.text,
            tool_calls=response.tool_calls,
            thinking_blocks=response.thinking_blocks,
        ),
        LLMConversationMessage(
            role="tool",
            content="镜子信息",
            tool_call_id="fc_1",
            tool_name="get_identity",
        ),
    ]
    await client.complete(turn2_req)
    model_parts = client.last_payload["contents"][1]["parts"]
    assert model_parts[0] == parts[0]
    assert model_parts[1] == parts[1]
    assert model_parts[2] == {
        "functionCall": {"id": "fc_1", "name": "get_identity", "args": {"query": "镜子"}},
        "thoughtSignature": SKIP_THOUGHT_SIGNATURE,
    }
