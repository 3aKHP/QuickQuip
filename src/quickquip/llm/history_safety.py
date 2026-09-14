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
        # OpenAI Responses output items：可读载荷嵌在 message content 与
        # reasoning summary 的 parts 里；function_call 的 name/arguments 在
        # 块级直接扫描（executions 的 arguments_json 为主通道，此处兜住
        # 记录不一致的形态）。encrypted_content 与签名同待遇不展开。
        if block.get("type") == "function_call":
            yield str(block.get("name") or "")
            if isinstance(block.get("arguments"), str):
                yield block["arguments"]
        for nested_key in ("content", "summary"):
            parts = block.get(nested_key)
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                for key in ("text", "refusal"):
                    if isinstance(part.get(key), str):
                        yield part[key]


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
