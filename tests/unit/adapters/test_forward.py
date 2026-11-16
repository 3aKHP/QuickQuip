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
    reply = DummyReply(
        message="[合并转发消息]", user_id="10001",
        sender=DummySender(nickname="Alice"), message_id="42",
    )
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


@pytest.mark.asyncio
@pytest.mark.parametrize("account", [1094950020, "1094950020"])
async def test_placeholder_sender_never_resolves_identity(account):
    from unittest.mock import Mock
    from quickquip.llm.identity import IdentityIndex
    from quickquip.adapters.nonebot._forward import FORWARD_IDENTITY_NOTICE
    identities = Mock(spec=IdentityIndex)
    nodes = [{"sender": {"nickname": name, "user_id": account},
              "content": [text_seg("话")]} for name in ("甲", "乙", "")]
    text, _ = await extract_forward_content(
        _StubBot(), [{"type": "forward", "data": {"content": nodes}}], str(account), identities,
    )
    assert "QQ 1094950020" not in text
    assert "甲（转发显示名，账号未知）" in text
    assert "乙（转发显示名，账号未知）" in text
    assert "未知发言者（转发账号未知）" in text
    assert text.count(FORWARD_IDENTITY_NOTICE) == 1
    identities.resolve_user.assert_not_called()


@pytest.mark.asyncio
async def test_nested_budget_keeps_outer_tail_and_all_images():
    from quickquip.adapters.nonebot._forward import MAX_FORWARD_TEXT_CHARS
    from quickquip.llm.forward_rendering import CHILD_START, CHILD_END, INNER_TRUNCATED
    child = [{"sender": {"nickname": "甲", "user_id": 1094950020},
              "content": [text_seg("内" * 10000), image_seg("https://example.test/end.png")]}]
    nodes = [{"sender": {"user_id": 10001}, "content": [text_seg("短句 A")]},
             {"sender": {"user_id": 10002},
              "content": [{"type": "forward", "data": {"content": child}}]},
             {"sender": {"user_id": 10003}, "content": [text_seg("短句 B")]}]
    text, images = await extract_forward_content(
        _StubBot(), [{"type": "forward", "data": {"content": nodes}}], "99",
    )
    assert "短句 A" in text and "短句 B" in text
    assert text.index(CHILD_START) < text.index(INNER_TRUNCATED) < text.index(CHILD_END)
    assert len(text) <= MAX_FORWARD_TEXT_CHARS
    assert images == ["https://example.test/end.png"]


def test_tree_budget_siblings_deep_blocks_and_small_limits():
    from quickquip.llm.forward_rendering import (
        ForwardBlock, render_forward_block, CHILD_START, CHILD_END, INNER_TRUNCATED,
    )
    tree = ForwardBlock(["A", ForwardBlock(["first" * 200]), "B",
                         ForwardBlock(["second", ForwardBlock(["deep" * 200])]), "C"])
    for limit in range(200):
        text = render_forward_block(tree, limit, outer=True)
        assert len(text) <= limit
        assert text.count(CHILD_START) == text.count(CHILD_END)
    text = render_forward_block(tree, 350, outer=True)
    assert all(word in text for word in ("A", "B", "C", "second"))
    assert INNER_TRUNCATED in text
