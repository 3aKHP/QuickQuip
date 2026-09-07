"""§8.2 确定性精简阶梯单测：结果收紧 → 档案 → 减半 → 最小档案 → 逐出。"""
from __future__ import annotations

from quickquip.llm.history_projection import (
    PATH_STRUCTURED,
    project_loops_with_budget,
)
from quickquip.llm.token_estimate import estimate_tokens
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
    reasons = {d.loop_id: d.reason or "" for d in result.decisions}
    # 最旧 Loop 走到最小档案或被逐出（reason 为叠加链）；最新 Loop 保留最多信息。
    assert (
        "reduced:minimal_archive" in reasons["loop_0"]
        or reasons["loop_0"] == "reduced:evicted"
    )
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


# ── 原生 CoT 计量与首档剥离 ──────────────────────────────────────


def _native_estimate(messages) -> int:
    """与实现同口径的估算（含原生/thinking 块；与 test_epoch 导入私有函数同例）。"""
    from quickquip.llm.history_projection import _estimate_messages_tokens

    return _estimate_messages_tokens(messages)


def _cot_loop(thinking_chars: int):
    blocks = [
        {"type": "thinking", "thinking": "思" * thinking_chars, "signature": "sig"},
        {"type": "tool_use", "id": "call_exec_0", "name": "get_identity", "input": {}},
    ]
    return _loop(
        "loop_cot",
        (
            _turn(
                "turn_0",
                tools=(_tool_exec("exec_0"),),
                native_state=_native_state(OWNER, blocks),
                owner=_owner_dict(OWNER),
            ),
        ),
    )


def test_native_cot_counted_into_projection_estimate():
    loop = _cot_loop(thinking_chars=4000)
    full = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=10**9
    )
    assert _native_estimate(full.messages) > estimate_tokens("思" * 4000)


def test_native_thinking_stripped_before_native_dropped():
    loop = _cot_loop(thinking_chars=4000)
    full = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=10**9
    )
    full_estimate = _native_estimate(full.messages)
    # 预算略低于全量：剥 thinking（≈4000×0.7 token）即达标，不应走到 native_dropped。
    result = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=full_estimate - 200
    )
    decision = result.decisions[0]
    assert decision.reason == "reduced:native_thinking_stripped"
    assistant = [m for m in result.messages if m.role == "assistant"][0]
    assert assistant.native_content is not None
    types = [block.get("type") for block in assistant.native_content]
    assert "thinking" not in types
    assert "tool_use" in types, "工具声明保留，配对完整"
    assert any(m.role == "tool" for m in result.messages), "工具结果保留"


def test_native_thinking_stripped_gemini_thought_parts():
    from dataclasses import replace

    gemini_owner = replace(OWNER, protocol="gemini")
    blocks = [
        {"text": "想" * 4000, "thought": True},
        {"functionCall": {"name": "get_identity", "args": {}}},
    ]
    loop = _loop(
        "loop_gcot",
        (
            _turn(
                "turn_0",
                tools=(_tool_exec("exec_0"),),
                native_state=_native_state(gemini_owner, blocks),
                owner=_owner_dict(gemini_owner),
            ),
        ),
    )
    full = project_loops_with_budget(
        [loop], target=gemini_owner, protocol="gemini", budget_tokens=10**9
    )
    full_estimate = _native_estimate(full.messages)
    result = project_loops_with_budget(
        [loop], target=gemini_owner, protocol="gemini", budget_tokens=full_estimate - 200
    )
    decision = result.decisions[0]
    assert decision.reason == "reduced:native_thinking_stripped"
    assistant = [m for m in result.messages if m.role == "assistant"][0]
    assert assistant.native_content is not None
    assert all(not block.get("thought") for block in assistant.native_content)
    assert any("functionCall" in block for block in assistant.native_content)


def test_huge_native_cot_still_reaches_deeper_ladder():
    # 大 CoT + 大工具结果：剥 thinking 后仍超限，继续走到 native_dropped
    # 或更深档位，签名块不再上 wire。
    blocks = [
        {"type": "thinking", "thinking": "思" * 100_000, "signature": "sig"},
        {"type": "tool_use", "id": "call_exec_0", "name": "get_identity", "input": {}},
    ]
    loop = _loop(
        "loop_cot_deep",
        (
            _turn(
                "turn_0",
                tools=(_big_result_exec("exec_0", 8000),),
                native_state=_native_state(OWNER, blocks),
                owner=_owner_dict(OWNER),
            ),
        ),
    )
    result = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=400
    )
    decision = result.decisions[0]
    assert decision.reason is not None
    assert "reduced:native_thinking_stripped" in (decision.reason or "")
    assert "reduced:native_dropped" in (decision.reason or "")
    for message in result.messages:
        assert message.native_content is None


def test_native_thinking_stripped_empty_turn_gets_placeholder():
    # 纯 thinking 轮（零正文零工具）剥空后退占位正文：空 text 块会被 Claude 拒 400。
    blocks = [{"type": "thinking", "thinking": "思" * 200, "signature": "sig"}]
    loop = _loop(
        "loop_pure_thinking",
        (
            _turn(
                "turn_0",
                text="",
                tools=(),
                native_state=_native_state(OWNER, blocks),
                owner=_owner_dict(OWNER),
            ),
        ),
    )
    full = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=10**9
    )
    result = project_loops_with_budget(
        [loop], target=OWNER, protocol="claude", budget_tokens=_native_estimate(full.messages) - 5
    )
    assert result.decisions[0].reason == "reduced:native_thinking_stripped"
    stripped_assistant = [m for m in result.messages if m.role == "assistant"][0]
    assert stripped_assistant.native_content is None
    assert stripped_assistant.content, "剥空轮必须有非空占位正文"
    assert estimate_tokens(stripped_assistant.content) > 0


def test_native_message_text_not_double_counted():
    # 原生消息正文内含于 native 块（serializer 忽略通用字段），估算不得双计。
    from quickquip.llm.history_projection import _estimate_messages_tokens
    from quickquip.llm.tools import LLMConversationMessage

    body = "正文内容。" * 50
    native_msg = LLMConversationMessage(
        role="assistant",
        content=body,
        native_content=[{"type": "text", "text": body}],
    )
    counted_once = _estimate_messages_tokens([native_msg])
    empty_body = LLMConversationMessage(
        role="assistant",
        content="",
        native_content=[{"type": "text", "text": body}],
    )
    assert _estimate_messages_tokens([empty_body]) == counted_once
    # 通用消息（无 native）仍单计 content。
    plain = LLMConversationMessage(role="assistant", content=body)
    assert _estimate_messages_tokens([plain]) == estimate_tokens(body)
