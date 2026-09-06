"""AgentRecordsStoreMixin 单测（§4 数据结构和迁移 / §5.5 恢复 / D5 保留）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from quickquip.llm.agent_records import (
    DeliveryKind,
    DeliveryPlanItem,
    DeliveryReceipt,
    DeliveryStatus,
    LoopStatus,
    MAX_LOOP_RECORD_BYTES,
    ResultRetention,
    TextPolicy,
    ToolDeclarationRecord,
    ToolExecutionStatus,
    ToolResultRecord,
    ToolSkipReason,
    TriggerKind,
    TurnOutputStatus,
    TurnResponseRecord,
)
from quickquip.llm.store import LLMStore
from quickquip.llm.store_parts.agent_records import (
    AgentStoreError,
    HistoryMutation,
    LoopHandle,
    LoopNotWritable,
    LoopRecordBudgetExceeded,
    RetentionPolicy,
    ScopeGenerationMismatch,
    StaleRevision,
    UserTriggerPayload,
)
from tests.fixtures.agent_loop import build_legacy_db, legacy_rows


@pytest.fixture
def store(tmp_path: Path) -> LLMStore:
    return LLMStore(tmp_path / "llm.db")


def _user_payload(content: str = "你好") -> UserTriggerPayload:
    return UserTriggerPayload(
        user_id="2002", sender_name="镜子", canonical_name="镜子", content=content,
        message_id="trigger-1",
    )


def _begin(store: LLMStore, scope: str = "1001") -> LoopHandle:
    return store.begin_loop(scope, 0, TriggerKind.GROUP_DIRECT, _user_payload())


def _response(text: str = "回复正文", *, tools: int = 0, native: dict | None = None) -> TurnResponseRecord:
    return TurnResponseRecord(
        text=text,
        text_policy=TextPolicy.ALLOWED,
        output_status=TurnOutputStatus.VISIBLE,
        finish_reason="stop",
        native_state=native,
    )


def _declarations(count: int) -> list[ToolDeclarationRecord]:
    return [
        ToolDeclarationRecord(
            execution_id=f"exec_{i}",
            call_index=i,
            provider_call_id=f"call_{i}",
            tool_name="get_identity",
            arguments_json='{"query":"镜子"}',
            arguments_omission_reason=None,
        )
        for i in range(count)
    ]


_chunk_seq = 0


def _chunk_plan(count: int, turn_id: str | None = None, text_len: int | None = None) -> list[DeliveryPlanItem]:
    if count == 0 or text_len is None:
        return []
    global _chunk_seq
    _chunk_seq += 1
    prefix = f"dlv{_chunk_seq}"
    return [
        DeliveryPlanItem(
            delivery_id=f"{prefix}_{i}",
            kind=DeliveryKind.TEXT_CHUNK,
            turn_id=turn_id,
            chunk_index=i,
            source_start=0,
            source_end=text_len,
        )
        for i in range(count)
    ]


# ── schema 与迁移 ─────────────────────────────────────────────────


def test_fresh_db_creates_agent_schema(store: LLMStore):
    with store._connect() as conn:
        for table in (
            "agent_scopes", "agent_loops", "agent_turns", "agent_tool_executions",
            "agent_deliveries", "agent_delivery_attempts", "agent_schema_migrations",
        ):
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None, f"缺表 {table}"
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(conversation_messages)")}
        assert {"agent_loop_id", "agent_turn_id"} <= columns


def test_migration_backfills_legacy_loops(tmp_path: Path):
    db_path = tmp_path / "llm.db"
    build_legacy_db(db_path)
    store = LLMStore(db_path)
    with store._connect() as conn:
        loops = conn.execute(
            "SELECT loop_id, trigger_kind, status, legacy, anchor_row_id FROM agent_loops ORDER BY anchor_row_id"
        ).fetchall()
        # 孤立段 + 三个 user 锚点 Loop（§4.3.3：连续 user 各自独立 Loop）
        assert [row["trigger_kind"] for row in loops] == [
            "legacy_orphan", "legacy", "legacy", "legacy",
        ]
        assert all(row["status"] == "legacy" for row in loops)
        # 原行原样保留：行数、ID、正文、message_id 不变（§4.3.4）。
        rows = conn.execute(
            "SELECT id, role, content, message_id, agent_loop_id, agent_turn_id FROM conversation_messages ORDER BY id"
        ).fetchall()
        assert len(rows) == len(legacy_rows())
        assert [row["id"] for row in rows] == list(range(1, len(legacy_rows()) + 1))
        assert all(row["agent_loop_id"] for row in rows)
        # a3（带 message_id=m3）→ sent receipt；其余 assistant → legacy_untracked。
        deliveries = conn.execute(
            "SELECT status, source_start, source_end FROM agent_deliveries"
        ).fetchall()
        statuses = sorted(row["status"] for row in deliveries)
        assert statuses == ["legacy_untracked", "legacy_untracked", "sent"]
        sent = conn.execute(
            """
            SELECT a.qq_message_id FROM agent_delivery_attempts a
            JOIN agent_deliveries d ON d.delivery_id = a.delivery_id
            WHERE d.status = 'sent'
            """
        ).fetchone()
        assert sent["qq_message_id"] == "m3"
        # 覆盖全文的源范围。
        sent_delivery = conn.execute(
            "SELECT source_start, source_end FROM agent_deliveries WHERE status='sent'"
        ).fetchone()
        a3_content = legacy_rows()[5].content
        assert (sent_delivery["source_start"], sent_delivery["source_end"]) == (0, len(a3_content))
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_is_idempotent_and_concurrent_safe(tmp_path: Path):
    db_path = tmp_path / "llm.db"
    build_legacy_db(db_path)
    LLMStore(db_path)
    LLMStore(db_path)  # 第二次打开（Bot/Web 同时首开的串行化面）
    with LLMStore(db_path)._connect() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM agent_loops").fetchone()["c"]
        versions = conn.execute("SELECT COUNT(*) c FROM agent_schema_migrations").fetchone()["c"]
    assert count == 4
    assert versions == 1


# ── Loop 生命周期 ─────────────────────────────────────────────────


def test_begin_loop_writes_user_trigger_row(store: LLMStore):
    handle = _begin(store)
    with store._connect() as conn:
        loop = conn.execute("SELECT * FROM agent_loops WHERE loop_id=?", (handle.loop_id,)).fetchone()
        user = conn.execute(
            "SELECT * FROM conversation_messages WHERE agent_loop_id=?", (handle.loop_id,)
        ).fetchone()
    assert loop["status"] == "running"
    assert loop["anchor_row_id"] == user["id"]
    assert user["role"] == "user"
    assert user["content"] == "你好"
    assert user["message_id"] == "trigger-1"


def test_second_open_loop_rejected(store: LLMStore):
    _begin(store)
    with pytest.raises(LoopNotWritable):
        store.begin_loop("1001", 0, TriggerKind.GROUP_DIRECT, _user_payload("再来"))


def test_commit_turn_atomic_write(store: LLMStore):
    handle = _begin(store)
    text = "第一段正文"
    turn_id = "turn_pre"
    record = store.commit_turn(
        handle, _response(text), _declarations(1),
        _chunk_plan(1, turn_id=turn_id, text_len=len(text)),
        turn_id=turn_id,
    )
    with store._connect() as conn:
        turn = conn.execute("SELECT * FROM agent_turns WHERE turn_id=?", (record.turn_id,)).fetchone()
        message = conn.execute(
            "SELECT * FROM conversation_messages WHERE id=?", (record.message_row_id,)
        ).fetchone()
        tools = conn.execute(
            "SELECT * FROM agent_tool_executions WHERE turn_id=?", (record.turn_id,)
        ).fetchall()
        delivery = conn.execute(
            "SELECT * FROM agent_deliveries WHERE delivery_id=?", (record.delivery_ids[0],)
        ).fetchone()
    assert turn["turn_index"] == 0
    assert message["agent_turn_id"] == record.turn_id
    assert message["content"] == text
    assert message["raw_content"] is None  # 新 assistant 行 raw_content 留空（§3.3）
    assert tools[0]["status"] == "declared"
    assert delivery["status"] == "planned"
    assert delivery["turn_id"] == record.turn_id
    parts = json.loads(turn["parts_json"])
    assert parts["version"] == 1


def test_commit_turn_rejects_dangling_part_refs(store: LLMStore):
    handle = _begin(store)
    bad_parts = ({"type": "tool_ref", "execution_id": "exec_missing"},)
    response = TurnResponseRecord(
        text="x", text_policy=TextPolicy.ALLOWED, output_status=TurnOutputStatus.VISIBLE,
        finish_reason="stop", parts=bad_parts,
    )
    with pytest.raises(AgentStoreError):
        store.commit_turn(handle, response, _declarations(0), [])
    # 事务原子性：失败后主表不留半个 Turn。
    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM conversation_messages WHERE role='assistant'"
        ).fetchone()["c"]
    assert count == 0


def test_generation_mismatch_blocks_late_writes(store: LLMStore):
    handle = _begin(store)
    store.mutate_history("1001", 0, HistoryMutation.CLEAR)
    with pytest.raises(ScopeGenerationMismatch):
        store.commit_turn(handle, _response("迟到"), _declarations(0), [])
    with pytest.raises(ScopeGenerationMismatch):
        store.begin_loop("1001", 0, TriggerKind.GROUP_DIRECT, _user_payload("过期"))


def test_mutate_history_revision_barrier(store: LLMStore):
    gen, rev = store.mutate_history("1001", 0, HistoryMutation.EDIT)
    assert (gen, rev) == (0, 1)
    with pytest.raises(StaleRevision):
        store.mutate_history("1001", 0, HistoryMutation.EDIT)
    gen2, rev2 = store.mutate_history("1001", 1, HistoryMutation.CLEAR)
    assert (gen2, rev2) == (1, 2)


# ── 工具状态 ──────────────────────────────────────────────────────


def test_tool_lifecycle_and_bounded_result(store: LLMStore):
    handle = _begin(store)
    text = "带工具的正文"
    store.commit_turn(handle, _response(text), _declarations(1), [])
    exec_id = _declarations(1)[0].execution_id
    store.mark_tool_started(handle, exec_id)
    big = "字" * (33_000)
    store.finish_tool(
        handle, exec_id,
        ToolResultRecord(content=big, is_error=False, original_bytes=len(big.encode("utf-8"))),
    )
    with store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tool_executions WHERE execution_id=?", (exec_id,)
        ).fetchone()
    result = json.loads(row["result_json"])
    assert row["status"] == "succeeded"
    assert row["result_omission_reason"] == "size_limit"
    assert result["original_bytes"] == 99_000  # "字"×33000 的 UTF-8 字节数
    assert len(result["content"].encode("utf-8")) <= 32_768
    assert result["retained_ranges"]


def test_ephemeral_result_never_persists_body(store: LLMStore):
    handle = _begin(store)
    store.commit_turn(handle, _response("查"), _declarations(1), [])
    exec_id = _declarations(1)[0].execution_id
    store.mark_tool_started(handle, exec_id)
    store.finish_tool(
        handle, exec_id,
        ToolResultRecord(content="命中正文" * 100, is_error=False, original_bytes=1200),
        result_retention=ResultRetention.EPHEMERAL,
    )
    with store._connect() as conn:
        row = conn.execute(
            "SELECT result_json, status, result_omission_reason FROM agent_tool_executions WHERE execution_id=?",
            (exec_id,),
        ).fetchone()
    result = json.loads(row["result_json"])
    assert result["content"] == ""  # D1：查询正文不入业务持久层
    assert row["status"] == "succeeded"  # 省略不改写工具成功事实
    assert row["result_omission_reason"] == "ephemeral_policy"


def test_not_executed_terminal_with_reason(store: LLMStore):
    handle = _begin(store)
    store.commit_turn(handle, _response("超限"), _declarations(1), [])
    exec_id = _declarations(1)[0].execution_id
    store.finish_tool(handle, exec_id, None, status=ToolExecutionStatus.NOT_EXECUTED,
                      skip_reason=ToolSkipReason.ROUND_LIMIT)
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status, result_json FROM agent_tool_executions WHERE execution_id=?", (exec_id,)
        ).fetchone()
    assert row["status"] == "not_executed"
    assert json.loads(row["result_json"])["detail"] == "limit"


# ── 交付 ─────────────────────────────────────────────────────────


def test_delivery_attempt_and_lookup(store: LLMStore):
    handle = _begin(store)
    text = "要发出去的正文"
    record = store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(1, text_len=len(text)))
    delivery_id = record.delivery_ids[0]
    attempt = store.start_delivery(handle, delivery_id)
    store.finish_delivery(attempt, DeliveryReceipt(status=DeliveryStatus.SENT, message_id="qq-1"))
    found = store.lookup_delivery("1001", "qq-1")
    assert found is not None
    assert found["delivery_id"] == delivery_id
    assert found["source_start"] == 0
    # scope 谓词：别的 scope 查不到。
    assert store.lookup_delivery("1002", "qq-1") is None
    with store._connect() as conn:
        delivery = conn.execute(
            "SELECT status FROM agent_deliveries WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
    assert delivery["status"] == "sent"


def test_attempt_terminal_not_overwritten(store: LLMStore):
    handle = _begin(store)
    text = "正文"
    record = store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(1, text_len=len(text)))
    attempt = store.start_delivery(handle, record.delivery_ids[0])
    store.finish_delivery(attempt, DeliveryReceipt(status=DeliveryStatus.FAILED, error_code="timeout"))
    store.finish_delivery(attempt, DeliveryReceipt(status=DeliveryStatus.SENT, message_id="late"))
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status FROM agent_delivery_attempts WHERE attempt_id=?", (attempt.attempt_id,)
        ).fetchone()
    assert row["status"] == "failed"


def test_unknown_upgrade_on_trusted_receipt(store: LLMStore):
    handle = _begin(store)
    text = "正文"
    record = store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(1, text_len=len(text)))
    attempt = store.start_delivery(handle, record.delivery_ids[0])
    # 模拟崩溃恢复：close_loop 把 sending 收敛为 unknown。
    store.close_loop(handle, LoopStatus.INTERRUPTED, "test")
    store.finish_delivery(attempt, DeliveryReceipt(status=DeliveryStatus.SENT, message_id="late-ok"))
    with store._connect() as conn:
        attempt_row = conn.execute(
            "SELECT status, qq_message_id FROM agent_delivery_attempts WHERE attempt_id=?",
            (attempt.attempt_id,),
        ).fetchone()
        delivery_row = conn.execute(
            "SELECT status FROM agent_deliveries WHERE delivery_id=?", (attempt.delivery_id,)
        ).fetchone()
    assert attempt_row["status"] == "sent"
    assert attempt_row["qq_message_id"] == "late-ok"
    assert delivery_row["status"] == "sent"


# ── 关闭与恢复 ────────────────────────────────────────────────────


def test_close_loop_sweeps_and_is_idempotent(store: LLMStore):
    handle = _begin(store)
    text = "多段"
    record = store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(2, text_len=len(text)))
    store.start_delivery(handle, record.delivery_ids[0])
    store.close_loop(handle, LoopStatus.INTERRUPTED, "delivery_failed")
    with store._connect() as conn:
        statuses = {
            row["delivery_id"]: row["status"]
            for row in conn.execute(
                "SELECT delivery_id, status FROM agent_deliveries WHERE loop_id=?", (handle.loop_id,)
            )
        }
    assert statuses[record.delivery_ids[0]] == "unknown"  # 已在途，回执未落库
    assert statuses[record.delivery_ids[1]] == "skipped"  # 未开始
    # 幂等关闭。
    store.close_loop(handle, LoopStatus.COMPLETED, "again")
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status, terminal_reason FROM agent_loops WHERE loop_id=?", (handle.loop_id,)
        ).fetchone()
    assert row["terminal_reason"] == "delivery_failed"


def test_recover_unfinished_loops(store: LLMStore):
    # Loop A：provider 未提交响应（无 Turn）。
    handle_a = _begin(store)
    # Loop B：Turn 已提交，工具 declared/running，交付 planned。
    handle_b = store.begin_loop("1002", 0, TriggerKind.PRIVATE_DIRECT, _user_payload("私聊"))
    text = "正文"
    store.commit_turn(handle_b, _response(text), _declarations(2), _chunk_plan(1, text_len=len(text)))
    exec_ids = [d.execution_id for d in _declarations(2)]
    store.mark_tool_started(handle_b, exec_ids[0])

    report = store.recover_unfinished_loops()

    assert set(report.closed_loops) == {handle_a.loop_id, handle_b.loop_id}
    assert report.tools_not_executed == (exec_ids[1],)
    assert report.tools_indeterminate == (exec_ids[0],)
    assert len(report.deliveries_skipped) == 1  # planned 交付收敛为 skipped 并入报告
    assert report.deliveries_unknown == ()
    with store._connect() as conn:
        statuses = {
            row["loop_id"]: (row["status"], row["terminal_reason"])
            for row in conn.execute("SELECT loop_id, status, terminal_reason FROM agent_loops")
        }
    for loop_id in (handle_a.loop_id, handle_b.loop_id):
        assert statuses[loop_id] == ("interrupted", "process_recovery")
    # 幂等：再跑一遍无新变化。
    again = store.recover_unfinished_loops()
    assert again.closed_loops == ()


# ── 读取 ─────────────────────────────────────────────────────────


def test_load_closed_loops_returns_complete_records(store: LLMStore):
    handle = _begin(store)
    text = "完整正文"
    record = store.commit_turn(handle, _response(text), _declarations(1), _chunk_plan(1, text_len=len(text)))
    store.close_loop(handle, LoopStatus.COMPLETED, None)
    loops = store.load_closed_loops("1001")
    assert len(loops) == 1
    loop = loops[0]
    assert loop.loop_id == handle.loop_id
    assert loop.user_row["content"] == "你好"
    assert len(loop.turns) == 1
    turn = loop.turns[0]
    assert turn.text == text
    assert turn.tools[0].tool_name == "get_identity"
    assert loop.deliveries[0].delivery_id == record.delivery_ids[0]
    # running loop 不出现。
    _begin(store)
    assert len(store.load_closed_loops("1001")) == 1


# ── 字节预算与保留 ────────────────────────────────────────────────


def test_loop_record_budget_exceeded(store: LLMStore, monkeypatch):
    import quickquip.llm.store_parts.agent_records as agent_store_module

    monkeypatch.setattr(agent_store_module, "MAX_LOOP_RECORD_BYTES", 100)
    handle = _begin(store)
    big_text = "长" * 200
    with pytest.raises(LoopRecordBudgetExceeded):
        store.commit_turn(handle, _response(big_text), _declarations(0), [])
    # 失败即回滚：主表不留行。
    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) c FROM conversation_messages WHERE role='assistant'"
        ).fetchone()["c"]
    assert count == 0
    assert MAX_LOOP_RECORD_BYTES == 8_388_608  # 常量本身未被改


def test_prune_closed_loops_by_age_and_count(store: LLMStore):
    for i in range(4):
        handle = store.begin_loop("1001", 0, TriggerKind.GROUP_DIRECT, _user_payload(f"问{i}"))
        text = f"答{i}"
        store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(1, text_len=len(text)))
        store.close_loop(handle, LoopStatus.COMPLETED, None)
    # 数量上限 2：清最旧的两个。
    report = store.prune_closed_loops("1001", active_anchors=[], policy=RetentionPolicy(retention_days=30, max_loops=2, max_bytes=64 * 1024 * 1024))
    assert len(report.deleted_loop_ids) == 2
    remaining = store.load_closed_loops("1001")
    assert len(remaining) == 2
    # 整 Loop 删除：主表行也一并清理。
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT content FROM conversation_messages WHERE role='user' ORDER BY id"
        ).fetchall()
    assert [row["content"] for row in rows] == ["问2", "问3"]


def test_prune_respects_active_epoch_floor(store: LLMStore):
    handles = []
    for i in range(4):
        handle = store.begin_loop("1001", 0, TriggerKind.GROUP_DIRECT, _user_payload(f"问{i}"))
        text = f"答{i}"
        store.commit_turn(handle, _response(text), _declarations(0), _chunk_plan(1, text_len=len(text)))
        store.close_loop(handle, LoopStatus.COMPLETED, None)
        handles.append(handle)
    # 活动纪元从第 3 个 Loop 开始：最旧两个可删，其后受保护。
    floor = handles[2]
    with store._connect() as conn:
        anchor = conn.execute(
            "SELECT anchor_row_id FROM agent_loops WHERE loop_id=?", (floor.loop_id,)
        ).fetchone()["anchor_row_id"]
    report = store.prune_closed_loops(
        "1001", active_anchors=[anchor],
        policy=RetentionPolicy(retention_days=30, max_loops=1, max_bytes=64 * 1024 * 1024),
    )
    assert len(report.deleted_loop_ids) == 2
    assert len(store.load_closed_loops("1001")) == 2
