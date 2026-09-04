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
    def __init__(self, forward_payloads: dict[str, dict] | None = None):
        self._payloads = forward_payloads or {}
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        return self._payloads.get(kwargs.get("message_id", ""), {})


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
    bot = _StubBot({"fid_direct": _forward_payload()})
    msg = DummyMessage([forward_seg("fid_direct"), text_seg("分析一下")])

    text, images = await extract_forward_content(bot=bot, message=msg, bot_self_id="12345")

    assert bot.calls == [("get_forward_msg", {"message_id": "fid_direct"})]
    assert "合并里第 1 条" in text
    assert "合并里第 2 条" in text
    assert images == ["https://example.test/fwd1.png"]


@pytest.mark.asyncio
async def test_forward_text_capped_with_marker():
    # 总量封顶：保头硬切 + 截断标记；递归内部不逐层裁剪，只在最外层出口生效
    from quickquip.adapters.nonebot._forward import MAX_FORWARD_TEXT_CHARS

    payload = {
        "messages": [
            {
                "sender": {"nickname": f"U{i}", "user_id": 10000 + i},
                "content": [{"type": "text", "data": {"text": "长文本" * 40}}],
            }
            for i in range(50)  # 50 节点 × 120 字 = 6000 字 > 4000 上限
        ]
    }
    bot = _StubBot({"fid_long": payload})
    msg = DummyMessage([forward_seg("fid_long"), text_seg("看看")])

    text, _ = await extract_forward_content(bot=bot, message=msg, bot_self_id="12345")

    marker = "…（合并转发内容过长，已截断）"
    assert text.endswith(marker)
    assert len(text) <= MAX_FORWARD_TEXT_CHARS + len(marker)
    assert "1. " in text  # 保头：首个节点仍在
    assert "U49" not in text  # 尾部节点被切掉


@pytest.mark.asyncio
async def test_extracts_from_reply_when_current_has_none():
    bot = _StubBot({"fid_via_reply": _forward_payload()})
    # Current message is the quote + @bot + user's question: no forward segment
    current = DummyMessage([at_seg("12345"), text_seg("你怎么看这个")])
    reply = DummyReply(message="[合并转发消息]", user_id="10001", sender=DummySender(nickname="Alice"), message_id="42")
    reply.raw_message = DummyMessage([forward_seg("fid_via_reply")])

    text, images = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=reply
    )

    assert bot.calls == [("get_forward_msg", {"message_id": "fid_via_reply"})]
    assert "合并里第 1 条" in text
    assert images == ["https://example.test/fwd1.png"]


@pytest.mark.asyncio
async def test_current_message_forward_wins_over_reply():
    bot = _StubBot({"fid_direct": _forward_payload(), "fid_in_reply": _forward_payload()})
    current = DummyMessage([forward_seg("fid_direct"), text_seg("说说")])
    reply_msg = DummyMessage([forward_seg("fid_in_reply")])
    reply = DummyReply(message=reply_msg, user_id="10001")

    text, _ = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=reply
    )

    assert bot.calls == [("get_forward_msg", {"message_id": "fid_direct"})]
    assert text


@pytest.mark.asyncio
async def test_no_forward_anywhere_returns_empty():
    bot = _StubBot({"fid": _forward_payload()})
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
    bot = _StubBot({"fid": _forward_payload()})
    current = DummyMessage([at_seg("12345"), text_seg("嗨")])

    text, images = await extract_forward_content(
        bot=bot, message=current, bot_self_id="12345", reply=None
    )

    assert bot.calls == []
    assert text == ""
    assert images == []


@pytest.mark.asyncio
async def test_nested_forward_expands_recursively_with_images_and_bot_marker():
    payloads = {
        "fid_outer": {
            "messages": [
                {
                    "sender": {"nickname": "Alice", "user_id": 10001},
                    "content": [
                        {"type": "text", "data": {"text": "外层开头"}},
                        {"type": "forward", "data": {"id": "fid_mid"}},
                        {"type": "image", "data": {"url": "https://example.test/outer.png"}},
                    ],
                }
            ]
        },
        "fid_mid": {
            "messages": [
                {
                    "sender": {"nickname": "", "user_id": 12345},
                    "content": [
                        {"type": "text", "data": {"text": "中层"}},
                        {"type": "forward", "data": {"id": "fid_inner"}},
                    ],
                }
            ]
        },
        "fid_inner": {
            "messages": [
                {
                    "sender": {"nickname": "Bob", "user_id": 10002},
                    "content": [
                        {"type": "text", "data": {"text": "里层"}},
                        {"type": "image", "data": {"url": "https://example.test/inner.png"}},
                    ],
                }
            ]
        },
    }
    bot = _StubBot(payloads)
    current = DummyMessage([forward_seg("fid_outer"), text_seg("看看这个")])

    text, images = await extract_forward_content(
        bot=bot,
        message=current,
        bot_self_id="12345",
        bot_self_ids={"12345", "67890"},
    )

    assert "机器人（QQ 12345）" in text
    assert "外层开头" in text
    assert "中层" in text
    assert "里层" in text
    assert images == ["https://example.test/inner.png", "https://example.test/outer.png"]
    assert [call[1]["message_id"] for call in bot.calls] == ["fid_outer", "fid_mid", "fid_inner"]
