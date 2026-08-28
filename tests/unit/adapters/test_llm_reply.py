from __future__ import annotations

from quickquip.adapters.nonebot._llm_reply import build_llm_reply_message


class _FakeSegment:
    @staticmethod
    def text(value: str):
        return ("text", value)

    @staticmethod
    def image(value: str):
        return ("image", value)


class _FakeMessage(list):
    def __init__(self, segments):
        super().__init__(segments)


def test_plain_reply_without_images():
    result = {"reply": "你好", "images": []}
    message = build_llm_reply_message(result, _FakeMessage, _FakeSegment)
    # 恒返回 Message：裸 str 直调 bot.send_* 会被服务端按 CQ 码解析
    assert isinstance(message, _FakeMessage)
    assert list(message) == [("text", "你好")]


def test_images_appended_after_text():
    result = {"reply": "看图", "images": ["QUJD", "REVG"]}
    message = build_llm_reply_message(result, _FakeMessage, _FakeSegment)
    assert isinstance(message, _FakeMessage)
    assert list(message) == [
        ("text", "看图"),
        ("image", "base64://QUJD"),
        ("image", "base64://REVG"),
    ]


def test_missing_images_key_returns_text_segment():
    result = {"reply": "只有文本"}
    message = build_llm_reply_message(result, _FakeMessage, _FakeSegment)
    assert isinstance(message, _FakeMessage)
    assert list(message) == [("text", "只有文本")]


def test_always_returns_message_even_for_cq_like_text():
    result = {"reply": "看这里 [CQ:at,qq=all]"}
    message = build_llm_reply_message(result, _FakeMessage, _FakeSegment)
    assert isinstance(message, _FakeMessage)
    assert list(message) == [("text", "看这里 [CQ:at,qq=all]")]
