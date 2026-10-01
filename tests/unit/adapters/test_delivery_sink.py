"""生产 DeliverySink 单测（§5.1/§6.2）：回执分类、节流、CQ 注入边界。"""
from __future__ import annotations

import asyncio
import time
import types

import pytest
from nonebot.exception import ActionFailed

from quickquip.adapters.nonebot._llm_reply import (
    OneBotDeliverySink,
    make_matcher_sink,
    make_mention_resolver,
    record_final_receipt,
    reset_delivery_throttle,
    reset_mention_cooldowns,
    text_only_message,
)
from quickquip.common.identity import IdentityEntry, IdentityIndex
from quickquip.common.identity_sources import IdentitySnapshot
from quickquip.llm.agent_records import DeliveryStatus


@pytest.fixture(autouse=True)
def _clean_state():
    reset_delivery_throttle()
    reset_mention_cooldowns()
    yield
    reset_delivery_throttle()
    reset_mention_cooldowns()


def _seg_text(message) -> str:
    """从 Message 提取纯文本段内容（验证不经 CQ 解析器）。"""
    return "".join(str(seg.data.get("text", "")) for seg in message)


def _seg_types(message) -> list[str]:
    return [seg.type for seg in message]


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
        seg.type = "text"
        seg.data["text"] = value
        return seg

    @classmethod
    def at(cls, qq):
        seg = cls()
        seg.type = "at"
        seg.data["qq"] = str(qq)
        return seg

    @classmethod
    def reply(cls, message_id):
        seg = cls()
        seg.type = "reply"
        seg.data["id"] = str(message_id)
        return seg


class _RecordingMatcher:
    def __init__(self, fail_on_reply: str | None = None):
        self.sent = []
        self.fail_on_reply = fail_on_reply

    async def send(self, message):
        self.sent.append(message)
        has_reply = any(getattr(seg, "type", "") == "reply" for seg in message)
        if has_reply and self.fail_on_reply == "action_failed":
            raise ActionFailed("test", "reply segment rejected")
        if has_reply and self.fail_on_reply == "timeout":
            raise asyncio.TimeoutError("Request timed out")
        return {"message_id": len(self.sent)}


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

    assert sink.sent_texts == []

    async def failed_send(text):
        raise RuntimeError("retcode=1200 rate limited")

    sink2 = OneBotDeliverySink(failed_send, scope_key="g2", interval_ms=0)
    receipt2 = await sink2("dlv_1", {"text": "正文"})
    assert receipt2.status == DeliveryStatus.FAILED
    assert receipt2.error_code == "RuntimeError"
    assert sink2.sent_texts == []


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


async def test_matcher_sink_quotes_first_chunk_only():
    """reply 段只挂首个 chunk，后续 chunk 纯文本。"""
    reset_delivery_throttle()
    matcher = _RecordingMatcher()
    sink = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-quote", interval_ms=0, reply_to_message_id="12345",
    )
    receipt1 = await sink("dlv_1", {"text": "第一段"})
    receipt2 = await sink("dlv_2", {"text": "第二段"})
    assert receipt1.status == DeliveryStatus.SENT
    assert receipt2.status == DeliveryStatus.SENT
    assert _seg_types(matcher.sent[0]) == ["reply", "text"]
    assert matcher.sent[0].segments[0].data["id"] == "12345"
    assert _seg_types(matcher.sent[1]) == ["text"]


async def test_reply_segment_action_failed_falls_back_to_plain():
    """协议端显式拒绝 reply 段时去段重发，正文必达。"""
    reset_delivery_throttle()
    matcher = _RecordingMatcher(fail_on_reply="action_failed")
    sink = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-fallback", interval_ms=0, reply_to_message_id="12345",
    )
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.SENT
    # 首次带 reply 段被拒，第二次纯文本补发成功。
    assert len(matcher.sent) == 2
    assert _seg_types(matcher.sent[0]) == ["reply", "text"]
    assert _seg_types(matcher.sent[1]) == ["text"]
    assert _seg_text(matcher.sent[1]) == "正文"


async def test_reply_timeout_is_not_retried():
    """超时属于传输层歧义（消息可能已发出），不重试，回执 UNKNOWN。"""
    reset_delivery_throttle()
    matcher = _RecordingMatcher(fail_on_reply="timeout")
    sink = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-timeout", interval_ms=0, reply_to_message_id="12345",
    )
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.UNKNOWN
    assert len(matcher.sent) == 1  # 只有带 reply 段的一次尝试


async def test_invalid_reply_id_sends_plain():
    """非数字 message_id 按无引用处理（防御性：测试桩事件可能出现）。"""
    reset_delivery_throttle()
    matcher = _RecordingMatcher()
    sink = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-invalid", interval_ms=0, reply_to_message_id="m1",
    )
    receipt = await sink("dlv_1", {"text": "正文"})
    assert receipt.status == DeliveryStatus.SENT
    assert _seg_types(matcher.sent[0]) == ["text"]


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


def _jingzi_snapshot() -> IdentitySnapshot:
    index = IdentityIndex(
        entries=[IdentityEntry(canonical_name="镜子", qq_ids=["2002"], aliases=[], note="")]
    )
    index._build_indexes()
    return IdentitySnapshot(index=index, names={})


async def test_matcher_sink_commits_mentions_after_confirmed_send():
    """带 resolver 的 sink：首次送达确认后记账，窗内同名提及降级为文本。"""
    matcher = _RecordingMatcher()
    resolver = make_mention_resolver(
        _jingzi_snapshot(), scope_key="g-cool", bot_qq="999", cooldown_seconds=600.0
    )
    sink = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-cool", interval_ms=0,
        resolve_mention=resolver, cooldown_seconds=600.0,
    )
    receipt1 = await sink("dlv_1", {"text": "@镜子 第一条"})
    receipt2 = await sink("dlv_2", {"text": "@镜子 第二条"})
    assert receipt1.status == DeliveryStatus.SENT
    assert receipt2.status == DeliveryStatus.SENT
    assert _seg_types(matcher.sent[0]) == ["at", "text"]
    assert _seg_types(matcher.sent[1]) == ["text"]
    assert _seg_text(matcher.sent[1]) == "@镜子 第二条"


async def test_matcher_sink_unknown_send_does_not_consume_cooldown():
    """发送无可信 message_id（UNKNOWN）不记账：后续同名提及仍真实艾特。"""

    class _NoIdMatcher(_RecordingMatcher):
        async def send(self, message):
            self.sent.append(message)
            return {}

    resolver = make_mention_resolver(
        _jingzi_snapshot(), scope_key="g-miss", bot_qq="999", cooldown_seconds=600.0
    )
    no_id_matcher = _NoIdMatcher()
    sink = make_matcher_sink(
        no_id_matcher, _Message, _Segment,
        scope_key="g-miss", interval_ms=0,
        resolve_mention=resolver, cooldown_seconds=600.0,
    )
    receipt = await sink("dlv_1", {"text": "@镜子 未确认"})
    assert receipt.status == DeliveryStatus.UNKNOWN
    assert _seg_types(no_id_matcher.sent[0]) == ["at", "text"]  # 艾特尝试了，但未确认送达

    matcher = _RecordingMatcher()
    sink2 = make_matcher_sink(
        matcher, _Message, _Segment,
        scope_key="g-miss", interval_ms=0,
        resolve_mention=resolver, cooldown_seconds=600.0,
    )
    receipt2 = await sink2("dlv_2", {"text": "@镜子 正常"})
    assert receipt2.status == DeliveryStatus.SENT
    assert _seg_types(matcher.sent[-1]) == ["at", "text"]
