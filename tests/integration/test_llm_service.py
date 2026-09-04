"""Core LLMService integration: generate_reply, recent message rendering,
quoted-reply injection, tool loop, and reasoning-content sanitization.
"""
from __future__ import annotations

import re

import pytest

from plugins.llm_provider import LLMResponse
from plugins.llm_tools import LLMToolCall
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
    # system prompt 静态化（前缀缓存字节稳定契约）：词表命中、时间等
    # 动态段不得残留在 system 中
    assert "通常指" not in sys_prompt
    assert "当前北京时间" not in sys_prompt

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

    # Recent messages get injected as context in the first user message
    history_msg = req.messages[0].content
    assert "昨晚排位真红温。" in history_msg
    assert "@4s 哈基镜今天又在发病。" in history_msg

    # Current speaker identity is in the last (current scene) message
    last_content = req.messages[-1].content
    assert "哈基镜是区吗？" in last_content
    assert "2002" in last_content
    assert "镜子" in last_content
    # 词表命中/时间等动态内容改由当轮 user 消息头部的【轮次上下文】信封
    # 携带；用户原文本身含「哈基镜」，必须断言信封专属构造而非裸词表名
    assert "【轮次上下文】" in last_content
    assert "通常指" in last_content
    assert re.search(r"当前时间：\d{4}-\d{2}-\d{2} 星期. \d{2}:\d{2}（北京时间）", last_content)


async def test_generate_reply_envelope_carries_time_for_cron_like_trigger(
    wired_service, patch_provider_builder
):
    """cron llm 任务形态（store_user_message=False + 合成 prompt）：
    时间感知由信封携带，system 不含时间——定时任务日期推算不回退。"""
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=0,
        sender_name="scheduled_timer",
        prompt="按 22:00 计划发送晚间提醒",
        store_user_message=False,
    )

    req = stub.last_request
    assert req is not None
    assert re.search(r"当前时间：\d{4}-\d{2}-\d{2} 星期. \d{2}:\d{2}（北京时间）", req.messages[-1].content)
    assert "当前北京时间" not in req.system_prompt


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


async def test_raw_user_text_stored_without_internal_trigger_instruction(
    wired_service, patch_provider_builder
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1005,
        user_id=3003,
        sender_name="测试用户",
        prompt="【内部触发说明】命中了兴趣话题，不要说明唤醒机制。\n【群友消息】马头蒸菜",
        raw_user_text="马头蒸菜",
        recent_messages=[],
    )

    last_user = stub.last_request.messages[-1].content
    assert "内部触发说明" in last_user
    assert "马头蒸菜" in last_user

    stored = wired_service.store.list_recent_conversation_messages(1005, 2)
    user_rows = [row for row in stored if row["role"] == "user"]
    assert len(user_rows) == 1
    assert user_rows[0]["content"] == "马头蒸菜"
    assert user_rows[0]["raw_content"] == "马头蒸菜"


async def test_empty_raw_user_text_does_not_persist_internal_trigger_instruction(
    wired_service, patch_provider_builder
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1007,
        user_id=3003,
        sender_name="测试用户",
        prompt="【内部触发说明】只有图片占位被剥离。\n【群友消息】[图片]",
        raw_user_text="",
        recent_messages=[],
    )

    last_user = stub.last_request.messages[-1].content
    assert "内部触发说明" in last_user

    stored = wired_service.store.list_recent_conversation_messages(1007, 2)
    user_rows = [row for row in stored if row["role"] == "user"]
    assert len(user_rows) == 1
    assert user_rows[0]["content"] == ""
    assert "内部触发说明" not in user_rows[0]["raw_content"]


async def test_can_skip_user_history_for_system_trigger(
    wired_service, patch_provider_builder
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1008,
        user_id="boredom_timer",
        sender_name="系统",
        prompt="【内部触发说明】群聊沉寂触发。\n【群友消息】",
        raw_user_text="",
        store_user_message=False,
        recent_messages=[],
    )

    stored = wired_service.store.list_recent_conversation_messages(1008, 2)
    assert [row["role"] for row in stored] == ["assistant"]
    assert "内部触发说明" in stub.last_request.messages[-1].content


async def test_internal_trigger_prompt_can_include_current_image(
    wired_service, patch_provider_builder
):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1006,
        user_id=3003,
        sender_name="测试用户",
        prompt=(
            "【内部触发说明】这条触发消息包含图片，请结合图片与文字自然回应。\n"
            "【群友消息】[图片] 这是什么？"
        ),
        image_urls=["https://example.test/passive.png"],
        raw_user_text="[图片] 这是什么？",
        recent_messages=[],
    )

    last_user = stub.last_request.messages[-1]
    assert "这条触发消息包含图片" in last_user.content
    assert "[图片] 这是什么？" in last_user.content
    assert last_user.image_urls == ["https://example.test/passive.png"]

    stored = wired_service.store.list_recent_conversation_messages(1006, 2)
    user_rows = [row for row in stored if row["role"] == "user"]
    assert user_rows[0]["content"] == "[图片] 这是什么？"


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


async def test_gemini_tool_loop_carries_signed_replay_parts(wired_service, patch_provider_builder):
    class SignedGeminiStub:
        def __init__(self):
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return LLMResponse(
                    text="",
                    model=request.model,
                    tool_calls=[LLMToolCall(
                        id="call_identity_1",
                        name="get_identity",
                        arguments_json='{"query":"哈基镜"}',
                    )],
                    thinking_blocks=[{
                        "type": "gemini_part",
                        "part": {
                            "functionCall": {
                                "id": "call_identity_1",
                                "name": "get_identity",
                                "args": {"query": "哈基镜"},
                            },
                            "thoughtSignature": "opaque-signature",
                        },
                    }],
                )
            return LLMResponse(text="签名回放成功。", model=request.model)

    stub = SignedGeminiStub()
    wired_service.config.providers["openai-main"].protocol = "gemini"
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="哈基镜是谁？",
        recent_messages=[],
    )

    assert result["reply"] == "签名回放成功。"
    assistant = stub.requests[1].messages[-2]
    assert assistant.thinking_blocks[0]["part"]["thoughtSignature"] == "opaque-signature"
    assert stub.requests[1].messages[-1].tool_call_id == "call_identity_1"


async def test_gemini_tool_loop_rejects_truncated_function_call_batch(
    wired_service,
    patch_provider_builder,
):
    class OverflowGeminiStub:
        def __init__(self):
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            return LLMResponse(
                text="",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id=f"call_{index}",
                        name="get_identity",
                        arguments_json='{"query":"哈基镜"}',
                    )
                    for index in range(4)
                ],
            )

    stub = OverflowGeminiStub()
    wired_service.config.providers["openai-main"].protocol = "gemini"
    wired_service.config.runtime.tool_max_calls_per_round = 3
    patch_provider_builder(lambda provider: stub)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="同时查四个人。",
        recent_messages=[],
    )

    assert result["reply"] == "模型一次请求了过多工具，已拒绝执行不完整的 Gemini 工具批次。"
    assert len(stub.requests) == 1


async def test_gemini_tool_loop_reject_notice_appended_to_existing_text(
    wired_service,
    patch_provider_builder,
    caplog,
):
    """fail-closed 拒批时模型附带的叙述文本必须保留，拒绝提示追加在后并记 warning。"""

    class NarratingOverflowStub:
        def __init__(self):
            self.requests = []

        async def complete(self, request):
            self.requests.append(request)
            return LLMResponse(
                text="我去查一下",
                model=request.model,
                tool_calls=[
                    LLMToolCall(
                        id=f"call_{index}",
                        name="get_identity",
                        arguments_json='{"query":"哈基镜"}',
                    )
                    for index in range(4)
                ],
            )

    stub = NarratingOverflowStub()
    wired_service.config.providers["openai-main"].protocol = "gemini"
    wired_service.config.runtime.tool_max_calls_per_round = 3
    patch_provider_builder(lambda provider: stub)

    with caplog.at_level("WARNING", logger="quickquip.llm.service"):
        result = await wired_service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="测试用户",
            prompt="同时查四个人。",
            recent_messages=[],
        )

    assert result["reply"] == (
        "我去查一下\n模型一次请求了过多工具，已拒绝执行不完整的 Gemini 工具批次。"
    )
    assert len(stub.requests) == 1
    assert any(
        "Gemini tool batch rejected" in record.message and "requested=4" in record.message
        for record in caplog.records
    )


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
    # 转发图片不再作为媒体本体附带（VLM 路径同）；[附图 N 张] 文本后缀仍在
    assert last_user.image_urls == []
    assert "[附图 1 张]" in last_user.content


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


async def test_history_is_cropped_after_cap(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="哈基镜是区吗？",
        recent_messages=[],
    )
    # Explicit crop by hard row cap (floor=None = 锚点缺失时只按 keep_last 兜底)
    for i in range(20):
        wired_service.store.append_conversation_message(1001, "u", "assistant", f"补充{i}")
    cap = 10
    wired_service.store.crop_conversation_messages(1001, floor_id=None, keep_last=cap)
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


def test_reload_personas_swaps_config_personas_only(llm_service):
    original_providers = llm_service.config.providers
    original_runtime = llm_service.config.runtime

    # Overwrite llm.toml with a different persona set (and different providers
    # to prove reload_personas does NOT touch providers).
    new_toml = """
[runtime]
enabled = true
default_provider = "openai-main"
default_persona = "chatter"
history_limit = 6
history_max_messages_per_group = 8
memory_limit = 3
memory_max_items_per_group = 20
max_prompt_chars = 1000
tool_calling_enabled = true

[triggers]
default_prefix = "/ai"
allow_prefix = true
allow_at = true

[[personas]]
id = "chatter"
display_name = "健谈人格"
system_prompt = "你特别健谈。"

[[personas]]
id = "silent"
display_name = "寡言人格"
system_prompt = "你话少。"

[[providers]]
id = "ghost-provider"
protocol = "openai"
base_url = "https://ghost.example/v1"
api_key_env = "GHOST_API_KEY"
default_model = "ghost-model"
"""
    llm_service.config_path.write_text(new_toml.lstrip(), encoding="utf-8")

    count, error = llm_service.reload_personas()
    assert error is None
    assert count == 2
    assert set(llm_service.config.personas.keys()) == {"chatter", "silent"}
    assert llm_service.config.personas["chatter"].display_name == "健谈人格"

    # Providers and runtime untouched — this is the whole point.
    assert llm_service.config.providers is original_providers
    assert llm_service.config.runtime is original_runtime
    assert "openai-main" in llm_service.config.providers


def test_reload_personas_falls_back_when_default_removed(llm_service):
    assert llm_service.config.runtime.default_persona == "default"

    new_toml = """
[runtime]
enabled = true
default_provider = "openai-main"
default_persona = "default"

[triggers]
default_prefix = "/ai"

[[personas]]
id = "freshling"
display_name = "新来人格"
system_prompt = "hi"

[[providers]]
id = "openai-main"
protocol = "openai"
base_url = "https://example.test/v1"
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-test"
"""
    llm_service.config_path.write_text(new_toml.lstrip(), encoding="utf-8")

    count, error = llm_service.reload_personas()
    assert error is None
    assert count == 1
    # default_persona no longer exists → falls back to first available
    assert llm_service.config.runtime.default_persona == "freshling"


def test_reload_personas_empty_keeps_previous(llm_service):
    original = llm_service.config.personas
    llm_service.config_path.write_text(
        '[runtime]\ndefault_provider = "x"\n', encoding="utf-8"
    )
    count, error = llm_service.reload_personas()
    assert count == 0
    assert error == "配置中没有可用的人格"
    assert llm_service.config.personas is original


def test_reload_config_rebuilds_image_preprocessor(llm_service, monkeypatch):
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    built = []

    class _StubClient:
        pass

    def _build(provider):
        built.append(provider)
        return _StubClient()

    monkeypatch.setattr("quickquip.llm.service_parts.tools.build_provider_client", _build)
    llm_service.config_path.write_text(
        MIN_LLM_CONFIG_TOML
        + """

[image_preprocessing]
enabled = true
provider_id = "openai-main"
model = "gpt-test"
""",
        encoding="utf-8",
    )

    llm_service.reload_config()

    assert llm_service.image_preprocessor is not None
    assert llm_service.image_preprocessor._model == "gpt-test"
    assert built and built[-1].id == "openai-main"

    llm_service.config_path.write_text(MIN_LLM_CONFIG_TOML, encoding="utf-8")
    llm_service.reload_config()

    assert llm_service.image_preprocessor is None


class _AutoMemoryStubClient:
    """Stub provider client that returns pre-canned replies in order."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.call_count = 0

    async def complete(self, request):
        from plugins.llm_provider import LLMResponse
        self.call_count += 1
        text = self._replies.pop(0) if self._replies else ""
        return LLMResponse(text=text, model=request.model, finish_reason="stop")


async def test_auto_memory_extraction_writes_memories_when_enabled(
    llm_service, patch_provider_builder
):
    import asyncio
    llm_service.config.runtime.auto_memory_enabled = True
    stub = _AutoMemoryStubClient([
        "收到！小明果然是程序员，奶茶也是好文明。",
        '{"memories": ["小明是程序员", "小明喜欢喝奶茶"]}',
    ])
    patch_provider_builder(lambda provider: stub)

    # Batch trigger: extract every 10 turns; pre-set counter so the next call hits the batch
    llm_service._auto_memory_turns["1001"] = 9
    await llm_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="小明",
        prompt="我叫小明，是个程序员，喜欢喝奶茶",
        recent_messages=[],
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert stub.call_count == 2
    memories = llm_service.list_group_memories(1001)
    contents = {m["content"] for m in memories}
    assert contents == {"小明是程序员", "小明喜欢喝奶茶"}
    assert all(m["source"] == "auto" for m in memories)


async def test_auto_memory_extraction_disabled_does_not_call_judge(
    llm_service, patch_provider_builder
):
    import asyncio
    # Default auto_memory_enabled == False.
    stub = _AutoMemoryStubClient(["收到。", "should-not-be-called"])
    patch_provider_builder(lambda provider: stub)

    await llm_service.generate_reply(
        group_id=1002,
        user_id=2002,
        sender_name="n",
        prompt="哈基镜是区吗？",
        recent_messages=[],
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert stub.call_count == 1
    assert llm_service.list_group_memories(1002) == []


async def test_auto_memory_extraction_swallows_judge_errors(
    llm_service, patch_provider_builder
):
    import asyncio
    llm_service.config.runtime.auto_memory_enabled = True
    stub = _AutoMemoryStubClient([
        "收到！让我仔细想想你的特点和性格。",
        "not valid json at all",
    ])
    patch_provider_builder(lambda provider: stub)

    # Batch trigger: extract every 10 turns
    llm_service._auto_memory_turns["1003"] = 9
    # Must not raise despite the judge returning junk.
    result = await llm_service.generate_reply(
        group_id=1003,
        user_id=2002,
        sender_name="n",
        prompt="你好，请介绍一下我自己的特点",
        recent_messages=[],
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert result["reply"] == "收到！让我仔细想想你的特点和性格。"
    assert llm_service.list_group_memories(1003) == []


async def test_auto_memory_respects_memory_disabled(
    llm_service, patch_provider_builder
):
    import asyncio
    llm_service.config.runtime.auto_memory_enabled = True
    llm_service.set_group_memory_enabled(1004, False)

    stub = _AutoMemoryStubClient(["收到。"])
    patch_provider_builder(lambda provider: stub)

    await llm_service.generate_reply(
        group_id=1004,
        user_id=2002,
        sender_name="n",
        prompt="我喜欢奶茶",
        recent_messages=[],
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # Only reply call; judge never runs because memory is off for this group.
    assert stub.call_count == 1
    assert llm_service.list_group_memories(1004) == []


async def test_auto_memory_per_chat_override_beats_global_default(
    llm_service, patch_provider_builder
):
    import asyncio
    llm_service.config.runtime.auto_memory_enabled = False
    llm_service.set_chat_auto_memory_enabled(1005, True, chat_type="group")

    stub = _AutoMemoryStubClient([
        "收到！编程开发是个不错的方向，继续加油坚持。",
        '{"memories": ["override works"]}',
    ])
    patch_provider_builder(lambda provider: stub)

    llm_service._auto_memory_turns["1005"] = 9
    await llm_service.generate_reply(
        group_id=1005,
        user_id=2002,
        sender_name="n",
        prompt="我最近在学编程开发",
        recent_messages=[],
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert stub.call_count == 2
    assert [m["content"] for m in llm_service.list_group_memories(1005)] == ["override works"]


# ── image preprocessor integration tests ──────────────────────────────


async def test_image_preprocessor_called_for_non_vision_model(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient
    wired_service.config.providers["openai-main"].non_vision_models.append("gpt-alt")
    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    patch_provider_builder(lambda provider: StubProviderClient())
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )
    assert stub_preprocessor.call_count == 1
    assert stub_preprocessor.last_urls == ["https://example.test/cat.png"]


async def test_image_preprocessor_skipped_when_no_images(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient
    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    patch_provider_builder(lambda provider: StubProviderClient())
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="纯文字提问",
        image_urls=[],
        recent_messages=[],
    )
    assert stub_preprocessor.call_count == 0


async def test_non_vision_model_strips_images_from_request(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    # Mark gpt-alt as non-vision in the provider config
    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")

    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    # All user messages should have empty image_urls since the image was stripped
    for msg in request.messages:
        if msg.role == "user":
            assert msg.image_urls == [], (
                f"Expected empty image_urls for non-VLM model, got {msg.image_urls}"
            )


async def test_vision_model_keeps_images_in_request(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    # non_vision_models is empty by default → all models treated as VLM
    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    # At least one user message should still contain the image URL
    image_urls_found = False
    for msg in request.messages:
        if msg.role == "user" and msg.image_urls:
            image_urls_found = True
            break
    assert image_urls_found, "Expected image_urls preserved for VLM model"
    assert stub_preprocessor.call_count == 0


async def test_non_vision_strips_even_when_preprocessor_fails(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubProviderClient
    from quickquip.llm.image_preprocessor import ImageDescription

    # Preprocessor that always fails
    class _FailingPreprocessor:
        async def describe_images(self, image_urls):
            return [
                ImageDescription(source_url=url, text_description="", success=False, error="fail")
                for url in image_urls
            ]

    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")

    wired_service.image_preprocessor = _FailingPreprocessor()

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    assert request is None
    assert result["reply"].startswith("前置图片识别失败")


async def test_non_vision_strips_without_preprocessor(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubProviderClient

    # No preprocessor bound, model is non-VLM
    wired_service.image_preprocessor = None
    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    assert request is None
    assert result["reply"].startswith("当前模型无法直接读取图片")


async def test_non_vision_preprocesses_recent_context_images(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")
    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="刚才那张图是什么意思",
        recent_messages=[
            {
                "user_id": "3003",
                "sender_name": "发图者",
                "text": "[图片]",
                "image_urls": ["https://example.test/recent.png"],
            }
        ],
        include_recent_images=True,
    )

    assert stub_preprocessor.last_urls == ["https://example.test/recent.png"]
    request = stub_client.last_request
    assert request is not None
    assert all(not msg.image_urls for msg in request.messages if msg.role == "user")
    assert "[近期上下文图片 1]" in request.messages[-1].content
    assert "stub description of https://example.test/recent.png" in request.messages[-1].content


async def test_non_vision_rejects_too_many_primary_images(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")
    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    result = await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看这些图",
        image_urls=[f"https://example.test/{index}.png" for index in range(6)],
        recent_messages=[],
    )

    assert result["reply"].startswith("一次最多识别 5 张图片")
    assert stub_preprocessor.call_count == 0
    assert stub_client.last_request is None


async def test_non_vision_strips_quoted_images(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看引用图",
        image_urls=[],
        quoted_text="上一条",
        quoted_image_urls=["https://example.test/reply.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    for msg in request.messages:
        if msg.role == "user":
            assert msg.image_urls == [], "Non-VLM must strip quoted images"
    assert "stub description of https://example.test/reply.png" in request.messages[-1].content


async def test_non_vision_strips_forward_images(wired_service, patch_provider_builder):
    from tests.fixtures.provider_stubs import StubImagePreprocessor, StubProviderClient

    provider = wired_service.config.providers["openai-main"]
    provider.non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()

    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="看看转发图",
        image_urls=[],
        forward_text="转发内容",
        forward_image_urls=["https://example.test/forward.png"],
        recent_messages=[],
    )

    request = stub_client.last_request
    for msg in request.messages:
        if msg.role == "user":
            assert msg.image_urls == [], "Non-VLM must strip forwarded images"
    assert "stub description of https://example.test/forward.png" in request.messages[-1].content


async def test_generate_reply_usage_scope_carries_group_and_persona(
    wired_service, patch_provider_builder, monkeypatch
):
    """#109-A：聊天主链路的 provider 调用运行在带 group/persona 归因的 scope 内。"""
    import contextlib

    import quickquip.llm.service as service_module
    from tests.fixtures.provider_stubs import StubProviderClient

    calls: list[tuple] = []

    @contextlib.contextmanager
    def _record(feature, **kwargs):
        calls.append((feature, kwargs))
        yield

    monkeypatch.setattr(service_module, "usage_scope", _record)
    stub_client = StubProviderClient()
    patch_provider_builder(lambda provider: stub_client)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="测试用户",
        prompt="哈基镜是区吗？",
        recent_messages=[],
    )

    assert ("chat", {"group_id": "1001", "persona_id": "default"}) in calls


async def test_clear_context_purges_store_and_recent_buffer(
    wired_service, patch_provider_builder
):
    """clear_context 必须同时清持久会话库与进程内最近消息缓冲。

    否则 build_messages 会继续把缓冲拼进提示词，/llm clear_context 之后
    模型仍然"看得见"清空前的群聊。
    """
    buf = wired_service.recent_message_buffer
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    wired_service.store.append_conversation_message(
        "1001", "2002", "user", "清空前的库内旧话", sender_name="乙"
    )
    deleted = wired_service.clear_context(1001)
    assert deleted == 1
    assert wired_service.store.list_recent_conversation_messages("1001", 10) == []
    assert buf.list_recent(1001) == []

    # 清空后下一条群消息到达：缓冲只重新累积新内容，旧消息没有回填路径。
    buf.add_message(1001, "2002", "乙", "镜子", "清空后的新话")
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="乙",
        prompt="清空后你还在吗？",
        recent_messages=buf.list_recent(1001, limit=20),
    )

    req = stub.last_request
    assert req is not None
    history_content = req.messages[0].content
    assert "清空后的新话" in history_content
    assert "哈基镜今天又在发病" not in history_content
    assert "刚才谁在神临" not in history_content
    assert "清空前的库内旧话" not in history_content


def test_clear_context_private_scope_uses_private_buffer_key(llm_service):
    """私聊缓冲以 private:{user_id} 为 key，clear_context 需按同一 scope 清。"""
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    llm_service.bind_recent_message_buffer(buf)
    buf.add_message("private:7001", "7001", "u", "U", "私聊旧话")
    llm_service.store.append_conversation_message(
        "private:7001", "7001", "user", "私聊旧话", sender_name="u"
    )

    deleted = llm_service.clear_context("7001", chat_type="private")

    assert deleted == 1
    assert llm_service.store.list_recent_conversation_messages("private:7001", 10) == []
    assert buf.list_recent("private:7001") == []


def test_end_private_session_without_save_clears_buffer(llm_service):
    """session end（不存档）与 clear_context 共用同一条短期上下文清理路径。"""
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    llm_service.bind_recent_message_buffer(buf)
    buf.add_message("private:7001", "7001", "u", "U", "私聊旧话")

    llm_service.set_chat_enabled("7001", True, chat_type="private")
    result = llm_service.end_private_session("7001", save=False)

    assert result["deleted"] == 0
    assert llm_service.store.list_recent_conversation_messages("private:7001", 10) == []
    assert buf.list_recent("private:7001") == []


def test_resume_private_session_clears_buffer(llm_service):
    """恢复存档前清空当前短期上下文时，进程内缓冲必须一并清掉。"""
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    llm_service.bind_recent_message_buffer(buf)
    llm_service.store.append_conversation_message(
        "private:7001", "7001", "user", "存档前的话", sender_name="u"
    )
    llm_service.end_private_session("7001", save=True)

    buf.add_message("private:7001", "7001", "u", "U", "存档后残留的缓冲")

    result = llm_service.resume_private_session("7001")

    assert result.get("archive_number") == 1
    assert buf.list_recent("private:7001") == []
    restored = [
        m["content"]
        for m in llm_service.store.list_recent_conversation_messages("private:7001", 10)
    ]
    assert "存档前的话" in restored


# ── 会话纪元（PR-B1）─────────────────────────────────────────────

from quickquip.llm.epoch import EpochKey  # noqa: E402


class _RecordingStub(StubProviderClient):
    """StubProviderClient + 全量请求留存（跨轮前缀比对用）。"""

    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return await super().complete(request)


def _fingerprints(request):
    return [(m.role, m.content) for m in request.messages]


async def test_epoch_history_byte_stable_across_turns(wired_service, patch_provider_builder):
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    for i in range(3):
        await wired_service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="n",
            prompt=f"第{i}轮问题",
            recent_messages=[],
        )

    assert len(stub.requests) == 3
    fp2 = _fingerprints(stub.requests[1])
    fp3 = _fingerprints(stub.requests[2])
    # 纪元内前缀逐字节稳定：第 2 轮除当轮 user 消息（信封+当前提问）外的全部
    # 内容，必须逐字节复现为第 3 轮的头部
    assert fp2[:-1], "第 2 轮应已有 history"
    assert fp3[: len(fp2) - 1] == fp2[:-1]
    assert len(fp3) > len(fp2)
    # 锚点在暖轮间不移动
    key = EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-alt")
    assert wired_service._epochs.current_anchor(key) is not None


async def test_epoch_cold_reset_after_idle(wired_service, patch_provider_builder, monkeypatch):
    runtime = wired_service.config.runtime
    runtime.epoch_context_tokens = 100
    runtime.epoch_cold_idle_seconds = 300
    runtime.epoch_cold_trigger_tokens = 80
    runtime.epoch_cold_target_tokens = 40
    runtime.epoch_hot_target_tokens = 10000
    runtime.epoch_cap_tokens = 20000

    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    now = [1_000.0]
    monkeypatch.setattr(wired_service._epochs, "_clock", lambda: now[0])
    key = EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-alt")

    for i in range(3):
        await wired_service.generate_reply(
            group_id=1001,
            user_id=2002,
            sender_name="n",
            prompt=f"第{i}轮问题",
            recent_messages=[],
        )
    anchor_before = wired_service._epochs.current_anchor(key)

    now[0] += 301  # 冷场：距上次请求 > T 且窗口 > H_cold
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="第3轮问题",
        recent_messages=[],
    )

    anchor_after = wired_service._epochs.current_anchor(key)
    assert anchor_after > anchor_before  # 冷场挪锚
    history_text = "".join(m.content for m in stub.requests[-1].messages[:-1])
    assert "第0轮问题" not in history_text  # 最早一对被裁出窗口
    assert "第1轮问题" in history_text  # MIN_EPOCH_ROWS 保护下保留最近两对
    assert "第2轮问题" in history_text


async def test_clear_context_also_resets_epoch(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="你好", recent_messages=[],
    )
    key = EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-alt")
    assert wired_service._epochs.current_anchor(key) is not None

    wired_service.clear_group_context(1001)
    assert wired_service._epochs.current_anchor(key) is None

    # 下一轮重新懒初始化，不崩溃、不残留旧锚点
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="再来", recent_messages=[],
    )
    assert wired_service._epochs.current_anchor(key) is not None


async def test_set_model_starts_new_epoch_key(wired_service, patch_provider_builder):
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="你好", recent_messages=[],
    )
    old_key = EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-alt")
    assert wired_service._epochs.current_anchor(old_key) is not None

    wired_service.set_group_model(1001, "openai-main", "gpt-test")
    result = await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="换模型了", recent_messages=[],
    )

    assert result["reply"].startswith("stub::gpt-test::")
    new_key = EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-test")
    # 新键懒初始化（CTX 跨度锚定）；旧键状态保留，互不干扰
    assert wired_service._epochs.current_anchor(new_key) is not None
    assert wired_service._epochs.current_anchor(old_key) is not None


async def test_set_persona_advances_anchor_to_cold_water(wired_service, monkeypatch):
    calls = []
    original = wired_service._epochs.advance_to_cold_water

    def spy(key, **kwargs):
        calls.append(key)
        return original(key, **kwargs)

    monkeypatch.setattr(wired_service._epochs, "advance_to_cold_water", spy)
    wired_service.set_group_persona(1001, "default")

    assert len(calls) == 1
    assert calls[0] == EpochKey(scope_key="1001", provider_id="openai-main", model="gpt-alt")


async def test_non_vision_persists_image_captions_in_raw_content(wired_service, patch_provider_builder):
    """非 VLM 路径：图注以文本身份落库（[图片 N 张：…]），下一轮 history 字节复现。"""
    from tests.fixtures.provider_stubs import StubImagePreprocessor

    wired_service.config.providers["openai-main"].non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )
    caption_part = "[图片 1 张：stub description of https://example.test/cat.png]"
    stored = wired_service.store.list_recent_conversation_messages(1001, 10)
    raw = [r["raw_content"] for r in stored if r["role"] == "user"][0]
    assert caption_part in raw

    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="第二轮", recent_messages=[],
    )
    assert len(stub.requests) == 2
    # 落库字节即前缀字节：第二轮 history 首条原样复现同一图注
    assert caption_part in stub.requests[1].messages[0].content


async def test_vision_path_keeps_v1_raw_content(wired_service, patch_provider_builder):
    """VLM 路径零行为变化：不落图注、不调预处理器、raw_content 保持 v1 形态。"""
    from tests.fixtures.provider_stubs import StubImagePreprocessor

    stub_preprocessor = StubImagePreprocessor()
    wired_service.image_preprocessor = stub_preprocessor
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )
    stored = wired_service.store.list_recent_conversation_messages(1001, 10)
    raw = [r["raw_content"] for r in stored if r["role"] == "user"][0]
    assert raw == "看看这张图"
    assert stub_preprocessor.call_count == 0


async def test_forward_captions_persist_byte_stable_across_turns(wired_service, patch_provider_builder):
    """转发图注并入 normalized_forward_text：当轮渲染与落库同源，下轮 history 字节复现。"""
    from tests.fixtures.provider_stubs import StubImagePreprocessor

    wired_service.config.providers["openai-main"].non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="看看这个转发",
        forward_text="1. Alice（QQ 10001）：转发内容",
        forward_image_urls=["https://example.test/forward.png"],
        recent_messages=[],
    )
    desc = "stub description of https://example.test/forward.png"
    # 当轮渲染：图注并入转发 speaker 行，不再出现独立的视觉转述行
    turn1_content = stub.requests[0].messages[-1].content
    assert desc in turn1_content
    assert "视觉转述" not in turn1_content
    # 落库：raw_content 含并入后的转发图注行
    stored = wired_service.store.list_recent_conversation_messages(1001, 10)
    raw = [r["raw_content"] for r in stored if r["role"] == "user"][0]
    assert "[转发图片 1 张：" in raw
    assert desc in raw

    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="n", prompt="第二轮", recent_messages=[],
    )
    assert len(stub.requests) == 2
    # 落库字节即前缀字节：第二轮 history 首条原样复现转发图注
    assert "[转发图片 1 张：" in stub.requests[1].messages[0].content
    assert desc in stub.requests[1].messages[0].content


async def test_recent_context_image_captions_not_persisted(wired_service, patch_provider_builder):
    """近期缓冲图片的图注不落库：那是他人消息的内容，落库会把图注记到触发者
    名下（张数虚报+归属错乱）且 recent 窗口存续期间跨轮重复累积。当轮渲染
    保留带标签的视觉转述行。"""
    from tests.fixtures.provider_stubs import StubImagePreprocessor

    wired_service.config.providers["openai-main"].non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="纯文字触发",
        recent_messages=[{
            "sender_name": "他人", "user_id": "3003",
            "text": "看看这个", "image_urls": ["https://example.test/other.png"],
        }],
        include_recent_images=True,
    )
    # 当轮渲染：近期图注以带标签的视觉转述行出现（正确归属）
    assert "stub description of https://example.test/other.png" in stub.requests[0].messages[-1].content
    # 落库：触发者的 raw_turn 不含他人图注
    stored = wired_service.store.list_recent_conversation_messages(1001, 10)
    raw = [r["raw_content"] for r in stored if r["role"] == "user"][0]
    assert raw == "纯文字触发"


async def test_media_meter_wired_with_attached_image_count(wired_service, patch_provider_builder, monkeypatch):
    """媒体账本 service 接线：VLM 带图轮计 1；非 VLM 剥离后计 0（0 是有效信号）。"""
    import quickquip.llm.service as svc
    from quickquip.llm.usage import media_meter as real_media_meter

    from tests.fixtures.provider_stubs import StubImagePreprocessor

    seen: list[int | None] = []

    def spy(count):
        seen.append(count)
        return real_media_meter(count)

    monkeypatch.setattr(svc, "media_meter", spy)
    patch_provider_builder(lambda provider: StubProviderClient())

    # VLM 路径：图随请求附带
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="看看这张图",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )
    assert seen == [1]

    # 非 VLM 路径：图被剥离转图注，附带数恒 0
    wired_service.config.providers["openai-main"].non_vision_models.append("gpt-alt")
    wired_service.image_preprocessor = StubImagePreprocessor()
    await wired_service.generate_reply(
        group_id=1001,
        user_id=2002,
        sender_name="n",
        prompt="再看看",
        image_urls=["https://example.test/cat.png"],
        recent_messages=[],
    )
    assert seen == [1, 0]


# ── 【现场】补丁（PR-B3）─────────────────────────────────────────────


async def test_scene_patch_self_served_with_history_dedup(wired_service, patch_provider_builder):
    """群聊不传 recent_messages 时 service 自取补丁：
    history 已覆盖的 message_id 与当前触发消息都不进【现场】。"""
    buf = wired_service.recent_message_buffer
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    wired_service.store.append_conversation_message(
        "1001", "3003", "user", "已落库的旧话", sender_name="丁", message_id="m-old",
    )
    buf.add_message(1001, "3003", "丁", "丁", "已落库的旧话", message_id="m-old")
    buf.add_message(1001, "4004", "丙", "4s", "真现场发言", message_id="m-live")
    buf.add_message(1001, "2002", "乙", "镜子", "触发问题", message_id="m-cur")

    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙",
        prompt="触发问题", message_id="m-cur",
    )

    content = stub.requests[-1].messages[-1].content
    assert "【现场】" in content
    live_seg = content[content.index("【现场】"):]
    assert "真现场发言" in live_seg
    # 已落库消息只出现在 history 一侧，不在【现场】重复
    assert "已落库的旧话" not in live_seg
    # 当前触发消息不进入【现场】（只以【当前提问】身份出现一次）
    assert content.count("触发问题") == 1


async def test_scene_patch_explicit_empty_list_disables_self_serve(wired_service, patch_provider_builder):
    """recent_messages=[] 是显式空（测试注入口语义），不触发自取。"""
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙", prompt="问题", recent_messages=[],
    )

    assert "【现场】" not in stub.requests[-1].messages[-1].content


async def test_scene_patch_incremental_across_turns(wired_service, patch_provider_builder, monkeypatch):
    """跨轮增量：已服役且超出滑动保底窗的消息不再进入下一轮补丁。"""
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=3600)
    wired_service.bind_recent_message_buffer(buf)
    stub = _RecordingStub()
    patch_provider_builder(lambda provider: stub)

    now = [1000.0]
    monkeypatch.setattr("quickquip.common.recent_message_buffer.time", lambda: now[0])

    buf.add_message(1001, "3003", "丁", "丁", "首轮现场", message_id="m-t1")
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙", prompt="第一轮", message_id="m-q1",
    )
    now[0] += 400  # 超出 recent_context_floor_seconds=300 的保底窗
    buf.add_message(1001, "4004", "丙", "4s", "二轮新发言", message_id="m-t2")
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙", prompt="第二轮", message_id="m-q2",
    )

    first = stub.requests[0].messages[-1].content
    second = stub.requests[1].messages[-1].content
    assert "首轮现场" in first
    assert "【现场】" in second
    second_live = second[second.index("【现场】"):]
    assert "二轮新发言" in second_live
    assert "首轮现场" not in second_live


async def test_synthetic_turn_persists_paired_row_without_auto_memory(
    llm_service, patch_provider_builder, monkeypatch
):
    """合成触发（唤醒/cron 同形态）：store_user_message=True + trigger_auto_memory=False
    → user/assistant 成对落库（assistant 不再孤行），auto_memory 不调度。"""
    import asyncio

    llm_service.config.runtime.auto_memory_enabled = True
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)
    memory_calls = []

    async def _spy(**kwargs):
        memory_calls.append(kwargs)

    monkeypatch.setattr(llm_service, "_extract_auto_memory", _spy)

    await llm_service.generate_reply(
        group_id=1001,
        user_id="boredom_timer",
        sender_name="系统",
        prompt="【内部触发说明】群聊冷了，来热热场。",
        recent_messages=[],
        raw_user_text="【自动唤醒】群内冷场已超过 45 分钟",
        store_user_message=True,
        trigger_auto_memory=False,
        message_id=None,
    )
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    rows = llm_service.store.list_recent_conversation_messages("1001", 10)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["user_id"] == "boredom_timer"
    assert "【自动唤醒】群内冷场已超过 45 分钟" in (rows[0]["raw_content"] or rows[0]["content"])
    assert memory_calls == []


async def test_cron_turn_persists_structured_summary(llm_service, patch_provider_builder):
    """cron 合成行落库结构化摘要（【定时消息】前缀），不抄任务指令全文进 raw。"""
    stub = StubProviderClient()
    patch_provider_builder(lambda provider: stub)

    await llm_service.generate_reply(
        group_id=1001,
        user_id="scheduled_timer",
        sender_name="定时任务",
        prompt="【内部触发说明】…【任务指令】" + "很长" * 100,
        recent_messages=[],
        raw_user_text="【定时消息】按 0 9 * * * 发送：" + "很长" * 30,
        store_user_message=True,
        trigger_auto_memory=False,
        message_id=None,
    )

    rows = llm_service.store.list_recent_conversation_messages("1001", 10)
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["user_id"] == "scheduled_timer"
    assert rows[0]["content"].startswith("【定时消息】按 0 9 * * * 发送：")


def test_synthetic_user_id_excluded_from_participants(llm_service):
    """非数字 user_id（合成触发源）不进信封参与者；数字 id 与名字回退照常。"""
    participants = llm_service._collect_known_participants(
        user_id="boredom_timer",
        sender_name="系统",
        history=[
            {"role": "user", "user_id": "boredom_timer", "sender_name": "系统", "canonical_name": ""},
            {"role": "user", "user_id": "2002", "sender_name": "乙", "canonical_name": "镜子"},
            {"role": "assistant", "content": "reply"},
        ],
        recent_messages=[
            {"user_id": "scheduled_timer", "sender_name": "定时任务", "canonical_name": ""},
            {"user_id": "", "sender_name": "无名氏", "canonical_name": ""},
        ],
        quoted_sender_name="",
        quoted_user_id="",
        group_id="1001",
    )
    ids = [p["user_id"] for p in participants]
    names = [p["sender_name"] for p in participants]
    assert "boredom_timer" not in ids
    assert "scheduled_timer" not in ids
    assert "2002" in ids
    assert "无名氏" in names  # 空 id 的名字回退不受过滤影响


async def test_patch_meter_wired_with_scene_patch_tokens(wired_service, patch_provider_builder, monkeypatch):
    """补丁账本 service 接线：自取补丁轮计【现场】估算值；显式空注入轮计 None。"""
    import quickquip.llm.service as svc
    from quickquip.llm.token_estimate import estimate_tokens
    from quickquip.llm.usage import patch_meter as real_patch_meter

    seen: list[int | None] = []

    def spy(tokens):
        seen.append(tokens)
        return real_patch_meter(tokens)

    monkeypatch.setattr(svc, "patch_meter", spy)
    patch_provider_builder(lambda provider: StubProviderClient())

    # 独立 buffer（fixture 预置的无 id 种子消息会一并进补丁，干扰求和断言）
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=3600)
    wired_service.bind_recent_message_buffer(buf)
    buf.add_message(1001, "3003", "丁", "丁", "现场一句", message_id="m-p1")
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙", prompt="问题", message_id="m-q1",
    )
    await wired_service.generate_reply(
        group_id=1001, user_id=2002, sender_name="乙", prompt="显式空", recent_messages=[],
    )

    assert seen[0] == estimate_tokens("现场一句")
    assert seen[1] is None
