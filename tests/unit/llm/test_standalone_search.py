"""Standalone search protocol, execution and permission boundaries."""

from unittest.mock import AsyncMock

import pytest

from quickquip.llm.config import ProviderConfig, provider_builtin_search_active
from quickquip.llm.provider.base import LLMRequest
from quickquip.llm.provider.openai_responses.client import OpenAIResponsesProviderClient
from quickquip.llm.provider.openai_responses.request import build_responses_payload
from quickquip.llm.provider.openai_responses.response import parse_responses_body
from quickquip.llm.search_policy import resolve_search_mode
from quickquip.llm.session import create_session_identity
from quickquip.llm.standalone_search import WebRun, prepare_web_run
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall, LLMToolSpec
from quickquip.search.responses_web import (
    DESCRIPTION,
    PROFILE_ID,
    command_schema,
    namespace_spec,
    read_result,
    validate_commands,
)


def provider():
    return ProviderConfig(
        id="test",
        protocol="openai_responses",
        base_url="https://example.test/v1",
        api_key_env="TEST_SEARCH_KEY",
        responses_profile=PROFILE_ID,
        default_model="test-model",
        models=["test-model"],
    )


def request():
    return LLMRequest(
        model="test-model",
        system_prompt="test",
        temperature=1,
        max_output_tokens=1000,
        messages=[],
        allow_tool_calls=True,
        builtin_search=True,
        session=create_session_identity(),
        epoch_id="epoch",
        tools=[LLMToolSpec("web_run", DESCRIPTION, command_schema())],
    )


def test_profile_routes_without_searxng_and_respects_permission():
    p = provider()
    assert provider_builtin_search_active(p)
    assert (
        resolve_search_mode(
            p,
            tools_allowed=True,
            local_search_enabled=False,
        )
        == "responses_standalone"
    )
    assert resolve_search_mode(p, tools_allowed=False, local_search_enabled=True) == "none"


def test_namespace_and_generic_history_preserve_function_pair():
    r = request()
    r.messages = [
        LLMConversationMessage(
            "assistant",
            tool_calls=[LLMToolCall("call1", "web_run", '{"time":[{"utc_offset":"+08:00"}]}')],
        ),
        LLMConversationMessage("tool", content="08:00", tool_call_id="call1"),
    ]
    body = build_responses_payload(r, provider(), stream=True, prepared_images=[[], []])
    assert body["tools"] == [namespace_spec(), {"type": "image_generation", "output_format": "png"}]
    assert body["store"] is False and "previous_response_id" not in body
    assert body["input"][0]["namespace"] == "web"
    assert body["input"][0]["name"] == "run"
    assert body["input"][1]["call_id"] == "call1"


def test_namespace_response_retains_native_identity_but_dispatches_registered_name():
    item = {
        "type": "function_call",
        "namespace": "web",
        "name": "run",
        "call_id": "call1",
        "arguments": '{"time":[{"utc_offset":"+08:00"}]}',
    }
    response = parse_responses_body(
        {"status": "completed", "output": [item]}, provider_id="test", fallback_model="test-model"
    )
    assert response.tool_calls[0].name == "web_run"
    assert response.native_blocks == [item]
    item["namespace"] = "untrusted"
    with pytest.raises(Exception, match="namespace"):
        parse_responses_body(
            {"status": "completed", "output": [item]},
            provider_id="test",
            fallback_model="test-model",
        )


@pytest.mark.parametrize(
    "commands",
    [
        {"injected": [{}]},
        {"find": [{"ref_id": "ref", "pattern": ""}]},
        {"click": [{"ref_id": "ref", "id": True}]},
        {"open": [{"ref_id": "ref", "lineno": -1}]},
        {"screenshot": [{"ref_id": "ref", "pageno": 0, "extra": "ignored"}]},
        {"search_query": []},
        {"response_length": "short"},
    ],
)
def test_invalid_nested_operations_never_reach_transport(commands):
    with pytest.raises(ValueError):
        validate_commands(commands)


@pytest.mark.parametrize("operation", ["search_query", "image_query"])
async def test_empty_domain_filter_is_a_valid_search_command(operation):
    post = AsyncMock(return_value={"output": "search material"})
    commands = {operation: [{"q": "synthetic", "domains": []}]}
    result = await WebRun(post, "session", "model", []).execute(commands)
    assert not result.is_error
    assert post.call_args.args[0]["commands"] == commands


async def test_real_search_material_is_not_replaced_by_ciphertext_and_errors_are_reported():
    post = AsyncMock(
        return_value={
            "output": "SOURCE_ID: unique-fact",
            "encrypted_output": "cipher",
            "results": [{"type": "text_result", "url": "https://example.test"}],
        }
    )
    run = WebRun(post, "session", "model", [])
    result = await run.execute({"find": [{"ref_id": "ref", "pattern": "SOURCE_ID"}]})
    assert "unique-fact" in result.content and "cipher" not in result.content
    assert result.search_metadata["mode"] == "responses_standalone"
    post.return_value = {"output": "Internal Error ()\nUnable to resolve screenshot", "results": []}
    assert (await run.execute({"screenshot": [{"ref_id": "ref", "pageno": 0}]})).is_error


async def test_operation_quota_counts_batched_operations_before_transport():
    post = AsyncMock(return_value={"output": "result"})
    run = WebRun(post, "session", "model", [], operations=63)
    result = await run.execute({"open": [{"ref_id": "a"}, {"ref_id": "b"}]})
    assert result.is_error
    post.assert_not_called()


def test_session_owner_and_epoch_are_part_of_search_identity():
    r = request()
    client = AsyncMock()
    one = prepare_web_run(provider(), r, client)
    assert one.session_id == prepare_web_run(provider(), r, client).session_id
    r.epoch_id = "new"
    assert one.session_id != prepare_web_run(provider(), r, client).session_id
    r.allow_tool_calls = False
    assert prepare_web_run(provider(), r, client) is None


async def test_overrides_cannot_inject_or_replace_namespace(monkeypatch):
    monkeypatch.setenv("TEST_SEARCH_KEY", "synthetic-test-key")
    p = provider()
    p.extra_body = {"tools": [namespace_spec()]}
    r = request()
    r.tools = []
    client = OpenAIResponsesProviderClient(p)
    with pytest.raises(Exception, match="namespace"):
        await client._build_request_parts(r)


def test_unknown_result_variants_do_not_crash_on_untrusted_titles():
    assert not read_result(
        {
            "output": "useful",
            "results": [{"title": [], "type": "new_variant"}],
        }
    )[2]


async def test_unknown_source_payload_never_enters_plaintext_history():
    post = AsyncMock(
        return_value={
            "output": "fact",
            "results": [
                {"title": "source", "unknown": {"encrypted_content": "CIPHER_SENTINEL"}},
            ],
        }
    )
    result = await WebRun(post, "session", "model", []).execute({"open": [{"ref_id": "url"}]})
    assert "CIPHER_SENTINEL" not in result.content
    assert "CIPHER_SENTINEL" not in str(result.search_metadata)


def test_mixed_results_and_parser_errors_are_not_reported_as_success():
    for output in (
        "useful\n---\nInternal Error ()\nunavailable",
        "Error parsing function call: invalid command",
    ):
        assert read_result({"output": output, "results": []})[2]


async def test_sports_normalizes_optional_backend_discriminator():
    post = AsyncMock(return_value={"output": "schedule"})
    commands = {"sports": [{"fn": "schedule", "league": "nba", "team": "GSW"}]}
    await WebRun(post, "session", "model", []).execute(commands)
    assert post.call_args.args[0]["commands"]["sports"][0]["tool"] == "sports"
    assert "tool" not in commands["sports"][0]


async def test_result_text_is_bounded_before_its_first_continuation():
    from quickquip.llm.token_estimate import estimate_tokens

    post = AsyncMock(return_value={"output": "长材料" * 1000})
    result = await WebRun(post, "session", "model", [], token_budget=100).execute(
        {"open": [{"ref_id": "url"}]},
    )
    assert estimate_tokens(result.content) <= 100
    assert result.search_metadata["truncated"]


async def test_cancelled_search_does_not_become_an_error_tool_result():
    import asyncio

    run = WebRun(AsyncMock(side_effect=asyncio.CancelledError), "session", "model", [])
    with pytest.raises(asyncio.CancelledError):
        await run.execute({"open": [{"ref_id": "url"}]})


async def test_screenshot_reference_without_media_is_an_explicit_failure():
    post = AsyncMock(return_value={"output": "PDF (https://example.test/file.pdf)\nreference"})
    result = await WebRun(post, "session", "model", []).execute(
        {"screenshot": [{"ref_id": "ref", "pageno": 0}]},
    )
    assert result.is_error and not result.images


def test_wire_model_override_changes_search_identity_and_route():
    p = provider()
    r = request()
    first = prepare_web_run(p, r, AsyncMock())
    p.extra_body = {"model": "wire-model"}
    second = prepare_web_run(p, r, AsyncMock())
    assert second.model == "wire-model" and second.session_id != first.session_id


def test_disabled_search_keeps_generic_tool_history_flat():
    r = request()
    r.allow_tool_calls = r.builtin_search = False
    r.messages = [
        LLMConversationMessage("assistant", tool_calls=[LLMToolCall("call", "web_run", "{}")]),
        LLMConversationMessage("tool", content="saved", tool_call_id="call"),
    ]
    payload = build_responses_payload(r, provider(), stream=False, prepared_images=[[], []])
    assert payload["input"][0]["name"] == "web_run"
    assert "namespace" not in payload["input"][0]
    assert "tools" not in payload


@pytest.mark.parametrize("batch_size,operations,space", [(2, 40, 100_000), (1, 1, 400)])
async def test_tool_loop_enforces_batch_quota_and_freezes_first_result(
    batch_size, operations, space
):
    import json
    import logging

    from quickquip.llm.config import RuntimeConfig
    from quickquip.llm.provider.base import LLMResponse
    from quickquip.llm.standalone_search import register_web_tool
    from quickquip.llm.tool_loop import run_tool_call_loop
    from quickquip.llm.tool_registry import ToolRegistry
    from quickquip.llm.tools import ToolExecutionContext

    registry = ToolRegistry()
    register_web_tool(registry)
    r = request()
    requests = []
    calls = [
        LLMToolCall(
            f"call{i}",
            "web_run",
            json.dumps(
                {
                    "open": [{"ref_id": "https://example.test"}] * operations,
                }
            ),
        )
        for i in range(batch_size)
    ]

    class Client:
        search_web = AsyncMock(return_value={"output": "事实材料" * 1000})

        async def complete(self, req):
            requests.append(req)
            return LLMResponse(
                text="" if len(requests) == 1 else "完成",
                model=r.model,
                tool_calls=calls if len(requests) == 1 else [],
            )

    client = Client()
    persisted = []

    class Recorder:
        def on_turn(self, response, **kwargs):
            return {call.id: call.id for call in response.tool_calls}

        async def deliver_turn(self):
            pass

        def on_tool_started(self, *args):
            pass

        def on_tool_finished(self, execution_id, result, **kwargs):
            persisted.append(result.content)

    result = await run_tool_call_loop(
        provider=provider(),
        request=r,
        context=ToolExecutionContext("scope", "user", "test", "test", r.model),
        build_provider_client=lambda config: client,
        tool_registry=registry,
        runtime_config=RuntimeConfig(),
        logger=logging.getLogger(__name__),
        search_tool_name="web_run",
        search_failsafe_max_rounds=4,
        search_failsafe_max_calls_per_round=3,
        result_space_probe=lambda req: space,
        turn_recorder=Recorder(),
    )
    assert result.text == "完成"
    continued = [m for m in requests[-1].messages if m.role == "tool"]
    assert [m.content for m in continued] == persisted
    assert {m.tool_call_id for m in continued} == {call.id for call in calls}
    if batch_size == 2:
        client.search_web.assert_not_called()
        assert all(m.is_tool_error for m in continued)
    else:
        client.search_web.assert_awaited_once()
        assert "截断" in continued[0].content and len(continued[0].content) < 1000


@pytest.mark.parametrize("no_slots,non_vision", [(True, False), (False, True)])
async def test_screenshot_success_is_finalized_after_media_processing(
    monkeypatch,
    no_slots,
    non_vision,
):
    from quickquip.llm.tool_result_pipeline import ToolResultPipeline
    from quickquip.llm.tools import LLMToolResult, ToolExecutionContext

    monkeypatch.setattr(
        "quickquip.search.media.fetch_image",
        AsyncMock(
            return_value=(b"validated-image", "image/png"),
        ),
    )
    raw = await WebRun(
        AsyncMock(
            return_value={
                "output": "PDF screenshot\nImage URL: https://images.example/page.png",
            }
        ),
        "session",
        "model",
        [],
    ).execute({"screenshot": [{"ref_id": "ref", "pageno": 0}]})
    assert not raw.is_error and raw.images
    r = request()
    if no_slots:
        r.messages = [LLMConversationMessage("user", image_urls=["existing"] * 5)]
    p = provider()
    if non_vision:
        p.non_vision_models = [r.model]
    pipeline = ToolResultPipeline(
        provider=p,
        request=r,
        context=ToolExecutionContext("scope", "user", "test", "test", r.model),
    )
    result = await pipeline.process_result(
        LLMToolCall("call", "web_run", "{}"),
        LLMToolResult(
            "call",
            "web_run",
            raw.content,
            images=raw.images,
            search_metadata=raw.search_metadata,
        ),
    )
    assert result.is_error and not result.images
    assert result.search_metadata["status"] == "failed"


async def test_service_supplies_remaining_budget_without_chat_history(monkeypatch):
    from types import SimpleNamespace
    from quickquip.llm.config import RuntimeConfig
    from quickquip.llm.service import LLMService
    from quickquip.llm.tools import ToolExecutionContext

    loop = AsyncMock()
    monkeypatch.setattr("quickquip.llm.service.run_tool_call_loop", loop)
    host = SimpleNamespace(
        config=SimpleNamespace(
            runtime=RuntimeConfig(),
            auto_search=SimpleNamespace(search_max_calls_per_round=3),
            tools=SimpleNamespace(discovery_search_limit=3, discovery_max_loaded_tools=12),
        ),
        tool_registry=None,
        image_preprocessor=None,
        _is_tool_discovery_enabled=lambda *args, **kwargs: False,
        _get_enabled_tool_names=lambda **kwargs: ["web_run"],
    )
    await LLMService._run_tool_call_loop(
        host,
        provider=provider(),
        request=request(),
        context=ToolExecutionContext("scope", "user", "test", "test", "test-model"),
    )
    assert callable(loop.call_args.kwargs["result_space_probe"])


async def test_service_search_material_fits_the_effective_context_window(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace

    from quickquip.llm.config import LLMConfig
    from quickquip.llm.provider.base import LLMResponse
    from quickquip.llm.request_budget import enforce_request_budget
    from quickquip.llm.service import LLMService
    from quickquip.llm.standalone_search import prepare_web_round
    from quickquip.llm.tools import ToolExecutionContext

    p = provider()
    p.max_output_tokens = 1000
    p.model_context_windows = {"test-model": 16_000}
    r = request()
    r.messages = [LLMConversationMessage("user", content="x" * 10_000)]
    config = LLMConfig()
    assert enforce_request_budget(config, p, r).ok
    loop = AsyncMock()
    monkeypatch.setattr("quickquip.llm.service.run_tool_call_loop", loop)
    host = SimpleNamespace(
        config=config,
        tool_registry=None,
        image_preprocessor=None,
        _is_tool_discovery_enabled=lambda *args, **kwargs: False,
        _get_enabled_tool_names=lambda **kwargs: ["web_run"],
    )
    await LLMService._run_tool_call_loop(
        host, provider=p, request=r,
        context=ToolExecutionContext("scope", "user", "test", "test", r.model),
    )
    probe = loop.call_args.kwargs["result_space_probe"]
    call = LLMToolCall("call", "web_run", '{"open":[{"ref_id":"https://example.test"}]}')
    response = LLMResponse(text="", model=r.model, tool_calls=[call])
    run = WebRun(AsyncMock(return_value={"output": "x" * 30_000}), "session", r.model, [])
    prepare_web_round(run, response, [call], probe(r))
    result = await run.execute({"open": [{"ref_id": "https://example.test"}]})
    assert result.search_metadata["truncated"]
    continued = replace(r, messages=[
        *r.messages,
        LLMConversationMessage("assistant", tool_calls=[call]),
        LLMConversationMessage("tool", content=result.content, tool_call_id=call.id),
    ])
    assert enforce_request_budget(config, p, continued).ok


async def test_successful_description_preserves_partial_media_status():
    from types import SimpleNamespace
    from quickquip.llm.tool_result_pipeline import ToolResultPipeline
    from quickquip.llm.tools import LLMInlineImage, LLMToolResult, ToolExecutionContext

    r = request()
    r.messages = [LLMConversationMessage("user", image_urls=["existing"] * 4)]
    p = provider()
    p.non_vision_models = [r.model]
    preprocessor = SimpleNamespace(
        describe_inline_images=AsyncMock(
            return_value=[
                SimpleNamespace(
                    source_url="one", success=True, text_description="page one description"
                ),
            ]
        )
    )
    pipeline = ToolResultPipeline(
        provider=p,
        request=r,
        image_preprocessor=preprocessor,
        context=ToolExecutionContext("scope", "user", "test", "test", r.model),
    )
    result = await pipeline.process_result(
        LLMToolCall("call", "web_run", "{}"),
        LLMToolResult(
            "call",
            "web_run",
            "two page screenshots",
            images=[
                LLMInlineImage(b"validated-image", "image/png", label) for label in ("one", "two")
            ],
            search_metadata={"version": 1, "requires_image": True, "status": "completed"},
        ),
    )
    assert not result.is_error
    assert result.search_metadata["status"] == "partial"
    assert result.search_metadata["media_omitted"] == 1
    assert result.search_metadata["media_state"] == "described"
