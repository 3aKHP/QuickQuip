"""Adapter-layer tests for the group message handler's LLM paths.

Covers the passive awakening input contract (#75): the current message must
not re-enter ``recent_messages`` on the passive path while still appearing
exactly once as the prompt's user text, explicit triggers keep their
pre-save context behavior, and voice transcripts participate in passive
trigger checks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

import quickquip.adapters.nonebot.group_messages as gm
import quickquip.chat.awakening as awakening_module
from quickquip.chat.repeat_detector import RepeatAction
from quickquip.chat.awakening import (
    AwakeningConfig,
    AwakeningDefaults,
    AwakeningState,
)
from quickquip.common.recent_message_buffer import RecentMessageBuffer
from quickquip.llm.identity import IdentityIndex
from quickquip.llm.service import QuickJudgeResult
from tests.fixtures.onebot import DummyMessage, DummySegment, at_seg, face_seg, record_seg, text_seg


class RecordingMatcher:
    def __init__(self) -> None:
        self.handlers = []
        self.sent = []

    def handle(self):
        def deco(fn):
            self.handlers.append(fn)
            return fn

        return deco

    async def send(self, message):
        self.sent.append(message)
        return {"message_id": "sent-1"}

    async def finish(self, message):
        self.sent.append(message)
        return {"message_id": "sent-1"}


class DummyGroupEvent:
    def __init__(self, message, group_id=100, user_id=1, self_id=999, message_id="m1"):
        self.message = message
        self.group_id = group_id
        self.user_id = user_id
        self.self_id = self_id
        self.message_id = message_id
        self.message_type = "group"
        self.to_me = False
        self.reply = None

    def get_message(self):
        return self.message


class FakeDedup:
    def is_duplicate(self, group_id, message_id):
        return False


class FakeRateLimiter:
    def __init__(self):
        self.allow_calls = []

    def allow(self, *args, **kwargs):
        self.allow_calls.append((args, kwargs))
        return True

    def can_allow(self, *args, **kwargs):
        return True


class FakeRuleSwitch:
    def is_enabled(self, group_id, rule):
        return True


class FakeStats:
    def record_message(self, *args, **kwargs):
        pass

    def record_trigger(self, *args, **kwargs):
        pass


def _llm_settings(**overrides):
    settings = SimpleNamespace(
        enabled=True,
        allow_prefix=False,
        trigger_prefix="/ai",
        allow_at=False,
        persona_id="p1",
    )
    settings.__dict__.update(overrides)
    return settings


def _make_svc(settings):
    return SimpleNamespace(
        identities=IdentityIndex(),
        config=SimpleNamespace(
            quick_judge=SimpleNamespace(timeout=2.0, max_tokens=64),
            personas={},
        ),
        get_group_settings=lambda group_id: settings,
        generate_reply=AsyncMock(
            return_value={
                "reply": "Kubernetes 部署我看看",
                "llm_used": True,
                "provider_id": "prov",
                "model": "test-model",
            }
        ),
        quick_judge=AsyncMock(return_value='{"trigger": true}'),
        quick_judge_detailed=AsyncMock(
            return_value=QuickJudgeResult(
                text='{"trigger": true}', outcome="ok", provider_id="prov", model="test-model"
            )
        ),
        store=SimpleNamespace(update_last_assistant_message_id=lambda *a, **k: None),
        recent_message_buffer=RecentMessageBuffer(),
    )


class Harness:
    def __init__(self, monkeypatch, settings):
        self.recorder = RecordingMatcher()
        self.svc = _make_svc(settings)
        self.recent = RecentMessageBuffer()
        self.awakening_state = AwakeningState()

        monkeypatch.setattr(gm, "_ensure_llm_bindings", lambda: None)
        monkeypatch.setattr(gm, "get_llm_service", lambda: self.svc)
        monkeypatch.setattr(gm, "message_deduper", FakeDedup())
        self.rate_limiter = FakeRateLimiter()
        monkeypatch.setattr(gm, "rate_limiter", self.rate_limiter)
        monkeypatch.setattr(gm, "rule_switch", FakeRuleSwitch())
        monkeypatch.setattr(gm, "stats_tracker", FakeStats())
        monkeypatch.setattr(gm, "offline_message_store", SimpleNamespace(pop_pending=lambda g, u: None))
        monkeypatch.setattr(gm, "recent_messages", self.recent)
        monkeypatch.setattr(gm, "awakening_state", self.awakening_state)
        monkeypatch.setattr(gm, "record_group_message", lambda *a, **k: None)
        monkeypatch.setattr(gm, "record_wordcloud_message", lambda *a, **k: None)
        monkeypatch.setattr(gm, "get_sender_name", lambda event: "Alice")
        monkeypatch.setattr(gm, "resolve_reply", AsyncMock(return_value=None))
        monkeypatch.setattr(awakening_module, "_state", self.awakening_state)
        monkeypatch.setattr(
            awakening_module,
            "get_config",
            lambda: AwakeningConfig(
                defaults=AwakeningDefaults(relevance_threshold=0.5, qa_threshold=1.0)
            ),
        )

        def _on_message(**kwargs):
            return self.recorder

        self.matcher = gm.register_message_matcher(_on_message, DummyMessage, DummySegment)

    async def handle(self, event):
        handler = self.recorder.handlers[0]
        await handler(None, event)


@pytest.fixture
def harness_factory(monkeypatch):
    def _factory(settings=None):
        return Harness(monkeypatch, settings or _llm_settings())

    return _factory


def _seed_recent(harness, texts):
    for index, text in enumerate(texts):
        harness.recent.add_message(100, 50 + index, f"member-{index}", f"member-{index}", text)


def _segment_snapshot(message):
    return [(segment.type, dict(segment.data)) for segment in message]


def test_repeat_original_preserves_all_message_segment_types():
    incoming = Message([
        MessageSegment.at(10001),
        MessageSegment.face(264),
        MessageSegment.image("same.jpg"),
        MessageSegment("marketface", {"id": "custom-1"}),
    ])
    before = _segment_snapshot(incoming)

    reply = gm._build_rule_reply_message(
        {"repeat_action": RepeatAction.COPY_ORIGINAL, "reply": "safe preview"},
        incoming,
        Message,
        MessageSegment,
    )

    assert isinstance(reply, Message)
    assert _segment_snapshot(reply) == before
    assert _segment_snapshot(incoming) == before
    assert reply is not incoming
    assert all(left is not right for left, right in zip(reply, incoming))


@pytest.mark.parametrize(
    ("incoming", "expected"),
    [
        (Message([MessageSegment.text("晚安")]), [("text", {"text": "晚"})]),
        (
            Message([MessageSegment.at(10001), MessageSegment.at(10002)]),
            [("at", {"qq": "10001"})],
        ),
        (
            Message([MessageSegment.face(264), MessageSegment.text("晚安")]),
            [("face", {"id": "264"}), ("text", {"text": "晚"})],
        ),
        (Message([MessageSegment.text("hello"), MessageSegment.face(264)]), [("text", {"text": "hello"})]),
    ],
)
def test_repeat_trim_removes_rightmost_content_unit(incoming, expected):
    before = _segment_snapshot(incoming)

    reply = gm._build_rule_reply_message(
        {"repeat_action": RepeatAction.TRIM_LAST, "reply": "safe preview"},
        incoming,
        Message,
        MessageSegment,
    )

    assert _segment_snapshot(reply) == expected
    assert _segment_snapshot(incoming) == before


def test_repeat_trim_suppresses_empty_message():
    incoming = Message([MessageSegment.face(264)])

    reply = gm._build_rule_reply_message(
        {"repeat_action": RepeatAction.TRIM_LAST, "reply": ""},
        incoming,
        Message,
        MessageSegment,
    )

    assert reply is None
    assert _segment_snapshot(incoming) == [("face", {"id": "264"})]


def test_plain_rule_reply_cq_literal_stays_text():
    reply = gm._build_rule_reply_message(
        {"reply": "[CQ:at,qq=10001]"},
        Message([MessageSegment.text("trigger")]),
        Message,
        MessageSegment,
    )
    outbound = Message()
    outbound += reply

    assert _segment_snapshot(outbound) == [("text", {"text": "[CQ:at,qq=10001]"})]


async def test_passive_trigger_excludes_current_message_from_context(harness_factory):
    h = harness_factory()
    h.awakening_state.bot_messages.add(100, "the Kubernetes deployment failed with ImagePullBackOff")
    _seed_recent(h, ["早上好", "今天吃什么", "周末去哪玩"])

    event = DummyGroupEvent(DummyMessage([text_seg("Kubernetes ImagePullBackOff again?")]))
    await h.handle(event)

    h.svc.generate_reply.assert_awaited_once()
    kwargs = h.svc.generate_reply.await_args.kwargs
    # 现场补丁由 service 自取（list_patch 按 message_id 去重，集成测试覆盖），
    # 适配层不再传 recent_messages 快照
    assert "recent_messages" not in kwargs
    assert kwargs["prompt"].count("Kubernetes ImagePullBackOff again?") == 1
    assert kwargs["raw_user_text"] == "Kubernetes ImagePullBackOff again?"


async def test_explicit_trigger_keeps_pre_save_context(harness_factory):
    h = harness_factory(_llm_settings(allow_prefix=True))
    _seed_recent(h, ["早上好", "今天吃什么", "周末去哪玩"])

    event = DummyGroupEvent(DummyMessage([text_seg("/ai Kubernetes 部署怎么样")]))
    await h.handle(event)

    h.svc.generate_reply.assert_awaited_once()
    kwargs = h.svc.generate_reply.await_args.kwargs
    assert "recent_messages" not in kwargs  # service 自取补丁
    assert kwargs["prompt"] == "Kubernetes 部署怎么样"
    h.svc.quick_judge_detailed.assert_not_awaited()


async def test_voice_transcript_can_hit_passive_trigger(harness_factory):
    h = harness_factory()
    h.awakening_state.bot_messages.add(100, "Kubernetes ImagePullBackOff warnings")
    _seed_recent(h, ["早上好"])

    message = DummyMessage([record_seg("voice.silk", text="Kubernetes ImagePullBackOff 又 warnings 了吗")])
    await h.handle(DummyGroupEvent(message))

    h.svc.quick_judge_detailed.assert_awaited_once()
    h.svc.generate_reply.assert_awaited_once()
    kwargs = h.svc.generate_reply.await_args.kwargs
    assert "[语音转文字：Kubernetes ImagePullBackOff 又 warnings 了吗]" in kwargs["prompt"]
    assert kwargs["prompt"].count("Kubernetes ImagePullBackOff") == 1
    assert "recent_messages" not in kwargs  # service 自取补丁
    assert kwargs["raw_user_text"] == "Kubernetes ImagePullBackOff 又 warnings 了吗"


async def test_passive_rules_receive_safe_text_and_separate_repeat_fingerprint(harness_factory):
    h = harness_factory()
    message = DummyMessage([
        text_seg("玩"),
        at_seg("10001"),
        text_seg("玩的"),
    ])

    await h.handle(DummyGroupEvent(message))

    h.svc.generate_reply.assert_not_awaited()
    gm.resolve_reply.assert_awaited_once()
    args, kwargs = gm.resolve_reply.await_args
    assert "[CQ:" not in args[0]
    assert "@" in args[0]
    assert kwargs["repeat_fingerprint"] == "玩[CQ:at,qq=10001]玩的"


async def test_face_segment_does_not_enter_passive_rule_text(harness_factory):
    h = harness_factory()
    message = DummyMessage([text_seg("我喜欢"), face_seg()])

    await h.handle(DummyGroupEvent(message))

    gm.resolve_reply.assert_awaited_once()
    args, kwargs = gm.resolve_reply.await_args
    assert args[0] == "我喜欢"
    assert kwargs["repeat_fingerprint"] == "我喜欢[CQ:face]"


async def test_empty_trimmed_repeat_does_not_send_or_consume_rate_limit(harness_factory):
    h = harness_factory()
    gm.resolve_reply.return_value = {
        "repeat_action": RepeatAction.TRIM_LAST,
        "reply": "",
        "rate_limit_key": "repeat_trim_last",
        "rule_name": "repeat_trim_last",
    }

    await h.handle(DummyGroupEvent(DummyMessage([face_seg()])))

    assert h.recorder.sent == []
    assert h.rate_limiter.allow_calls == []
