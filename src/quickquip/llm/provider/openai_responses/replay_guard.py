"""Responses 原生历史回放的发送前守门（纯函数，协议侧归属）。

投影层（``history_projection``）完成路径决策后，对本协议的原生 Loop 段
执行两类确定性检查，违例 Loop 由投影层降级为通用重建（stable wire id
构造性唯一），保证可预判的序列化失败不落到发送期 fail-closed：

- **call_id 冲突**（``native_call_id_collision``）：同一 Loop 内或跨 Loop
  重复声明同一 call_id（中转可能回显短 id）。序列化端 ``_declare`` 对
  重复声明 fail-closed，且部分执行的批次必然破坏协议配对。
- **配对完整**（``native_pairing_incomplete``）：Loop 段内声明的 call_id
  （原生 function_call items + 通用重建的 tool_calls）与 tool 消息的应答
  集不一致（记录部分损坏）。通用重建自 executions 出发、自洽配对，是
  该违例的安全落点。

声明全集与序列化端 ``serialize_input_items`` 同构：原生批次声明其
function_call items 的 call_id，通用 assistant 消息声明其 tool_calls 的
id；应答集是全部 tool 消息的 tool_call_id。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from quickquip.llm.tools import LLMConversationMessage

REASON_CALL_ID_COLLISION = "native_call_id_collision"
REASON_PAIRING_INCOMPLETE = "native_pairing_incomplete"


def _native_declared_call_ids(messages: Sequence[LLMConversationMessage]) -> list[str]:
    """原生批次声明的 function call_id（按出现顺序；仅 assistant native 消息）。"""
    declared: list[str] = []
    for message in messages:
        if message.native_content is None:
            continue
        for item in message.native_content:
            if isinstance(item, dict) and item.get("type") == "function_call":
                call_id = item.get("call_id")
                if isinstance(call_id, str) and call_id:
                    declared.append(call_id)
    return declared


def _structured_declared_call_ids(messages: Sequence[LLMConversationMessage]) -> list[str]:
    """通用重建声明的 call_id（assistant 消息的 tool_calls；native 消息不带）。"""
    return [
        call.id
        for message in messages
        if message.role == "assistant" and message.native_content is None
        for call in message.tool_calls
    ]


def replay_guard_violations(
    segments: Mapping[str, Sequence[LLMConversationMessage]],
    native_loop_ids: Iterable[str],
) -> dict[str, str]:
    """逐原生 Loop 检查回放违例；返回 ``{loop_id: 降级原因}``（按输入序）。

    跨 Loop 冲突只降后到 Loop（先到者保持原生）；Loop 内冲突与配对不完整
    降该 Loop 本身。守门视野限于已投影的历史段；历史段与当前活循环之间
    的撞车由序列化端 fail-closed 终防（活循环 id 来自实时响应，投影层
    不可见）。
    """
    violations: dict[str, str] = {}
    seen_call_ids: set[str] = set()
    for loop_id in native_loop_ids:
        messages = segments.get(loop_id)
        if messages is None:
            continue
        declared = (
            _native_declared_call_ids(messages)
            + _structured_declared_call_ids(messages)
        )
        if len(set(declared)) != len(declared):
            violations[loop_id] = REASON_CALL_ID_COLLISION
            continue
        answered = {
            message.tool_call_id
            for message in messages
            if message.role == "tool" and message.tool_call_id
        }
        if answered != set(declared):
            violations[loop_id] = REASON_PAIRING_INCOMPLETE
            continue
        if any(call_id in seen_call_ids for call_id in declared):
            violations[loop_id] = REASON_CALL_ID_COLLISION
            continue
        seen_call_ids.update(declared)
    return violations
