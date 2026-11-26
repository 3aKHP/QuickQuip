from __future__ import annotations

import base64

import pytest

from quickquip.adapters.nonebot import long_messages
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
async def test_send_long_group_message_falls_back_to_single_long_image(monkeypatch):
    bot = _FallbackBot()
    render_calls: list[tuple[str, str, str]] = []
    fake_png = b"\x89PNG\r\n\x1a\nfake-long-image"

    def _fake_render(content: str, *, title: str = "", footer: str = "") -> bytes:
        render_calls.append((content, title, footer))
        return fake_png

    monkeypatch.setattr(long_messages, "render_text_to_image", _fake_render)
    body = "第一段内容\n\n" + "测试长图渲染" * 200

    await send_long_group_message(
        bot,
        456,
        body,
        node_name="群聊日报",
        log_name="daily_summary",
    )

    assert len(render_calls) == 1
    assert render_calls[0][0] == body
    assert render_calls[0][1] == "群聊日报"
    assert render_calls[0][2] == long_messages._IMAGE_FALLBACK_FOOTER
    # 合并转发失败时只发 1 条图片消息，不拆成多条纯文本刷屏
    assert len(bot.sent) == 1
    assert bot.sent[0]["group_id"] == 456
    message = bot.sent[0]["message"]
    assert len(message) == 1
    assert message[0].type == "image"
    file_uri = message[0].data["file"]
    assert file_uri.startswith("base64://")
    raw_png = base64.b64decode(file_uri.removeprefix("base64://"))
    assert raw_png == fake_png


@pytest.mark.asyncio
async def test_send_long_group_message_raises_without_text_spam_when_image_fails(monkeypatch):
    bot = _FallbackBot(fail_send=True)
    monkeypatch.setattr(
        long_messages,
        "render_text_to_image",
        lambda content, *, title="", footer="": b"\x89PNG\r\n\x1a\nfake-long-image",
    )

    with pytest.raises(RuntimeError, match="image send failed"):
        await send_long_group_message(
            bot,
            456,
            "b" * 900,
            node_name="人物志",
            log_name="profile",
        )

    assert bot.sent == []


@pytest.mark.asyncio
async def test_send_long_group_message_blocks_before_forward_and_image_fallback(
    tmp_path, monkeypatch
):
    from quickquip.common.sensitive_filter import DEFAULT_OUTPUT_FALLBACK
    from tests.fixtures.sensitive_filter import make_sensitive_filter

    sf = make_sensitive_filter(tmp_path, "block", "违禁词")
    monkeypatch.setattr("quickquip.common.sensitive_filter.get_filter", lambda: sf)

    bot = _FallbackBot()
    rendered = []
    monkeypatch.setattr(
        long_messages,
        "render_text_to_image",
        lambda *args, **kwargs: rendered.append(args) or b"png",
    )

    await send_long_group_message(
        bot,
        456,
        "长文内容包含违禁词" * 50,
        node_name="群聊日报",
        log_name="daily_summary",
    )

    assert rendered == []
    assert len(bot.sent) == 1
    assert bot.sent[0]["group_id"] == 456
    assert str(bot.sent[0]["message"]) == DEFAULT_OUTPUT_FALLBACK


@pytest.mark.asyncio
async def test_send_long_group_message_allows_soft_hit_and_falls_back_to_image(
    tmp_path, monkeypatch
):
    from tests.fixtures.sensitive_filter import make_sensitive_filter

    sf = make_sensitive_filter(tmp_path, "soft", "擦边词")
    monkeypatch.setattr("quickquip.common.sensitive_filter.get_filter", lambda: sf)

    bot = _FallbackBot()
    monkeypatch.setattr(
        long_messages,
        "render_text_to_image",
        lambda content, *, title="", footer="": b"\x89PNG\r\n\x1a\nok",
    )

    await send_long_group_message(
        bot,
        456,
        "长文包含擦边词" * 50,
        node_name="群聊日报",
        log_name="daily_summary",
    )

    assert len(bot.sent) == 1
    assert bot.sent[0]["message"][0].type == "image"
