"""Request cancellation and trigger attribution across the real service/store boundary."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from quickquip.llm.agent_records import TriggerKind
from quickquip.llm.provider import LLMResponse
from quickquip.llm.tools import LLMToolCall
from tests.fixtures.agent_loop import CollectingSink


async def _reply(service, *, private=False, **kwargs):
    args = dict(user_id="2002", sender_name="Tester", prompt="Check the result.", **kwargs)
    if private:
        return await service.generate_private_reply(**args)
    return await service.generate_reply(group_id=1001, **args)


@pytest.mark.parametrize(
    ("stage", "delivery_enabled", "private"),
    [
        ("first_provider", True, False),
        ("first_provider", False, False),
        ("first_provider", True, True),
        ("next_provider", True, False),
        ("tool", True, False),
        ("delivery", True, False),
    ],
)
async def test_cancellation_closes_loop_preserves_facts_and_allows_next_request(
    llm_service, patch_provider_builder, monkeypatch, stage, delivery_enabled, private
):
    if private:
        llm_service.start_private_session(2002)
    runtime = llm_service.config.runtime
    monkeypatch.setattr(runtime, "agent_delivery_enabled", delivery_enabled)
    monkeypatch.setattr(runtime, "reply_split_threshold_chars", 120)
    monkeypatch.setattr(runtime, "reply_chunk_max_chars", 240)
    text = "A" * 120 + "\n\n" + "B" * 120 + "\n\n" + "C" * 120
    blocked = asyncio.Event()

    async def wait_for_cancellation():
        blocked.set()
        await asyncio.Future()

    async def complete(request):
        if stage == "first_provider" or client.complete.await_count == 2:
            await wait_for_cancellation()
        return LLMResponse(
            text=text, model=request.model, finish_reason="tool_calls",
            tool_calls=[
                LLMToolCall(id=f"call-{i}", name="get_identity", arguments_json='{"query":"2002"}')
                for i in range(2)
            ],
        )

    client = AsyncMock()
    client.complete.side_effect = complete
    patch_provider_builder(lambda provider: client)
    original_execute = llm_service.tool_registry.execute

    async def execute(call, context):
        if stage == "tool" and call.id == "call-1":
            await wait_for_cancellation()
        return await original_execute(call, context)

    execute_mock = AsyncMock(side_effect=execute)
    monkeypatch.setattr(llm_service.tool_registry, "execute", execute_mock)
    sink = CollectingSink()

    async def deliver(delivery_id, payload):
        if stage == "delivery" and delivery_mock.await_count == 2:
            await wait_for_cancellation()
        return await sink(delivery_id, payload)

    delivery_mock = AsyncMock(side_effect=deliver)
    task = asyncio.create_task(
        _reply(llm_service, private=private, delivery_sink=delivery_mock)
    )
    try:
        await asyncio.wait_for(blocked.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    with llm_service.store._connect() as conn:
        loop = dict(conn.execute("SELECT * FROM agent_loops").fetchone())
        turns = [dict(row) for row in conn.execute("SELECT * FROM agent_turns")]
        tools = [dict(row) for row in conn.execute(
            "SELECT * FROM agent_tool_executions ORDER BY call_index"
        )]
        deliveries = [dict(row) for row in conn.execute(
            "SELECT * FROM agent_deliveries ORDER BY delivery_index"
        )]
        attempts = [dict(row) for row in conn.execute(
            "SELECT * FROM agent_delivery_attempts ORDER BY rowid"
        )]

    assert task.cancelled()
    assert loop["status"] == "interrupted"
    assert loop["closed_at"] is not None
    assert loop["terminal_reason"] == "request_cancelled"
    assert loop["scope_key"] == ("private:2002" if private else "1001")
    if stage == "first_provider":
        assert turns == tools == deliveries == attempts == []
        assert execute_mock.await_count == delivery_mock.await_count == 0
    else:
        assert len(turns) == 1
        assert [row["status"] for row in tools] == {
            "next_provider": ["succeeded", "succeeded"],
            "tool": ["succeeded", "indeterminate"],
            "delivery": ["not_executed", "not_executed"],
        }[stage]
        assert [row["status"] for row in deliveries] == (
            ["sent", "unknown", "skipped"] if stage == "delivery" else ["sent"] * 3
        )
        assert [row["status"] for row in attempts] == (
            ["sent", "unknown"] if stage == "delivery" else ["sent"] * 3
        )
        assert execute_mock.await_count == (0 if stage == "delivery" else 2)
        assert delivery_mock.await_count == (2 if stage == "delivery" else 3)
        assert all(row["result_json"] for row in tools if row["status"] == "succeeded")
    assert client.complete.await_count == (2 if stage == "next_provider" else 1)

    client.complete.side_effect = None
    client.complete.return_value = LLMResponse(text=text, model="gpt-test")
    next_sink = CollectingSink()
    tool_attempts_before = execute_mock.await_count
    delivery_attempts_before = delivery_mock.await_count
    result = await _reply(llm_service, private=private, delivery_sink=next_sink)

    assert result["agent_turn_row_id"] is not None
    assert result["reply"] == ("" if delivery_enabled else text)
    assert len(next_sink.deliveries) == (3 if delivery_enabled else 0)
    assert execute_mock.await_count == tool_attempts_before
    assert delivery_mock.await_count == delivery_attempts_before
    with llm_service.store._connect() as conn:
        loops = [dict(row) for row in conn.execute("SELECT * FROM agent_loops ORDER BY rowid")]
        assert len(loops) == 2
        assert loops[0] == loop
        assert loops[1]["status"] == "completed"
        assert loops[1]["closed_at"] is not None
        assert [dict(row) for row in conn.execute(
            "SELECT * FROM agent_turns WHERE loop_id = ?", (loop["loop_id"],)
        )] == turns
        assert [dict(row) for row in conn.execute(
            "SELECT * FROM agent_tool_executions ORDER BY call_index"
        )] == tools
        assert [dict(row) for row in conn.execute(
            "SELECT * FROM agent_deliveries WHERE loop_id = ? ORDER BY delivery_index",
            (loop["loop_id"],),
        )] == deliveries


@pytest.mark.parametrize(
    ("private", "trigger", "expected"),
    [
        (False, TriggerKind.GROUP_PASSIVE, "group_passive"),
        (False, TriggerKind.GROUP_DIRECT, "group_direct"),
        (False, None, "group_direct"),
        (True, TriggerKind.PRIVATE_DIRECT, "private_direct"),
        (True, None, "private_direct"),
    ],
)
async def test_request_trigger_is_persisted(
    llm_service, patch_provider_builder, private, trigger, expected
):
    if private:
        llm_service.start_private_session(2002)
    client = AsyncMock()
    client.complete.return_value = LLMResponse(text="Done.", model="gpt-test")
    patch_provider_builder(lambda provider: client)
    result = await _reply(llm_service, private=private, trigger_kind=trigger)

    assert result["reply"] == "Done."
    assert result["agent_turn_row_id"] is not None
    with llm_service.store._connect() as conn:
        row = conn.execute("SELECT trigger_kind, status FROM agent_loops").fetchone()
    assert row["trigger_kind"] == expected
    assert row["status"] == "completed"
    loops = llm_service.store.load_closed_loops("private:2002" if private else "1001")
    assert len(loops) == 1
    assert loops[0].trigger_kind == expected
