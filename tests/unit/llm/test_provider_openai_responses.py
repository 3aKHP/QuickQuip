"""OpenAI Responses 协议后端：序列化 / 终态解析 / 流折叠 / 档位映射 / 接线。

契约来源：1.16.0 主题 PR-A（ROADMAP「OpenAI Responses 协议后端」条目）；
模块级 docstring 与 docs/dev/llm-module.md 的 provider 节为公开契约面。
"""
from __future__ import annotations

import base64
from copy import deepcopy
import json
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
from quickquip.llm.provider.base import TOOL_IMAGE_FLUSH_NOTICE
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
from quickquip.llm.token_estimate import NATIVE_ENCRYPTED_FLAT_TOKENS, estimate_native_block_tokens
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
        ("max", "xhigh"),  # 超出官方已核对词表，降档到最高支持档
        ("ultra", "xhigh"),  # 超出官方已核对词表，降档到最高支持档
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
    assert flush["content"][1]["type"] == "input_text"
    assert flush["content"][1]["text"] == TOOL_IMAGE_FLUSH_NOTICE
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


def test_stream_incomplete_event_folds_to_length_finish():
    """流式 incomplete 终态照常折叠：max_output_tokens 归一 length。"""
    chunks = [
        {
            "type": "response.output_text.delta",
            "sequence_number": 0,
            "delta": "截断前的一半",
        },
        {
            "type": "response.incomplete",
            "sequence_number": 1,
            "response": {
                "id": "resp_4",
                "model": "gpt-test",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "截断前的一半"}
                        ],
                    }
                ],
            },
        },
    ]
    response = _fold(chunks)
    assert response.finish_reason == "length"
    assert response.text == "截断前的一半"


def test_stream_sequence_relaxed_after_unnumbered_event():
    """中转剥除个别事件序号后退化为单调校验：缺口放行、回跳仍 fail-closed。"""
    terminal = RESPONSES_TEXT_CHUNKS[-1]["response"]
    gap_chunks = [
        {"type": "response.created", "sequence_number": 0},
        {"type": "codex.rate_limits"},  # 剥除序号（占了一个全局序号位）
        {"type": "response.in_progress", "sequence_number": 2},  # 缺口 1
        {"type": "response.output_text.delta", "sequence_number": 3, "delta": "你好"},
        {"type": "response.output_text.delta", "sequence_number": 4, "delta": "，世界"},
        {"type": "response.completed", "sequence_number": 5, "response": terminal},
    ]
    response = _fold(gap_chunks, profile_id="codex-http-relay")
    assert response.text == "你好，世界"

    backward = [
        {"type": "response.created", "sequence_number": 0},
        {"type": "codex.rate_limits"},
        {"type": "response.in_progress", "sequence_number": 0},  # 回跳
    ]
    with pytest.raises(LLMProviderError, match="回跳"):
        _fold(backward, profile_id="codex-http-relay")


def test_stream_error_event_fatal_code_not_retryable():
    """error 事件携带致命码（与 response.failed 共用判据）直接终态拒绝。"""
    chunks = [
        {
            "type": "error",
            "error": {"code": "insufficient_quota", "message": "quota"},
        }
    ]
    with pytest.raises(LLMProviderError) as excinfo:
        _fold(chunks)
    assert excinfo.value.status_code == 400
    assert excinfo.value.transport is False


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
    """profiles 注册表/档位词表与 config 单源常量双向同步（防词表漂移剪错 provider）。"""
    from quickquip.llm.config import (
        REASONING_EFFORT_CHOICES,
        RESPONSES_PROFILE_IDS,
    )

    assert set(PROFILES) == set(RESPONSES_PROFILE_IDS)
    assert REASONING_EFFORT_TIERS == REASONING_EFFORT_CHOICES
    # profile 词表必须是六档的子集（降档规则以词表为边界派生）
    for profile in PROFILES.values():
        assert profile.wire_efforts <= set(REASONING_EFFORT_TIERS)
        assert profile.wire_efforts


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
    assert delta >= NATIVE_ENCRYPTED_FLAT_TOKENS


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


# ── Deep-CR 补充用例 ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        _completed_body([], status="failed", error="boom"),  # error 非对象
        _completed_body(
            [],
            status="cancelled",
            incomplete_details="max_output_tokens",  # 非 incomplete 状态不宽限
        ),
    ],
)
def test_parse_body_non_dict_failure_fields_fail_closed(body):
    """failed/cancelled 状态的非 dict 失败字段按 LLMProviderError 终止
    （不得 AttributeError 逃逸成 complete() 的非流式 fallback）。"""
    with pytest.raises(LLMProviderError):
        parse_responses_body(body, provider_id="fake", fallback_model="gpt-test")


def test_parse_body_incomplete_max_output_tokens_normalized_to_length():
    """incomplete 是正常截断：max_output_tokens 归一为兄弟协议的 length
    终值照常返回（可空正文——截断可能发生在可见输出之前）。"""
    body = _completed_body(
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "截断前的一半"}],
            }
        ],
        status="incomplete",
        incomplete_details={"reason": "max_output_tokens"},
    )
    response = parse_responses_body(body, provider_id="fake", fallback_model="m")
    assert response.finish_reason == "length"
    assert response.text == "截断前的一半"

    empty = _completed_body(
        [{"type": "reasoning", "id": "rs_1", "encrypted_content": "x"}],
        status="incomplete",
        incomplete_details={"reason": "max_output_tokens"},
    )
    assert parse_responses_body(empty, provider_id="fake", fallback_model="m").text == ""


def test_parse_body_incomplete_other_reasons_pass_through():
    body = _completed_body(
        [],
        status="incomplete",
        incomplete_details={"reason": "content_filter"},
    )
    response = parse_responses_body(body, provider_id="fake", fallback_model="m")
    assert response.finish_reason == "content_filter"


@pytest.mark.parametrize(
    "event",
    [
        {"type": "response.failed", "response": "boom"},
        {"type": "response.incomplete", "response": 42},
        {"type": "error", "error": "oops"},
    ],
)
def test_stream_non_dict_failure_payloads_fail_closed(event):
    """失败事件的载荷形状先守卫：畸形载荷以 LLMProviderError 终止。"""
    with pytest.raises(LLMProviderError):
        _fold([event])


def test_stream_failed_without_error_object_not_retryable():
    """无 error 对象的 failed 是终态失败（对齐移植源），不做满额重发。"""
    with pytest.raises(LLMProviderError) as excinfo:
        _fold([{"type": "response.failed", "response": {}}])
    assert excinfo.value.status_code == 400


def test_stream_error_event_transport_retryable():
    """error 事件（中转瞬断）按传输层失败归类，交基座退避重试。"""
    with pytest.raises(LLMProviderError) as excinfo:
        _fold([{"type": "error", "error": {"code": "EIO", "message": "断流"}}])
    assert excinfo.value.transport is True


def test_stream_missing_terminal_transport_retryable():
    with pytest.raises(LLMProviderError) as excinfo:
        _fold([{"type": "response.created"}, {"type": "response.in_progress"}])
    assert excinfo.value.transport is True


def test_stream_reasoning_delta_terminal_mismatch():
    chunks = [dict(e) for e in RESPONSES_TOOL_CHUNKS]
    for chunk in chunks:
        if chunk.get("type") == "response.reasoning_summary_text.delta":
            chunk["delta"] = "被篡改的思考"
    with pytest.raises(LLMProviderError, match="reasoning"):
        _fold(chunks)


def test_stream_relay_reconcile_mismatch_fail_closed():
    """中转终态 output 与流式 done items 语义不一致（非子集）时 fail-closed。"""
    chunks = deepcopy(RESPONSES_RELAY_TOOL_CHUNKS)
    # 终态把 function_call 的 arguments 改成不同值：非子集关系
    chunks[-1]["response"]["output"][-1]["arguments"] = '{"query":"tampered"}'
    with pytest.raises(LLMProviderError, match="不一致"):
        _fold(chunks, profile_id="codex-http-relay")


def test_reasoning_effort_relay_profile_identity_mapping():
    """AGW/CPA 中转的 gpt-6/gpt-5.6 系六档全支持（服务器能力位核对）：恒等不降档。"""
    for tier in ("low", "medium", "high", "xhigh", "max", "ultra"):
        control = reasoning_control(
            _config(reasoning_effort=tier), resolve_profile("codex-http-relay")
        )
        assert control == {"effort": tier, "summary": "auto"}


def test_combine_stream_trace_annotations():
    combine = OpenAIResponsesProviderClient._combine_stream_trace
    completed = [
        {"type": "response.completed", "response": {"id": "r1", "status": "completed"}}
    ]
    assert combine(completed, "m") == {"id": "r1", "status": "completed"}
    failed = [
        {
            "type": "response.failed",
            "response": {"error": {"code": "server_error", "message": "x"}},
        }
    ]
    assert combine(failed, "m")["status"] == "failed"
    assert combine(failed, "m")["error"]["code"] == "server_error"
    assert combine([{"type": "response.created"}], "m")["status"] == (
        "stream_ended_without_terminal"
    )


def test_sse_wire_format_end_to_end():
    """真实 wire 形状（event:/data: 行、无 [DONE]）从基座 SSE 解析到折叠全链。"""
    from quickquip.llm.provider.base import _parse_sse_text

    raw = "\n".join(
        f"event: {chunk['type']}\ndata: {json.dumps(chunk)}\n"
        for chunk in RESPONSES_TEXT_CHUNKS
    )
    events = _parse_sse_text(raw)
    response = _fold(events)
    assert response.text == "你好，世界"
    assert response.input_tokens == 300


def test_cross_round_call_id_reuse_fail_closed():
    """跨原生批次复用 call_id（模型/中转异常形态）按重复声明 fail-closed。"""
    messages = [
        LLMConversationMessage(
            role="assistant",
            native_content=[dict(item) for item in _NATIVE_TOOL_ITEMS],
        ),
        LLMConversationMessage(
            role="tool", content="镜子", tool_call_id="call_1", tool_name="get_identity"
        ),
        LLMConversationMessage(
            role="assistant",
            native_content=[dict(item) for item in _NATIVE_TOOL_ITEMS],
        ),
        LLMConversationMessage(
            role="tool", content="再来", tool_call_id="call_1", tool_name="get_identity"
        ),
    ]
    with pytest.raises(LLMProviderError, match="重复声明"):
        serialize_input_items(messages, [[] for _ in messages], provider_id="fake")


def test_completed_finish_reason_accepted_by_summary_policy():
    """completed 进入正常终值词表：总结族功能用 Responses provider 不误杀。"""
    from quickquip.llm.response_acceptance import classify_response

    response = parse_responses_body(
        _completed_body(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "总结正文"}],
                }
            ]
        ),
        provider_id="fake",
        fallback_model="gpt-test",
    )
    assert response.finish_reason == "completed"
    assert classify_response(response) == "accepted"


def test_wire_items_native_no_double_count():
    """native_content 消息按原生块单计（不叠加 tool_calls/thinking_blocks），
    与 estimate_request_tokens 的单计口径一致。"""
    from quickquip.llm.request_budget import count_wire_items

    native_request = _request(
        [
            LLMConversationMessage(role="user", content="hi"),
            LLMConversationMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(id="call_1", name="t", arguments_json="{}")
                ],
                thinking_blocks=[{"type": "reasoning", "reasoning_content": "x"}],
                native_content=[dict(item) for item in _NATIVE_TOOL_ITEMS],
            ),
        ]
    )
    portable_request = _request(
        [
            LLMConversationMessage(role="user", content="hi"),
            LLMConversationMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LLMToolCall(id="call_1", name="t", arguments_json="{}")
                ],
                thinking_blocks=[{"type": "reasoning", "reasoning_content": "x"}],
            ),
        ]
    )
    native_count = count_wire_items(native_request) - count_wire_items(
        _request([LLMConversationMessage(role="user", content="hi")])
    )
    portable_count = count_wire_items(portable_request) - count_wire_items(
        _request([LLMConversationMessage(role="user", content="hi")])
    )
    # 原生路径：1 条消息 + 2 个原生块；通用路径：1 条消息 + 1 call + 1 thinking
    assert native_count == 3
    assert portable_count == 3


def test_usage_metering_input_semantics_inclusive():
    """usage 落库行口径：openai_responses 标 inclusive（三处核对之一落测试）。"""
    from quickquip.llm.pricing import normalize_usage

    usage = normalize_usage("openai_responses", 300, 40, None, 250)
    assert usage.prompt == 300  # inclusive：不叠加 cache_read
    assert usage.cache_read == 250
    assert usage.fresh_input == 50


# ── 历史降级重试（PR-B：portable checkpoint 移植） ─────────────────────────


_HISTORY_NATIVE = [
    {
        "type": "reasoning",
        "id": "rs_hist",
        "summary": [{"type": "summary_text", "text": "历史思考。"}],
        "encrypted_content": "gAAA-hist-cipher",
    },
    {
        "type": "message",
        "id": "msg_hist",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "历史回答。"}],
    },
]

# 仅含 message item 的历史批次（无可剥 reasoning 的显式前提）。
_HISTORY_MESSAGE_ONLY = {
    "type": "message",
    "id": "msg_hist",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "历史回答。"}],
}

_CURRENT_LOOP_NATIVE = [
    {
        "type": "reasoning",
        "id": "rs_cur",
        "summary": [{"type": "summary_text", "text": "当前思考。"}],
        "encrypted_content": "gAAA-current-cipher",
    },
    {
        "type": "function_call",
        "id": "fc_cur",
        "call_id": "call_cur",
        "name": "get_identity",
        "arguments": '{"query":"镜子"}',
    },
]


def _history_replay_request() -> LLMRequest:
    """历史原生批次（最后 user 之前）+ 当前循环原生批次（其后）。"""
    return _request(
        [
            LLMConversationMessage(role="user", content="旧问题"),
            LLMConversationMessage(
                role="assistant", content="历史回答。", native_content=list(_HISTORY_NATIVE)
            ),
            LLMConversationMessage(role="user", content="新问题"),
            LLMConversationMessage(
                role="assistant", content="", native_content=list(_CURRENT_LOOP_NATIVE)
            ),
            LLMConversationMessage(
                role="tool", content="镜子是群友。", tool_call_id="call_cur",
                tool_name="get_identity",
            ),
        ]
    )


class _RejectingThenOkFake(FakeOpenAIResponsesClient):
    """第一次 _post_json 抛指定错误，之后回放正常响应体。"""

    def __init__(self, config, error: LLMProviderError, bodies: list[dict]):
        super().__init__(config, bodies)
        self.error = error

    async def _post_json(self, url, headers, payload):
        self.payloads.append(payload)
        if self.error is not None:
            error = self.error
            self.error = None
            raise error
        return self.response_bodies.pop(0)


_OK_BODY = _completed_body(
    [{"type": "message", "role": "assistant",
      "content": [{"type": "output_text", "text": "降级后回答"}]}]
)


async def test_client_400_history_reasoning_degrades_and_retries(caplog):
    client = _RejectingThenOkFake(
        _config(),
        LLMProviderError("HTTP 400 bad request", status_code=400, http_reject=True),
        [_OK_BODY],
    )
    with caplog.at_level("WARNING", logger="quickquip.llm.provider.openai_responses.client"):
        response = await client.complete(_history_replay_request())
    assert response.text == "降级后回答"
    assert len(client.payloads) == 2
    first_input = client.payloads[0]["input"]
    second_input = client.payloads[1]["input"]
    assert any(item.get("type") == "reasoning" for item in first_input)
    # 降级请求：历史 reasoning 剥除、历史 message 保留（工具事实/正文不丢）。
    assert not any(
        item.get("id") == "rs_hist" for item in second_input
    )
    assert any(item.get("id") == "msg_hist" for item in second_input)
    # 当前循环批次不受降级影响（协议要求原样回传）。
    assert {
        item.get("id") for item in second_input if item.get("type") == "reasoning"
    } == {"rs_cur"}
    assert any(item.get("call_id") == "call_cur" for item in second_input)


async def test_client_400_without_history_reasoning_surfaces():
    client = _RejectingThenOkFake(
        _config(),
        LLMProviderError("HTTP 400 bad request", status_code=400, http_reject=True),
        [_OK_BODY],
    )
    plain = _request(
        [
            LLMConversationMessage(role="user", content="问题"),
            LLMConversationMessage(
                role="assistant", content="历史回答。",
                native_content=[dict(_HISTORY_MESSAGE_ONLY)],
            ),
            LLMConversationMessage(role="user", content="新问题"),
        ]
    )
    with pytest.raises(LLMProviderError):
        await client.complete(plain)
    # 无历史密文可剥：不重试。
    assert len(client.payloads) == 1


async def test_client_non_400_error_not_degrade_retried():
    client = _RejectingThenOkFake(
        _config(), LLMProviderError("HTTP 403 forbidden", status_code=403), [_OK_BODY]
    )
    with pytest.raises(LLMProviderError):
        await client.complete(_history_replay_request())
    assert len(client.payloads) == 1


async def test_client_degrade_retry_second_failure_surfaces():
    class _Always400Fake(FakeOpenAIResponsesClient):
        async def _post_json(self, url, headers, payload):
            self.payloads.append(payload)
            raise LLMProviderError("HTTP 400 bad request", status_code=400, http_reject=True)

    client = _Always400Fake(_config(), [])
    with pytest.raises(LLMProviderError):
        await client.complete(_history_replay_request())
    assert len(client.payloads) == 2


async def test_client_protocol_level_400_not_degrade_retried():
    """协议层归一的 400（failed/cancelled 终态、流致命码）不触发降级重试：
    该类失败与请求历史形状无关，重试只会加倍成本与延迟。"""
    client = _RejectingThenOkFake(
        _config(),
        LLMProviderError("Provider 响应未完成：cyber_policy", status_code=400),
        [_OK_BODY],
    )
    with pytest.raises(LLMProviderError):
        await client.complete(_history_replay_request())
    assert len(client.payloads) == 1


async def test_client_transport_error_not_degrade_retried():
    from quickquip.llm.provider.retry import RetryPolicy

    class _TransportFake(FakeOpenAIResponsesClient):
        def __init__(self, config):
            super().__init__(config, [])
            self.retry_policy = RetryPolicy(max_attempts=1)

        async def _post_json(self, url, headers, payload):
            self.payloads.append(payload)
            raise LLMProviderError("网络错误：断连", transport=True)

    client = _TransportFake(_config())
    with pytest.raises(LLMProviderError):
        await client.complete(_history_replay_request())
    # 传输错误走基座退避轨道，不触发降级重试。
    assert len(client.payloads) == 1


async def test_client_degrade_pure_reasoning_batch_gets_placeholder():
    """纯 reasoning 历史批次剥空后退通用表达并补占位（空 content item
    部分端点会拒）。"""
    client = _RejectingThenOkFake(
        _config(), LLMProviderError("HTTP 400 x", status_code=400, http_reject=True),
        [_OK_BODY],
    )
    request = _request(
        [
            LLMConversationMessage(role="user", content="旧问题"),
            LLMConversationMessage(
                role="assistant", content="", native_content=[
                    dict(_HISTORY_NATIVE[0]),
                ],
            ),
            LLMConversationMessage(role="user", content="新问题"),
        ]
    )
    await client.complete(request)
    second = client.payloads[1]["input"]
    assert not any(item.get("type") == "reasoning" for item in second)
    degraded = [item for item in second if item.get("role") == "assistant"]
    assert any(
        isinstance(item.get("content"), str) and item["content"].strip()
        for item in degraded
    ), "剥空批次必须有非空占位正文"


async def test_client_degrade_retry_metering_two_rows(monkeypatch):
    """降级重试的计量口径（有意为之）：两次 complete() 各落一行 usage
    （error + ok）——对应两次真实 HTTP 交互与两条 trace；与基座退避轨道
    "被吸收的失败不产生额外行"（test_provider_retry）是两条不同契约。"""
    from quickquip.llm.usage import drain_usage_tasks

    calls = []

    async def spy(
        client, request, response, started, stream_used, state,
        error_msg="", finished_at=None,
    ):
        calls.append((state, response is not None))

    monkeypatch.setattr("quickquip.llm.usage._record_usage", spy)
    client = _RejectingThenOkFake(
        _config(),
        LLMProviderError("HTTP 400 bad request", status_code=400, http_reject=True),
        [_OK_BODY],
    )
    await client.complete(_history_replay_request())
    await drain_usage_tasks()
    assert calls == [("error", False), ("ok", True)]


async def test_client_stream_400_history_reasoning_degrades_and_retries():
    """流式主路径（生产默认）的降级重试：SSE 传输抛 HTTP 400 后剥历史
    reasoning 重试一次，非流式端点不被触碰。"""

    class _StreamRejectingThenOkFake(FakeOpenAIResponsesClient):
        def __init__(self, config, error, bodies):
            super().__init__(config, bodies)
            self.config.stream_enabled = True
            self.error = error
            self.stream_payloads: list[dict] = []

        async def _post_stream_sse(self, url, headers, payload):
            self.stream_payloads.append(payload)
            if self.error is not None:
                error = self.error
                self.error = None
                raise error
            # 复用非流式成功体构造流事件序列。
            body = self.response_bodies.pop(0)
            return [{"type": "response.completed", "response": body}]

    client = _StreamRejectingThenOkFake(
        _config(),
        LLMProviderError("HTTP 400 bad request", status_code=400, http_reject=True),
        [_OK_BODY],
    )
    response = await client.complete(_history_replay_request())
    assert response.text == "降级后回答"
    assert len(client.stream_payloads) == 2
    assert not client.payloads, "非流式端点不被触碰"
    second = client.stream_payloads[1]["input"]
    assert not any(item.get("id") == "rs_hist" for item in second)
    assert any(item.get("id") == "rs_cur" for item in second)


# ── 内置 image_generation 条目（服务端注入工具） ──────────────────────────

_PNG_BASE64 = base64.b64encode(b"\x89PNG-fake-bytes").decode()

_IMAGE_CALL_ITEM = {
    "type": "image_generation_call",
    "id": "ig_1",
    "status": "completed",
    "size": "1024x1024",
    "output_format": "png",
    "result": _PNG_BASE64,
}

_TEXT_ITEM = {
    "type": "message",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "画好了！", "annotations": []}],
}


def test_parse_body_extracts_image_generation_call():
    response = parse_responses_body(
        _completed_body([dict(_IMAGE_CALL_ITEM), dict(_TEXT_ITEM)]),
        provider_id="fake",
        fallback_model="gpt-test",
    )
    assert response.text == "画好了！"
    assert len(response.generated_images) == 1
    image = response.generated_images[0]
    assert image.data == b"\x89PNG-fake-bytes"
    assert image.media_type == "image/png"
    assert image.source == "responses.image_generation"
    # 图片条目剥除出原生回放批次：base64 不进 native_blocks
    assert [item["type"] for item in (response.native_blocks or [])] == ["message"]


def test_parse_body_image_generation_bad_payload_stripped_silently():
    output = [
        {"type": "image_generation_call", "id": "ig_1", "status": "failed", "result": "%%%"},
        dict(_TEXT_ITEM),
    ]
    response = parse_responses_body(
        _completed_body(output), provider_id="fake", fallback_model="gpt-test"
    )
    assert response.generated_images == []
    assert response.text == "画好了！"
    assert [item["type"] for item in (response.native_blocks or [])] == ["message"]


def test_parse_body_image_only_response_not_malformed():
    response = parse_responses_body(
        _completed_body([dict(_IMAGE_CALL_ITEM)]),
        provider_id="fake",
        fallback_model="gpt-test",
    )
    assert response.text == ""
    assert len(response.generated_images) == 1


def test_stream_fold_with_builtin_image_generation_events():
    terminal = _completed_body(
        [dict(_IMAGE_CALL_ITEM), dict(_TEXT_ITEM)], id="resp_ig"
    )
    chunks = [
        {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_ig"}},
        {"type": "response.in_progress", "sequence_number": 1},
        {"type": "response.output_item.added", "sequence_number": 2, "output_index": 0},
        {
            "type": "response.image_generation_call.in_progress",
            "sequence_number": 3,
            "output_index": 0,
            "item_id": "ig_1",
        },
        {
            "type": "response.image_generation_call.generating",
            "sequence_number": 4,
            "output_index": 0,
            "item_id": "ig_1",
        },
        {
            "type": "response.image_generation_call.completed",
            "sequence_number": 5,
            "output_index": 0,
            "item_id": "ig_1",
        },
        {
            "type": "response.output_item.done",
            "sequence_number": 6,
            "output_index": 0,
            "item": dict(_IMAGE_CALL_ITEM),
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 7,
            "item_id": "msg_1",
            "output_index": 1,
            "content_index": 0,
            "delta": "画好了！",
        },
        {"type": "response.output_text.done", "sequence_number": 8, "text": "画好了！"},
        {"type": "response.completed", "sequence_number": 9, "response": terminal},
    ]
    response = _fold(chunks)
    assert response.text == "画好了！"
    assert len(response.generated_images) == 1
    assert response.generated_images[0].source == "responses.image_generation"
    assert [item["type"] for item in (response.native_blocks or [])] == ["message"]


def test_stream_relay_keepalive_events_tolerated_on_relay_profile():
    terminal = _completed_body(
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "保活也画好了", "annotations": []}
                ],
            }
        ],
        id="resp_ka",
    )
    chunks = [
        {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_ka"}},
        {"type": "response.in_progress", "sequence_number": 1},
        {"type": "keepalive", "sequence_number": 2},
        {"type": "keepalive", "sequence_number": 3},
        {
            "type": "response.output_text.delta",
            "sequence_number": 4,
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "保活也画好了",
        },
        {"type": "response.output_text.done", "sequence_number": 5, "text": "保活也画好了"},
        {"type": "response.completed", "sequence_number": 6, "response": terminal},
    ]
    response = _fold(chunks, profile_id="codex-http-relay")
    assert response.text == "保活也画好了"


def test_stream_keepalive_rejected_on_public_profile():
    chunks = [
        {"type": "response.created", "sequence_number": 0, "response": {"id": "resp_ka"}},
        {"type": "keepalive", "sequence_number": 1},
    ]
    with pytest.raises(LLMProviderError, match="未知"):
        _fold(chunks, profile_id="openai-public")
