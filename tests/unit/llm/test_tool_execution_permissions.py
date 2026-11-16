"""A hosted tool allowance never authorizes undeclared local functions."""
import logging

import pytest

from quickquip.llm.config import ProviderConfig, RuntimeConfig
from quickquip.llm.provider.base import LLMRequest, LLMResponse
from quickquip.llm.tool_loop import run_tool_call_loop
from quickquip.llm.tool_registry import ToolRegistry
from quickquip.llm.tools import LLMToolCall, LLMToolSpec, ToolExecutionContext


@pytest.mark.parametrize("protocol", ["openai", "claude", "gemini", "openai_responses"])
@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("declare_local", [False, True])
async def test_only_currently_declared_functions_can_execute(protocol, discovery, declare_local):
    effects = []
    registry = ToolRegistry()
    allowed = LLMToolSpec(name="allowed", description="enabled", input_schema={"type": "object"})
    disabled = LLMToolSpec(name="disabled", description="disabled", input_schema={"type": "object"})
    registry.register(allowed, lambda args, ctx: effects.append("allowed") or "ok")
    registry.register(disabled, lambda args, ctx: effects.append("disabled") or "unexpected")
    requests = []

    class Client:
        async def complete(self, request):
            requests.append(request)
            if len(requests) == 1:
                return LLMResponse(text="", model="model", tool_calls=[
                    LLMToolCall(id="allowed-call", name="allowed", arguments_json="{}"),
                    LLMToolCall(id="disabled-call", name="disabled", arguments_json="{}"),
                ])
            return LLMResponse(text="完成", model="model")

    await run_tool_call_loop(
        provider=ProviderConfig(id="test", protocol=protocol, base_url="https://example.test/v1",
                                api_key_env="TEST_KEY", default_model="model", models=["model"]),
        request=LLMRequest(model="model", system_prompt="", messages=[], temperature=0.2,
                           max_output_tokens=100, tools=[allowed] if declare_local else [],
                           allow_tool_calls=True, builtin_search=True),
        context=ToolExecutionContext(group_id="scope", user_id="user", sender_name="测试",
                                     provider_id="test", model="model"),
        build_provider_client=lambda config: Client(), tool_registry=registry,
        runtime_config=RuntimeConfig(tool_max_rounds=2), logger=logging.getLogger(__name__),
        search_tool_name="search_web", search_failsafe_max_rounds=4,
        search_failsafe_max_calls_per_round=3, tool_discovery_enabled=discovery,
        enabled_tool_names=["allowed"] if declare_local else [],
    )
    assert effects == (["allowed"] if declare_local else [])
    results = [message for message in requests[1].messages if message.role == "tool"]
    assert len(results) == 2
    assert results[1].is_tool_error
    assert results[0].is_tool_error is (not declare_local)
