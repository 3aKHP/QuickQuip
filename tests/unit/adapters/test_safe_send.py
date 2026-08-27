from __future__ import annotations

import pytest
from nonebot.adapters.onebot.v11 import Message

from quickquip.adapters.nonebot._safe_send import send_group_text


class _Bot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_group_msg(self, **kwargs):
        self.sent.append(kwargs)


@pytest.mark.asyncio
async def test_send_group_text_sends_single_text_segment():
    bot = _Bot()

    await send_group_text(bot, 123, "hello")

    assert bot.sent[0]["group_id"] == 123
    message = bot.sent[0]["message"]
    assert isinstance(message, Message)
    assert len(message) == 1
    assert message[0].type == "text"
    assert message[0].data["text"] == "hello"


@pytest.mark.asyncio
async def test_send_group_text_keeps_cq_like_text_literal():
    bot = _Bot()

    await send_group_text(bot, 123, "看这里 [CQ:at,qq=all]")

    message = bot.sent[0]["message"]
    assert message[0].type == "text"
    assert message[0].data["text"] == "看这里 [CQ:at,qq=all]"
