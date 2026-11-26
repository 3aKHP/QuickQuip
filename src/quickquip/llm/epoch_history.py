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
    diff_summary: str | None = None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
    ).encode()).hexdigest()


def _row_for_digest(row: dict[str, object]) -> dict[str, object]:
    """Exclude assistant.message_id, which is backfilled asynchronously and never rendered."""
    if row.get("role") == "assistant" and "message_id" in row:
        return {k: v for k, v in row.items() if k != "message_id"}
    return row


_MISSING = object()


def _summarize_history_diff(
    previous: FrozenHistory,
    rows: list[dict[str, object]],
    sources: dict[str, str],
) -> str:
    prev_ids = list(previous.sources)
    curr_ids = list(sources)
    if curr_ids[:len(prev_ids)] != prev_ids:
        for idx, prev_id in enumerate(prev_ids):
            if idx >= len(curr_ids) or curr_ids[idx] != prev_id:
                return (
                    f"prefix_mismatch prev_len={len(prev_ids)} "
                    f"curr_len={len(curr_ids)} first_id={prev_id}"
                )
    prev_by_id = {str(r["id"]): _row_for_digest(r) for r in previous.rows}
    curr_by_id = {str(r["id"]): _row_for_digest(r) for r in rows}
    for key, prev_digest in previous.sources.items():
        if sources.get(key) != prev_digest:
            p_row = prev_by_id.get(key, {})
            c_row = curr_by_id.get(key, {})
            fields = sorted(
                f for f in set(p_row) | set(c_row)
                if p_row.get(f, _MISSING) != c_row.get(f, _MISSING)
            )
            if fields:
                return f"row={key} role={c_row.get('role', '')} fields={','.join(fields)}"
            return f"row={key} loop={c_row.get('agent_loop_id')} kind=loop_or_archive"
    return "unknown"


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
    responses_search_enabled: bool = True,
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
                _row_for_digest(row),
                loop_sources.get(str(row.get("agent_loop_id"))),
                str(row.get("agent_loop_id")) in archive_loop_ids,
            )) for row in selected_rows
        }

    sources = sources_for(rows)
    reason = None
    diff_summary = None
    if previous is not None:
        if previous.profile != profile:
            reason = "profile"
        elif (list(sources)[:len(previous.sources)] != list(previous.sources)
              or any(sources.get(k) != v for k, v in previous.sources.items())):
            reason = "history"
            diff_summary = _summarize_history_diff(previous, rows, sources)
    if reason or rebuild_budget is not None:
        previous = None
    segments = deepcopy(previous.segments) if previous else {}
    new_loops = [loop for loop in loops if loop.loop_id not in segments
                 and (any(turn.tools for turn in loop.turns) or (
                     protocol == "openai_responses" and any(
                         block.get("type") == "web_search_call"
                         for turn in loop.turns
                         for block in ((turn.native_state or {}).get("blocks") or [])
                         if isinstance(block, dict)
                     )
                 ))]
    projected = project_loops(
        new_loops, target=target, protocol=protocol, archive_loop_ids=archive_loop_ids,
        responses_search_enabled=responses_search_enabled,
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
        diff_summary = None
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
                responses_search_enabled=responses_search_enabled,
            ).segments
            segments = {loop.loop_id: segments.get(loop.loop_id, []) for loop in retained_loops}
        else:
            segments = {k: v for k, v in segments.items() if k in retained_ids}
        total = sum(_estimate_messages_tokens(v, effort=effort) for v in segments.values())
        sources = sources_for(rows)
    return HistorySelection(
        FrozenHistory(profile, sources, segments, total, deepcopy(rows)),
        reason,
        anchor,
        diff_summary,
    )
