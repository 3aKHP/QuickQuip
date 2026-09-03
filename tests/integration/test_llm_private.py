"""Private-chat scope symmetry.

Private conversations use scope key "private:USER_ID" and must:
- route start_private_session / end_private_session correctly
- keep memories and history under the private scope
- expose different status / tool behavior than group chats
"""
from __future__ import annotations

import pytest

from plugins.llm_runtime import LLMService
import quickquip.llm.service as llm_runtime_module

from tests.fixtures.provider_stubs import StubProviderClient


@pytest.fixture
def configured_service(llm_service: LLMService):
    llm_service.set_chat_persona(3003, "default", chat_type="private")
    llm_service.set_chat_trigger_prefix(3003, "/dm", chat_type="private")
    llm_service.set_chat_allow_prefix(3003, True, chat_type="private")
    return llm_service


def test_private_status_reflects_session_off(configured_service):
    status = configured_service.format_status(3003, chat_type="private")
    assert "当前会话：私聊" in status
    assert "总开关：OFF" in status
    assert "前缀触发：ON (/dm)" in status
    assert "会话状态：未开启" in status
    assert "艾特触发：OFF（私聊不适用）" in status


def test_private_memory_isolated_from_group(configured_service):
    mid = configured_service.remember_memory(3003, "阿桃在私聊里更愿意长篇回复。", chat_type="private")
    assert mid >= 1
    private_memories = configured_service.list_memories(3003, chat_type="private")
    assert private_memories[0]["content"] == "阿桃在私聊里更愿意长篇回复。"

    scope_key = configured_service.build_chat_scope_key(3003, chat_type="private")
    matched = configured_service.store.search_memories(
        scope_key, user_id=3003, query="私聊时你会怎么回复？", limit=3
    )
    assert matched
    assert matched[0]["content"] == "阿桃在私聊里更愿意长篇回复。"


async def test_generate_private_reply_uses_private_system_prompt(
    configured_service, monkeypatch
):
    stub = StubProviderClient()
    monkeypatch.setattr(llm_runtime_module, "build_provider_client", lambda provider: stub)

    # Seed memory before starting session (start_private_session doesn't touch memories)
    configured_service.remember_memory(3003, "阿桃在私聊里更愿意长篇回复。", chat_type="private")
    configured_service.start_private_session(3003)

    # Seed conversation history AFTER start_private_session, which clears context.
    scope_key = configured_service.build_chat_scope_key(3003, chat_type="private")
    for i in range(50):
        configured_service.store.append_conversation_message(
            scope_key,
            "3003" if i % 2 == 0 else None,
            "user" if i % 2 == 0 else "assistant",
            f"私聊历史{i}",
            sender_name="阿桃" if i % 2 == 0 else "",
        )

    result = await configured_service.generate_private_reply(
        user_id=3003,
        sender_name="阿桃",
        prompt="私聊里继续我们刚才的话题",
    )

    assert "私聊里继续我们刚才的话题" in result["reply"]
    sys_prompt = stub.last_request.system_prompt
    assert "当前会话类型：私聊" in sys_prompt
    assert "当前私聊对象 QQ：3003" in sys_prompt
    # 持久记忆属动态段，改由当轮信封携带，不再进 system（前缀缓存契约）
    assert "阿桃在私聊里更愿意长篇回复。" not in sys_prompt
    last_content = stub.last_request.messages[-1].content
    assert "【轮次上下文】" in last_content
    assert "阿桃在私聊里更愿意长篇回复。" in last_content
    assert "私聊里继续我们刚才的话题" in last_content
    # Alternating user/assistant seed produces 25 user scenes + 25 assistant + 1 current = 51
    assert len(stub.last_request.messages) == 51


def test_end_private_session_clears_history(configured_service):
    configured_service.start_private_session(3003)
    scope_key = configured_service.build_chat_scope_key(3003, chat_type="private")
    for i in range(5):
        configured_service.store.append_conversation_message(
            scope_key, "3003", "user", f"msg{i}", sender_name="阿桃"
        )
    assert configured_service.get_chat_settings(3003, chat_type="private").enabled is True

    ctx = configured_service.end_private_session(3003, save=False)
    assert ctx["deleted"] == 5
    assert configured_service.get_chat_settings(3003, chat_type="private").enabled is False
    assert configured_service.store.list_recent_conversation_messages(scope_key, 100) == []
