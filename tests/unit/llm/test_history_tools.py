"""群历史工具（#72 B 线）：handler 行为、预算与 ephemeral 记录管线。

查询本体（keyset/撤回/覆盖）由 tests/unit/chat/test_history_query.py 覆盖；
此处验证工具层语义：群聊限定、双开关门控、参数解析、成员解析、渲染、
预算扣减与临时结果落库政策（声明脱敏 + 结果省略 + 原生省略）。
"""
from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from time import time

import pytest

from quickquip.chat.archive import ChatArchive
from quickquip.chat.history_query import HistoryQueryService
from quickquip.llm.agent_records import (
    LoopStatus,
    NativeOmissionReason,
    ToolExecutionStatus,
    TriggerKind,
)
from quickquip.llm.history_tools import (
    DIRECT_HISTORY_LOOP_BUDGET,
    HistoryToolDeps,
    HistoryToolState,
    SEARCH_RESULT_TOKEN_CAP,
    parse_history_time,
    redact_read_arguments,
    redact_recent_arguments,
    redact_search_arguments,
    run_group_history_read,
    run_group_history_search,
)
from quickquip.llm.store import LLMStore
from quickquip.llm.store_parts.agent_records import (
    LoopHandle,
    UserTriggerPayload,
)
from quickquip.llm.service_parts.agent_runtime import RecorderConfig, TurnRecorder
from quickquip.llm.tools import LLMToolCall, LLMToolSpec, ToolExecutionContext
from quickquip.llm.tool_registry import ToolRegistry

G1 = "1000000000"
UTC = timezone.utc


def _context(group_id=G1, chat_type="group", history: HistoryToolState | None = None):
    return ToolExecutionContext(
        group_id=group_id,
        user_id="1000000002",
        sender_name="触发者",
        provider_id="p1",
        model="m1",
        chat_type=chat_type,
        history=history,
    )


def _deps(tmp_path: Path, *, enabled=True, speaker_map=None) -> HistoryToolDeps:
    archive = ChatArchive(tmp_path / "archive.db")
    service = HistoryQueryService(archive)

    def _resolve(group_id, query):
        return list((speaker_map or {}).get(query, ()))

    return HistoryToolDeps(
        query_service=service,
        is_enabled=lambda group_id: enabled,
        resolve_speaker=_resolve,
    )


def _archive_for(deps: HistoryToolDeps) -> ChatArchive:
    return deps.query_service.archive


@pytest.mark.asyncio
async def test_search_read_flow_with_refs_and_cursors(tmp_path: Path):
    deps = _deps(tmp_path)
    archive = _archive_for(deps)
    now = time()
    for i in range(8):
        archive.record(
            G1, f"成员{i}", f"部署讨论{i}", ts=now - i * 60,
            user_id=str(1000 + i), message_id=f"m{i}",
        )
    state = HistoryToolState()
    context = _context(history=state)

    result = await run_group_history_search(
        deps, {"terms": ["部署讨论"]}, context
    )
    assert "命中" in result and "ref hr1." in result
    assert "归档覆盖" in result
    # 续查游标：默认 5 条命中即分页
    assert "cursor：" in result

    # 提取 ref 与 cursor 做阅读 + 续查（渲染行内携带）
    ref = next(
        part for part in result.replace("（", " ").replace("）", " ").split()
        if part.startswith("hr1.")
    )
    read = await run_group_history_read(deps, {"anchor": ref}, context)
    assert "归档消息（时间升序）" in read
    assert "部署讨论" in read

    cursor = result.split("cursor：", 1)[1].strip().splitlines()[0].strip()
    cont = await run_group_history_search(deps, {"cursor": cursor}, context)
    assert "命中" in cont


@pytest.mark.asyncio
async def test_private_and_disabled_gates(tmp_path: Path):
    deps = _deps(tmp_path)
    state = HistoryToolState()

    private = await run_group_history_search(
        deps, {"terms": ["x"]}, _context(chat_type="private", history=state)
    )
    assert private == "该工具仅支持群聊使用。"

    disabled = _deps(tmp_path, enabled=False)
    blocked = await run_group_history_search(
        disabled, {"terms": ["x"]}, _context(history=state)
    )
    assert "未开启" in blocked

    no_state = await run_group_history_search(
        deps, {"terms": ["x"]}, _context(history=None)
    )
    assert "未开启" in no_state

    read_blocked = await run_group_history_read(
        disabled, {}, _context(history=None)
    )
    assert "未开启" in read_blocked


@pytest.mark.asyncio
async def test_search_argument_validation(tmp_path: Path):
    deps = _deps(tmp_path)
    state = HistoryToolState()
    context = _context(history=state)

    assert "至少提供一个非空词" in await run_group_history_search(
        deps, {"terms": []}, context
    )
    assert "时间格式无法解析" in await run_group_history_search(
        deps, {"terms": ["a"], "start": "not-a-date"}, context
    )
    assert "结束时间需要晚于开始时间" in await run_group_history_search(
        deps,
        {"terms": ["a"], "start": "2026-11-07", "end": "2026-11-01"},
        context,
    )
    assert "续查只需传 cursor" in await run_group_history_search(
        deps, {"terms": ["a"], "cursor": "whatever"}, context
    )


@pytest.mark.asyncio
async def test_speaker_resolution_paths(tmp_path: Path):
    deps = _deps(tmp_path, speaker_map={"小张": ["1001"], "张": ["1001", "1002"]})
    archive = _archive_for(deps)
    now = time()
    archive.record(G1, "小张", "我说的", ts=now, user_id="1001", message_id="s1")
    archive.record(G1, "小李", "他说的", ts=now, user_id="1002", message_id="s2")
    state = HistoryToolState()
    context = _context(history=state)

    unique = await run_group_history_search(
        deps, {"terms": ["说的"], "speaker": "小张"}, context
    )
    assert "我说的" in unique and "他说的" not in unique

    qq = await run_group_history_search(
        deps, {"terms": ["说的"], "speaker": "1002"}, context
    )
    assert "他说的" in qq and "我说的" not in qq

    ambiguous = await run_group_history_search(
        deps, {"terms": ["说的"], "speaker": "张"}, context
    )
    assert "多位成员" in ambiguous

    unknown = await run_group_history_search(
        deps, {"terms": ["说的"], "speaker": "不存在的人"}, context
    )
    assert "没有找到叫" in unknown


@pytest.mark.asyncio
async def test_honest_partial_and_empty_rendering(tmp_path: Path):
    deps = _deps(tmp_path, speaker_map={})
    state = HistoryToolState()
    context = _context(history=state)

    empty = await run_group_history_search(deps, {"terms": ["不存在"]}, context)
    assert "没有匹配" in empty and "归档覆盖" in empty


def test_parse_history_time_beijing_semantics():
    parsed = parse_history_time("2026-11-07")
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 11 and parsed.day == 7
    assert parse_history_time("2026-11-07T08:00:00+00:00") is not None
    # 无时区 ISO → 北京时间
    naive = parse_history_time("2026-11-07T08:00:00")
    assert naive is not None and naive.utcoffset().total_seconds() == 8 * 3600
    assert parse_history_time("garbage") is None
    assert parse_history_time("") is None


def test_history_state_budget_math():
    state = HistoryToolState()
    assert state.allowance(SEARCH_RESULT_TOKEN_CAP, 0) == min(
        SEARCH_RESULT_TOKEN_CAP, DIRECT_HISTORY_LOOP_BUDGET
    )
    state.begin_round(1500)
    # 剩余空间扣续轮预留（512）后低于单次帽
    assert state.allowance(SEARCH_RESULT_TOKEN_CAP, 0) == 1500 - 512
    # 本批还有其他调用时再扣最小封套
    assert state.allowance(SEARCH_RESULT_TOKEN_CAP, 2) == 1500 - 512 - 2 * 256
    state.consume(400)
    assert state.direct_budget_tokens == DIRECT_HISTORY_LOOP_BUDGET - 400
    assert state.round_space_tokens == 1100
    # Loop 历史额度耗尽后归零
    state.direct_budget_tokens = 10
    state.consume(100)
    assert state.direct_budget_tokens == 0
    assert state.allowance(SEARCH_RESULT_TOKEN_CAP, 0) == 0


@pytest.mark.asyncio
async def test_budget_exhaustion_returns_explicit_reply(tmp_path: Path):
    deps = _deps(tmp_path)
    archive = _archive_for(deps)
    now = time()
    archive.record(G1, "成员", "预算测试内容", ts=now, user_id="1", message_id="b1")
    state = HistoryToolState()
    state.direct_budget_tokens = 0
    result = await run_group_history_search(
        deps, {"terms": ["预算测试"]}, _context(history=state)
    )
    assert "额度已用完" in result


def test_redact_declared_arguments_whitelists():
    raw = json.dumps(
        {"terms": ["内部词"], "speaker": "某人", "start": "2026-11-01"},
        ensure_ascii=False,
    )
    redacted = json.loads(redact_search_arguments(raw))
    assert redacted == {"mode": "search", "start": "2026-11-01"}
    assert "terms" not in redacted and "speaker" not in redacted

    cont = json.loads(redact_search_arguments('{"cursor": "tok9"}'))
    assert cont == {"mode": "continue"}

    read = json.loads(redact_read_arguments('{"anchor": "hr1.ab.12"}'))
    assert read == {"mode": "anchor", "anchor_kind": "message_ref"}
    assert "hr1" not in json.dumps(read)

    recent = json.loads(redact_recent_arguments('{"query": "秘密词"}'))
    assert recent == {"mode": "recent", "has_query": True}


# ── ephemeral 记录管线：声明脱敏 + 结果省略 + 原生省略 ─────────────


def _registry_with_history_tool() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        LLMToolSpec(
            name="search_group_history",
            description="测试",
            input_schema={"type": "object", "properties": {}},
        ),
        lambda args, ctx: "ok",
        category="history",
        result_retention="ephemeral",
        redact_arguments=redact_search_arguments,
    )
    registry.register(
        LLMToolSpec(
            name="get_identity",
            description="测试",
            input_schema={"type": "object", "properties": {}},
        ),
        lambda args, ctx: "ok",
    )
    return registry


def test_registry_retention_and_redaction():
    registry = _registry_with_history_tool()
    assert registry.retention_of("search_group_history") == "ephemeral"
    assert registry.retention_of("get_identity") == "bounded"
    assert registry.retention_of("unknown_tool") == "bounded"

    call = LLMToolCall(
        id="c1",
        name="search_group_history",
        arguments_json='{"terms": ["内部词"], "start": "2026-11-01"}',
    )
    redacted = registry.redacted_declaration(call)
    payload = json.loads(redacted.arguments_json)
    assert payload["mode"] == "search"
    assert "terms" not in payload

    plain = LLMToolCall(id="c2", name="get_identity", arguments_json='{"q": 1}')
    assert registry.redacted_declaration(plain) is plain


class _Response:
    """on_turn 需要的最小响应形态。"""

    def __init__(self, *, text="回复", native=None):
        self.text = text
        self.finish_reason = "stop"
        self.tool_calls = []
        self.thinking_blocks = []
        self.native_blocks = native
        self.owner = None


def test_recorder_ephemeral_retention_flow(tmp_path: Path):
    store = LLMStore(tmp_path / "llm.db")
    handle: LoopHandle = store.begin_loop(
        "1001", 0, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="u1", sender_name="n", canonical_name="n", content="问"),
    )
    recorder = TurnRecorder(
        store=store, handle=handle, config=RecorderConfig(), sink=None
    )

    registry = _registry_with_history_tool()
    raw_call = LLMToolCall(
        id="call_1",
        name="search_group_history",
        arguments_json='{"terms": ["内部词"]}',
    )
    response = _Response(native=[{"type": "reasoning", "text": "thinking"}])
    execution_ids = recorder.on_turn(
        response,
        declared_calls=[registry.redacted_declaration(raw_call)],
        executable_calls=[raw_call],
        has_more_rounds=True,
        native_state_omission=NativeOmissionReason.EPHEMERAL_POLICY,
    )
    assert execution_ids["call_1"]
    recorder.on_tool_started(execution_ids["call_1"])
    from quickquip.llm.tools import LLMToolResult

    recorder.on_tool_finished(
        execution_ids["call_1"],
        LLMToolResult(call_id="call_1", name="search_group_history", content="群聊正文"),
        retention="ephemeral",
    )
    recorder.close(LoopStatus.COMPLETED, None)

    conn = store._connect()
    try:
        execution = conn.execute(
            "SELECT arguments_json, result_json, result_retention,"
            " result_omission_reason, status FROM agent_tool_executions"
            " WHERE provider_call_id = 'call_1'"
        ).fetchone()
        # 声明参数只留白名单
        assert json.loads(execution["arguments_json"]) == {"mode": "search"}
        # 结果正文不入业务持久层，保留政策与省略原因落库
        assert execution["result_retention"] == "ephemeral"
        assert execution["result_omission_reason"] == "ephemeral_policy"
        assert execution["result_json"] is None or "群聊正文" not in execution["result_json"]
        assert execution["status"] == str(ToolExecutionStatus.SUCCEEDED)
        # 原生副本按 ephemeral 策略省略
        turn = conn.execute(
            "SELECT native_state_json, native_omission_reason FROM agent_turns"
            " ORDER BY turn_index DESC LIMIT 1"
        ).fetchone()
        assert turn["native_state_json"] is None
        assert turn["native_omission_reason"] == "ephemeral_policy"
    finally:
        conn.close()
