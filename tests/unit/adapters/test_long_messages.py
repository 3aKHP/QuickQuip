from __future__ import annotations

import base64

import pytest

from quickquip.adapters.nonebot.long_messages import send_long_group_message, split_long_message


class _ForwardBot:
    self_id = "10000"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, name: str, **kwargs):
        self.calls.append((name, kwargs))


class _FallbackBot:
    self_id = "10000"

    def __init__(self, *, fail_send: bool = False):
        self.sent: list[dict] = []
        self._fail_send = fail_send

    async def call_api(self, name: str, **kwargs):
        raise RuntimeError("forward unavailable")

    async def send_group_msg(self, **kwargs):
        if self._fail_send:
            raise RuntimeError("image send failed")
        self.sent.append(kwargs)


def test_split_long_message_prefers_paragraph_boundaries():
    chunks = split_long_message("第一段\n\n第二段内容很长", max_chars=8)

    assert chunks == ["第一段", "第二段内容很长"]


@pytest.mark.asyncio
async def test_send_long_group_message_uses_forward_nodes():
    bot = _ForwardBot()

    await send_long_group_message(
        bot,
        123,
        "a" * 900,
        node_name="人物志",
        log_name="profile",
    )

    assert bot.calls[0][0] == "send_group_forward_msg"
    payload = bot.calls[0][1]
    assert payload["group_id"] == 123
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["data"]["name"] == "人物志"


@pytest.mark.asyncio
async def test_send_long_group_message_falls_back_to_single_long_image():
    bot = _FallbackBot()

    await send_long_group_message(
        bot,
        456,
        "第一段内容\n\n" + "测试长图渲染" * 200,
        node_name="群聊日报",
        log_name="daily_summary",
    )

    # 合并转发失败时只发 1 条图片消息，不拆成多条纯文本刷屏
    assert len(bot.sent) == 1
    assert bot.sent[0]["group_id"] == 456
    message = bot.sent[0]["message"]
    assert len(message) == 1
    assert message[0].type == "image"
    file_uri = message[0].data["file"]
    assert file_uri.startswith("base64://")
    raw_png = base64.b64decode(file_uri.removeprefix("base64://"))
    assert raw_png[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_send_long_group_message_raises_without_text_spam_when_image_fails():
    bot = _FallbackBot(fail_send=True)

    with pytest.raises(RuntimeError, match="image send failed"):
        await send_long_group_message(
            bot,
            456,
            "b" * 900,
            node_name="人物志",
            log_name="profile",
        )

    assert bot.sent == []
