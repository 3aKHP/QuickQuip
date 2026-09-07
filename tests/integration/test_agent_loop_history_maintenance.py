"""阶段 D 集成测试：Loop 投影历史、预算门禁、撤回/清空/归档领域操作。"""
from __future__ import annotations

from pathlib import Path


from plugins.llm_runtime import LLMService
from quickquip.llm.provider import LLMRequest, LLMResponse
from tests.fixtures.configs import write_llm_config_bundle


def _store_service(tmp_path: Path) -> LLMService:
    paths = write_llm_config_bundle(tmp_path)
    return LLMService(**paths)


def _seed_loop_with_turn(store, scope="1001", *, text="工具轮正文", qq_id="qq-1"):
    """落一个已关闭的带工具 Loop，返回 (handle-like ids, turn_row_id)。"""
    from quickquip.llm.agent_records import (
        DeliveryKind,
        DeliveryPlanItem,
        TextPolicy,
        ToolDeclarationRecord,
        ToolResultRecord,
        TriggerKind,
        TurnOutputStatus,
        TurnResponseRecord,
    )
    from quickquip.llm.store_parts.agent_records import (
        UserTriggerPayload,
    )

    handle = store.begin_loop(
        scope, 0, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="2002", sender_name="镜子", content="查一下镜子是谁"),
    )
    turn_id = "turn_seed_0"
    record = store.commit_turn(
        handle,
        TurnResponseRecord(
            text=text,
            text_policy=TextPolicy.ALLOWED,
            output_status=TurnOutputStatus.VISIBLE,
            finish_reason="tool_calls",
            parts=({"type": "text_ref", "start": 0, "end": len(text), "origin": "model"},
                   {"type": "tool_ref", "execution_id": "exec_seed_0"}),
        ),
        [
            ToolDeclarationRecord(
                execution_id="exec_seed_0", call_index=0, provider_call_id="call_seed_0",
                tool_name="get_identity", arguments_json='{"query":"镜子"}',
                arguments_omission_reason=None,
            )
        ],
        [
            DeliveryPlanItem(
                delivery_id="dlv_seed_0", kind=DeliveryKind.TEXT_CHUNK, turn_id=turn_id,
                chunk_index=0, source_start=0, source_end=len(text),
            )
        ],
        turn_id=turn_id,
    )
    store.mark_tool_started(handle, "exec_seed_0")
    store.finish_tool(
        handle, "exec_seed_0",
        ToolResultRecord(content="镜子是群友。", is_error=False, original_bytes=18),
    )
    attempt = store.start_delivery(handle, "dlv_seed_0")
    from quickquip.llm.agent_records import DeliveryReceipt, DeliveryStatus

    store.finish_delivery(attempt, DeliveryReceipt(status=DeliveryStatus.SENT, message_id=qq_id))
    store.close_loop(handle, __import__("quickquip.llm.agent_records", fromlist=["LoopStatus"]).LoopStatus.COMPLETED, None)
    return handle, record


# ── 投影历史接入主链路 ─────────────────────────────────────────────


async def test_tool_loop_history_replays_with_tool_facts(tmp_path: Path, patch_provider_builder):
    service = _store_service(tmp_path)
    _seed_loop_with_turn(service.store)

    captured: list[LLMRequest] = []

    class SecondRoundClient:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            captured.append(request)
            return LLMResponse(text="基于历史工具事实回答。", model=request.model)

    patch_provider_builder(lambda provider: SecondRoundClient())
    await service.generate_reply(
        group_id=1001, user_id="4004", sender_name="4s", prompt="所以结论是？",
    )

    request = captured[0]
    roles = [m.role for m in request.messages]
    assert "tool" in roles  # 历史中的工具事实进入下次请求（§11.2 五轮主例断言面）
    tool_message = next(m for m in request.messages if m.role == "tool")
    assert "镜子是群友" in tool_message.content
    assistant_with_calls = [
        m for m in request.messages if m.role == "assistant" and m.tool_calls
    ]
    assert assistant_with_calls, "历史投影必须带工具调用声明"
    # user 触发与工具配对：call id 一致。
    call = assistant_with_calls[0].tool_calls[0]
    assert any(m.tool_call_id == call.id for m in request.messages if m.role == "tool")


# ── 撤回（§9.2） ──────────────────────────────────────────────────


async def test_recall_by_qq_id_masks_chunk_and_clears_evidence(tmp_path: Path):
    service = _store_service(tmp_path)
    _seed_loop_with_turn(service.store, text="这一段会被撤回。", qq_id="qq-9")

    hit = service.delete_message_from_context("1001", "qq-9")
    assert hit is True

    store = service.store
    with store._connect() as conn:
        row = conn.execute(
            "SELECT content FROM conversation_messages WHERE agent_loop_id IS NOT NULL AND role='assistant'"
        ).fetchone()
        delivery = conn.execute(
            "SELECT recall_status FROM agent_deliveries WHERE delivery_id='dlv_seed_0'"
        ).fetchone()
        execution = conn.execute(
            "SELECT result_json, result_omission_reason FROM agent_tool_executions WHERE execution_id='exec_seed_0'"
        ).fetchone()
    assert "▇" in row["content"]  # 等 code point 遮蔽，保留坐标
    assert delivery["recall_status"] == "recalled"
    assert execution["result_json"] is None  # 工具证据清理
    assert execution["result_omission_reason"] == "recall_cleanup"
    # 重复 recall 幂等：不再命中。
    assert service.delete_message_from_context("1001", "qq-9") is True  # 已 recalled，仍算命中定位


async def test_recall_user_trigger_deletes_whole_loop(tmp_path: Path):
    service = _store_service(tmp_path)
    handle, record = _seed_loop_with_turn(service.store)

    hit = service.delete_message_from_context("1001", "trigger-nonexistent")
    assert hit is False
    # 用 user 行 message_id 触发整 Loop 删除（§9.3）。
    with service.store._connect() as conn:
        anchor = conn.execute(
            "SELECT id FROM conversation_messages WHERE role='user' AND agent_loop_id=?",
            (handle.loop_id,),
        ).fetchone()["id"]
        conn.execute(
            "UPDATE conversation_messages SET message_id='trigger-1' WHERE id=?", (anchor,)
        )
        conn.commit()
    assert service.delete_message_from_context("1001", "trigger-1") is True
    loops = service.store.load_closed_loops("1001")
    assert loops == []


# ── 清空（§9.3） ──────────────────────────────────────────────────


async def test_clear_context_purges_loops_and_bumps_generation(tmp_path: Path):
    service = _store_service(tmp_path)
    _seed_loop_with_turn(service.store)
    service.clear_group_context(1001)

    store = service.store
    assert store.load_closed_loops("1001") == []
    generation, _ = store.agent_scope_state("1001")
    assert generation == 1
    with store._connect() as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) c FROM agent_turns t LEFT JOIN agent_loops l ON l.loop_id=t.loop_id WHERE l.loop_id IS NULL"
        ).fetchone()["c"]
    assert orphans == 0  # 侧表无孤儿（阶段 B 验收面）


# ── 私聊归档（§9.4） ──────────────────────────────────────────────


async def test_private_archive_roundtrip_migrates_loops(tmp_path: Path):
    service = _store_service(tmp_path)
    service.set_chat_enabled(4004, True, chat_type="private")
    handle, record = _seed_loop_with_turn(service.store, scope="private:4004")

    result = service.end_private_session(4004, save=True)
    assert result["archive_number"] == 1
    store = service.store
    migrated = store.load_closed_loops("archive:4004:1")
    assert len(migrated) == 1
    assert migrated[0].loop_id == handle.loop_id  # Loop ID 不变
    with store._connect() as conn:
        stray = conn.execute(
            "SELECT COUNT(*) c FROM conversation_messages WHERE group_id='private:4004'"
        ).fetchone()["c"]
    assert stray == 0

    resume = service.resume_private_session(4004, 1)
    assert resume["archive_number"] == 1
    restored = store.load_closed_loops("private:4004")
    assert len(restored) == 1
    assert restored[0].turns[0].text == migrated[0].turns[0].text


# ── 预算门禁（§8.3） ──────────────────────────────────────────────


async def test_request_budget_gate_blocks_oversized_input(
    tmp_path: Path, patch_provider_builder, monkeypatch
):
    service = _store_service(tmp_path)

    called = {"count": 0}

    class NeverClient:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            called["count"] += 1
            return LLMResponse(text="不应到达", model=request.model)

    patch_provider_builder(lambda provider: NeverClient())
    monkeypatch.setattr(service.config.runtime, "request_input_token_budget", 200)

    result = await service.generate_reply(
        group_id=1001, user_id="2002", sender_name="镜子",
        prompt="长" * 900,
    )
    assert called["count"] == 0  # 预算门禁先于 provider
    assert "上下文" in result["reply"]
    assert result["llm_used"] is False


def test_config_parses_budget_and_retention_fields(tmp_path: Path):
    from tests.fixtures.configs import MIN_LLM_CONFIG_TOML

    toml = MIN_LLM_CONFIG_TOML.replace(
        "tool_max_rounds = 2",
        "tool_max_rounds = 2\nrequest_input_token_budget = 50000\nagent_record_retention_days = 14",
    )
    paths = write_llm_config_bundle(tmp_path, config_toml=toml)
    service = LLMService(**paths)
    assert service.config.runtime.request_input_token_budget == 50000
    assert service.config.runtime.agent_record_retention_days == 14
    assert service.config.runtime.agent_record_max_bytes_per_scope == 67_108_864
