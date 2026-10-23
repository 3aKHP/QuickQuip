"""Immutable historical expressions selected for one in-memory epoch.

The store owns source facts. This module selects expressions and detects when
they must be rebuilt; EpochManager owns the corresponding window transition.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.history_projection import (
    _estimate_messages_tokens,
    project_loops,
    project_loops_with_budget,
)
from quickquip.llm.provider.openai_responses import replay_guard_violations
from quickquip.llm.store_parts.agent_records import LoadedLoop
from quickquip.llm.tools import LLMConversationMessage


@dataclass(slots=True)
class FrozenHistory:
    profile: str
    sources: dict[str, str]
    segments: dict[str, list[LLMConversationMessage]]
    replay_tokens: int
    rows: list[dict[str, object]] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return len(history_units(self.rows))


@dataclass(slots=True)
class HistorySelection:
    frozen: FrozenHistory
    reason: str | None = None
    anchor: int | None = None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
    ).encode()).hexdigest()


def history_units(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """Group recorded Loops and legacy user/assistant pairs without splitting them."""
    units: list[list[dict[str, object]]] = []
    for row in rows:
        loop_id = row.get("agent_loop_id")
        if units and loop_id and units[-1][0].get("agent_loop_id") == loop_id:
            units[-1].append(row)
        elif units and not loop_id and not units[-1][0].get("agent_loop_id") \
                and row["role"] != "user":
            units[-1].append(row)
        else:
            units.append([row])
    return units


def select_history(
    rows: list[dict[str, object]],
    loops: list[LoadedLoop],
    *,
    previous: FrozenHistory | None,
    target: ResponseOwner | None,
    protocol: str,
    profile: str,
    budget: int,
    target_ratio: float,
    archive_loop_ids: frozenset[str],
    effort: str,
    rebuild_budget: int | None = None,
) -> HistorySelection:
    """Append new expressions, or choose a new suffix at an explicit reset."""
    units = history_units(rows)
    # Fingerprint the readable, policy-processed source as well as its DB revision.
    # An already archived Loop may be scrubbed differently after a policy reload.
    loop_sources = {
        loop.loop_id: _digest((
            loop.replay_revision, loop.user_row,
            [(turn.text, turn.text_policy,
              [(tool.tool_name, tool.status, tool.result_omission_reason) for tool in turn.tools])
             for turn in loop.turns],
        )) for loop in loops
    }

    def sources_for(selected_rows):
        return {
            str(row["id"]): _digest((
                row,
                loop_sources.get(str(row.get("agent_loop_id"))),
                str(row.get("agent_loop_id")) in archive_loop_ids,
            )) for row in selected_rows
        }

    sources = sources_for(rows)
    reason = None
    if previous is not None:
        if previous.profile != profile:
            reason = "profile"
        elif (list(sources)[:len(previous.sources)] != list(previous.sources)
              or any(sources.get(k) != v for k, v in previous.sources.items())):
            reason = "history"
    if reason or rebuild_budget is not None:
        previous = None
    segments = deepcopy(previous.segments) if previous else {}
    new_loops = [loop for loop in loops if loop.loop_id not in segments
                 and any(turn.tools for turn in loop.turns)]
    projected = project_loops(
        new_loops, target=target, protocol=protocol, archive_loop_ids=archive_loop_ids,
    )
    segments.update(projected.segments)
    if protocol == "openai_responses":
        violations = replay_guard_violations(segments, segments)
        for loop in new_loops:
            if loop.loop_id in violations:
                segments[loop.loop_id] = project_loops(
                    [loop], target=None, protocol=protocol, archive_loop_ids=archive_loop_ids,
                ).messages

    def cost(loop_id):
        return _estimate_messages_tokens(segments.get(loop_id, []), effort=effort)

    total = sum(cost(key) for key in segments)
    anchor = None
    if total > budget or rebuild_budget is not None:
        reason = "budget"
        limit = min(budget, rebuild_budget) if rebuild_budget is not None else budget
        target_tokens = max(1, int(limit * target_ratio))
        retained = []
        retained_tokens = 0
        for unit in reversed(units):
            unit_cost = cost(str(unit[0].get("agent_loop_id")))
            if retained and retained_tokens + unit_cost > target_tokens:
                # Two units are a soft minimum, subordinate to the hard budget.
                if len(retained) >= 2 or retained_tokens + unit_cost > limit:
                    break
            retained.append(unit)
            retained_tokens += unit_cost
        rows = [row for unit in reversed(retained) for row in unit]
        if rows:
            anchor = int(rows[0]["id"])
        retained_ids = {str(row.get("agent_loop_id")) for row in rows}
        retained_loops = [loop for loop in loops
                          if loop.loop_id in retained_ids and loop.loop_id in segments]
        if retained_tokens > limit:
            # A single large Loop needs the existing deterministic reduction ladder.
            segments = project_loops_with_budget(
                retained_loops, target=target, protocol=protocol, budget_tokens=limit,
                archive_loop_ids=archive_loop_ids, effort=effort,
            ).segments
            segments = {loop.loop_id: segments.get(loop.loop_id, []) for loop in retained_loops}
        else:
            segments = {k: v for k, v in segments.items() if k in retained_ids}
        total = sum(_estimate_messages_tokens(v, effort=effort) for v in segments.values())
        sources = sources_for(rows)
    return HistorySelection(
        FrozenHistory(profile, sources, segments, total, deepcopy(rows)), reason, anchor,
    )
