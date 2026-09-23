"""身份工具通过注册表返回当前会话的实际 provider 与 model。"""

from __future__ import annotations

import json

from quickquip.llm.tools import LLMToolCall, ToolExecutionContext


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        group_id=10001,
        user_id=20002,
        sender_name="tester",
        provider_id="openai-main",
        model="gpt-test",
        chat_scope="10001",
    )


async def _execute(llm_service, name: str, arguments: dict) -> str:
    result = await llm_service.tool_registry.execute(
        LLMToolCall(
            id="call_1",
            name=name,
            arguments_json=json.dumps(arguments),
        ),
        _context(),
    )
    assert result.is_error is False
    return result.content


async def test_get_current_model_returns_active_identity(llm_service):
    content = await _execute(llm_service, "get_current_model", {})

    assert "openai-main" in content
    assert "gpt-test" in content


async def test_get_llm_status_returns_active_identity_in_both_details(llm_service):
    for detail in ("status", "current"):
        content = await _execute(llm_service, "get_llm_status", {"detail": detail})

        assert "openai-main" in content
        assert "gpt-test" in content
