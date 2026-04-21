from __future__ import annotations

from pathlib import Path

from plugins.llm_identity import IdentityIndex
from plugins.llm_inputs import extract_llm_input, extract_llm_prompt, extract_private_llm_input
from plugins.llm_runtime import ResolvedGroupSettings

from tests.fixtures.configs import IDENTITIES_YAML
from tests.fixtures.onebot import DummyMessage, DummyReply, DummySender, at_seg, image_seg, text_seg


PREFIX_SETTINGS = ResolvedGroupSettings(
    enabled=True,
    memory_enabled=True,
    provider_id="openai-main",
    model="gpt-test",
    persona_id="default",
    trigger_prefix="/ai",
    allow_prefix=True,
    allow_at=True,
)


def _identity_index(tmp_path: Path) -> IdentityIndex:
    path = tmp_path / "identities.yaml"
    path.write_text(IDENTITIES_YAML, encoding="utf-8")
    return IdentityIndex.from_file(path)


def test_prefix_trigger():
    msg = DummyMessage([text_seg("/ai 你好")])
    assert extract_llm_prompt(msg, "12345", PREFIX_SETTINGS) == "你好"


def test_mention_trigger():
    msg = DummyMessage([at_seg("12345"), text_seg(" 讲个笑话")])
    assert extract_llm_prompt(msg, "12345", PREFIX_SETTINGS) == "讲个笑话"


def test_to_me_allows_free_text():
    msg = DummyMessage([text_seg("来一句")])
    assert extract_llm_prompt(msg, "12345", PREFIX_SETTINGS, is_to_me=True) == "来一句"


def test_mention_of_user_is_rendered_as_canonical_name(tmp_path: Path):
    idx = _identity_index(tmp_path)
    msg = DummyMessage([
        text_seg("/ai 你看看"),
        at_seg("2002"),
        text_seg(" 今天又在说什么"),
    ])
    assert (
        extract_llm_prompt(msg, "12345", PREFIX_SETTINGS, identity_index=idx)
        == "你看看@镜子 今天又在说什么"
    )


def test_image_only_with_prefix():
    msg = DummyMessage([text_seg("/ai"), image_seg("https://example.test/cat.png")])
    inp = extract_llm_input(msg, "12345", PREFIX_SETTINGS)
    assert inp is not None
    assert inp.prompt == ""
    assert inp.image_urls == ["https://example.test/cat.png"]


def test_quoted_reply_extracts_image_and_sender(tmp_path: Path):
    idx = _identity_index(tmp_path)
    reply = DummyReply(
        message=DummyMessage([
            at_seg("2002"),
            text_seg(" 这张图什么意思"),
            image_seg("https://example.test/reply-cat.png"),
        ]),
        user_id="2002",
        sender=DummySender(nickname="镜子"),
        message_id=7788,
    )
    msg = DummyMessage([at_seg("12345"), text_seg(" 帮我看看")])
    inp = extract_llm_input(msg, "12345", PREFIX_SETTINGS, identity_index=idx, reply=reply)
    assert inp is not None
    assert inp.prompt == "帮我看看"
    assert inp.quoted_text == "@镜子 这张图什么意思[图片]"
    assert inp.quoted_image_urls == ["https://example.test/reply-cat.png"]
    assert inp.quoted_sender_name == "镜子"
    assert inp.quoted_user_id == "2002"


def test_non_trigger_message_returns_none():
    msg = DummyMessage([text_seg("普通消息")])
    assert extract_llm_prompt(msg, "12345", PREFIX_SETTINGS) is None


def test_private_free_text_always_accepted():
    msg = DummyMessage([text_seg("普通私聊消息")])
    inp = extract_private_llm_input(msg, "12345", PREFIX_SETTINGS)
    assert inp is not None
    assert inp.prompt == "普通私聊消息"


def test_private_image_only_accepted():
    msg = DummyMessage([image_seg("https://example.test/private-cat.png")])
    inp = extract_private_llm_input(msg, "12345", PREFIX_SETTINGS)
    assert inp is not None
    assert inp.prompt == ""
    assert inp.image_urls == ["https://example.test/private-cat.png"]


def test_private_with_quoted_reply(tmp_path: Path):
    idx = _identity_index(tmp_path)
    reply = DummyReply(
        message=DummyMessage([
            at_seg("2002"),
            text_seg(" 这张图什么意思"),
            image_seg("https://example.test/q.png"),
        ]),
        user_id="2002",
        sender=DummySender(nickname="镜子"),
    )
    msg = DummyMessage([text_seg("帮我接着说")])
    inp = extract_private_llm_input(msg, "12345", PREFIX_SETTINGS, identity_index=idx, reply=reply)
    assert inp is not None
    assert inp.prompt == "帮我接着说"
    assert inp.quoted_text == "@镜子 这张图什么意思[图片]"
