from __future__ import annotations

from pathlib import Path

from plugins.llm_identity import IdentityIndex
from plugins.message_rendering import render_message_for_llm

from tests.fixtures.configs import IDENTITIES_YAML
from tests.fixtures.onebot import DummyMessage, at_seg, forward_seg, image_seg, text_seg


def _identity_index(tmp_path: Path) -> IdentityIndex:
    path = tmp_path / "identities.yaml"
    path.write_text(IDENTITIES_YAML, encoding="utf-8")
    return IdentityIndex.from_file(path)


def test_render_replaces_at_with_canonical_name(tmp_path: Path):
    idx = _identity_index(tmp_path)
    msg = DummyMessage([
        text_seg("/ai 你看看"),
        at_seg("2002"),
        text_seg(" 今天又在说什么"),
    ])
    rendered = render_message_for_llm(
        msg,
        bot_self_id="12345",
        identity_index=idx,
        include_image_placeholder=True,
    )
    assert rendered.text == "/ai 你看看@镜子 今天又在说什么"


def test_render_handles_dict_segments(tmp_path: Path):
    """Forward / merged-message API yields plain dicts; renderer must accept them."""
    idx = _identity_index(tmp_path)
    dict_message = [
        {"type": "text", "data": {"text": "hello "}},
        {"type": "at", "data": {"qq": "2002"}},
        {"type": "text", "data": {"text": " world"}},
        {"type": "image", "data": {"url": "https://example.test/dict-img.png"}},
    ]
    rendered = render_message_for_llm(dict_message, bot_self_id="12345", identity_index=idx)
    assert rendered.text == "hello @镜子 world"
    assert rendered.image_urls == ["https://example.test/dict-img.png"]


def test_render_image_placeholder_can_be_disabled(tmp_path: Path):
    idx = _identity_index(tmp_path)
    msg = DummyMessage([
        text_seg("看这个"),
        image_seg("https://example.test/x.png"),
    ])
    rendered = render_message_for_llm(
        msg,
        bot_self_id="12345",
        identity_index=idx,
        include_image_placeholder=False,
    )
    # When the placeholder is off, only image_urls is populated; the text omits "[图片]"
    assert rendered.text == "看这个"
    assert rendered.image_urls == ["https://example.test/x.png"]


def test_render_forward_segment_emits_placeholder_when_enabled():
    msg = DummyMessage([forward_seg("fid_123"), text_seg("看一下")])
    rendered = render_message_for_llm(
        msg,
        bot_self_id="12345",
        include_image_placeholder=True,
    )
    assert "[合并转发消息]" in rendered.text
    assert "看一下" in rendered.text


def test_render_forward_segment_ignored_when_placeholder_off():
    msg = DummyMessage([forward_seg("fid_123"), text_seg("看一下")])
    rendered = render_message_for_llm(
        msg,
        bot_self_id="12345",
        include_image_placeholder=False,
    )
    # Without the placeholder opt-in, rule-matching path stays untouched: forward
    # segment collapses silently, plain text is returned as before.
    assert rendered.text == "看一下"
