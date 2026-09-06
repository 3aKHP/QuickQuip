"""Agent Loop 运行时记录与交付（§5.3/§6）：service 接入层。

一次外部触发 = 一个 Loop。每个完整模型响应形成一个 Turn：清理正文 →
原子提交（Turn + 工具声明 + 交付计划）→ 按序发送文字 Chunk → 依模型
原顺序执行工具 batch → 关闭。D3：首个 failed/unknown 交付即终止后续
发送、工具启动与生成。

上线开关（§6.3）：``agent_delivery_enabled=false`` 时仍记录全部 Turn 与
工具，非最终正文标记 ``suppressed_by_policy``，最终正文由适配层按现有
单次交付方式发送。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import json

from quickquip.llm.agent_records import (
    AGENT_RECORD_VERSION,
    DeliveryKind,
    DeliveryPlanItem,
    DeliveryReceipt,
    DeliveryStatus,
    DeliverySummary,
    MAX_NATIVE_STATE_BYTES,
    NativeOmissionReason,
    LoopStatus,
    TextPolicy,
    ToolDeclarationRecord,
    ToolExecutionStatus,
    ToolResultRecord,
    ToolSkipReason,
    TurnOutputStatus,
    TurnResponseRecord,
    new_agent_id,
)
from quickquip.llm.delivery import SplitLimitError, SplitParams, plan_text_chunks
from quickquip.llm.provider import LLMResponse, strip_leading_reasoning_content
from quickquip.llm.store_parts.agent_records import (
    LoopHandle,
    LoopRecordBudgetExceeded,
    ScopeGenerationMismatch,
    TurnRecord,
)
from quickquip.llm.tools import LLMToolResult

if TYPE_CHECKING:
    from quickquip.llm.store import LLMStore

logger = logging.getLogger(__name__)


class DeliverySink(Protocol):
    """交付出口（§5.1）：接收稳定 delivery ID 与冻结 payload，返回回执。"""

    async def __call__(self, delivery_id: str, payload: dict[str, Any]) -> DeliveryReceipt: ...


def _dumps_compact(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class DeliveryAborted(RuntimeError):
    """D3 终止信号：后续生成、工具启动与交付全部停止。"""


@dataclass(slots=True)
class RecorderConfig:
    agent_delivery_enabled: bool = False
    reply_split_threshold_chars: int = 800
    reply_chunk_max_chars: int = 1200
    reply_max_chunks_per_loop: int = 64

    def split_params(self) -> SplitParams:
        params = SplitParams(
            threshold=self.reply_split_threshold_chars,
            chunk_max=self.reply_chunk_max_chars,
        )
        params.validate()
        return params


class TurnRecorder:
    """单 Loop 的记录器：由 service 持有，tool_loop 通过钩子驱动。

    不做 scope 排队（沿用入口限流）；generation 屏障由 store 写入校验
    兜底（ScopeGenerationMismatch → Loop 关闭为 interrupted）。
    """

    def __init__(
        self,
        *,
        store: "LLMStore",
        handle: LoopHandle,
        config: RecorderConfig,
        sink: DeliverySink | None,
        sensitive_scan=None,
    ):
        self._store = store
        self._handle = handle
        self._config = config
        self._sink = sink if config.agent_delivery_enabled else None
        self._sensitive_scan = sensitive_scan
        self._delivery_count = 0
        self._delivery_stats = {"sent": 0, "failed": 0, "unknown": 0, "skipped": 0, "suppressed": 0}
        self._final_turn_record: TurnRecord | None = None
        self._terminal_reason: str | None = None

    @property
    def handle(self) -> LoopHandle:
        return self._handle

    @property
    def final_turn_record(self) -> TurnRecord | None:
        return self._final_turn_record

    def _clean_text(self, raw: str) -> str:
        text = strip_leading_reasoning_content(raw or "")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _scrubbed_text(self, raw: str) -> tuple[str, TextPolicy]:
        text = self._clean_text(raw)
        if self._sensitive_scan is not None:
            scan = self._sensitive_scan(text)
            if scan.blocked:
                return "本次回复内容未能通过安全检查，已替换。", TextPolicy.REPLACED_BY_FILTER
        return text, TextPolicy.ALLOWED

    def _plan_deliveries(
        self, turn_id: str, text: str, *, is_final: bool
    ) -> list[DeliveryPlanItem]:
        policy = self._config
        items: list[DeliveryPlanItem] = []
        if not text:
            return items
        if not policy.agent_delivery_enabled and not is_final:
            # 关闭开关：非最终正文只记 suppressed（§6.3）。
            items.append(
                DeliveryPlanItem(
                    delivery_id=new_agent_id("dlv"), kind=DeliveryKind.TEXT_CHUNK,
                    turn_id=turn_id, chunk_index=0, source_start=0, source_end=len(text),
                )
            )
            self._delivery_stats["suppressed"] += 1
            return items
        if not policy.agent_delivery_enabled:
            # 最终正文沿现有单次交付，交付记录由 receipt 回填阶段写入。
            return items
        if self._sink is None:
            raise RuntimeError("agent_delivery_enabled=true 但缺少 DeliverySink（编程错误）")
        try:
            chunks, limit_reason = plan_text_chunks(
                text,
                policy.split_params(),
                reserved_delivery_slots=self._delivery_count,
                max_chunks=policy.reply_max_chunks_per_loop,
            )
        except SplitLimitError:
            # §6.1.5：单个 grapheme 超限——拒绝该交付计划并明确终止，
            # 不让内部 ValueError 以「LLM 调用异常」面世。
            self._terminal_reason = "split_limit"
            raise DeliveryAborted("split_limit") from None
        if limit_reason == "delivery_limit":
            self._terminal_reason = "delivery_limit"
            return []
        for chunk in chunks:
            items.append(
                DeliveryPlanItem(
                    delivery_id=new_agent_id("dlv"),
                    kind=DeliveryKind.TEXT_CHUNK,
                    turn_id=turn_id,
                    chunk_index=chunk.chunk_index,
                    source_start=chunk.start,
                    source_end=chunk.end,
                )
            )
        return items

    def on_turn(
        self,
        response: LLMResponse,
        *,
        declared_calls: list,
        executable_calls: list,
        has_more_rounds: bool,
    ) -> dict[str, str]:
        """完整响应到达后的原子提交（§5.3.4-5）。

        ``declared_calls`` = 响应声明的全部调用（含超出执行预算的），
        ``executable_calls`` = 本轮实际执行子集；差集由 ``on_tool_skipped``
        记 not_executed。预算/字节触顶抛 ``DeliveryAborted``；文字交付由
        ``deliver_turn`` 在工具执行前单独驱动（§5.3.6）。
        """
        text, text_policy = self._scrubbed_text(response.text)
        is_final = not executable_calls or not has_more_rounds
        turn_id = new_agent_id("turn")
        output_status = (
            TurnOutputStatus.VISIBLE if text else
            (TurnOutputStatus.NO_VISIBLE_OUTPUT if is_final else TurnOutputStatus.EMPTY)
        )
        declarations = [
            ToolDeclarationRecord(
                execution_id=new_agent_id("exec"),
                call_index=index,
                provider_call_id=call.id,
                tool_name=call.name,
                arguments_json=call.arguments_json,
                arguments_omission_reason=None,
            )
            for index, call in enumerate(declared_calls)
        ]
        execution_ids = {d.provider_call_id: d.execution_id for d in declarations}
        parts: list[dict[str, Any]] = []
        if text:
            parts.append({"type": "text_ref", "start": 0, "end": len(text), "origin": "model"})
        for declaration in declarations:
            parts.append({"type": "tool_ref", "execution_id": declaration.execution_id})
        native_state = None
        native_omission = None
        if response.native_blocks:
            candidate = {
                "version": AGENT_RECORD_VERSION,
                "owner": _owner_payload(response.owner),
                "blocks": response.native_blocks,
            }
            encoded = _dumps_compact(candidate)
            if len(encoded.encode("utf-8")) > MAX_NATIVE_STATE_BYTES:
                # 存储契约预检（§2 MAX_NATIVE_STATE_BYTES）：超限省略原生
                # 副本、保留通用事实，而不是让提交抛错炸掉整条回复。
                native_omission = NativeOmissionReason.SIZE_LIMIT
                logger.warning(
                    "native state exceeds %d bytes; omitting blocks for turn %s",
                    MAX_NATIVE_STATE_BYTES, turn_id,
                )
            else:
                native_state = candidate
        plan = self._plan_deliveries(turn_id, text, is_final=is_final)
        record = self._store.commit_turn(
            self._handle,
            TurnResponseRecord(
                text=text,
                text_policy=text_policy,
                output_status=output_status,
                finish_reason=response.finish_reason,
                parts=tuple(parts),
                native_state=native_state,
                native_omission_reason=native_omission,
                owner=_owner_payload(response.owner),
            ),
            declarations,
            plan,
            turn_id=turn_id,
        )
        if is_final or not has_more_rounds:
            self._final_turn_record = record
        # 关闭开关的非最终 suppressed 交付落 planned 即收敛为 suppressed。
        if not self._config.agent_delivery_enabled and not is_final:
            for delivery_id in record.delivery_ids:
                self._store.suppress_delivery(self._handle, delivery_id)
        if self._terminal_reason == "delivery_limit":
            raise DeliveryAborted("delivery_limit")
        self._pending_record = record
        self._pending_text = text
        self._pending_plan = {item.delivery_id: item for item in plan}
        return execution_ids

    async def deliver_turn(self) -> None:
        """提交后的文字 Chunk 交付（§5.3.6）：先于所属工具执行。"""
        record = getattr(self, "_pending_record", None)
        text = getattr(self, "_pending_text", "")
        plan = getattr(self, "_pending_plan", {})
        self._pending_record = None
        self._pending_text = ""
        self._pending_plan = {}
        if record is None or not self._config.agent_delivery_enabled or self._sink is None:
            return
        for delivery_id in record.delivery_ids:
            if self._terminal_reason is not None:
                break
            item = plan.get(delivery_id)
            chunk_text = text[item.source_start : item.source_end] if item else text
            attempt = self._store.start_delivery(self._handle, delivery_id)
            receipt = await self._sink(delivery_id, {"text": chunk_text})
            if receipt.status == DeliveryStatus.SENT and receipt.message_id:
                self._store.set_first_chunk_message_id(record.message_row_id, receipt.message_id)
            self._store.finish_delivery(attempt, receipt)
            self._delivery_stats[str(receipt.status)] = self._delivery_stats.get(str(receipt.status), 0) + 1
            self._delivery_count += 1
            if receipt.status in (DeliveryStatus.FAILED, DeliveryStatus.UNKNOWN):
                # D3：终止当前 Loop 后续生成、工具启动和交付。
                self._terminal_reason = f"delivery_{receipt.status}"
                raise DeliveryAborted(self._terminal_reason)

    def on_tool_started(self, execution_id: str) -> None:
        try:
            self._store.mark_tool_started(self._handle, execution_id)
        except (ScopeGenerationMismatch, LoopRecordBudgetExceeded) as exc:
            raise DeliveryAborted(str(exc)) from exc

    def on_tool_finished(
        self,
        execution_id: str,
        result: LLMToolResult | None,
        *,
        is_error: bool = False,
        retention: str = "bounded",
        media: tuple[dict[str, Any], ...] = (),
    ) -> None:
        if result is not None:
            content_bytes = len(result.content.encode("utf-8"))
            failed = is_error or result.is_error
            self._store.finish_tool(
                self._handle,
                execution_id,
                ToolResultRecord(
                    content=result.content,
                    is_error=failed,
                    original_bytes=content_bytes,
                    # 重放按 status 区分 error 语义（§7.2 冻结表达）：
                    # is_error 只进 result_json 会让 functionResponse 丢失
                    # 原链路的 is_error 标记。
                    status=ToolExecutionStatus.FAILED if failed else ToolExecutionStatus.SUCCEEDED,
                ),
                result_retention=retention,
                outbound_media=media,
            )
        # not_executed 终态由 on_tool_skipped 显式写入。

    def on_tool_skipped(self, execution_id: str, reason: ToolSkipReason) -> None:
        self._store.finish_tool(
            self._handle, execution_id, None,
            status=ToolExecutionStatus.NOT_EXECUTED, skip_reason=reason,
        )

    def close(self, status: LoopStatus, reason: str | None) -> None:
        try:
            self._store.close_loop(self._handle, status, reason or self._terminal_reason)
        except Exception:
            logger.exception("close_loop 失败 loop=%s", self._handle.loop_id)

    def summary(self) -> DeliverySummary:
        return DeliverySummary(
            total=self._delivery_count + self._delivery_stats["suppressed"],
            **{k: v for k, v in self._delivery_stats.items()},
        )


def _owner_payload(owner) -> dict[str, Any] | None:
    if owner is None:
        return None
    return {
        "provider_id": owner.provider_id,
        "protocol": owner.protocol,
        "wire_model": owner.wire_model,
        "display_model": owner.display_model,
        "endpoint_fingerprint": owner.endpoint_fingerprint,
        "profile_fingerprint": owner.profile_fingerprint,
    }
