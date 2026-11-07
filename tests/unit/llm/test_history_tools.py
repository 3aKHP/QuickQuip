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
    redact_count_arguments,
    redact_read_arguments,
    redact_recent_arguments,
    redact_search_arguments,
    run_group_history_count,
    run_group_history_read,
    run_group_history_search,
)
from quickquip.llm.store import LLMStore
from quickquip.llm.store_parts.agent_records import (
    LoopHandle,
    UserTriggerPayload,
)
from quickquip.llm.service_parts.agent_runtime import RecorderConfig, TurnRecorder
from quickquip.llm.service_parts.tools import ToolMixin as _ToolMixin
from quickquip.llm.token_estimate import estimate_tokens
from quickquip.llm.tools import LLMToolCall, LLMToolSpec, ToolExecutionContext
from quickquip.llm.tool_registry import ToolRegistry

G1 = "1000000000"
UTC = timezone.utc


def _context(group_id=G1, chat_type="group", history: HistoryToolState | None = None):
    return ToolExecutionContext(
        group_id=group_id,
        user_id="123456",
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


# ── B1 回归：ephemeral 触达后最终轮 Turn 原生副本省略（CR 评审） ────


def types_proxy():
    class _P:
        id = "p1"
        protocol = "openai"
        non_vision_models: list = []
        temperature = 0.3
        max_output_tokens = 64
        reasoning_effort = None
        style_overrides = ""
    return _P()


class _LoopResponse:
    def __init__(self, *, text="", tool_calls=None, native=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.model = "m1"
        self.finish_reason = "stop"
        self.thinking_blocks = []
        self.native_blocks = native
        self.owner = None
        self.generated_images = []


class _LoopClient:
    def __init__(self, script):
        self.script = list(script)

    async def complete(self, request):
        assert self.script, "脚本耗尽"
        return self.script.pop(0)


@pytest.mark.asyncio
async def test_final_turn_native_state_omitted_after_ephemeral_tool(tmp_path, monkeypatch):
    """ephemeral 工具触达后，模型合成答案的最终轮原生副本不得落库。"""
    import logging
    from quickquip.llm.config import RuntimeConfig
    from quickquip.llm.tool_loop import run_tool_call_loop
    from quickquip.llm.provider import LLMRequest
    from quickquip.llm.store import LLMStore
    from quickquip.llm.store_parts.agent_records import (
        UserTriggerPayload,
    )

    store = LLMStore(tmp_path / "llm.db")
    handle: LoopHandle = store.begin_loop(
        "1001", 0, TriggerKind.GROUP_DIRECT,
        UserTriggerPayload(user_id="u1", sender_name="n", canonical_name="n", content="问"),
    )
    recorder = TurnRecorder(store=store, handle=handle, config=RecorderConfig(), sink=None)

    registry = _registry_with_history_tool()
    context = _context()
    request = LLMRequest(
        model="m1", system_prompt="s", temperature=0.3, max_output_tokens=64,
        messages=[], allow_tool_calls=True,
        tools=[registry.list_specs()[0]],
    )
    script = [
        _LoopResponse(tool_calls=[LLMToolCall(
            id="call_1", name="search_group_history",
            arguments_json='{"terms": ["词"]}',
        )]),
        _LoopResponse(text="最终答案", native=[{"type": "reasoning", "text": "引用了检索内容"}]),
    ]
    client = _LoopClient(script)

    await run_tool_call_loop(
        provider=types_proxy(),
        request=request,
        context=context,
        build_provider_client=lambda prov: client,
        tool_registry=registry,
        runtime_config=RuntimeConfig(tool_calling_enabled=True, tool_max_rounds=4),
        logger=logging.getLogger("test"),
        search_tool_name="search_web",
        search_failsafe_max_rounds=8,
        search_failsafe_max_calls_per_round=8,
        turn_recorder=recorder,
    )
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT native_state_json, native_omission_reason FROM agent_turns"
            " ORDER BY turn_index"
        ).fetchall()
        assert len(rows) == 2
        # 中间轮（声明 ephemeral 工具）与最终轮（引用临时内容的 reasoning）
        # 原生副本都按 ephemeral 政策省略
        for row in rows:
            assert row["native_state_json"] is None
            assert row["native_omission_reason"] == "ephemeral_policy"
    finally:
        conn.close()


# ── R01 回归：调查工具生产入口（真实 handler → 解析 → runner 接线） ──


class _InvestigationHost(_ToolMixin):
    """最小宿主：只供调查 handler 的依赖面（GPT 外审 R01 生产路径）。"""

    def __init__(self, config, store, query_service):
        self.config = config
        self.store = store
        self.group_history_service = query_service
        self._identity_repository = None


def _investigation_config(provider_id="p1", model=None):
    from quickquip.llm.config import LLMConfig, ProviderConfig, GroupHistoryConfig

    provider = ProviderConfig(
        id=provider_id, protocol="openai", base_url="http://localhost",
        api_key_env="K", default_model="m1", enabled=True, models=["m1", "m2"],
    )
    return LLMConfig(
        providers={provider.id: provider},
        group_history=GroupHistoryConfig(enabled=True, investigation_model=model or ""),
    )


@pytest.mark.asyncio
async def test_investigate_tool_entry_resolves_and_runs(tmp_path, monkeypatch):
    """生产入口全链：handler → 模型解析（元组解包）→ runner 接线 → 渲染。"""
    import quickquip.llm.history_investigation as investigation
    from quickquip.chat.archive import ChatArchive
    from quickquip.chat.history_query import HistoryQueryService
    from quickquip.llm.store import LLMStore

    config = _investigation_config()
    archive = ChatArchive(tmp_path / "a.db")
    archive.record("1000000000", "成员", "内容", ts=1_700_000_000, user_id="1", message_id="m1")
    service = HistoryQueryService(archive)
    host = _InvestigationHost(config, LLMStore(tmp_path / "llm.db"), service)

    calls: list[dict] = {}

    class _Result:
        status = "completed"
        findings = []
        unresolved = ""
        suggested_followup = ""
        evidence = {}
        coverage_note = "归档覆盖：测试。"
        stop_reason = "done"
        elapsed_seconds = 1.0
        model_calls = 1
        tool_calls = 1
        detail = ""

    async def _fake_run(**kwargs):
        calls.update(kwargs)
        return _Result()

    monkeypatch.setattr(investigation, "run_history_investigation", _fake_run)

    state = HistoryToolState()
    context = _context(history=state)
    result = await host._tool_investigate_group_history(
        {"question": "部署方案怎么定的？"}, context
    )
    # R01 核心：不抛 TypeError，provider/model 正确传入 runner
    assert "历史调查报告" in result
    assert calls["provider"].id == "p1"
    assert calls["model"] == "m1"
    assert state.investigation_used is True
    # 重复调用返回既有结果，不再启动子任务
    calls.clear()
    again = await host._tool_investigate_group_history({"question": "再查"}, context)
    assert "既有结果" in again and not calls


@pytest.mark.asyncio
async def test_investigate_tool_entry_override_and_errors(tmp_path, monkeypatch):
    import quickquip.llm.history_investigation as investigation
    from quickquip.chat.archive import ChatArchive
    from quickquip.chat.history_query import HistoryQueryService
    from quickquip.llm.store import LLMStore

    archive = ChatArchive(tmp_path / "a.db")
    service = HistoryQueryService(archive)

    # 专用模型覆盖：走指定模型
    config = _investigation_config(model="m2")
    host = _InvestigationHost(config, LLMStore(tmp_path / "l1.db"), service)
    seen: list[tuple[str, str]] = []

    class _R:
        status = "completed"
        findings = []
        unresolved = ""
        suggested_followup = ""
        evidence = {}
        coverage_note = ""
        stop_reason = "done"
        elapsed_seconds = 0.1
        model_calls = 1
        tool_calls = 0
        detail = ""

    async def _fake(**kwargs):
        seen.append((kwargs["provider"].id, kwargs["model"]))
        return _R()

    monkeypatch.setattr(investigation, "run_history_investigation", _fake)
    await host._tool_investigate_group_history(
        {"question": "q"}, _context(history=HistoryToolState())
    )
    assert seen == [("p1", "m2")]

    # 无效覆盖：显式错误字符串，不偷偷换渠道
    bad = _investigation_config(model="missing-model")
    host2 = _InvestigationHost(bad, LLMStore(tmp_path / "l2.db"), service)
    message = await host2._tool_investigate_group_history(
        {"question": "q"}, _context(history=HistoryToolState())
    )
    assert "不可用" in message and "missing-model" in message


def test_trim_to_budget_hard_caps_first_line_and_footer():
    """R02：首行/footer/截断提示全部计入硬帽——超长首行切片而非整条保留。"""
    from quickquip.llm.history_tools import _trim_to_budget

    long_line = "长" * 400
    lines = [long_line, "第二条"]
    header = "头部"
    footer = "尾部说明" + "补" * 300
    kept, trimmed, footer_final = _trim_to_budget(lines, header, footer, 200)
    assert trimmed is True
    assert len(kept) == 1
    assert estimate_tokens("\n".join([header, *kept, footer_final])) <= 200
    # 首行被裁为片段（短于原 400 字，且整包入帽）
    assert len(kept[0]) < 400


def test_trim_to_budget_zero_cap_returns_nothing():
    from quickquip.llm.history_tools import _trim_to_budget

    kept, trimmed, _ = _trim_to_budget(["行"], "头", "脚", 0)
    assert kept == [] and trimmed is False


# ── count_group_history：证无通道（调查子面专用，此处直测 handler/渲染） ──


class _RecordingStub:
    """ RecordingQueryService 的最小鸭子面：仅提供回执登记。"""

    def __init__(self, inner):
        self.inner = inner
        self.receipts: list[tuple] = []

    def register_count_receipt(self, terms_text, window_text, count, *, coverage_note=""):
        self.receipts.append((terms_text, window_text, count, coverage_note))
        return "hr1c.deadbeef"

    def count(self, group_id, *, terms, start_ts, end_ts):
        return self.inner.count(
            group_id, terms=terms, start_ts=start_ts, end_ts=end_ts
        )


def _count_deps(tmp_path: Path, *, recording=False):
    deps = _deps(tmp_path)
    if recording:
        deps.query_service = _RecordingStub(deps.query_service)  # type: ignore[assignment]
    return deps


def _seed_count_archive(deps: HistoryToolDeps, *, count=3):
    """铺一个有数据的归档（N01 后零计数断言必须有真实覆盖范围）。"""
    archive = deps.query_service.inner.archive if isinstance(
        deps.query_service, _RecordingStub
    ) else _archive_for(deps)
    now = time()
    for i in range(count):
        archive.record(
            G1, f"成员{i}", f"复读{i}", ts=now - (count - i) * 3600,
            user_id=str(i), message_id=f"c{i}",
        )
    return now


@pytest.mark.asyncio
@pytest.mark.parametrize("recording", [False, True])
async def test_count_zero_definitive_with_receipt(tmp_path: Path, recording: bool):
    deps = _count_deps(tmp_path, recording=recording)
    _seed_count_archive(deps)
    state = HistoryToolState()
    result = await run_group_history_count(
        deps,
        {"terms": ["从未出现的词"], "start": "2020-01-01"},
        _context(history=state),
    )
    assert "共 0 条命中" in result
    # N01：确定性断言限定在「已归档可读记录」，并附覆盖说明
    assert "确定性结论" in result and "已归档可读记录中从未" in result
    assert "归档覆盖" in result
    if recording:
        assert "回执 hr1c.deadbeef" in result
        stub = deps.query_service
        assert isinstance(stub, _RecordingStub)
        assert stub.receipts and "连续性未知" in stub.receipts[0][3]
    else:
        assert "回执" not in result


@pytest.mark.asyncio
async def test_count_nonzero_is_not_row_evidence(tmp_path: Path):
    deps = _count_deps(tmp_path, recording=True)
    _seed_count_archive(deps, count=3)
    state = HistoryToolState()
    result = await run_group_history_count(
        deps, {"terms": ["复读"], "start": "2000-01-01"}, _context(history=state)
    )
    assert "共 3 条命中" in result
    assert "不是行级证据" in result and "search_group_history" in result
    assert "回执 hr1c.deadbeef" in result
    assert "归档覆盖" in result


@pytest.mark.asyncio
async def test_count_no_data_windows_never_issue_receipt(tmp_path: Path):
    """N01：空库与采集前窗口是数据缺失，不是证无——不签回执。"""
    deps = _count_deps(tmp_path, recording=True)
    stub = deps.query_service
    assert isinstance(stub, _RecordingStub)

    empty = await run_group_history_count(
        deps, {"terms": ["任意词"]}, _context(history=HistoryToolState())
    )
    assert "暂无归档记录" in empty
    assert stub.receipts == []

    _seed_count_archive(deps, count=2)
    # 窗口完全早于归档起点：无数据不构成证无
    before = await run_group_history_count(
        deps,
        {"terms": ["任意词"], "start": "2020-01-01", "end": "2020-02-01"},
        _context(history=HistoryToolState()),
    )
    assert "没有交集" in before and "不构成" in before
    assert stub.receipts == []


@pytest.mark.asyncio
async def test_count_recall_excluded_but_scoped(tmp_path: Path):
    """仅有的命中全被撤回：可读记录计数为 0，措辞自带「已排除撤回」限定。"""
    deps = _count_deps(tmp_path, recording=True)
    _seed_count_archive(deps, count=1)
    archive = deps.query_service.inner.archive
    archive.record_recall(G1, "c0")
    result = await run_group_history_count(
        deps, {"terms": ["复读"], "start": "2020-01-01"},
        _context(history=HistoryToolState()),
    )
    assert "共 0 条命中" in result
    assert "未撤回" in result
    stub = deps.query_service
    assert isinstance(stub, _RecordingStub)
    assert stub.receipts  # 回执照发：已归档可读记录的 0 是真实陈述


@pytest.mark.asyncio
async def test_count_receipt_window_in_beijing_time(tmp_path: Path):
    """N03：带偏移的 ISO 输入换算北京时间入回执，end 标注不含。"""
    from datetime import datetime as _dt

    deps = _count_deps(tmp_path, recording=True)
    now = _seed_count_archive(deps, count=1)
    start_iso = _dt.fromtimestamp(now - 7200, tz=UTC).replace(
        minute=0, second=0
    ).isoformat()
    end_iso = _dt.fromtimestamp(now + 3600, tz=UTC).replace(
        minute=0, second=30
    ).isoformat()
    result = await run_group_history_count(
        deps, {"terms": ["复读"], "start": start_iso, "end": end_iso},
        _context(history=HistoryToolState()),
    )
    assert "共 1 条命中" in result
    stub = deps.query_service
    assert isinstance(stub, _RecordingStub)
    window_text = stub.receipts[0][1]
    # UTC 时刻在回执中必须以北京时间呈现（+8h）；零秒走分钟格式、
    # 非零秒保留（N03 精度要求）
    assert ":00:30" in window_text
    assert "end 不含" in window_text
    assert "（北京时间" in window_text
    # 换算正确性：start 的北京时间小时 = UTC 小时 + 8
    start_local_hour = (_dt.fromtimestamp(now - 7200, tz=UTC).hour + 8) % 24
    assert f"{start_local_hour:02d}:00" in window_text


@pytest.mark.asyncio
async def test_count_budget_and_term_guards(tmp_path: Path):
    """N02：额度耗尽拒绝执行；超长词项入口拒绝，不回显不登记。"""
    deps = _count_deps(tmp_path, recording=True)
    stub = deps.query_service
    assert isinstance(stub, _RecordingStub)

    long_terms = await run_group_history_count(
        deps, {"terms": ["超" * 65]}, _context(history=HistoryToolState())
    )
    assert "词项过长" in long_terms
    assert stub.receipts == []

    _seed_count_archive(deps, count=1)
    state = HistoryToolState()
    state.direct_budget_tokens = 0
    refused = await run_group_history_count(
        deps, {"terms": ["复读"]}, _context(history=state)
    )
    assert "额度已用完" in refused
    assert stub.receipts == []


@pytest.mark.asyncio
async def test_count_deadline_advises_narrowing_no_receipt(tmp_path: Path, monkeypatch):
    from quickquip.chat.history_query import CountOutcome, QueryStatus

    deps = _count_deps(tmp_path, recording=True)
    stub = deps.query_service
    assert isinstance(stub, _RecordingStub)

    def _deadline(group_id, *, terms, start_ts, end_ts):
        return CountOutcome(status=QueryStatus.PARTIAL, stop_reason="deadline")

    monkeypatch.setattr(stub.inner, "count", _deadline)
    result = await run_group_history_count(
        deps, {"terms": ["任意词"]}, _context(history=HistoryToolState())
    )
    assert "未产生回执" in result and "缩小时间窗" in result
    assert stub.receipts == []  # deadline 绝不签发回执


@pytest.mark.asyncio
async def test_count_clamps_long_range_and_reports_it(tmp_path: Path):
    deps = _count_deps(tmp_path)
    _seed_count_archive(deps, count=1)
    state = HistoryToolState()
    result = await run_group_history_count(
        deps,
        {"terms": ["词"], "start": "2020-01-01", "end": "2026-12-31"},
        _context(history=state),
    )
    assert "最大跨度收敛为最近 180 天" in result
    assert "分段计数" in result
    assert "归档覆盖" in result


@pytest.mark.asyncio
async def test_count_gates_and_validation(tmp_path: Path):
    deps = _deps(tmp_path)
    assert "仅支持群聊" in await run_group_history_count(
        deps, {"terms": ["a"]}, _context(chat_type="private")
    )
    disabled = _deps(tmp_path, enabled=False)
    assert "未开启" in await run_group_history_count(
        disabled, {"terms": ["a"]}, _context()
    )
    no_terms = await run_group_history_count(
        deps, {"terms": []}, _context(history=HistoryToolState())
    )
    assert "缺少搜索词项" in no_terms
    bad_time = await run_group_history_count(
        deps, {"terms": ["a"], "start": "不是日期"}, _context(history=HistoryToolState())
    )
    assert "时间格式无法解析" in bad_time
    bad_order = await run_group_history_count(
        deps, {"terms": ["a"], "start": "2026-02-01", "end": "2026-01-01"},
        _context(history=HistoryToolState()),
    )
    assert "结束时间需要晚于开始时间" in bad_order


def test_redact_count_arguments_whitelist():
    raw = json.dumps(
        {"terms": ["内部词"], "start": "2026-11-01", "end": "2026-11-07"},
        ensure_ascii=False,
    )
    redacted = json.loads(redact_count_arguments(raw))
    assert redacted == {"mode": "count", "start": "2026-11-01", "end": "2026-11-07"}
    assert "terms" not in redacted


def test_render_investigation_result_includes_receipt_evidence():
    from quickquip.llm.history_investigation import InvestigationFinding, InvestigationResult
    from quickquip.llm.history_tools import render_investigation_result

    result = InvestigationResult(
        status="completed",
        findings=[InvestigationFinding(
            claim="「黑历史」在窗口内从未出现",
            evidence_refs=["hr1c.deadbeef"],
        )],
        evidence={"hr1c.deadbeef": "计数核验：窗口 X 内共 0 条命中——从未出现（确定性结论）。"},
    )
    text = render_investigation_result(result)
    assert "从未出现" in text
    assert "hr1c.deadbeef" in text
    assert "计数核验" in text


# ── 工具帽配置接线与交接卫生（证无+预算修正 PR） ─────────────────────


@pytest.mark.asyncio
async def test_investigation_limits_read_configured_tool_calls(tmp_path, monkeypatch):
    """max_tool_calls 来自 investigation_tool_calls 配置（默认 30，可覆盖）。"""
    import quickquip.llm.history_investigation as investigation
    from quickquip.llm.store import LLMStore

    calls: list[dict] = []

    class _Result:
        status = "completed"
        findings = []
        unresolved = ""
        suggested_followup = ""
        evidence = {}
        coverage_note = "归档覆盖：测试。"
        stop_reason = "done"
        elapsed_seconds = 1.0
        model_calls = 1
        tool_calls = 1
        detail = ""

    async def _fake_run(**kwargs):
        calls.append(kwargs)
        return _Result()

    monkeypatch.setattr(investigation, "run_history_investigation", _fake_run)

    from quickquip.chat.archive import ChatArchive
    from quickquip.chat.history_query import HistoryQueryService
    from quickquip.llm.config import GroupHistoryConfig

    archive = ChatArchive(tmp_path / "a.db")
    service = HistoryQueryService(archive)

    # 默认值
    config = _investigation_config()
    host = _InvestigationHost(config, LLMStore(tmp_path / "d.db"), service)
    await host._tool_investigate_group_history(
        {"question": "q"}, _context(history=HistoryToolState())
    )
    assert calls[-1]["limits"].max_tool_calls == 30

    # 显式覆盖
    config2 = _investigation_config()
    config2.group_history = GroupHistoryConfig(
        enabled=True, investigation_tool_calls=7
    )
    host2 = _InvestigationHost(config2, LLMStore(tmp_path / "e.db"), service)
    await host2._tool_investigate_group_history(
        {"question": "q"}, _context(history=HistoryToolState())
    )
    assert calls[-1]["limits"].max_tool_calls == 7


def test_prompts_teach_cross_session_followup_and_optional_leads():
    """交接卫生：子任务提示词禁游标；报告渲染声明未决线索可选。"""
    from quickquip.llm.history_investigation import InvestigationTask, _system_prompt
    from quickquip.llm.history_tools import render_investigation_result

    class _RecordingStub:
        def coverage_note(self):
            return "归档覆盖：测试。"

    prompt = _system_prompt(_RecordingStub(), InvestigationTask(question="q"))
    assert "不要写游标" in prompt
    assert "另一个会话" in prompt
    assert "hr1c" in prompt and "count_group_history" in prompt

    from quickquip.llm.history_investigation import InvestigationFinding, InvestigationResult
    report = render_investigation_result(InvestigationResult(
        status="completed",
        findings=[InvestigationFinding(claim="结论", evidence_refs=["hr1.deadbeef.1"])],
        evidence={"hr1.deadbeef.1": "证据"},
    ))
    assert "可选线索" in report and "无需自动补查" in report


# ── F01/F02：渲染截断的重签链路（门面转发 + 耗尽页不丢内容） ────────


@pytest.mark.asyncio
async def test_search_truncation_on_exhausted_page_continues(tmp_path: Path):
    """F02（搜索）：查询层已证耗尽（has_more=False）但渲染截断丢弃了
    命中时，仍必须重签续查游标；经 RecordingQueryService 门面转发
    （F01：原 AttributeError）。续页从交付边界继续，不重不漏。"""
    from quickquip.llm.history_investigation import RecordingQueryService

    deps = _deps(tmp_path)
    archive = _archive_for(deps)
    deps.query_service = RecordingQueryService(deps.query_service, G1)  # type: ignore[assignment]
    now = time()
    for i in range(4):
        archive.record(
            G1, f"成员{i}", f"独有词{i}：" + "内" * 400,
            ts=now - i * 60, user_id=str(i), message_id=f"x{i}",
        )
    state = HistoryToolState()
    # 紧轮空间：预览行也只装得下 ~2 行，剩余命中被渲染截断丢弃
    state.begin_round(800)
    result = await run_group_history_search(
        deps, {"terms": ["独有词"]}, _context(history=state)
    )
    assert "预算截断" in result
    assert "工具执行失败" not in result
    assert "cursor：" in result  # 耗尽页被截断也要有续查句柄

    cursor = result.split("cursor：", 1)[1].strip().splitlines()[0].strip()
    state.begin_round(8000)
    state.direct_budget_tokens = DIRECT_HISTORY_LOOP_BUDGET
    cont = await run_group_history_search(deps, {"cursor": cursor}, _context(history=state))
    seen1 = {m for m in ("独有词0", "独有词1", "独有词2", "独有词3") if m in result}
    seen2 = {m for m in ("独有词0", "独有词1", "独有词2", "独有词3") if m in cont}
    assert seen1 and not seen1 & seen2
    assert seen1 | seen2 == {"独有词0", "独有词1", "独有词2", "独有词3"}


@pytest.mark.asyncio
async def test_read_exhausted_window_render_clip_continues(tmp_path: Path):
    """F02（阅读）：整窗一页取尽（查询层无游标）但渲染只装下前几行——
    续读句柄仍须签发且从最后交付行继续（原：无游标，未交付行不可达）。"""
    deps = _deps(tmp_path)
    archive = _archive_for(deps)
    now = time()
    for i in range(12):
        archive.record(
            G1, f"行员{i}", f"行{i}：" + "字" * 90,
            ts=now - (12 - i) * 60, user_id=str(i), message_id=f"r{i}",
        )
    state = HistoryToolState()
    state.direct_budget_tokens = 400
    result = await run_group_history_read(
        deps,
        {"start": "2000-01-01", "end": "2100-01-01"},
        _context(history=state),
    )
    assert "预算截断" in result
    assert "newer_cursor=" in result  # 修复点：耗尽页 + 渲染截断 → 重签

    import re

    cursor = re.search(r"newer_cursor=(\S+)", result).group(1)
    state.direct_budget_tokens = DIRECT_HISTORY_LOOP_BUDGET
    state.begin_round(8000)
    cont = await run_group_history_read(
        deps, {"cursor": cursor}, _context(history=state)
    )
    first_rows = {f"行{i}" for i in range(12) if f"行{i}：" in result}
    cont_rows = {f"行{i}" for i in range(12) if f"行{i}：" in cont}
    assert first_rows and cont_rows
    assert not first_rows & cont_rows
    assert first_rows | cont_rows == {f"行{i}" for i in range(12)}


@pytest.mark.asyncio
async def test_read_fragment_resumes_at_rendered_boundary(tmp_path: Path):
    """F02（偏移精度）：片段行被渲染层二次裁剪时，续读从「实际交付的
    正文位置」继续，不跳过被裁掉的正文（原：跳到查询层片段全长）。"""
    deps = _deps(tmp_path)
    archive = _archive_for(deps)
    now = time()
    text = "".join(f"〔标{i:03d}记〕" + "字" * 92 for i in range(60))
    archive.record(G1, "作者", text, ts=now - 60, user_id="1", message_id="long1")
    state = HistoryToolState()
    result = await run_group_history_read(
        deps,
        {"start": "2000-01-01", "end": "2100-01-01"},
        _context(history=state),
    )
    import re

    assert "newer_cursor=" in result and "预算截断" in result
    markers1 = [int(m) for m in re.findall(r"〔标(\d{3})记〕", result)]
    cursor = re.search(r"newer_cursor=(\S+)", result).group(1)
    state.direct_budget_tokens = DIRECT_HISTORY_LOOP_BUDGET
    state.begin_round(8000)
    cont = await run_group_history_read(
        deps, {"cursor": cursor}, _context(history=state)
    )
    markers2 = [int(m) for m in re.findall(r"〔标(\d{3})记〕", cont)]
    # 无缺漏/无重复：续页首标记紧接首屏末标记（±3 容忍标记内裁剪），
    # 且旧缺陷（跳 ~18 块）会被 min > max+3 捕获
    assert markers1 and markers2
    assert not set(markers1) & set(markers2)
    assert min(markers2) <= max(markers1) + 3
    assert 59 in markers2  # 续读抵达消息尾部
