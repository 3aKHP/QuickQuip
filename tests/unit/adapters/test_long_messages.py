from __future__ import annotations

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

    def __init__(self):
        self.sent: list[dict] = []

    async def call_api(self, name: str, **kwargs):
        raise RuntimeError("forward unavailable")

    async def send_group_msg(self, **kwargs):
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
async def test_send_long_group_message_falls_back_to_chunks(monkeypatch):
    async def no_sleep(delay):
        return None

    monkeypatch.setattr("quickquip.adapters.nonebot.long_messages.asyncio.sleep", no_sleep)
    bot = _FallbackBot()

    await send_long_group_message(
        bot,
        456,
        "b" * 900,
        node_name="人物志",
        log_name="profile",
    )

    assert [item["group_id"] for item in bot.sent] == [456, 456]
    assert "".join(item["message"] for item in bot.sent) == "b" * 900
