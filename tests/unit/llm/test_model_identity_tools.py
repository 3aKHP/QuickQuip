"""模型可见的身份类工具（get_current_model / get_llm_status）输出契约。

两者面向模型输出 provider/model 身份时必须附带路由说明，避免模型把
画图/语音/搜索等能力走不同通道误解为对话中"换过模型"；`/llm status`
等用户侧命令输出保持原样，不带该说明。
"""

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


async def test_get_current_model_appends_routing_note(llm_service):
    content = await _execute(llm_service, "get_current_model", {})

    assert "- Provider：" in content
    assert "- Model：" in content
    assert "路由说明" in content
    assert "同一个机器人" in content


async def test_get_llm_status_appends_routing_note_in_both_details(llm_service):
    for detail in ("status", "current"):
        content = await _execute(llm_service, "get_llm_status", {"detail": detail})

        assert f"LLM {'当前配置' if detail == 'current' else '状态'}" in content
        assert "路由说明" in content


async def test_user_facing_status_commands_stay_without_routing_note(llm_service):
    """/llm status 与 /llm current 的输出不附带面向模型的路由说明。"""
    assert "路由说明" not in llm_service.format_status(10001, chat_type="group")
    assert "路由说明" not in llm_service.format_current(10001, chat_type="group")
