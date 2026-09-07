"""生产 DeliverySink 单测（§5.1/§6.2）：回执分类、节流、CQ 注入边界。"""
from __future__ import annotations

import asyncio
import time
import types


from quickquip.adapters.nonebot._llm_reply import (
    OneBotDeliverySink,
    record_final_receipt,
    reset_delivery_throttle,
    text_only_message,
)
from quickquip.llm.agent_records import DeliveryStatus


def _seg_text(message) -> str:
    """从 Message 提取纯文本段内容（验证不经 CQ 解析器）。"""
    return "".join(str(seg.data.get("text", "")) for seg in message)


class _Message:
    def __init__(self, segments):
        self.segments = segments

    def __iter__(self):
        return iter(self.segments)


class _Segment:
    def __init__(self):
        self.data: dict[str, str] = {}

    @classmethod
    def text(cls, value: str):
        seg = cls()
        seg.data["text"] = value
        return seg


async def test_sent_receipt_requires_trusted_message_id():
    reset_delivery_throttle()

    async def send(text):
        return {"message_id": 12345}

    sink = OneBotDeliverySink(send, scope_key="g1", interval_ms=0)
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.SENT
    assert receipt.message_id == "12345"
    assert sink.sent_texts == ["正文"]


async def test_missing_message_id_is_unknown_not_sent():
    reset_delivery_throttle()

    async def send(text):
        return {"message_id": None}

    sink = OneBotDeliverySink(send, scope_key="g1", interval_ms=0)
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.UNKNOWN
    assert receipt.error_code == "missing_message_id"
    assert sink.sent_texts == []


async def test_timeout_classified_unknown_and_plain_error_failed():
    reset_delivery_throttle()

    async def timeout_send(text):
        raise asyncio.TimeoutError("Request timed out")

    sink = OneBotDeliverySink(timeout_send, scope_key="g1", interval_ms=0)
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.UNKNOWN

    async def failed_send(text):
        raise RuntimeError("retcode=1200 rate limited")

    sink2 = OneBotDeliverySink(failed_send, scope_key="g2", interval_ms=0)
    receipt2 = await sink2("dlv_1", {"text": "正文"})
    assert receipt2.status == DeliveryStatus.FAILED
    assert receipt2.error_code == "RuntimeError"
    assert sink2.sent_texts == []


async def test_timeout_is_not_recorded_as_visible_text():
    reset_delivery_throttle()

    async def timeout_send(text):
        raise asyncio.TimeoutError("Request timed out")

    sink = OneBotDeliverySink(timeout_send, scope_key="g-timeout", interval_ms=0)
    receipt = await sink("dlv_1", {"text": "可能已送达"})
    assert receipt.status == DeliveryStatus.UNKNOWN
    assert sink.sent_texts == []


async def test_same_scope_sends_are_throttled():
    reset_delivery_throttle()
    stamps: list[float] = []

    async def send(text):
        stamps.append(time.monotonic())
        return {"message_id": len(stamps)}

    sink = OneBotDeliverySink(send, scope_key="g-throttle", interval_ms=60)
    await sink("dlv_1", {"text": "a"})
    await sink("dlv_2", {"text": "b"})
    assert len(stamps) == 2
    assert stamps[1] - stamps[0] >= 0.05  # 第二次发送等待了间隔


def test_text_only_message_uses_text_segment():
    message = text_only_message("含[CQ:at,qq=all]的正文", _Message, _Segment)
    assert _seg_text(message) == "含[CQ:at,qq=all]的正文"  # 原样文本段，不进 CQ 解析器


async def test_record_final_receipt_uses_exact_row_id():
    calls: list[tuple[int, str]] = []
    store = types.SimpleNamespace(
        set_first_chunk_message_id=lambda row_id, qq: calls.append(("exact", row_id, qq)),
        update_last_assistant_message_id=lambda scope, qq: calls.append(("legacy", scope, qq)),
    )
    svc = types.SimpleNamespace(store=store)
    record_final_receipt(svc, {"agent_turn_row_id": 42, "scope_key": "1001"}, "qq-7")
    assert calls == [("exact", 42, "qq-7")]
    # 无 row_id 的回退路径（记录器未启用的旧链路）。
    record_final_receipt(svc, {"scope_key": "1001"}, "qq-8")
    assert calls[-1] == ("legacy", "1001", "qq-8")
