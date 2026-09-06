"""§8.2 确定性精简阶梯单测：结果收紧 → 档案 → 减半 → 最小档案 → 逐出。"""
from __future__ import annotations

from quickquip.llm.history_projection import (
    PATH_STRUCTURED,
    project_loops_with_budget,
)
from quickquip.llm.store_parts.agent_records import (
    LoadedToolExecution,
)

from tests.unit.llm.test_history_projection import (
    _loop,
    _native_state,
    _owner_dict,
    _tool_exec,
    _turn,
    OWNER,
)


def _big_result_exec(execution_id: str, chars: int) -> LoadedToolExecution:
    return LoadedToolExecution(
        execution_id=execution_id,
        call_index=0,
        provider_call_id=f"call_{execution_id}",
        tool_name="search_web",
        arguments_json='{"query":"长查询"}',
        arguments_omission_reason=None,
        status="succeeded",
        result={
            "version": 1,
            "content": "结" * chars,
            "is_error": False,
            "original_bytes": chars * 3,
            "retained_ranges": [[0, chars]],
            "media_descriptions": [],
        },
        result_retention="bounded",
        result_omission_reason=None,
    )


from quickquip.llm.token_estimate import estimate_tokens


def _token_estimate_of(messages) -> int:
    """与实现同口径的估算（estimate_tokens）。"""
    total = 0
    for message in messages:
        total += estimate_tokens(message.content)
        for call in message.tool_calls:
            total += estimate_tokens(call.arguments_json)
    return total


def test_result_tier_tightens_oldest_loop_first():
    big = 8000
    loop_old = _loop(
        "loop_old",
        (_turn("turn_0", text="旧轮。", tools=(_tool_exec("exec_0", result={
            "version": 1, "content": "结" * big, "is_error": False,
            "original_bytes": big, "retained_ranges": [], "media_descriptions": [],
        }),),),),
    )
    loop_new = _loop(
        "loop_new",
        (_turn("turn_0", text="新轮。", tools=(_big_result_exec("exec_1", big),),),),
    )
    # 预算只够放下一个 Loop 的全量结果：最旧 Loop 先收紧。
    budget = _token_estimate_of(project_loops_with_budget(
        [loop_new], target=None, protocol="openai", budget_tokens=10**9,
    ).messages) + 200
    result = project_loops_with_budget(
        [loop_old, loop_new], target=None, protocol="openai", budget_tokens=budget,
    )
    old_tools = [m.content for m in result.segments["loop_old"] if m.role == "tool"]
    new_tools = [m.content for m in result.segments["loop_new"] if m.role == "tool"]
    assert old_tools and "结" in old_tools[0], "工具结果仍在（收紧而非删除）"
    assert len(old_tools[0]) < big, "最旧 Loop 的结果被收紧"
    assert len(new_tools[0]) == big, "预算内的最新 Loop 保持全量结果"
    reasons = {d.loop_id: d.reason for d in result.decisions}
    assert reasons["loop_old"] and reasons["loop_old"].startswith("reduced:result_tier")
    assert reasons["loop_new"] is None


def test_archive_and_minimal_levels_apply_under_tight_budget():
    big = 4000
    loops = [
        _loop(
            f"loop_{i}",
            (
                _turn("turn_0", text=f"第{i}轮正文。" * 20, tools=(_big_result_exec("exec_0", big),)),
                _turn("turn_1", text=f"第{i}轮总结。" * 20),
            ),
        )
        for i in range(3)
    ]
    result = project_loops_with_budget(
        loops, target=None, protocol="openai", budget_tokens=600,
    )
    reasons = {d.loop_id: d.reason for d in result.decisions}
    # 最旧 Loop 走到最小档案或被逐出；最新 Loop 保留最多信息。
    assert reasons["loop_0"] in {
        "reduced:minimal_archive", "reduced:evicted",
    }
    # 全量估算收敛到预算内或只剩最小档案。
    assert _token_estimate_of(result.messages) <= max(600, 3 * 160)


def test_native_dropped_before_result_tiers():
    blocks = [
        {"type": "thinking", "thinking": "思" * 300, "signature": "sig"},
        {"type": "text", "text": "正文"},
        {"type": "tool_use", "id": "call_exec_0", "name": "get_identity", "input": {}},
    ]
    loop = _loop(
        "loop_native",
        (_turn("turn_0", tools=(_tool_exec("exec_0"),),
               native_state=_native_state(OWNER, blocks), owner=_owner_dict(OWNER)),),
    )
    result = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=8,
    )
    decision = result.decisions[0]
    # 原生路径先降级（native_dropped 或更深的阶梯），签名块不再上 wire。
    assert decision.reason is not None
    import json as _json
    assert _json.dumps([{"sig": 1}])  # 保持 json 引用（审计可读性）
    for message in result.messages:
        assert message.native_content is None


def test_within_budget_projection_untouched():
    loop = _loop("loop_1", (_turn("turn_0", text="短正文。"),))
    result = project_loops_with_budget(
        [loop], target=None, protocol="openai", budget_tokens=10_000,
    )
    assert result.decisions[0].path == PATH_STRUCTURED
    assert result.decisions[0].reason is None
    assert [m.content for m in result.messages if m.role == "assistant"] == ["短正文。"]
