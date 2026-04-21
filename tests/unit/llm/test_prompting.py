from __future__ import annotations

from quickquip.llm.prompting import build_user_message_content


def test_forward_only_content():
    content = build_user_message_content(
        prompt="你怎么看？",
        forward_text="1. Alice（QQ 10001）：你好",
        forward_image_urls=["https://example.test/fwd.png"],
        max_quoted_message_chars=1200,
    )
    assert "以下是用户转发的合并消息" in content
    assert "1. Alice（QQ 10001）：你好" in content
    assert "转发附图：1 张" in content
    assert "当前用户消息：" in content
    assert "你怎么看？" in content


def test_quoted_only_content():
    content = build_user_message_content(
        prompt="这是什么？",
        quoted_text="原来的消息",
        quoted_sender_name="镜子",
        quoted_user_id="2002",
        quoted_image_urls=["https://example.test/q.png"],
        max_quoted_message_chars=1200,
    )
    assert "以下是当前用户显式引用的消息" in content
    assert "镜子" in content
    assert "2002" in content
    assert "引用附图：1 张" in content
    assert "这是什么？" in content


def test_both_quoted_and_forward_coexist():
    content = build_user_message_content(
        prompt="你怎么看？",
        quoted_text="原来的消息",
        quoted_sender_name="镜子",
        quoted_user_id="2002",
        quoted_image_urls=["https://example.test/q.png"],
        forward_text="1. Alice（QQ 10001）：转发内容",
        forward_image_urls=["https://example.test/f.png"],
        max_quoted_message_chars=1200,
    )
    assert "以下是当前用户显式引用的消息" in content
    assert "以下是用户转发的合并消息" in content
    assert "引用附图：1 张" in content
    assert "转发附图：1 张" in content


def test_plain_prompt_without_extras():
    content = build_user_message_content(prompt="只有正文", max_quoted_message_chars=1200)
    assert "以下是当前用户显式引用的消息" not in content
    assert "以下是用户转发的合并消息" not in content
    assert "只有正文" in content
