"""Apply the current text policy to request-local execution history."""
from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

from quickquip.common.sensitive_filter import SensitiveFilter
from quickquip.llm.store_parts.agent_records import LoadedLoop, LoadedTurn


def _strings(value: Any) -> Iterator[str]:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        elif item is not None:
            yield str(item)


def _native_text(turn: LoadedTurn) -> Iterator[str]:
    """Inspect readable protocol fields; opaque signatures and media stay opaque."""
    blocks = (turn.native_state or {}).get("blocks")
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ("text", "thinking", "reasoning_content"):
            if isinstance(block.get(key), str):
                yield block[key]
        if block.get("type") == "tool_use":
            yield from _strings(block.get("input"))
            yield str(block.get("name") or "")
        call = block.get("functionCall")
        if isinstance(call, dict):
            yield from _strings(call.get("args"))
            yield str(call.get("name") or "")


def _requires_archive(loop: LoadedLoop, sensitive: SensitiveFilter) -> bool:
    if any(turn.text_policy == "replaced_by_filter" for turn in loop.turns):
        return True
    if not sensitive.is_loaded:
        return False

    def blocked(values: Iterator[str]) -> bool:
        return any(sensitive.scan(text).blocked for text in values)

    if blocked(_strings({key: loop.user_row.get(key) for key in ("content", "raw_content")})):
        return True
    for turn in loop.turns:
        if sensitive.scan(turn.text).blocked or blocked(_native_text(turn)):
            return True
        for tool in turn.tools:
            if sensitive.scan(tool.tool_name).blocked or blocked(_strings(tool.result)):
                return True
            if tool.arguments_json:
                if sensitive.scan(tool.arguments_json).blocked:
                    return True
                try:
                    arguments = json.loads(tool.arguments_json)
                except (ValueError, RecursionError):
                    # Invalid historical arguments cannot be safely inspected or replayed.
                    return True
                if blocked(_strings(arguments)):
                    return True
    return False


def prepare_safe_history(
    loops: Sequence[LoadedLoop], sensitive: SensitiveFilter,
) -> tuple[list[LoadedLoop], frozenset[str]]:
    """Return safe copies and Loop IDs constrained to text archives for this request.

    Affected archives retain scrubbed text and tool status counts. Native blocks
    and tool payloads are excluded from replay without changing durable records.
    """
    prepared: list[LoadedLoop] = []
    archived: set[str] = set()
    for loop in loops:
        if not _requires_archive(loop, sensitive):
            prepared.append(loop)
            continue
        archived.add(loop.loop_id)
        user_row = dict(loop.user_row)
        for field in ("content", "raw_content"):
            if isinstance(user_row.get(field), str):
                user_row[field] = sensitive.scrub(user_row[field])
        turns = tuple(
            replace(turn, text=sensitive.scrub(turn.text), native_state=None, owner=None)
            for turn in loop.turns
        )
        prepared.append(replace(loop, user_row=user_row, turns=turns))
    return prepared, frozenset(archived)
