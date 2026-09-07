"""历史重放投影单测（§7.2/§7.4 兼容矩阵的 Phase C 切面）。"""
from __future__ import annotations

from dataclasses import replace

import pytest

from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.history_projection import (
    HistoryProjectionError,
    PATH_ARCHIVE,
    PATH_NATIVE,
    PATH_STRUCTURED,
    missing_result_explanation,
    project_loops,
    stable_wire_tool_call_id,
)
from quickquip.llm.store_parts.agent_records import (
    LoadedLoop,
    LoadedToolExecution,
    LoadedTurn,
)

OWNER = ResponseOwner(
    provider_id="p1",
    protocol="claude",
    wire_model="m1",
    display_model="m1",
    endpoint_fingerprint="ef-1",
    profile_fingerprint="pf-1",
)

OTHER_OWNER = replace(OWNER, endpoint_fingerprint="ef-2", wire_model="m2")


def _owner_dict(owner: ResponseOwner) -> dict:
    return {
        "provider_id": owner.provider_id,
        "protocol": owner.protocol,
        "wire_model": owner.wire_model,
        "display_model": owner.display_model,
        "endpoint_fingerprint": owner.endpoint_fingerprint,
        "profile_fingerprint": owner.profile_fingerprint,
    }


def _native_state(owner: ResponseOwner, blocks: list[dict]) -> dict:
    return {"version": 1, "owner": _owner_dict(owner), "blocks": blocks}


def _tool_exec(
    execution_id: str,
    *,
    status: str = "succeeded",
    result: dict | None = None,
    arguments_json: str | None = '{"query":"镜子"}',
    retention: str = "bounded",
) -> LoadedToolExecution:
    if result is None and status == "succeeded":
        result = {
            "version": 1, "content": "镜子是群友。", "is_error": False,
            "original_bytes": 15, "retained_ranges": [[0, 5]], "media_descriptions": [],
        }
    return LoadedToolExecution(
        execution_id=execution_id,
        call_index=int(execution_id.rsplit("_", 1)[-1]),
        provider_call_id=f"call_{execution_id}",
        tool_name="get_identity",
        arguments_json=arguments_json,
        arguments_omission_reason=None,
        status=status,
        result=result,
        result_retention=retention,
        result_omission_reason=None,
    )


def _turn(
    turn_id: str,
    *,
    text: str = "先查一下。",
    tools: tuple[LoadedToolExecution, ...] = (),
    native_state: dict | None = None,
    owner: dict | None = None,
) -> LoadedTurn:
    return LoadedTurn(
        turn_id=turn_id,
        turn_index=int(turn_id.rsplit("_", 1)[-1]),
        message_row_id=100 + int(turn_id.rsplit("_", 1)[-1]),
        text=text,
        parts=({"type": "text_ref", "start": 0, "end": len(text), "origin": "model"},),
        native_state=native_state,
        native_omission_reason=None,
        owner=owner,
        finish_reason="tool_calls" if tools else "stop",
        text_policy="allowed",
        output_status="visible",
        delivery_policy="all_turns",
        tools=tools,
        deliveries=(),
    )


def _loop(
    loop_id: str,
    turns: tuple[LoadedTurn, ...],
    *,
    trigger: str = "K甲赛况如何？",
) -> LoadedLoop:
    return LoadedLoop(
        loop_id=loop_id,
        scope_key="1001",
        anchor_row_id=1,
        trigger_kind="group_direct",
        started_at="2026-09-01T00:00:00+00:00",
        closed_at="2026-09-01T00:01:00+00:00",
        status="completed",
        terminal_reason=None,
        legacy=False,
        replay_revision=0,
        record_bytes=100,
        user_row={"content": trigger, "role": "user"},
        turns=turns,
        deliveries=(),
    )


CLAUDE_SIGNED_BLOCKS = [
    {"type": "thinking", "thinking": "先核对榜单。", "signature": "sig-a"},
    {"type": "text", "text": "先查一下。"},
    {"type": "tool_use", "id": "call_exec_0", "name": "get_identity", "input": {"query": "镜子"}},
]

GEMINI_PARTS = [
    {"text": "检索线索。", "thoughtSignature": "ts-a", "thought": True},
    {"text": "先查一下。"},
    {"functionCall": {"id": "gemini_tool_1", "name": "get_identity", "args": {"query": "镜子"}}},
]


# ── 同 owner：原生路径 ─────────────────────────────────────────────


def test_claude_same_owner_replays_native_blocks_with_signatures():
    loop = _loop(
        "loop_1",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(OWNER, CLAUDE_SIGNED_BLOCKS),
               owner=_owner_dict(OWNER)),),
    )
    result = project_loops([loop], target=OWNER, protocol="claude")
    assert result.decisions[0].path == PATH_NATIVE
    assistant = [m for m in result.messages if m.role == "assistant"][0]
    assert assistant.native_content == CLAUDE_SIGNED_BLOCKS
    tool_messages = [m for m in result.messages if m.role == "tool"]
    # 原生路径保持原 call ID 与签名关联（§7.4）。
    assert tool_messages[0].tool_call_id == "call_exec_0"


def test_gemini_same_owner_replays_parts_in_order():
    gemini_owner = replace(OWNER, protocol="gemini")
    loop = _loop(
        "loop_1",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(gemini_owner, GEMINI_PARTS),
               owner=_owner_dict(gemini_owner)),),
    )
    result = project_loops([loop], target=gemini_owner, protocol="gemini")
    assert result.decisions[0].path == PATH_NATIVE
    assistant = [m for m in result.messages if m.role == "assistant"][0]
    assert assistant.native_content == GEMINI_PARTS
    assert assistant.native_content[0]["thoughtSignature"] == "ts-a"


# ── 跨 owner / 缺签名：降级 ───────────────────────────────────────


def test_claude_owner_mismatch_degrades_to_archive_not_forged():
    loop = _loop(
        "loop_1",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(OWNER, CLAUDE_SIGNED_BLOCKS),
               owner=_owner_dict(OWNER)),),
    )
    result = project_loops([loop], target=OTHER_OWNER, protocol="claude")
    decision = result.decisions[0]
    assert decision.path == PATH_ARCHIVE
    assert decision.reason == "owner_mismatch_claude_signed_history"
    # 无签名伪造：档案里没有任何 thinking/signature 或 tool_use。
    for message in result.messages:
        assert not message.thinking_blocks
        assert message.native_content is None
        assert not message.tool_calls


def test_claude_missing_signature_degrades_to_archive():
    broken = [
        {"type": "thinking", "thinking": "签名丢了。", "signature": ""},
        {"type": "tool_use", "id": "call_exec_0", "name": "get_identity", "input": {}},
    ]
    loop = _loop(
        "loop_1",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(OWNER, broken),
               owner=_owner_dict(OWNER)),),
    )
    result = project_loops([loop], target=OWNER, protocol="claude")
    assert result.decisions[0].path == PATH_ARCHIVE
    assert result.decisions[0].reason == "native_structure_invalid"


def test_gemini_owner_mismatch_uses_structured_without_signed_parts():
    gemini_owner = replace(OWNER, protocol="gemini")
    other_gemini = replace(OTHER_OWNER, protocol="gemini")
    loop = _loop(
        "loop_1",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(gemini_owner, GEMINI_PARTS),
               owner=_owner_dict(gemini_owner)),),
    )
    result = project_loops([loop], target=other_gemini, protocol="gemini")
    assert result.decisions[0].path == PATH_STRUCTURED
    assert result.decisions[0].reason == "owner_mismatch"
    assistant = [m for m in result.messages if m.role == "assistant"][0]
    # 通用路径去掉不具备有效来源的原生推理（无 gemini_part）。
    assert assistant.native_content is None
    assert not assistant.thinking_blocks
    assert assistant.tool_calls[0].name == "get_identity"


def test_openai_owner_match_keeps_reasoning_cross_owner_drops():
    openai_owner = replace(OWNER, protocol="openai")
    blocks = [{"type": "reasoning", "reasoning_content": "解题思路。"}]
    loop = _loop(
        "loop_1",
        (_turn("turn_0", native_state=_native_state(openai_owner, blocks),
               owner=_owner_dict(openai_owner)),),
    )
    kept = project_loops([loop], target=openai_owner, protocol="openai")
    assistant = [m for m in kept.messages if m.role == "assistant"][0]
    assert kept.decisions[0].path == PATH_STRUCTURED
    assert assistant.thinking_blocks == blocks

    other_openai = replace(OTHER_OWNER, protocol="openai")
    dropped = project_loops([loop], target=other_openai, protocol="openai")
    assistant2 = [m for m in dropped.messages if m.role == "assistant"][0]
    assert not assistant2.thinking_blocks


# ── 稳定 wire ID 与配对 ───────────────────────────────────────────


def test_structured_path_disambiguates_duplicate_provider_call_ids():
    # 跨 Turn 重复 call_0（§3.1：provider call_id 只在批次内有意义）。
    loop = _loop(
        "loop_1",
        (
            _turn("turn_0", tools=(_tool_exec("exec_0"),)),
            _turn("turn_1", tools=(_tool_exec("exec_1"),)),
        ),
    )
    result = project_loops([loop], target=None, protocol="openai")
    assert result.decisions[0].path == PATH_STRUCTURED
    wire_ids = [m.tool_call_id for m in result.messages if m.role == "tool"]
    assert len(wire_ids) == 2
    assert wire_ids[0] != wire_ids[1]
    # 同输入同输出（确定性切分契约的投影面）。
    again = project_loops([loop], target=None, protocol="openai")
    assert [m.tool_call_id for m in again.messages if m.role == "tool"] == wire_ids


def test_stable_wire_tool_call_id_is_deterministic_and_distinct():
    a = stable_wire_tool_call_id("loop_1", "turn_0", 0)
    assert a == stable_wire_tool_call_id("loop_1", "turn_0", 0)
    assert a != stable_wire_tool_call_id("loop_1", "turn_1", 0)
    assert a != stable_wire_tool_call_id("loop_2", "turn_0", 0)


def test_orphan_result_fails_before_sending():
    dangling = _tool_exec("exec_0", status="declared")
    loop = _loop("loop_1", (_turn("turn_0", tools=(dangling,)),))
    with pytest.raises(HistoryProjectionError):
        project_loops([loop], target=None, protocol="openai")


# ── 缺失结果的确定说明（§5.5） ────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        ("not_executed", "未执行"),
        ("failed", "执行失败"),
        ("indeterminate", "结果未知"),
        ("succeeded", "结果正文按政策未保留"),
    ],
)
def test_missing_result_explanations_are_deterministic(status, fragment):
    result_payload = {"detail": "limit"} if status == "not_executed" else None
    execution = _tool_exec("exec_0", status=status, result=result_payload)
    text = missing_result_explanation(execution)
    assert fragment in text
    assert "get_identity" in text


def test_ephemeral_tool_result_replays_as_explanation_only():
    ephemeral = _tool_exec(
        "exec_0",
        status="succeeded",
        retention="ephemeral",
        result={
            "version": 1, "content": "", "is_error": False,
            "original_bytes": 1200, "retained_ranges": [],
            "media_descriptions": [], "retention": "ephemeral",
        },
    )
    loop = _loop("loop_1", (_turn("turn_0", tools=(ephemeral,), native_state=None),))
    result = project_loops([loop], target=None, protocol="openai")
    tool_message = [m for m in result.messages if m.role == "tool"][0]
    assert tool_message.content == missing_result_explanation(ephemeral)
    assert "命中" not in tool_message.content


def test_legacy_orphan_loop_uses_host_note_trigger():
    loop = LoadedLoop(
        loop_id="legacy_orphan_1",
        scope_key="1001",
        anchor_row_id=1,
        trigger_kind="legacy_orphan",
        started_at="t",
        closed_at="t",
        status="legacy",
        terminal_reason=None,
        legacy=True,
        replay_revision=0,
        record_bytes=1,
        user_row={},
        turns=(_turn("turn_0", text="开场白。"),),
        deliveries=(),
    )
    result = project_loops([loop], target=None, protocol="openai")
    first_user = [m for m in result.messages if m.role == "user"][0]
    assert "原始触发消息未保留" in first_user.content


def test_archive_path_summarizes_tool_states():
    indeterminate = _tool_exec("exec_0", status="indeterminate", result=None)
    ok = _tool_exec("exec_1")
    loop = _loop(
        "loop_1",
        (_turn("turn_0", text="正文A。", tools=(indeterminate, ok)),),
    )
    result = project_loops(
        [loop], target=OTHER_OWNER, protocol="claude"
    )  # 无原生 → owner 未知路径也走档案判定？此 loop 无原生，decision 仍需可观测
    archive_messages = [m for m in result.messages if m.role == "assistant"]
    blob = "\n".join(m.content for m in archive_messages)
    assert "Turn 0" in blob
    assert "indeterminate×1" in blob
    assert "succeeded×1" in blob


# ── owner 指纹（provider/owner.py） ───────────────────────────────


def test_endpoint_fingerprint_strips_sensitive_query():
    from quickquip.llm.provider.owner import endpoint_fingerprint, normalize_endpoint

    with_key = "https://api.example.test/v1/models/gemini-pro:generateContent?key=SECRET&alt=json"
    without_key = "https://api.example.test/v1/models/gemini-pro:generateContent?alt=json"
    assert "SECRET" not in normalize_endpoint(with_key)
    assert endpoint_fingerprint(with_key) == endpoint_fingerprint(without_key)
    # 路由参数参与指纹（?beta=true）。
    beta = "https://api.example.test/v1/messages?beta=true"
    plain = "https://api.example.test/v1/messages"
    assert endpoint_fingerprint(beta) != endpoint_fingerprint(plain)


def test_wire_model_resolution_honors_extra_body_override():
    from quickquip.llm.config import ProviderConfig
    from quickquip.llm.provider.owner import resolve_wire_model

    config = ProviderConfig(
        id="p1", protocol="openai", base_url="https://e.test/v1",
        api_key_env="K", default_model="display-a", models=["display-a", "wire-b"],
    )
    assert resolve_wire_model(config, "display-a") == "display-a"
    config.extra_body = {"model": "wire-b"}
    assert resolve_wire_model(config, "display-a") == "wire-b"
