"""OpenAI Responses 协议后端：序列化 / 终态解析 / 流折叠 / 档位映射 / 接线。

契约来源：dev/plans/2026-09-14-1.16.0-theme-kickoff.md §二（PR-A）与移植源
prism-vesicle 的 request/response/stream 防御策略。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from plugins.llm_config import ProviderConfig
from plugins.llm_provider import (
    LLMImageInput,
    LLMProviderError,
    LLMRequest,
    OpenAIResponsesProviderClient,
    build_provider_client,
)
from plugins.llm_tools import LLMConversationMessage, LLMToolCall, LLMToolSpec

from quickquip.llm.config import load_llm_config
from quickquip.llm.provider.openai_responses.profiles import (
    PROFILES,
    REASONING_EFFORT_TIERS,
    resolve_profile,
)
from quickquip.llm.provider.openai_responses.request import (
    build_responses_payload,
    reasoning_control,
    serialize_input_items,
)
from quickquip.llm.provider.openai_responses.response import parse_responses_body
from quickquip.llm.provider.openai_responses.stream import fold_stream_events
from quickquip.llm.token_estimate import estimate_native_block_tokens
from tests.fixtures.provider_fakes import FakeOpenAIResponsesClient
from tests.fixtures.stream_chunks import (
    RESPONSES_RELAY_TOOL_CHUNKS,
    RESPONSES_TEXT_CHUNKS,
    RESPONSES_TOOL_CHUNKS,
)


def _config(**overrides) -> ProviderConfig:
    kwargs = dict(
        id="fake",
        protocol="openai_responses",
        base_url="https://example.test/v1",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-test",
        models=["gpt-test"],
    )
    kwargs.update(overrides)
    return ProviderConfig(**kwargs)


def _request(messages: list[LLMConversationMessage], **overrides) -> LLMRequest:
    kwargs = dict(
        model="gpt-test",
        system_prompt="系统提示",
        messages=messages,
        temperature=0.2,
        max_output_tokens=128,
    )
    kwargs.update(overrides)
    return LLMRequest(**kwargs)


def _payload(request: LLMRequest, config: ProviderConfig | None = None) -> dict:
    images: list[list] = [[] for _ in request.messages]
    return build_responses_payload(
        request, config or _config(), stream=False, prepared_images=images
    )


def _tool_spec() -> LLMToolSpec:
    return LLMToolSpec(
        name="get_identity",
        description="身份查询",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )


_NATIVE_TOOL_ITEMS = [
    {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "需要先查询身份。"}],
        "encrypted_content": "gAAAAABoGogL0EiS",
    },
    {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "get_identity",
        "arguments": '{"query":"哈基镜"}',
    },
]


# ── 请求形状 ───────────────────────────────────────────────────────────────


def test_payload_store_false_include_and_instructions():
    payload = _payload(_request([LLMConversationMessage(role="user", content="hi")]))
    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["instructions"] == "系统提示"
    assert payload["input"] == [{"role": "user", "content": "hi"}]
    assert payload["stream"] is False
    assert payload["service_tier"] == "auto"  # openai-public 默认
    assert "reasoning" not in payload  # 未配置档位不发送
    assert "tools" not in payload
    assert "previous_response_id" not in payload


def test_payload_relay_profile_omits_service_tier():
    payload = _payload(
        _request([LLMConversationMessage(role="user", content="hi")]),
        _config(responses_profile="codex-http-relay"),
    )
    assert "service_tier" not in payload


def test_payload_tools_declaration():
    payload = _payload(
        _request(
            [LLMConversationMessage(role="user", content="查一下")],
            tools=[_tool_spec()],
            allow_tool_calls=True,
        )
    )
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "get_identity",
            "description": "身份查询",
            "parameters": _tool_spec().input_schema,
        }
    ]
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True


# ── reasoning 档位映射 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tier", "expected_effort"),
    [
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "xhigh"),  # 超支持降档
        ("ultra", "xhigh"),  # 超支持降档
    ],
)
def test_reasoning_effort_mapping(tier, expected_effort):
    control = reasoning_control(
        _config(reasoning_effort=tier), resolve_profile("openai-public")
    )
    assert control == {"effort": expected_effort, "summary": "auto"}
    payload = _payload(
        _request([LLMConversationMessage(role="user", content="hi")]),
        _config(reasoning_effort=tier),
    )
    assert payload["reasoning"] == control


def test_reasoning_effort_invalid_tier_fail_closed():
    with pytest.raises(LLMProviderError):
        reasoning_control(
            _config(reasoning_effort="extreme"), resolve_profile("openai-public")
        )


def test_unknown_profile_fail_closed():
    with pytest.raises(LLMProviderError):
        _payload(
            _request([LLMConversationMessage(role="user", content="hi")]),
            _config(responses_profile="mimo-subset"),
        )


# ── input items 序列化与 call_id 记账 ──────────────────────────────────────


def test_portable_assistant_projects_function_call_items():
    messages = [
        LLMConversationMessage(role="user", content="查一下"),
        LLMConversationMessage(
            role="assistant",
            content="我先查。",
            tool_calls=[
                LLMToolCall(id="call_1", name="get_identity", arguments_json='{"query":"x"}')
            ],
        ),
        LLMConversationMessage(
            role="tool", content="镜子", tool_call_id="call_1", tool_name="get_identity"
        ),
    ]
    items = serialize_input_items(messages, [[] for _ in messages], provider_id="fake")
    assert items == [
        {"role": "user", "content": "查一下"},
        {"role": "assistant", "content": "我先查。"},
        {"type": "function_call", "call_id": "call_1", "name": "get_identity",
         "arguments": '{"query":"x"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "镜子"},
    ]


def test_native_items_replayed_verbatim_once():
    """当前循环 assistant 原生批次：原顺序回放（含密文），通用字段不二次投影。"""
    native = [dict(item) for item in _NATIVE_TOOL_ITEMS]
    messages = [
        LLMConversationMessage(role="user", content="查一下"),
        LLMConversationMessage(
            role="assistant",
            content="",
            tool_calls=[
                LLMToolCall(id="call_1", name="get_identity", arguments_json='{"query":"x"}')
            ],
            native_content=native,
        ),
        LLMConversationMessage(
            role="tool", content="镜子", tool_call_id="call_1", tool_name="get_identity"
        ),
    ]
    items = serialize_input_items(messages, [[] for _ in messages], provider_id="fake")
    assert items == [
        {"role": "user", "content": "查一下"},
        *_NATIVE_TOOL_ITEMS,
        {"type": "function_call_output", "call_id": "call_1", "output": "镜子"},
    ]
    # 回放是深拷贝：后续修改原生批次不影响已序列化结果
    assert items[1] is not native[0]


@pytest.mark.parametrize(
    ("messages", "detail"),
    [
        # 未声明先输出
        (
            [
                LLMConversationMessage(
                    role="tool", content="x", tool_call_id="call_missing",
                    tool_name="t",
                )
            ],
            "没有前置声明",
        ),
        # 重复应答
        (
            [
                LLMConversationMessage(
                    role="assistant",
                    tool_calls=[LLMToolCall(id="call_1", name="t", arguments_json="{}")],
                ),
                LLMConversationMessage(
                    role="tool", content="x", tool_call_id="call_1", tool_name="t"
                ),
                LLMConversationMessage(
                    role="tool", content="y", tool_call_id="call_1", tool_name="t"
                ),
            ],
            "重复应答",
        ),
        # 声明无应答
        (
            [
                LLMConversationMessage(
                    role="assistant",
                    tool_calls=[LLMToolCall(id="call_1", name="t", arguments_json="{}")],
                ),
                LLMConversationMessage(
                    role="tool", content="x", tool_call_id="call_1", tool_name="t"
                ),
                LLMConversationMessage(
                    role="assistant",
                    tool_calls=[LLMToolCall(id="call_2", name="t", arguments_json="{}")],
                ),
            ],
            "没有对应结果",
        ),
    ],
)
def test_call_id_accounting_fail_closed(messages, detail):
    with pytest.raises(LLMProviderError, match=detail):
        serialize_input_items(messages, [[] for _ in messages], provider_id="fake")


def test_duplicate_declaration_fail_closed():
    messages = [
        LLMConversationMessage(
            role="assistant",
            tool_calls=[
                LLMToolCall(id="call_1", name="t", arguments_json="{}"),
                LLMToolCall(id="call_1", name="t", arguments_json="{}"),
            ],
        ),
    ]
    with pytest.raises(LLMProviderError, match="重复声明"):
        serialize_input_items(messages, [[] for _ in messages], provider_id="fake")


def test_tool_images_flushed_after_complete_batch():
    """工具产出图片不能挂 function_call_output：完整批次后合成 user 消息。"""
    messages = [
        LLMConversationMessage(role="user", content="画一张"),
        LLMConversationMessage(
            role="assistant",
            tool_calls=[LLMToolCall(id="call_1", name="draw", arguments_json="{}")],
        ),
        LLMConversationMessage(
            role="tool", content="已生成", tool_call_id="call_1", tool_name="draw"
        ),
        LLMConversationMessage(role="user", content="再画一张"),
    ]
    images = [
        [],
        [],
        [LLMImageInput(
            source_url="tool://1", media_type="image/png", data_base64="AAAA"
        )],
        [],
    ]
    items = serialize_input_items(messages, images, provider_id="fake")
    flush = items[-2]
    assert flush["role"] == "user"
    assert flush["content"][0]["type"] == "input_image"
    assert flush["content"][0]["image_url"] == "data:image/png;base64,AAAA"
    assert flush["content"][1] == {
        "type": "input_text",
        "text": "以下图片来自刚才工具调用，仅用于继续推理。",
    }
    assert items[-1] == {"role": "user", "content": "再画一张"}


# ── 终态解析 ───────────────────────────────────────────────────────────────


def _completed_body(output: list[dict], **extra) -> dict:
    body = {
        "id": "resp_1",
        "model": "gpt-test",
        "status": "completed",
        "output": output,
        "usage": {
            "input_tokens": 300,
            "output_tokens": 40,
            "input_tokens_details": {"cached_tokens": 250},
            "output_tokens_details": {"reasoning_tokens": 15},
        },
    }
    body.update(extra)
    return body


def test_parse_body_happy_path_with_reasoning_and_tool_call():
    body = _completed_body(_NATIVE_TOOL_ITEMS)
    response = parse_responses_body(body, provider_id="fake", fallback_model="gpt-test")
    assert response.text == ""
    assert response.finish_reason == "completed"
    assert [(c.id, c.name) for c in response.tool_calls] == [("call_1", "get_identity")]
    assert response.thinking_blocks == [
        {"type": "reasoning", "reasoning_content": "需要先查询身份。"}
    ]
    assert response.native_blocks == _NATIVE_TOOL_ITEMS
    assert response.input_tokens == 300
    assert response.output_tokens == 40
    assert response.cache_read_tokens == 250
    assert response.thinking_tokens == 15


def test_parse_body_message_text_and_refusal():
    body = _completed_body(
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "回答"}],
            }
        ]
    )
    response = parse_responses_body(body, provider_id="fake", fallback_model="gpt-test")
    assert response.text == "回答"
    assert response.tool_calls == []


def test_parse_body_requires_completion():
    with pytest.raises(LLMProviderError):
        parse_responses_body(
            _completed_body([], status="failed", error={"message": "boom"}),
            provider_id="fake",
            fallback_model="gpt-test",
        )


@pytest.mark.parametrize(
    "output",
    [
        [{"type": "web_search_call", "id": "ws_1", "status": "completed"}],  # 未启用工具族
        [{"type": "message", "role": "user", "content": []}],  # 非 assistant
        [{"type": "function_call", "call_id": "", "name": "t", "arguments": "{}"}],
        [
            {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}"},
            {"type": "function_call", "call_id": "c1", "name": "t", "arguments": "{}"},
        ],
        [],  # 无正文无调用
    ],
)
def test_parse_body_fail_closed_on_bad_items(output):
    with pytest.raises(LLMProviderError):
        parse_responses_body(
            _completed_body(output), provider_id="fake", fallback_model="gpt-test"
        )


# ── 流折叠 ────────────────────────────────────────────────────────────────


def _fold(chunks, profile_id="openai-public"):
    return fold_stream_events(
        chunks,
        provider_id="fake",
        fallback_model="gpt-test",
        profile=resolve_profile(profile_id),
    )


def test_stream_fold_text_chunks():
    response = _fold(RESPONSES_TEXT_CHUNKS)
    assert response.text == "你好，世界"
    assert response.input_tokens == 300
    assert response.cache_read_tokens == 250
    assert response.thinking_tokens == 15


def test_stream_fold_tool_round_cross_validated():
    response = _fold(RESPONSES_TOOL_CHUNKS)
    assert [(c.id, c.name) for c in response.tool_calls] == [
        ("call_1", "get_identity"),
        ("call_2", "search_web"),
    ]
    assert response.native_blocks[0]["encrypted_content"] == "gAAAAABoGogL0EiS"
    assert response.thinking_blocks[0]["reasoning_content"] == "需要先查询身份。"


def test_stream_fold_relay_reconciliation():
    response = _fold(RESPONSES_RELAY_TOOL_CHUNKS, profile_id="codex-http-relay")
    # 终态缺省可选字段：以流式完整 item 为准（summary: [] 保留）
    assert response.native_blocks[0] == {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [],
        "encrypted_content": "gAAAAABrelay",
    }
    assert response.tool_calls[0].id == "call_1"


def test_stream_relay_events_rejected_on_public_profile():
    with pytest.raises(LLMProviderError, match="未知"):
        _fold(RESPONSES_RELAY_TOOL_CHUNKS, profile_id="openai-public")


def test_stream_sequence_jump_fail_closed():
    chunks = [dict(e) for e in RESPONSES_TEXT_CHUNKS]
    del chunks[2]  # 制造序号跳变
    with pytest.raises(LLMProviderError, match="序号"):
        _fold(chunks)


def test_stream_event_after_terminal_fail_closed():
    chunks = [
        *RESPONSES_TEXT_CHUNKS,
        {"type": "response.in_progress"},
    ]
    with pytest.raises(LLMProviderError, match="终态事件后"):
        _fold(chunks)


def test_stream_unknown_event_fail_closed():
    chunks = [
        {"type": "response.created"},
        {"type": "response.future_shiny_event"},
    ]
    with pytest.raises(LLMProviderError, match="未知"):
        _fold(chunks)


def test_stream_missing_terminal():
    with pytest.raises(LLMProviderError, match="response.completed 前"):
        _fold([{"type": "response.created"}, {"type": "response.in_progress"}])


def test_stream_terminal_text_mismatch():
    chunks = [dict(e) for e in RESPONSES_TEXT_CHUNKS]
    for chunk in chunks:
        if chunk.get("type") == "response.output_text.delta":
            chunk["delta"] = "被篡改的"
    with pytest.raises(LLMProviderError, match="正文"):
        _fold(chunks)


def test_stream_terminal_arguments_mismatch():
    chunks = [dict(e) for e in RESPONSES_TOOL_CHUNKS]
    for chunk in chunks:
        if chunk.get("type") == "response.function_call_arguments.delta":
            chunk["delta"] = '{"tampered":1}'
    with pytest.raises(LLMProviderError, match="arguments"):
        _fold(chunks)


def test_stream_failed_event_fatal_code_not_retryable():
    chunks = [
        {
            "type": "response.failed",
            "response": {"error": {"code": "insufficient_quota", "message": "quota"}},
        }
    ]
    with pytest.raises(LLMProviderError) as excinfo:
        _fold(chunks)
    assert excinfo.value.status_code == 400  # 不可重试


def test_stream_failed_event_server_error_retryable():
    chunks = [
        {
            "type": "response.failed",
            "response": {"error": {"code": "server_error", "message": "boom"}},
        }
    ]
    with pytest.raises(LLMProviderError) as excinfo:
        _fold(chunks)
    assert excinfo.value.status_code == 500  # 基座 _is_retryable 判可重试


def test_stream_incomplete_event():
    chunks = [
        {
            "type": "response.incomplete",
            "response": {"incomplete_details": {"reason": "max_output_tokens"}},
        }
    ]
    with pytest.raises(LLMProviderError, match="max_output_tokens"):
        _fold(chunks)


def test_stream_error_event():
    chunks = [{"type": "error", "error": {"code": "EIO", "message": "断流"}}]
    with pytest.raises(LLMProviderError, match="断流"):
        _fold(chunks)


# ── client 编排 ────────────────────────────────────────────────────────────


async def test_client_non_stream_round_trip():
    body = _completed_body(
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "回答"}],
            }
        ]
    )
    client = FakeOpenAIResponsesClient(_config(), [body])
    response = await client.complete(
        _request([LLMConversationMessage(role="user", content="hi")])
    )
    assert response.text == "回答"
    assert response.owner is not None
    assert client.payloads[0]["store"] is False
    assert client.payloads[0]["stream"] is False


async def test_client_stream_round_trip():
    """流式主路径：payload 带 stream:true，折叠结果与终态一致。"""

    class _StreamFake(FakeOpenAIResponsesClient):
        def __init__(self, config, chunks):
            super().__init__(config, [])
            self.config.stream_enabled = True
            self.stream_chunks = chunks
            self.stream_calls: list[tuple[str, dict]] = []

        async def _post_stream_sse(self, url, headers, payload):
            self.stream_calls.append((url, payload))
            return list(self.stream_chunks)

    client = _StreamFake(_config(), RESPONSES_TOOL_CHUNKS)
    response = await client.complete(
        _request([LLMConversationMessage(role="user", content="hi")])
    )
    assert [c.id for c in response.tool_calls] == ["call_1", "call_2"]
    url, payload = client.stream_calls[0]
    assert url == "https://example.test/v1/responses"
    assert payload["stream"] is True


def test_factory_builds_responses_client():
    client = build_provider_client(_config())
    assert isinstance(client, OpenAIResponsesProviderClient)


# ── 配置面与词表同步 ───────────────────────────────────────────────────────


def test_profiles_registry_matches_config_vocabulary():
    """config.py 校验词表（不能 import provider 包避免环）与注册表同步守护。"""
    assert set(PROFILES) == {"openai-public", "codex-http-relay"}
    assert REASONING_EFFORT_TIERS == (
        "low", "medium", "high", "xhigh", "max", "ultra",
    )


def _load_config(tmp_path: Path, provider_body: str):
    body = f"""
    [runtime]
    enabled = true
    default_provider = "rp"

    [[providers]]
    {provider_body}

    [[personas]]
    id = "p1"
    display_name = "P1"
    system_prompt = "hello"
    """
    path = tmp_path / "llm.toml"
    path.write_text(textwrap.dedent(body).strip(), encoding="utf-8")
    return load_llm_config(path)


def test_config_accepts_responses_provider(tmp_path: Path):
    loaded = _load_config(
        tmp_path,
        """
        id = "rp"
        protocol = "openai_responses"
        base_url = "https://api.example.test/v1"
        api_key_env = "RP_KEY"
        default_model = "gpt-5.2"
        models = ["gpt-5.2"]
        reasoning_effort = "high"
        """,
    )
    provider = loaded.providers["rp"]
    assert provider.protocol == "openai_responses"
    assert provider.responses_profile == "openai-public"  # 缺省
    assert provider.reasoning_effort == "high"


@pytest.mark.parametrize(
    "extra",
    [
        'responses_profile = "mimo-subset"',
        'reasoning_effort = "extreme"',
    ],
)
def test_config_prunes_invalid_responses_keys(tmp_path: Path, extra):
    loaded = _load_config(
        tmp_path,
        f"""
        id = "rp"
        protocol = "openai_responses"
        base_url = "https://api.example.test/v1"
        api_key_env = "RP_KEY"
        default_model = "gpt-5.2"
        models = ["gpt-5.2"]
        {extra}
        """,
    )
    assert "rp" not in loaded.providers
    assert loaded.load_error


# ── 预算口径 ───────────────────────────────────────────────────────────────


def test_encrypted_content_flat_token_estimate():
    """密文字节不折算 token：字段按固定档预留，长度翻倍估算不变。"""
    small = {
        "type": "reasoning",
        "id": "rs_1",
        "encrypted_content": "A" * 100,
    }
    big = {
        "type": "reasoning",
        "id": "rs_1",
        "encrypted_content": "A" * 100_000,
    }
    assert estimate_native_block_tokens(small) == estimate_native_block_tokens(big)


def test_native_items_enter_request_budget_estimate():
    """循环内原生 items 经 native_content 计入请求预算（request_budget 通用路径）。"""
    from quickquip.llm.request_budget import estimate_request_tokens

    base = _request(
        [
            LLMConversationMessage(role="user", content="hi"),
            LLMConversationMessage(
                role="assistant",
                native_content=[dict(item) for item in _NATIVE_TOOL_ITEMS],
            ),
        ]
    )
    without_native = _request(
        [
            LLMConversationMessage(role="user", content="hi"),
            LLMConversationMessage(role="assistant", content=""),
        ]
    )
    delta = estimate_request_tokens(base) - estimate_request_tokens(without_native)
    # reasoning 密文固定档 + function_call 参数字符估算都计入
    assert delta >= 2048


def test_zero_impact_existing_protocols_unchanged():
    """不配置新 protocol 时既有协议行为不变：factory 分支与序列化互不干扰。"""
    for protocol, client_name in (
        ("openai", "OpenAIProviderClient"),
        ("claude", "ClaudeProviderClient"),
        ("gemini", "GeminiProviderClient"),
    ):
        client = build_provider_client(
            _config(protocol=protocol, base_url="https://example.test/v1")
        )
        assert type(client).__name__ == client_name


def test_response_owner_endpoint_branch():
    from quickquip.llm.provider.owner import primary_endpoint_url

    assert (
        primary_endpoint_url(_config(), "gpt-test")
        == "https://example.test/v1/responses"
    )
