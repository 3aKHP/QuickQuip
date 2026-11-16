"""Persisted display projection, source coordinates, replay and cleanup boundaries."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from quickquip.llm.agent_records import (
    DeliveryKind, DeliveryPlanItem, DeliveryReceipt, DeliveryStatus, LoopStatus,
    NativeOmissionReason, ResponseOwner, TextPolicy, TriggerKind, TurnOutputStatus,
    TurnResponseRecord,
)
from quickquip.llm.history_projection import project_loops
from quickquip.llm.provider.base import LLMResponse, LLMWebSearchReport, LLMWebSearchSource
from quickquip.llm.reply_chain import finalize_reply
from quickquip.llm.reply_presentation import prepare_reply
from quickquip.llm.service_parts.agent_runtime import RecorderConfig, TurnRecorder
from quickquip.llm.store import LLMStore
from quickquip.llm.store_parts.agent_records import LoopRecordBudgetExceeded, UserTriggerPayload


def _recorder(store, *, sink=None, scan=None, enabled=True):
    handle = store.begin_loop("scope", 0, TriggerKind.GROUP_DIRECT,
                              UserTriggerPayload(user_id="user", content="查询"))
    return TurnRecorder(store=store, handle=handle, config=RecorderConfig(
        agent_delivery_final_enabled=enabled, reply_split_threshold_chars=10,
        reply_chunk_max_chars=10, reply_max_chunks_per_loop=2,
    ), sink=sink, sensitive_scan=scan)


def _response():
    url = "https://source.example/" + "x" * 200
    citation = "(" + url + ")"
    text = "甲" * 8 + citation + "\n\n" + "乙" * 8
    owner = ResponseOwner("provider", "openai_responses", "model", "model", "ep", "pf")
    return LLMResponse(
        text=text, model="model", citation_spans=[(8, 8 + len(citation))], owner=owner,
        native_blocks=[{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text, "annotations": []}]}],
        web_search=LLMWebSearchReport(sources=[LLMWebSearchSource("站点", url)],
                                        raw_metadata={"original": url}),
    )


async def test_visible_budget_frozen_payload_replay_and_recall_use_original_ranges(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    sent = []

    async def sink(delivery_id, payload):
        sent.append(payload["text"])
        return DeliveryReceipt(DeliveryStatus.SENT, message_id=f"message-{len(sent)}")

    response = _response()
    recorder = _recorder(store, sink=sink)
    recorder.on_turn(response, declared_calls=[], executable_calls=[], has_more_rounds=False)
    # The delivery payload was frozen before the provider object was subsequently changed.
    original_native = response.native_blocks
    response.text = "changed after commit"
    await recorder.deliver_turn()
    recorder.close(LoopStatus.COMPLETED, None)
    assert sent == ["甲" * 8, "乙" * 8]

    reopened = LLMStore(store.path)
    loop = reopened.load_closed_loops("scope")[0]
    turn = loop.turns[0]
    assert "https://source.example/" in turn.text
    assert turn.native_state["blocks"] == original_native
    assert [d.display_text.rstrip() for d in turn.deliveries] == sent
    assert turn.deliveries[0].source_start == 0
    assert turn.deliveries[0].source_end == turn.deliveries[1].source_start
    assert turn.deliveries[1].source_end == len(turn.text)
    assert "".join(turn.text[d.source_start:d.source_end] for d in turn.deliveries) == turn.text
    assert turn.presentation["search"]["raw_metadata"]["original"].startswith("https:")
    assert turn.presentation["display_text"] == "甲" * 8 + "\n\n" + "乙" * 8
    assert reopened.load_closed_loops("other-scope") == []

    # Display metadata must not alter either native or portable protocol history.
    bare_loop = replace(loop, turns=(replace(turn, presentation=None),))
    for protocol, owner in [("openai_responses", response.owner), ("openai", None)]:
        actual = project_loops([loop], protocol=protocol, target=owner)
        expected = project_loops([bare_loop], protocol=protocol, target=owner)
        assert actual.messages == expected.messages
    native = project_loops([loop], protocol="openai_responses", target=response.owner)
    assert native.messages[-1].native_content == original_native

    first = turn.deliveries[0]
    assert not reopened.recall_delivery_chunk("other-scope", first.delivery_id)
    assert reopened.recall_delivery_chunk("scope", first.delivery_id)
    recalled = reopened.load_closed_loops("scope")[0].turns[0]
    assert recalled.text[:first.source_end] == "▇" * first.source_end
    assert recalled.text[first.source_end:] == turn.text[first.source_end:]
    assert recalled.native_state is None
    assert recalled.presentation is None
    assert recalled.deliveries[0].display_text is None
    assert recalled.deliveries[1].display_text == turn.deliveries[1].display_text


async def test_citation_only_reply_is_suppressed_without_sending_empty_message(tmp_path):
    async def forbidden_sink(*args):
        pytest.fail("empty citation display must not be sent")

    store = LLMStore(tmp_path / "chat.db")
    recorder = _recorder(store, sink=forbidden_sink)
    response = LLMResponse(text="[1](https://source.example/)", model="test")
    recorder.on_turn(response, declared_calls=[], executable_calls=[], has_more_rounds=False)
    await recorder.deliver_turn()
    recorder.close(LoopStatus.COMPLETED, None)
    turn = store.load_closed_loops("scope")[0].turns[0]
    assert turn.text == response.text
    assert turn.deliveries[0].status == "suppressed"
    assert recorder.summary().suppressed == 1


def test_sensitive_and_ephemeral_replies_do_not_persist_source_metadata(tmp_path):
    blocked = SimpleNamespace(
        is_loaded=True, scan=lambda text: SimpleNamespace(blocked=True, hits=[]),
    )
    finalized = finalize_reply(_response(), provider_id="test", model="model",
                               sensitive=blocked, scope_key="scope")
    assert finalized.presentation is None
    assert finalized.display.text == finalized.text
    store = LLMStore(tmp_path / "blocked.db")
    recorder = _recorder(store, scan=blocked.scan, enabled=False)
    recorder.on_turn(_response(), declared_calls=[], executable_calls=[], has_more_rounds=False)
    recorder.close(LoopStatus.COMPLETED, None)
    turn = store.load_closed_loops("scope")[0].turns[0]
    assert turn.presentation is None
    assert turn.text_policy == TextPolicy.REPLACED_BY_FILTER
    assert "source.example" not in turn.text

    ephemeral = LLMStore(tmp_path / "ephemeral.db")
    recorder = _recorder(ephemeral, enabled=False)
    recorder.on_turn(_response(), declared_calls=[], executable_calls=[], has_more_rounds=False,
                     native_state_omission=NativeOmissionReason.EPHEMERAL_POLICY)
    recorder.close(LoopStatus.COMPLETED, None)
    assert ephemeral.load_closed_loops("scope")[0].turns[0].presentation is None


def test_v4_upgrade_preserves_saved_history_and_legacy_delivery_semantics(tmp_path):
    store = LLMStore(tmp_path / "chat.db")
    recorder = _recorder(store, enabled=False)
    recorder.on_turn(LLMResponse(text="旧正文", model="test"), declared_calls=[],
                     executable_calls=[], has_more_rounds=False)
    recorder.close(LoopStatus.COMPLETED, None)
    with store._connect() as conn:
        before = [tuple(r) for r in conn.execute("SELECT id, content FROM conversation_messages")]
        for table, column in [("agent_turns", "presentation_json"),
                              ("agent_deliveries", "display_text"),
                              ("conversation_messages", "presentation_json")]:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("DELETE FROM agent_schema_migrations WHERE version=5")
    reopened = LLMStore(store.path)
    assert not reopened._unavailable
    with reopened._connect() as conn:
        after = [tuple(r) for r in conn.execute("SELECT id, content FROM conversation_messages")]
    assert after == before
    assert reopened.load_closed_loops("scope")[0].turns[0].presentation is None


@pytest.mark.parametrize("large_field", ["presentation", "display"])
def test_additional_persisted_payload_counts_toward_loop_budget(tmp_path, monkeypatch, large_field):
    from quickquip.llm.store_parts import agent_records
    store = LLMStore(tmp_path / "budget.db")
    handle = store.begin_loop("scope", 0, TriggerKind.GROUP_DIRECT,
                              UserTriggerPayload(user_id="user", content="查询"))
    monkeypatch.setattr(agent_records, "MAX_LOOP_RECORD_BYTES", 512)
    response = LLMResponse(text="事实", model="test", web_search=LLMWebSearchReport(
        raw_metadata={"payload": "字" * 1000},
    ))
    presentation = prepare_reply(response).presentation if large_field == "presentation" else None
    record = TurnResponseRecord(text="事实", text_policy=TextPolicy.ALLOWED,
                                output_status=TurnOutputStatus.VISIBLE, finish_reason="stop",
                                presentation=presentation)
    plan = [DeliveryPlanItem(delivery_id="budget-delivery", kind=DeliveryKind.TEXT_CHUNK,
                             source_start=0, source_end=2,
                             display_text="字" * 1000 if large_field == "display" else None)]
    with pytest.raises(LoopRecordBudgetExceeded):
        store.commit_turn(handle, record, [], plan)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM agent_turns").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_deliveries").fetchone()[0] == 0


def test_non_loop_session_write_preserves_sources_without_changing_history_text(tmp_path):
    store = LLMStore(tmp_path / "session.db")
    identity, _ = store.get_or_create_chat_session("scope")
    generation, _ = store.agent_scope_state("scope")
    prepared = prepare_reply(_response())
    store.append_session_reply("scope", identity, generation, user_message=None,
                                assistant_text=prepared.text,
                                assistant_presentation=prepared.presentation)
    with store._connect() as conn:
        row = conn.execute("SELECT content,presentation_json FROM conversation_messages").fetchone()
    assert row["content"] == prepared.text
    assert json.loads(row["presentation_json"])["search"] == prepared.presentation["search"]


@pytest.mark.parametrize("location", ["root", "source", "annotation"])
def test_source_metadata_does_not_bypass_native_cipher_size_limit(tmp_path, location):
    from quickquip.llm.agent_records import MAX_NATIVE_STATE_BYTES
    from quickquip.llm.provider.openai_responses.response import parse_responses_body

    store = LLMStore(tmp_path / "bounded.db")
    items = [
        {"type": "web_search_call", "id": "search", "status": "completed",
         "action": {"type": "search", "query": "test", "sources": [
             {"type": "url", "url": "https://source.example/"}]}},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "结论。", "annotations": [
             {"type": "url_citation", "url": "https://source.example/", "title": "来源"}]}]},
    ]
    payload = {"root": items[0], "source": items[0]["action"]["sources"][0],
               "annotation": items[1]["content"][0]["annotations"][0]}[location]
    payload["encrypted_content"] = "cipher-sentinel" + "x" * MAX_NATIVE_STATE_BYTES
    response = parse_responses_body({"status": "completed", "output": items},
                                    provider_id="test", fallback_model="test")
    recorder = _recorder(store, enabled=False)
    recorder.on_turn(response, declared_calls=[], executable_calls=[], has_more_rounds=False)
    recorder.close(LoopStatus.COMPLETED, None)
    turn = store.load_closed_loops("scope")[0].turns[0]
    assert turn.native_state is None
    assert turn.native_omission_reason == NativeOmissionReason.SIZE_LIMIT
    serialized = json.dumps(turn.presentation)
    assert "cipher-sentinel" not in serialized
    assert "https://source.example/" in serialized
