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


from quickquip.llm.service_parts.tools import ToolMixin as _ToolMixin


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
    from quickquip.llm.config import LLMConfig, ProviderConfig
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
