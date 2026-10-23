"""Frozen historical expressions must survive appends and change only at resets."""
from copy import deepcopy
from dataclasses import replace

import pytest

from quickquip.llm.epoch_history import select_history
from quickquip.llm.provider.gemini import GeminiProviderClient
from quickquip.llm.provider.openai_responses.request import serialize_input_items
from tests.unit.llm.test_history_projection import (
    GEMINI_PARTS, OWNER, RESPONSES_OUTPUT_ITEMS,
    _loop, _native_state, _owner_dict, _tool_exec, _turn,
)
from tests.unit.llm.test_projection_budget import _big_result_exec
from tests.unit.llm.test_provider_gemini import _provider_config


def _sources(count, chars=100):
    loops, rows = [], []
    for index in range(count):
        loop_id = f"loop_{index}"
        loop = replace(_loop(loop_id, (
            _turn("turn_0", tools=(_big_result_exec(f"exec_{index}", chars),)),
        )), anchor_row_id=index * 2 + 1)
        loops.append(loop)
        rows.extend([
            {"id": index * 2 + 1, "role": "user", "content": "query",
             "agent_loop_id": loop_id},
            {"id": index * 2 + 2, "role": "assistant", "content": "answer",
             "agent_loop_id": loop_id},
        ])
    return loops, rows


def _select(loops, rows, previous=None, budget=10000, protocol="gemini",
            archive_loop_ids=frozenset(), target=None, **kwargs):
    return select_history(
        rows, loops, previous=previous, target=target, protocol=protocol,
        profile="profile", budget=budget, target_ratio=0.5,
        archive_loop_ids=archive_loop_ids, effort="", **kwargs,
    )


@pytest.mark.parametrize("protocol", ["gemini", "openai_responses"])
@pytest.mark.parametrize("native", [False, True])
async def test_three_rounds_preserve_serialized_history(protocol, native):
    previous = None
    previous_wire = []
    client = GeminiProviderClient(_provider_config())
    owner = replace(OWNER, protocol=protocol) if native else None
    for count in range(1, 4):
        loops, rows = _sources(count)
        if native:
            blocks = GEMINI_PARTS if protocol == "gemini" else RESPONSES_OUTPUT_ITEMS
            loops = [replace(loop, turns=(
                _turn("turn_0", tools=(_tool_exec("exec_0",
                      provider_call_id="call_resp_identity"),),
                      native_state=_native_state(owner, blocks), owner=_owner_dict(owner)),
            )) for loop in loops]
        result = _select(loops, rows, previous, protocol=protocol, target=owner)
        assert result.reason is None
        messages = [m for segment in result.frozen.segments.values() for m in segment]
        if native:
            assert any(m.native_content for m in result.frozen.segments["loop_0"])
        wire = (await client._serialize_messages(messages) if protocol == "gemini"
                else serialize_input_items(messages, [[] for _ in messages], provider_id="p"))
        assert wire[:len(previous_wire)] == previous_wire
        previous_wire, previous = wire, result.frozen
    request_copy = deepcopy(previous.segments)
    request_copy["loop_0"][0].content = "request-local mutation"
    assert previous.segments["loop_0"][0].content != "request-local mutation"


def test_budget_selects_new_epoch_suffix_and_then_stays_stable():
    loops, rows = _sources(2, chars=8000)
    first = _select(loops[:1], rows[:2], budget=7000)
    old_segment = deepcopy(first.frozen.segments["loop_0"])
    second = _select(loops, rows, first.frozen, budget=7000)
    assert second.reason == "budget" and second.anchor == 3
    assert first.frozen.segments["loop_0"] == old_segment
    assert list(second.frozen.segments) == ["loop_1"]
    third = _select(loops[1:], rows[2:], second.frozen, budget=7000)
    assert third.reason is None
    assert third.frozen.segments == second.frozen.segments


def test_source_change_and_late_revision_rebuild():
    loops, rows = _sources(1)
    original = _select(loops, rows).frozen
    changed = deepcopy(rows)
    changed[0]["raw_content"] = "filtered source"
    assert _select(loops, changed, original).reason == "history"
    revised = [replace(loops[0], replay_revision=1)]
    assert _select(revised, rows, original).reason == "history"
    assert _select([], [], original).reason == "history"


def test_single_large_loop_is_reduced_once_and_kept():
    loops, rows = _sources(1, chars=8000)
    first = _select(loops, rows, budget=600)
    assert first.reason == "budget"
    assert first.frozen.rows == rows
    assert first.frozen.replay_tokens <= 600
    second = _select(loops, rows, first.frozen, budget=600)
    assert second.reason is None
    assert first.frozen.segments == second.frozen.segments


def test_already_archived_loop_rebuilds_when_scrubbed_turn_changes():
    loops, rows = _sources(1)
    original_turn = replace(loops[0].turns[0], text="PRIVATE_SENTINEL")
    loops = [replace(loops[0], turns=(original_turn,))]
    archived = frozenset({"loop_0"})
    first = _select(loops, rows, archive_loop_ids=archived)
    assert "PRIVATE_SENTINEL" in str(first.frozen.segments)
    cleaned = [replace(loops[0], turns=(replace(original_turn, text="[内容已过滤]"),))]
    second = _select(cleaned, rows, first.frozen, archive_loop_ids=archived)
    assert second.reason == "history"
    assert "PRIVATE_SENTINEL" not in str(second.frozen.segments)
    assert "[内容已过滤]" in str(second.frozen.segments)
    assert _select(cleaned, rows, second.frozen, archive_loop_ids=archived).reason is None
