"""历史调查执行器（#72 C 线）：假 provider + 真归档的全链路集成。

覆盖：成功报告与证据取回、引用校验与预算内修复、无效报告降级、
并发占用、时限/调用帽降级、父取消传播、同群隔离。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import time

import pytest

from quickquip.chat.archive import ChatArchive
from quickquip.chat.history_query import HistoryQueryService
from quickquip.llm.config import ProviderConfig, RuntimeConfig
from quickquip.llm.history_investigation import (
    InvestigationLimits,
    InvestigationTask,
    ParentCancelled,
    run_history_investigation,
)
from quickquip.llm.tools import LLMToolCall

G1 = "1000000000"
G2 = "1000000001"


def _archive_with_history(tmp_path: Path) -> tuple[ChatArchive, HistoryQueryService, str]:
    archive = ChatArchive(tmp_path / "archive.db")
    now = time()
    base = now - 3600
    for i in range(6):
        archive.record(
            G1, f"成员{i}", f"关于部署方案的讨论{i}", ts=base + i * 60,
            user_id=str(1000 + i), message_id=f"m{i}",
        )
    archive.record(G2, "他群", "关于部署方案的讨论0", ts=base, user_id="9", message_id="x0")
    ref_row = 1
    service = HistoryQueryService(archive)
    return archive, service, service.encode_ref(ref_row)


@dataclass
class _FakeResponse:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    model: str = "test-model"
    finish_reason: str = "stop"
    thinking_blocks: list = field(default_factory=list)
    native_blocks: list | None = None
    owner: object = None
    generated_images: list = field(default_factory=list)


class _FakeClient:
    def __init__(self, script: list[_FakeResponse]):
        self.script = list(script)
        self.requests: list = []

    async def complete(self, request):
        self.requests.append(request)
        if not self.script:
            raise AssertionError("脚本耗尽：模型调用超出预期")
        return self.script.pop(0)


def _provider() -> ProviderConfig:
    return ProviderConfig(
        id="test", protocol="openai", base_url="http://localhost", api_key_env="K",
        default_model="test-model", enabled=True, models=["test-model"],
    )


def _runtime() -> RuntimeConfig:
    return RuntimeConfig(tool_calling_enabled=True, tool_max_rounds=8,
                         tool_max_calls_per_round=4)


async def _run(tmp_path, script, *, task=None, limits=None, parent_check=None,
               group=G1):
    archive, service, _ = _archive_with_history(tmp_path)
    client = _FakeClient(script)

    def _build(prov):
        return client

    result = await run_history_investigation(
        task=task or InvestigationTask(question="部署方案怎么定的？"),
        provider=_provider(),
        model="test-model",
        runtime_config=_runtime(),
        query_service=service,
        group_id=group,
        parent_scope_key=f"scope-{group}",
        build_provider_client=_build,
        limits=limits or InvestigationLimits(timeout_seconds=30, max_model_calls=5),
        parent_cancel_check=parent_check,
    )
    return result, client


@pytest.mark.asyncio
async def test_completed_report_with_evidence(tmp_path: Path):
    archive, service, ref = _archive_with_history(tmp_path)
    # 第一轮：搜索；第二轮：读锚点；第三轮：出报告
    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c2", name="read_group_history",
            arguments_json=json.dumps({"anchor": ref, "direction": "around"}),
        )]),
        _FakeResponse(text=json.dumps({
            "findings": [{"claim": "成员0 提出了部署方案", "evidence_refs": [ref]}],
            "unresolved": "未确认最终拍板人",
            "suggested_followup": "问一下群主",
        }, ensure_ascii=False)),
    ]
    result, client = await _run(tmp_path, script)
    assert result.status == "completed"
    assert result.findings and result.findings[0].evidence_refs == [ref]
    assert ref in result.evidence and "成员0" in result.evidence[ref]
    assert result.model_calls >= 3
    assert result.tool_calls == 2
    assert result.coverage_note.startswith("归档覆盖")
    # 无持久化 recorder：子任务不产生任何落库（这里仅验证调用链无记录路径）


@pytest.mark.asyncio
async def test_fabricated_ref_rejected_then_repaired(tmp_path: Path):
    archive, service, ref = _archive_with_history(tmp_path)
    bad = json.dumps({
        "findings": [{"claim": "编造结论", "evidence_refs": ["hr1.deadbeef.999999"]}],
    }, ensure_ascii=False)
    good_ref = service.encode_ref(6)  # 搜索首页命中的最新行（已读）
    good = json.dumps({
        "findings": [{"claim": "成员5 参与了讨论", "evidence_refs": [good_ref]}],
    }, ensure_ascii=False)
    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        _FakeResponse(text=bad),   # 初版报告：引用未读来源
        _FakeResponse(text=good),  # 修复调用：修正引用
    ]
    result, _ = await _run(tmp_path, script)
    assert result.status == "completed"
    assert result.findings[0].claim == "成员5 参与了讨论"


@pytest.mark.asyncio
async def test_invalid_report_returns_fallback_evidence(tmp_path: Path):
    archive, service, ref = _archive_with_history(tmp_path)
    script = [
        _FakeResponse(text="我认为方案是大家讨论决定的（无 JSON）"),
        _FakeResponse(text="还是不给你 JSON"),  # 修复仍失败
    ]
    result, _ = await _run(tmp_path, script)
    assert result.status == "invalid_report"
    # 降级证据：本任务实际读过的行（这里没读过任何行 → 空证据 + 说明）
    assert result.evidence == {}
    assert "校验" in result.detail or "报告" in result.detail


@pytest.mark.asyncio
async def test_busy_when_group_permit_held(tmp_path: Path):
    from quickquip.llm.history_investigation import (
        _acquire_investigation_permit,
        _release_investigation_permit,
    )
    assert await _acquire_investigation_permit(G1) is True
    try:
        script = [_FakeResponse(text="{}")]
        result, _ = await _run(tmp_path, script, group=G1)
        assert result.status == "busy"
    finally:
        await _release_investigation_permit(G1)


@pytest.mark.asyncio
async def test_tool_call_budget_notice_guides_report(tmp_path: Path):
    """工具帽（2 次）触顶后：第三次调用返回引导消息，模型据此出报告。"""
    archive, service, _ = _archive_with_history(tmp_path)
    good_ref = service.encode_ref(6)
    report = json.dumps({
        "findings": [{"claim": "成员5 参与了讨论", "evidence_refs": [good_ref]}],
    }, ensure_ascii=False)
    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c2", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        # 第三次搜索会拿到额度用尽消息（不计入执行）；模型随即出报告
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c3", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        _FakeResponse(text=report),
    ]
    result, _ = await _run(
        tmp_path, script,
        limits=InvestigationLimits(timeout_seconds=30, max_model_calls=6,
                                   max_tool_calls=2),
    )
    assert result.status == "completed"
    assert result.tool_calls == 2  # 第三次只拿到引导消息，未执行


@pytest.mark.asyncio
async def test_parent_cancel_propagates(tmp_path: Path):
    def _cancelled():
        raise RuntimeError("session invalidated")

    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
    ]
    with pytest.raises(ParentCancelled):
        await _run(tmp_path, script, parent_check=_cancelled)


@pytest.mark.asyncio
async def test_timeout_degrades_with_partial(tmp_path: Path):
    def _slow_search(i: int) -> _FakeResponse:
        return _FakeResponse(tool_calls=[LLMToolCall(
            id=f"c{i}", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )])

    script = [_slow_search(i) for i in range(6)]
    result, _ = await _run(
        tmp_path, script,
        limits=InvestigationLimits(timeout_seconds=0.0, max_model_calls=5),
    )
    assert result.status == "partial"


def test_scoped_recording_isolation(tmp_path: Path):
    """RecordingQueryService 群号钉死：他群同名消息不进证据池。"""
    from quickquip.llm.history_investigation import RecordingQueryService

    archive, service, _ = _archive_with_history(tmp_path)
    recording = RecordingQueryService(service, G1)
    now = time()
    outcome = recording.search(G1, recording.session,
                               terms=["部署方案"], start_ts=now - 7200, end_ts=now)
    assert outcome.hits
    rows = set(recording.delivered)
    # G2 的同名消息不可见（同群隔离）
    all_rows = archive.read_window(G1, 0, now + 10)
    assert rows <= {int(r["message_id"].replace("m", "")) + 1 for r in all_rows}


@pytest.mark.asyncio
async def test_unreferenced_finding_rejected_and_no_answer_form_ok(tmp_path):
    """R06：无证据结论被拒（修复后仍拒→invalid_report）；空 findings + unresolved 合法。"""
    no_evidence = json.dumps({"findings": [{"claim": "无据断言", "evidence_refs": []}]})
    no_answer = json.dumps({"findings": [], "unresolved": "归档无相关记录，无法确认"})
    # 空引用 → 拒绝 → 修复仍空引用 → invalid_report
    script = [_FakeResponse(text=no_evidence), _FakeResponse(text=no_evidence)]
    result, _ = await _run(tmp_path, script)
    assert result.status == "invalid_report"

    # 合法无答案形态 → completed（无结论，不迫使编造）
    ok_script = [_FakeResponse(text=no_answer)]
    result2, _ = await _run(tmp_path, ok_script)
    assert result2.status == "completed"
    assert result2.findings == [] and "无法确认" in result2.unresolved


class _SlowClient:
    def __init__(self, delay: float):
        self.delay = delay

    async def complete(self, request):
        await asyncio.sleep(self.delay)
        return _FakeResponse(text="{}")


@pytest.mark.asyncio
async def test_timeout_during_provider_wait_degrades_partial(tmp_path):
    """B1 回归：总时限落在 provider 等待窗口 → partial/timeout（非父失效）。"""
    archive, service, _ = _archive_with_history(tmp_path)

    async def _run_case():
        return await run_history_investigation(
            task=InvestigationTask(question="q"),
            provider=_provider(),
            model="test-model",
            runtime_config=_runtime(),
            query_service=service,
            group_id=G1,
            parent_scope_key=f"scope-{G1}",
            build_provider_client=lambda prov: _SlowClient(0.4),
            limits=InvestigationLimits(timeout_seconds=0.1, max_model_calls=4),
        )

    result = await _run_case()
    assert result.status == "partial"
    assert result.stop_reason == "timeout"


@pytest.mark.asyncio
async def test_watchdog_cancel_semantics_unit():
    """B1 单元：外部取消裸上抛（交 asyncio.timeout 转 TimeoutError）；
    看门狗检出的父失效转 ParentCancelled。"""
    from quickquip.llm.history_investigation import run_with_parent_watchdog

    async def _slow_ok():
        await asyncio.sleep(0.3)
        return "done"

    def healthy():
        return None
    # 外部超时：裸取消逃逸，asyncio.timeout 侧转为 TimeoutError
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await run_with_parent_watchdog(_slow_ok(), healthy, interval=10.0)

    async def _sleep_long():
        await asyncio.sleep(1.0)

    def _invalid():
        raise ParentCancelled("session cleared")

    # 看门狗检出父失效 → ParentCancelled（非裸取消）
    with pytest.raises(ParentCancelled):
        await run_with_parent_watchdog(_sleep_long(), _invalid, interval=0.05)


# ── 计数证无通道：回执作为 evidence_refs 的合法形态 ─────────────────


@pytest.mark.asyncio
async def test_count_receipt_as_evidence(tmp_path: Path, monkeypatch):
    """count=0 回执可独立支撑「从未出现」结论：completed + 证据含回执文本。"""
    monkeypatch.setattr(
        "quickquip.llm.history_investigation.secrets.token_hex",
        lambda n: "deadbeef",
    )
    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="count_group_history",
            arguments_json=json.dumps({"terms": ["从未出现的黑料"]}),
        )]),
        _FakeResponse(text=json.dumps({
            "findings": [{
                "claim": "「从未出现的黑料」在归档窗口内 0 次出现",
                "evidence_refs": ["hr1c.deadbeef"],
            }],
            "unresolved": "",
            "suggested_followup": "",
        }, ensure_ascii=False)),
    ]
    result, client = await _run(tmp_path, script)
    assert result.status == "completed"
    assert result.findings[0].evidence_refs == ["hr1c.deadbeef"]
    assert "hr1c.deadbeef" in result.evidence
    receipt_text = result.evidence["hr1c.deadbeef"]
    assert "0 条" in receipt_text and "确定性" in receipt_text
    assert result.tool_calls == 1
    # 子任务请求里确实向模型交付过回执引用
    last_request = client.requests[-1]
    assert any(
        "hr1c.deadbeef" in str(part) for part in getattr(last_request, "messages", [])
    )


@pytest.mark.asyncio
async def test_fabricated_count_receipt_rejected_then_repaired(tmp_path: Path):
    """伪造 hr1c 与伪造消息引用同罪：校验拒绝，走预算内修复。"""
    archive, service, ref = _archive_with_history(tmp_path)
    good_ref = service.encode_ref(6)  # 搜索首页命中的最新行（已读）
    script = [
        _FakeResponse(tool_calls=[LLMToolCall(
            id="c1", name="search_group_history",
            arguments_json=json.dumps({"terms": ["部署方案"]}),
        )]),
        _FakeResponse(text=json.dumps({
            "findings": [{
                "claim": "某词从未出现",
                "evidence_refs": ["hr1c.00000000"],
            }],
            "unresolved": "",
        }, ensure_ascii=False)),
        _FakeResponse(text=json.dumps({
            "findings": [{
                "claim": "成员5 参与了讨论",
                "evidence_refs": [good_ref],
            }],
            "unresolved": "",
        }, ensure_ascii=False)),
    ]
    result, _ = await _run(tmp_path, script)
    assert result.status == "completed"
    assert result.findings[0].evidence_refs == [good_ref]
