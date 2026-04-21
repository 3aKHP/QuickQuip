from __future__ import annotations

import pytest

from quickquip.adapters.nonebot._forward import extract_forward_content

from tests.fixtures.onebot import (
    DummyMessage,
    DummyReply,
    DummySender,
    at_seg,
    forward_seg,
    image_seg,
    text_seg,
)


class _StubBot:
    def __init__(self, forward_payload: dict | None = None):
        self._payload = forward_payload or {}
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return self._payload


def _forward_payload() -> dict:
    return {
        "messages": [
            {
                "sender": {"nickname": "Alice", "user_id": 10001},
                "content": [
                    {"type": "text", "data": {"text": "合并里第 1 条"}},
                    {"type": "image", "data": {"url": "https://example.test/fwd1.png"}},
                ],
            },
            {
                "sender": {"nickname": "Bob", "user_id": 10002},
                "content": [{"type": "text", "data": {"text": "合并里第 2 条"}}],
            },
        ]
    }


@pytest.mark.asyncio
async def test_extracts_from_current_message():
    bot = _StubBot(_forward_payload())
    msg = DummyMessage([forward_seg("fid_direct"), text_seg("分析一下")])

    text, images = await extract_forward_content(bot=bot, message=msg, bot_self_id="12345")

    assert bot.calls == [("get_forward_msg", {"id": "fid_direct"})]
    assert "合并里第 1 条" in text
    assert "合并里第 2 条" in text
    assert images == ["https://example.test/fwd1.png"]


@pytest.mark.asyncio
async def test_extracts_from_reply_when_current_has_none():
    bot = _StubBot(_forward_payload())
    # Current message is the quote + @bot + user's question: no forward segment
    current = DummyMessage([at_seg("12345"), text_seg("你怎么看这个")])
    reply_msg = DummyMessage([forward_seg("fid_via_reply")])
    reply = DummyReply(
        message=reply_msg,
        user_id="10001",
        sender=DummySender(nickname="Alice"),
        message_id="42",
    )

    text, images = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=reply
    )

    assert bot.calls == [("get_forward_msg", {"id": "fid_via_reply"})]
    assert "合并里第 1 条" in text
    assert images == ["https://example.test/fwd1.png"]


@pytest.mark.asyncio
async def test_current_message_forward_wins_over_reply():
    bot = _StubBot(_forward_payload())
    current = DummyMessage([forward_seg("fid_direct"), text_seg("说说")])
    reply_msg = DummyMessage([forward_seg("fid_in_reply")])
    reply = DummyReply(message=reply_msg, user_id="10001")

    text, _ = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=reply
    )

    assert bot.calls == [("get_forward_msg", {"id": "fid_direct"})]
    assert text


@pytest.mark.asyncio
async def test_no_forward_anywhere_returns_empty():
    bot = _StubBot(_forward_payload())
    current = DummyMessage([at_seg("12345"), text_seg("嗨")])
    reply_msg = DummyMessage([text_seg("之前那句话"), image_seg("https://example.test/prev.png")])
    reply = DummyReply(message=reply_msg, user_id="10001")

    text, images = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=reply
    )

    assert bot.calls == []
    assert text == ""
    assert images == []


@pytest.mark.asyncio
async def test_reply_none_is_safe():
    bot = _StubBot(_forward_payload())
    current = DummyMessage([at_seg("12345"), text_seg("嗨")])

    text, images = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=None
    )

    assert bot.calls == []
    assert text == ""
    assert images == []
