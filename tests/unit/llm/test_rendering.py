from __future__ import annotations

from pathlib import Path

from plugins.llm_identity import IdentityIndex
from plugins.message_rendering import render_message_for_llm, render_reply_for_llm

from tests.fixtures.configs import IDENTITIES_YAML
from tests.fixtures.onebot import DummyMessage, DummyReply, DummySender, at_seg, forward_seg, image_seg, text_seg


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


def test_render_replaces_at_for_any_bot_id(tmp_path: Path):
    idx = _identity_index(tmp_path)
    msg = DummyMessage([at_seg("67890"), text_seg(" 继续")])
    rendered = render_message_for_llm(
        msg,
        bot_self_ids={"12345", "67890"},
        identity_index=idx,
        include_image_placeholder=True,
    )
    assert rendered.text == "继续"
    assert rendered.mentioned_bot is True


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


def test_render_reply_marks_bot_self_with_multi_ids():
    reply = DummyReply(
        message=DummyMessage([text_seg("我是自己")]),
        user_id="67890",
        sender=DummySender(nickname="Bot"),
    )
    rendered = render_reply_for_llm(
        reply,
        bot_self_ids={"12345", "67890"},
        include_image_placeholder=True,
    )
    assert rendered is not None
    assert rendered.is_bot_self is True


# ---------------------------------------------------------------------------
# append_web_search_source_block — grounding 来源块
# ---------------------------------------------------------------------------

def _report(urls_titles: list[tuple[str, str]]):
    from plugins.llm_provider import LLMWebSearchReport, LLMWebSearchSource

    return LLMWebSearchReport(
        queries=["查询词"],
        sources=[LLMWebSearchSource(title=title, url=url) for url, title in urls_titles],
    )


def test_source_block_appends_title_and_domain():
    from plugins.message_rendering import append_web_search_source_block

    text = append_web_search_source_block(
        "有根据的回答。", _report([("https://example.test/a?x=1", "来源甲")])
    )

    assert text == "有根据的回答。\n\n来源：\n- 来源甲 — example.test"


def test_source_block_caps_at_three_entries():
    from plugins.message_rendering import append_web_search_source_block

    text = append_web_search_source_block(
        "回答。",
        _report([
            ("https://a.test/1", "甲"),
            ("https://b.test/2", "乙"),
            ("https://c.test/3", "丙"),
            ("https://d.test/4", "丁"),
        ]),
    )

    assert text.endswith("来源：\n- 甲 — a.test\n- 乙 — b.test\n- 丙 — c.test")
    assert "丁" not in text


def test_source_block_skips_urls_already_in_text_and_dedupes():
    from plugins.message_rendering import append_web_search_source_block

    text = append_web_search_source_block(
        "详见 https://example.test/a 已在正文。",
        _report([
            ("https://example.test/a", "正文来源"),  # URL 已出现 → 跳过
            ("https://example.test/b", "重复一"),
            ("https://example.test/b", "重复二"),  # 同 URL 即同来源，按 URL 去重
            ("https://example.test/c", "同域不同页"),  # 同域不同 URL 保留
        ]),
    )

    assert text == (
        "详见 https://example.test/a 已在正文。\n\n来源：\n- 重复一 — example.test\n- 同域不同页 — example.test"
    )


def test_source_block_title_missing_or_equal_domain_renders_domain_only():
    from plugins.message_rendering import append_web_search_source_block

    text = append_web_search_source_block(
        "回答。",
        _report([
            ("https://example.test/b", ""),
            ("https://example.test/c", "example.test"),
        ]),
    )

    assert text.endswith("来源：\n- example.test\n- example.test")


def test_source_block_empty_sources_returns_text_unchanged():
    from plugins.message_rendering import append_web_search_source_block

    assert append_web_search_source_block("原样。", _report([])) == "原样。"
