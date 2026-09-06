"""历史重放投影（§7.2/§7.4）：归属选择、通用投影与冻结表达。

输入是执行记录的完整已关闭 Loop（``store_parts.agent_records.LoadedLoop``），
输出是目标协议可用的 ``LLMConversationMessage`` 序列。三条合法路径：

- **native**：目标 owner 五元组精确匹配且协议结构校验通过时，原样使用
  保存的有序原生块（Claude content / Gemini parts），保留签名与位置；
  不追加通用副本。
- **structured**：有序普通正文 + 工具名/稳定 wire ID/结果/终态；去掉
  不具备有效来源的原生推理。Claude 带 thinking 的工具 Turn 不能走该路径
  （签名不可伪造），自动降级档案。
- **archive**：纯文本历史档案——每 Loop 一段 user 触发 + 一段 assistant
  档案（Turn N 与工具状态）。工具内容是历史数据，不产生可执行调用。

本模块是纯函数层：不做 I/O、不读配置、不改记录。降级理由通过
``ProjectionResult.decisions`` 可观测（§7.2）。
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.provider.owner import owner_matches
from quickquip.llm.store_parts.agent_records import (
    LoadedLoop,
    LoadedToolExecution,
    LoadedTurn,
)
from quickquip.llm.tools import LLMConversationMessage, LLMToolCall

PATH_NATIVE = "native"
PATH_STRUCTURED = "structured"
PATH_ARCHIVE = "archive"

_ARCHIVE_TAG = "[历史档案]"
_ORPHAN_TRIGGER_NOTE = "[系统说明] 该段历史的原始触发消息未保留。"


class HistoryProjectionError(RuntimeError):
    """执行记录结构损坏（§7.4：孤立/重复/漏结果在发送请求前失败）。"""


@dataclass(frozen=True, slots=True)
class LoopProjectionDecision:
    loop_id: str
    path: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    messages: list[LLMConversationMessage]
    decisions: tuple[LoopProjectionDecision, ...]
    # 按 Loop 边界切分的消息段（loop_id -> messages），与 decisions 同序。
    segments: dict[str, list[LLMConversationMessage]]


def stable_wire_tool_call_id(loop_id: str, turn_id: str, call_index: int) -> str:
    """通用路径的稳定 wire ID（§7.4）：按 (loop, turn, call_index) 派生。

    跨 Turn 重复的 provider call_id（如每轮都有的 call_0）在通用路径下
    由此消歧；原生路径保持原 call ID 与签名关联不变。
    """
    digest = hashlib.sha1(f"{loop_id}:{turn_id}:{call_index}".encode("utf-8")).hexdigest()[:16]
    return f"call_{digest}"


def missing_result_explanation(execution: LoadedToolExecution) -> str:
    """缺失/省略结果的确定说明（§5.5）：不虚构工具返回正文或成功结论。"""
    result = execution.result or {}
    detail = result.get("detail")
    if execution.status == "not_executed":
        return f"工具 {execution.tool_name} 未执行（原因：{detail or '未知'}）。"
    if execution.status == "failed":
        return f"工具 {execution.tool_name} 执行失败，无可用结果。"
    if execution.status == "indeterminate":
        return f"工具 {execution.tool_name} 的执行结果未知。"
    if execution.status == "succeeded":
        return f"工具 {execution.tool_name} 已成功执行，结果正文按政策未保留。"
    return f"工具 {execution.tool_name} 状态为 {execution.status}，无结果正文。"


def _turn_native_blocks(turn: LoadedTurn) -> list[dict[str, Any]] | None:
    native = turn.native_state
    if not native or turn.native_omission_reason is not None:
        return None
    blocks = native.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return None
    return blocks


def _native_blocks_valid(protocol: str, blocks: Sequence[dict[str, Any]]) -> bool:
    """协议结构校验（§7.2）：签名缺失/损坏、未知块形态都判无效并降级。"""
    for block in blocks:
        if not isinstance(block, dict):
            return False
        kind = block.get("type")
        if protocol == "claude":
            if kind == "thinking":
                if not isinstance(block.get("signature"), str) or not block["signature"].strip():
                    return False
            elif kind == "redacted_thinking":
                if not isinstance(block.get("data"), str) or not block["data"].strip():
                    return False
            elif kind == "text":
                if not isinstance(block.get("text"), str):
                    return False
            elif kind == "tool_use":
                if not str(block.get("id", "")).strip() or not str(block.get("name", "")).strip():
                    return False
                if not isinstance(block.get("input"), dict):
                    return False
            else:
                return False
        elif protocol == "gemini":
            # parts 形态：text / functionCall（thought 与 thoughtSignature 可选）。
            if "functionCall" in block:
                call = block.get("functionCall")
                if not isinstance(call, dict) or not str(call.get("name", "")).strip():
                    return False
            elif "text" not in block and "inlineData" not in block and "fileData" not in block:
                return False
        else:
            return False
    return True


def _validate_tool_pairing(turn: LoadedTurn) -> None:
    """配对校验（§7.4）：声明与结果必须成对，损坏在投影期失败。"""
    for execution in turn.tools:
        terminal = execution.status in {"succeeded", "failed", "indeterminate", "not_executed"}
        if not terminal:
            raise HistoryProjectionError(
                f"turn={turn.turn_id} execution={execution.execution_id} 无终态（{execution.status}）"
            )
        if execution.status in {"succeeded", "failed"} and execution.result is None:
            raise HistoryProjectionError(
                f"turn={turn.turn_id} execution={execution.execution_id} 终态无结果记录"
            )


def _tool_result_content(execution: LoadedToolExecution) -> str:
    result = execution.result or {}
    content = str(result.get("content") or "")
    if content:
        return content
    return missing_result_explanation(execution)


def _decide_loop_path(
    loop: LoadedLoop,
    *,
    target: ResponseOwner | None,
    protocol: str,
) -> tuple[str, str | None]:
    """单 Loop 路径决策。返回 (path, 降级原因)。

    Claude 的通用工具历史需要合法 thinking 签名；签名不可伪造（§7.2），
    因此只有当每个带工具的 Turn 都能"证明无 thinking"（原生块在场且
    不含 thinking 块）时才允许 structured，否则降级档案。
    """
    native_turn_blocks = {
        turn.turn_id: _turn_native_blocks(turn) for turn in loop.turns
    }
    has_any_native = any(blocks is not None for blocks in native_turn_blocks.values())
    owner_matched = all(
        owner_matches(turn.owner, target)
        for turn in loop.turns
        if _turn_native_blocks(turn) is not None
    )
    if protocol in ("claude", "gemini") and has_any_native and target is not None and owner_matched:
        for blocks in native_turn_blocks.values():
            if blocks is not None and not _native_blocks_valid(protocol, blocks):
                return PATH_ARCHIVE, "native_structure_invalid"
        return PATH_NATIVE, None
    if protocol == "claude":
        for turn in loop.turns:
            if not turn.tools:
                continue
            blocks = native_turn_blocks[turn.turn_id]
            proves_no_thinking = blocks is not None and not any(
                block.get("type") in {"thinking", "redacted_thinking"} for block in blocks
            )
            if not proves_no_thinking:
                reason = (
                    "owner_unknown_claude_signed_history"
                    if target is None
                    else "owner_mismatch_claude_signed_history"
                )
                return PATH_ARCHIVE, reason
    if has_any_native:
        return PATH_STRUCTURED, "owner_mismatch"
    return PATH_STRUCTURED, None


def _user_trigger_message(loop: LoadedLoop) -> LLMConversationMessage:
    if loop.user_row:
        content = str(loop.user_row.get("content") or "")
    else:
        content = _ORPHAN_TRIGGER_NOTE
    return LLMConversationMessage(role="user", content=content)


def _project_loop_native(
    loop: LoadedLoop,
) -> list[LLMConversationMessage]:
    messages = [_user_trigger_message(loop)]
    for turn in loop.turns:
        blocks = _turn_native_blocks(turn)
        if blocks is None:
            # 同 Loop 内个别 Turn 无原生副本：该 Turn 退通用表达，
            # 其余 Turn 保持原生（Loop 级路径已由决策保证合法）。
            messages.extend(_project_turn_structured(turn, loop.loop_id, native_owner_match=False))
            continue
        messages.append(
            LLMConversationMessage(role="assistant", content=turn.text, native_content=list(blocks))
        )
        for execution in turn.tools:
            wire_id = execution.provider_call_id or stable_wire_tool_call_id(
                loop.loop_id, turn.turn_id, execution.call_index
            )
            messages.append(
                LLMConversationMessage(
                    role="tool",
                    content=_tool_result_content(execution),
                    tool_call_id=wire_id,
                    tool_name=execution.tool_name,
                    is_tool_error=execution.status == "failed",
                )
            )
    return messages


def _project_turn_structured(
    turn: LoadedTurn,
    loop_id: str,
    *,
    native_owner_match: bool,
) -> list[LLMConversationMessage]:
    tool_calls = [
        LLMToolCall(
            id=stable_wire_tool_call_id(loop_id, turn.turn_id, execution.call_index),
            name=execution.tool_name,
            arguments_json=execution.arguments_json
            or _omitted_arguments_json(execution),
        )
        for execution in turn.tools
    ]
    thinking_blocks: list[Any] = []
    if native_owner_match:
        blocks = _turn_native_blocks(turn)
        if blocks is not None:
            thinking_blocks = [
                block for block in blocks if block.get("type") in {"thinking", "redacted_thinking", "reasoning", "gemini_part"}
            ]
    messages = [
        LLMConversationMessage(
            role="assistant",
            content=turn.text,
            tool_calls=tool_calls,
            thinking_blocks=thinking_blocks,
        )
    ]
    messages.extend(
        _tool_messages(
            turn,
            wire_id_for=lambda e: stable_wire_tool_call_id(loop_id, turn.turn_id, e.call_index),
        )
    )
    return messages


def _omitted_arguments_json(execution: LoadedToolExecution) -> str:
    """参数被政策省略时的有界档案描述（§8.4）：不把摘录重用作函数参数。"""
    reason = execution.arguments_omission_reason or "omitted"
    return '{"_omitted": "参数正文未保留（' + reason + '）"}'


def _tool_messages(turn: LoadedTurn, *, wire_id_for) -> list[LLMConversationMessage]:
    messages: list[LLMConversationMessage] = []
    for execution in turn.tools:
        messages.append(
            LLMConversationMessage(
                role="tool",
                content=_tool_result_content(execution),
                tool_call_id=wire_id_for(execution),
                tool_name=execution.tool_name,
                is_tool_error=execution.status == "failed",
            )
        )
    return messages


def _project_loop_archive(loop: LoadedLoop) -> list[LLMConversationMessage]:
    lines: list[str] = [f"{_ARCHIVE_TAG} 以下为归档的历史会话记录，工具内容为历史数据。"]
    for turn in loop.turns:
        body = turn.text.strip()
        summary = f"Turn {turn.turn_index}：" + (body if body else "（无普通正文）")
        lines.append(summary)
        status_counts: dict[str, int] = {}
        for execution in turn.tools:
            status_counts[execution.status] = status_counts.get(execution.status, 0) + 1
        if turn.tools:
            tool_summary = "、".join(
                f"{name}×{count}" for name, count in status_counts.items()
            )
            lines.append(f"（Turn {turn.turn_index} 工具：{tool_summary}，正文未保留）")
    return [
        _user_trigger_message(loop),
        LLMConversationMessage(role="assistant", content="\n".join(lines)),
    ]


def project_loops(
    loops: Sequence[LoadedLoop],
    *,
    target: ResponseOwner | None,
    protocol: str,
) -> ProjectionResult:
    """把完整已关闭 Loop 投影为目标协议消息序列（§7.2 两条合法路径 + 档案）。"""
    messages: list[LLMConversationMessage] = []
    decisions: list[LoopProjectionDecision] = []
    segments: dict[str, list[LLMConversationMessage]] = {}
    for loop in loops:
        for turn in loop.turns:
            _validate_tool_pairing(turn)
        path, reason = _decide_loop_path(loop, target=target, protocol=protocol)
        if path == PATH_NATIVE:
            loop_messages = _project_loop_native(loop)
        elif path == PATH_STRUCTURED:
            loop_messages = [_user_trigger_message(loop)]
            owner_match = target is not None and all(
                owner_matches(turn.owner, target) for turn in loop.turns if turn.owner
            )
            for turn in loop.turns:
                loop_messages.extend(_project_turn_structured(turn, loop.loop_id, native_owner_match=owner_match))
        else:
            loop_messages = _project_loop_archive(loop)
        messages.extend(loop_messages)
        segments[loop.loop_id] = loop_messages
        decisions.append(LoopProjectionDecision(loop_id=loop.loop_id, path=path, reason=reason))
    return ProjectionResult(messages=messages, decisions=tuple(decisions), segments=segments)
