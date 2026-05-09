from __future__ import annotations

from types import SimpleNamespace

from quickquip.llm.prompting import (
    _build_scene_from_current_message,
    _build_scene_from_recent_buffer,
    _build_scenes_from_history,
    _render_scene_to_text,
    build_messages,
    build_system_prompt,
    build_user_message_content,
    format_participant_label,
    merge_image_urls,
)
from quickquip.llm.tools import (
    LLMSceneMessage,
    SCENE_MARKER_CONTEXT,
    SCENE_MARKER_CURRENT,
)


# ---------------------------------------------------------------------------
# format_participant_label
# ---------------------------------------------------------------------------

def test_label_registered_with_different_display_name():
    label = format_participant_label(
        user_id="123", sender_name="昵称A", canonical_name="标准A",
    )
    assert "标准A" in label
    assert "QQ 123" in label
    assert "昵称A" in label


def test_label_registered_same_name():
    label = format_participant_label(
        user_id="123", sender_name="标准A", canonical_name="标准A",
    )
    assert "标准A（QQ 123）" == label


def test_label_unregistered():
    label = format_participant_label(user_id="123", sender_name="路人")
    assert "路人" in label
    assert "QQ 123" in label
    assert "未登记" in label


def test_label_missing_all():
    assert format_participant_label(user_id="") == "未知用户"


# ---------------------------------------------------------------------------
# merge_image_urls
# ---------------------------------------------------------------------------

def test_merge_deduplicates_and_preserves_order():
    result = merge_image_urls(
        ["a.png", "b.png"], ["b.png", "c.png"], [],
    )
    assert result == ["a.png", "b.png", "c.png"]


def test_merge_filters_empty_and_whitespace():
    result = merge_image_urls(["", "  ", "a.png"])
    assert result == ["a.png"]


# ---------------------------------------------------------------------------
# Scene building — history
# ---------------------------------------------------------------------------

def test_scenes_from_history_groups_between_assistant():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "msg1", "raw_content": "msg1"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "msg2", "raw_content": "msg2"},
        {"role": "assistant", "content": "reply1"},
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "msg3", "raw_content": "msg3"},
    ]
    scenes = _build_scenes_from_history(history)
    assert len(scenes) == 2
    assert scenes[0].scene_type == "history"
    assert len(scenes[0].speakers) == 2
    assert scenes[0].speakers[0]["text"] == "msg1"
    assert scenes[0].speakers[1]["text"] == "msg2"
    assert scenes[1].scene_type == "history"
    assert len(scenes[1].speakers) == 1
    assert scenes[1].speakers[0]["text"] == "msg3"


def test_scenes_from_history_no_assistant():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "msg1", "raw_content": "msg1"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "msg2", "raw_content": "msg2"},
    ]
    scenes = _build_scenes_from_history(history)
    assert len(scenes) == 1
    assert len(scenes[0].speakers) == 2


def test_scenes_from_history_skips_empty_and_unknown_roles():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "", "raw_content": ""},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "ok", "raw_content": "ok"},
        {"role": "system", "content": "ignored"},
    ]
    scenes = _build_scenes_from_history(history)
    assert len(scenes) == 1
    assert len(scenes[0].speakers) == 1


def test_scenes_from_history_prefers_raw_content():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A",
         "content": "FORMATTED: 历史会话消息\n- 发言者：A\n- 内容：raw",
         "raw_content": "raw"},
    ]
    scenes = _build_scenes_from_history(history)
    assert scenes[0].speakers[0]["text"] == "raw"


def test_scenes_from_history_falls_back_to_content():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A",
         "content": "plain text",
         "raw_content": ""},
    ]
    scenes = _build_scenes_from_history(history)
    assert scenes[0].speakers[0]["text"] == "plain text"


# ---------------------------------------------------------------------------
# Scene building — recent buffer
# ---------------------------------------------------------------------------

def test_scene_from_recent_buffer_empty():
    assert _build_scene_from_recent_buffer([], max_trigger_context_messages=5) is None


def test_scene_from_recent_buffer_truncates():
    msgs = [
        {"user_id": str(i), "sender_name": f"user{i}", "text": f"msg{i}"}
        for i in range(10)
    ]
    scene = _build_scene_from_recent_buffer(msgs, max_trigger_context_messages=3)
    assert scene is not None
    assert len(scene.speakers) == 3
    assert scene.speakers[0]["text"] == "msg7"
    assert scene.speakers[-1]["text"] == "msg9"


# ---------------------------------------------------------------------------
# Scene building — current message
# ---------------------------------------------------------------------------

def test_current_scene_basic():
    scene = _build_scene_from_current_message(
        prompt="你好", image_urls=[], sender_name="扎师傅", user_id="123456",
    )
    assert scene.scene_type == "current"
    assert len(scene.speakers) == 1
    assert scene.speakers[0]["text"] == "你好"


def test_current_scene_with_quoted():
    scene = _build_scene_from_current_message(
        prompt="他说了什么？", image_urls=[],
        sender_name="扎师傅", user_id="123456",
        quoted_text="你好", quoted_sender_name="小明", quoted_user_id="789",
    )
    assert len(scene.speakers) == 2
    assert scene.speakers[0]["text"].startswith("[引用]")
    assert "你好" in scene.speakers[0]["text"]
    assert scene.speakers[1]["text"] == "他说了什么？"


def test_current_scene_with_forward():
    scene = _build_scene_from_current_message(
        prompt="怎么看？", image_urls=[],
        sender_name="扎师傅", user_id="123456",
        forward_text="合并消息内容",
    )
    assert len(scene.speakers) == 2
    assert "[转发]" in scene.speakers[0]["text"]
    assert "合并消息内容" in scene.speakers[0]["text"]


def test_current_scene_with_bot_self_quote():
    scene = _build_scene_from_current_message(
        prompt="你怎么看？", image_urls=[],
        sender_name="4s", user_id="4004",
        quoted_text="旧消息", quoted_sender_name="4s", quoted_user_id="4004",
        quoted_is_bot_self=True,
    )
    assert scene.speakers[0]["sender_name"] == "机器人自己"
    assert scene.speakers[0]["canonical_name"] == "机器人自己"


def test_current_scene_empty_prompt_with_quoted():
    scene = _build_scene_from_current_message(
        prompt="", image_urls=[],
        sender_name="扎师傅", user_id="123456",
        quoted_text="你好", quoted_sender_name="小明", quoted_user_id="789",
    )
    assert len(scene.speakers) == 2
    # When prompt is empty, should still render the current speaker with placeholder
    assert scene.speakers[1]["text"] == "[图片消息]"


def test_current_scene_image_only_quoted():
    scene = _build_scene_from_current_message(
        prompt="这是什么", image_urls=[],
        sender_name="扎师傅", user_id="123456",
        quoted_image_urls=["a.png", "b.png"],
    )
    assert "[引用]" in scene.speakers[0]["text"]
    assert "2 张" in scene.speakers[0]["text"]
    assert "a.png" in scene.images


def test_current_scene_collects_all_images():
    scene = _build_scene_from_current_message(
        prompt="看看", image_urls=["current.png"],
        sender_name="扎师傅", user_id="123456",
        quoted_image_urls=["quoted.png"],
        forward_image_urls=["forward.png"],
    )
    assert "current.png" in scene.images
    assert "quoted.png" in scene.images
    assert "forward.png" in scene.images


# ---------------------------------------------------------------------------
# Scene rendering
# ---------------------------------------------------------------------------

def test_render_current_scene():
    scene = LLMSceneMessage(
        speakers=[{"user_id": "123", "sender_name": "扎师傅", "canonical_name": "扎师傅", "text": "你好"}],
        images=[], scene_type="current",
    )
    text = _render_scene_to_text(scene)
    assert SCENE_MARKER_CURRENT in text
    assert "扎师傅" in text
    assert "你好" in text


def test_render_history_scene():
    scene = LLMSceneMessage(
        speakers=[{"user_id": "456", "sender_name": "小明", "canonical_name": "", "text": "哈哈"}],
        images=[], scene_type="history",
    )
    text = _render_scene_to_text(scene)
    assert SCENE_MARKER_CONTEXT in text
    assert SCENE_MARKER_CURRENT not in text


# ---------------------------------------------------------------------------
# build_messages (new scene-based)
# ---------------------------------------------------------------------------

def test_build_messages_empty():
    msgs = build_messages(
        prompt="你好", image_urls=[],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert SCENE_MARKER_CURRENT in msgs[0].content


def test_build_messages_with_history():
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "hi", "raw_content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    msgs = build_messages(
        prompt="你好", image_urls=[],
        history=history, recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="B", current_user_id="2",
    )
    assert len(msgs) == 3
    assert msgs[0].role == "user"
    assert SCENE_MARKER_CONTEXT in msgs[0].content
    assert msgs[1].role == "assistant"
    assert msgs[1].content == "hello"
    assert msgs[2].role == "user"
    assert SCENE_MARKER_CURRENT in msgs[2].content


def test_build_messages_user_assistant_alternation():
    """The final messages array must alternate user/assistant for provider compatibility."""
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A", "content": "a", "raw_content": "a"},
        {"role": "assistant", "content": "reply_a"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "b", "raw_content": "b"},
    ]
    msgs = build_messages(
        prompt="c", image_urls=[],
        history=history, recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="C", current_user_id="3",
    )
    roles = [m.role for m in msgs]
    # History scene → assistant → pending merged with current = user/assistant/user
    assert roles == ["user", "assistant", "user"]


def test_build_messages_with_recent_buffer():
    recent = [
        {"user_id": "1", "sender_name": "A", "text": "recent1"},
        {"user_id": "2", "sender_name": "B", "text": "recent2"},
    ]
    msgs = build_messages(
        prompt="当前", image_urls=[],
        history=[], recent_messages=recent,
        max_trigger_context_messages=3,
        current_sender_name="C", current_user_id="3",
    )
    # Pending context merged with current into a single user message
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "recent1" in msgs[0].content
    assert "recent2" in msgs[0].content
    assert SCENE_MARKER_CONTEXT in msgs[0].content
    assert SCENE_MARKER_CURRENT in msgs[0].content


def test_build_messages_with_quoted_in_current():
    msgs = build_messages(
        prompt="他说什么", image_urls=[],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
        quoted_text="你好", quoted_sender_name="B", quoted_user_id="2",
    )
    assert "[引用]" in msgs[-1].content


def test_build_messages_forward_in_current():
    msgs = build_messages(
        prompt="怎么看", image_urls=[],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
        forward_text="转发内容",
    )
    assert "[转发]" in msgs[-1].content


def test_build_messages_images_attached():
    msgs = build_messages(
        prompt="看图", image_urls=["img.png"],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
    )
    assert "img.png" in msgs[-1].image_urls


# ---------------------------------------------------------------------------
# Deprecated functions (backward-compat, remove in cleanup phase)
# ---------------------------------------------------------------------------

def test_build_user_message_content_quoted():
    content = build_user_message_content(
        prompt="这是什么？",
        quoted_text="原来的消息",
        quoted_sender_name="镜子",
        quoted_user_id="2002",
        quoted_image_urls=["https://example.test/q.png"],
        max_quoted_message_chars=1200,
    )
    assert "以下是当前用户显式引用的消息" in content
    assert "引用附图：1 张" in content


def test_build_user_message_content_forward():
    content = build_user_message_content(
        prompt="你怎么看？",
        forward_text="1. Alice（QQ 10001）：你好",
        forward_image_urls=["https://example.test/fwd.png"],
        max_quoted_message_chars=1200,
    )
    assert "以下是用户转发的合并消息" in content
    assert "转发附图：1 张" in content


def test_build_user_message_content_self_quote():
    content = build_user_message_content(
        prompt="你怎么看？",
        quoted_text="旧消息",
        quoted_sender_name="4s",
        quoted_user_id="4004",
        quoted_is_bot_self=True,
        max_quoted_message_chars=1200,
    )
    assert "机器人自己" in content
    assert "角色关系：当前提问者就是现在发消息的人" in content


def test_build_user_message_content_plain():
    content = build_user_message_content(prompt="只有正文", max_quoted_message_chars=1200)
    assert "以下是当前用户显式引用的消息" not in content
    assert "只有正文" in content


def test_system_prompt_disambiguates_quote_roles():
    persona = SimpleNamespace(system_prompt="你是测试人格。", style_prompt="", extras={})
    vocab = SimpleNamespace(find_matches=lambda prompt: [], find_glossary=lambda prompt: [])
    prompt = build_system_prompt(
        persona=persona,
        group_id=1001,
        user_id=2002,
        sender_name="A",
        prompt="B说了什么？",
        memories=[],
        tool_specs=[],
        identities=None,
        vocab=vocab,
        beijing_timezone="Asia/Shanghai",
        search_tool_name="search_web",
    )
    assert "当前提问者永远是本条消息的发送者" in prompt
    assert "引用发送者只是被引用对象" in prompt
