from __future__ import annotations

import pytest
from nonebot.adapters.onebot.v11 import Message

from quickquip.adapters.nonebot._safe_send import send_group_text, send_private_text


class _Bot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_group_msg(self, **kwargs):
        self.sent.append(kwargs)

    async def send_private_msg(self, **kwargs):
        self.sent.append(kwargs)


@pytest.mark.asyncio
async def test_send_group_text_sends_single_text_segment():
    bot = _Bot()

    await send_group_text(bot, 123, "看这里 [CQ:at,qq=all]")

    assert bot.sent[0]["group_id"] == 123
    message = bot.sent[0]["message"]
    assert isinstance(message, Message)
    assert len(message) == 1
    assert message[0].type == "text"
    assert message[0].data["text"] == "看这里 [CQ:at,qq=all]"


@pytest.mark.asyncio
async def test_send_private_text_sends_single_text_segment():
    bot = _Bot()

    await send_private_text(bot, 456, "歌词 [CQ:image,file=http://evil.test/x]")

    assert bot.sent[0]["user_id"] == 456
    message = bot.sent[0]["message"]
    assert isinstance(message, Message)
    assert len(message) == 1
    assert message[0].type == "text"
    assert message[0].data["text"] == "歌词 [CQ:image,file=http://evil.test/x]"
