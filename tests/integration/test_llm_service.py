"""Core LLMService integration: generate_reply, recent message rendering,
quoted-reply injection, tool loop, and reasoning-content sanitization.
"""
from __future__ import annotations

import pytest

from plugins.message_stats import GroupStatsTracker
from plugins.recent_message_buffer import RecentMessageBuffer
from plugins.rule_switch import GroupRuleSwitch

from tests.fixtures.provider_stubs import (
    StubProviderClient,
    StubReasoningLeakProviderClient,
    StubToolCallingProviderClient,
)


@pytest.fixture
def wired_service(llm_service):
    """LLMService with stats/rule_switch/recent_buffer bound (group 1001)."""
    stats = GroupStatsTracker()
    stats.record_message(1001, "2002", "镜子")
    stats.record_message(1001, "4004", "4s")
    stats.record_message(1001, "2002", "镜子")
    stats.record_trigger(1001, "divine_arrival")
    stats.record_trigger(1001, "divine_arrival")

    rule_switch = GroupRuleSwitch()
    rule_switch.disable(1001, "play_target")

    recent = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    recent.add_message(1001, "2002", "乙", "镜子", "@4s 哈基镜今天又在发病。")
    recent.add_message(1001, "4004", "丙", "4s", "刚才谁在神临。")

    llm_service.bind_group_stats_tracker(stats)
    llm_service.bind_rule_switch(rule_switch)
    llm_service.bind_recent_message_buffer(recent)

    # Switch to gpt-alt and set up group overrides so later tests can assert model choice.
    llm_service.set_group_model(1001, "openai-main", "gpt-alt")
    llm_service.set_group_persona(1001, "default")
    llm_service.set_group_trigger_prefix(1001, "/bot")
    llm_service.set_group_allow_at(1001, False)
    llm_service.set_group_allow_prefix(1001, True)

    return llm_service


async def test_generate_reply_populates_system_prompt_and_tools(
    wired_service, patch_provider_builder
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="哈基镜是区吗？",
        recent_messages=[
            {
                "user_id": "u1",
                "sender_name": "甲",
                "canonical_name": "",
                "text": "昨晚排位真红温。",
            },
            {
                "user_id": "2002",
                "sender_name": "乙",
                "canonical_name": "镜子",
                "text": "@4s 哈基镜今天又在发病。",
            },
        ],
    )

    assert result["rule_name"] == "llm_chat"
    # gpt-alt because set_group_model(1001, "openai-main", "gpt-alt")
    assert result["reply"].startswith("stub::gpt-alt::")
    assert result["reply"].endswith("哈基镜是区吗？")

    req = stub.last_request
    assert req is not None
    sys_prompt = req.system_prompt
    # structural, not verbatim
    assert "2002" in sys_prompt  # current asker QQ
    assert "镜子" in sys_prompt  # canonical name
    # Vocab/identity content flows in
    assert "镜千翎" in sys_prompt or "哈基镜" in sys_prompt

    # Tools registered
    tool_names = {t.name for t in req.tools}
    expected = {
        "get_identity",
        "list_memories",
        "search_web",
        "get_group_stats",
        "get_rule_status",
        "search_recent_messages",
        "get_llm_status",
        "get_current_model",
    }
    assert expected <= tool_names

    # Recent messages get injected as a leading assistant/history message
    history_msg = req.messages[0].content
    assert "昨晚排位真红温。" in history_msg
    assert "@4s 哈基镜今天又在发病。" in history_msg

    # Last message is the user's prompt, no leaked echo in earlier messages
    assert req.messages[-1].content.endswith("哈基镜是区吗？")
    assert all(m.content != "哈基镜是区吗？" for m in req.messages[:-1])


async def test_quoted_reply_content_in_user_message(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1002,
        user_id=3003,
        sender_name="测试用户",
        prompt="帮我看看",
        image_urls=[],
        quoted_text="@镜子 这张图什么意思[图片]",
        quoted_image_urls=["https://example.test/reply-cat.png"],
        quoted_sender_name="镜子",
        quoted_user_id="2002",
    )

    assert result["reply"].startswith("stub::gpt-test::")
    last_user = stub.last_request.messages[-1]
    assert "镜子" in last_user.content
    assert "2002" in last_user.content
    assert "@镜子 这张图什么意思[图片]" in last_user.content
    assert "帮我看看" in last_user.content
    assert last_user.image_urls == ["https://example.test/reply-cat.png"]


async def test_tool_call_loop_runs_identity_tool(wired_service, patch_provider_builder):
    stub = StubToolCallingProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="哈基镜是谁？",
        recent_messages=[],
    )

    assert result["reply"] == "哈基镜通常指镜子。"
    assert len(stub.requests) == 2
    round2 = stub.requests[-1]
    assert round2.messages[-2].role == "assistant"
    assert round2.messages[-2].tool_calls[0].name == "get_identity"
    assert round2.messages[-1].role == "tool"
    assert round2.messages[-1].tool_name == "get_identity"
    assert "镜子" in round2.messages[-1].content


async def test_forward_message_content_rendered(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1004,
        user_id=2002,
        sender_name="测试用户",
        prompt="分析一下",
        forward_text="1. Alice（QQ 10001）：这是合并转发",
        forward_image_urls=["https://example.test/forward.png"],
    )

    assert result["reply"].startswith("stub::gpt-test::")
    last_user = stub.last_request.messages[-1]
    assert "转发" in last_user.content
    assert "1. Alice（QQ 10001）：这是合并转发" in last_user.content
    assert last_user.image_urls == ["https://example.test/forward.png"]


async def test_reasoning_content_sanitized_at_service_level(
    wired_service, patch_provider_builder
):
    patch_provider_builder(lambda provider: StubReasoningLeakProviderClient())

    result = await wired_service.generate_reply(
        group_id=1003,
        user_id=3004,
        sender_name="测试用户",
        prompt="解释一下",
        recent_messages=[],
    )
    assert result["reply"] == "给群友看的答案"


async def test_history_is_pruned_after_cap(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="哈基镜是区吗？",
        recent_messages=[],
    )
    # Explicit prune below history_max_messages_per_group cap
    for i in range(20):
        wired_service.store.append_conversation_message(1001, "u", "assistant", f"补充{i}")
    cap = min(wired_service.config.runtime.history_max_messages_per_group, 20)
    wired_service.store.prune_conversation_messages(1001, cap)
    assert len(wired_service.store.list_recent_conversation_messages(1001, 100)) == cap

    deleted = wired_service.clear_group_context(1001)
    assert deleted == cap
    assert wired_service.store.list_recent_conversation_messages(1001, 100) == []


async def test_memory_crud_basic(wired_service):
    memory_id = wired_service.remember_group_memory(1001, "阿桃喜欢薄荷糖。")
    assert memory_id >= 1
    memories = wired_service.list_group_memories(1001)
    assert memories[0]["content"] == "阿桃喜欢薄荷糖。"

    matched = wired_service.store.search_memories(1001, user_id=2002, query="阿桃喜欢什么？", limit=3)
    assert matched
    assert matched[0]["content"] == "阿桃喜欢薄荷糖。"

    deleted = wired_service.forget_group_memories(1001, "薄荷糖")
    assert deleted == 1
    assert wired_service.list_group_memories(1001) == []
