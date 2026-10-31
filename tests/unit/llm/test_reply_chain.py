import pytest

from quickquip.llm.reply_chain import (
    _EMPTY_IMAGE_PROMPT,
    _EMPTY_QUOTED_TEXT_PROMPT,
    normalize_turn_input,
)
from quickquip.llm.reply_types import ChatTurnRequest


def _normalize(**overrides):
    kwargs = {
        "chat_id": 1000000000,
        "chat_type": "group",
        "user_id": 123456,
        "sender_name": "测试用户",
        "prompt": "",
    }
    kwargs.update(overrides)
    return normalize_turn_input(ChatTurnRequest(**kwargs), max_prompt_chars=10000)


def test_quoted_text_without_current_text_gets_default_prompt():
    turn = _normalize(quoted_text="原文")

    assert turn.trimmed_prompt == _EMPTY_QUOTED_TEXT_PROMPT


def test_image_only_message_keeps_default_image_prompt():
    turn = _normalize(image_urls=["https://example.test/current.png"])

    assert turn.trimmed_prompt == _EMPTY_IMAGE_PROMPT


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"prompt": "你怎么看？", "quoted_text": "原文"}, "你怎么看？"),
        (
            {
                "quoted_text": "原文",
                "image_urls": ["https://example.test/current.png"],
            },
            "",
        ),
        (
            {
                "quoted_text": "原文",
                "quoted_image_urls": ["https://example.test/quoted.png"],
            },
            "",
        ),
    ],
    ids=["additional-text", "current-image", "quoted-image"],
)
def test_non_quote_only_inputs_keep_prompt(overrides, expected):
    turn = _normalize(**overrides)

    assert turn.trimmed_prompt == expected
