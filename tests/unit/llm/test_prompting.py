from __future__ import annotations

from types import SimpleNamespace

from quickquip.llm.image_preprocessor import ImageDescription
from quickquip.llm.prompting import (
    MAX_IMAGE_DESCRIPTION_CHARS,
    _build_scene_from_current_message,
    _build_scene_from_recent_buffer,
    _build_scenes_from_history,
    _compile_structured_persona,
    _render_scene_to_text,
    build_messages,
    build_system_prompt,
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


def test_scenes_from_history_keeps_placeholder_only_user_rows():
    """content 为空、raw_content 为占位符（纯图片/引用落库形态）的 user 行是有效轮次。"""
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A",
         "content": "", "raw_content": "[图片 1 张]"},
        {"role": "assistant", "content": "哦哦 sora 发图了"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "b", "raw_content": "b"},
    ]
    scenes = _build_scenes_from_history(history)
    assert len(scenes) == 2
    assert scenes[0].speakers[0]["text"] == "[图片 1 张]"
    assert scenes[1].speakers[0]["text"] == "b"


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


def _assert_user_assistant_alternation(messages):
    """严格交替断言：相邻消息角色必须不同（三家 provider 的顺序要求）。"""
    roles = [m.role for m in messages]
    assert roles, "messages should not be empty"
    for prev, cur in zip(roles, roles[1:]):
        assert prev != cur, f"roles must strictly alternate, got {roles}"


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
    _assert_user_assistant_alternation(msgs)


def test_build_messages_keeps_placeholder_only_user_rows():
    """纯图片/引用消息落库为空 content + 占位符 raw_content，过滤后不得丢失该 user 轮。"""
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A",
         "content": "", "raw_content": "[图片 1 张]"},
        {"role": "assistant", "content": "哦哦 sora 发图了"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "b", "raw_content": "b"},
        {"role": "assistant", "content": "reply_b"},
    ]
    msgs = build_messages(
        prompt="c", image_urls=[],
        history=history, recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="C", current_user_id="3",
    )
    roles = [m.role for m in msgs]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    _assert_user_assistant_alternation(msgs)
    # 占位符行回到上下文：既带占位符文本，也带发送者身份标注
    assert SCENE_MARKER_CONTEXT in msgs[0].content
    assert "[图片 1 张]" in msgs[0].content
    assert "QQ 1" in msgs[0].content


def test_build_messages_blank_placeholder_row_still_dropped():
    """raw_content 为纯空白时整行仍视为空，占位符缺失时回退 content。"""
    history = [
        {"role": "user", "user_id": "1", "sender_name": "A",
         "content": "", "raw_content": "   "},
        {"role": "assistant", "content": "reply_a"},
        {"role": "user", "user_id": "2", "sender_name": "B", "content": "legacy"},
        {"role": "assistant", "content": "reply_b"},
    ]
    msgs = build_messages(
        prompt="c", image_urls=[],
        history=history, recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="C", current_user_id="3",
    )
    _assert_user_assistant_alternation(msgs)
    # 空白占位符行被丢弃（首个 assistant 前无 user 轮）；缺 raw_content 键回退 content
    assert msgs[0].role == "assistant"
    assert msgs[0].content == "reply_a"
    assert "legacy" in msgs[1].content


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


def test_build_messages_labels_image_descriptions_by_source():
    msgs = build_messages(
        prompt="第二张是什么", image_urls=[],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
        image_descriptions=[
            ImageDescription(
                source_url="quoted.png",
                text_description="一张聊天截图",
                success=True,
                context_label="引用消息图片 1",
            ),
            ImageDescription(
                source_url="forward.png",
                text_description="一张风景照",
                success=True,
                context_label="转发消息图片 1",
            ),
        ],
    )

    assert "[引用消息图片 1]\n一张聊天截图" in msgs[-1].content
    assert "[转发消息图片 1]\n一张风景照" in msgs[-1].content


def test_build_messages_truncates_large_image_descriptions():
    msgs = build_messages(
        prompt="看图", image_urls=[],
        history=[], recent_messages=None,
        max_trigger_context_messages=5,
        current_sender_name="A", current_user_id="1",
        image_descriptions=[
            ImageDescription(
                source_url="large.png",
                text_description="x" * (MAX_IMAGE_DESCRIPTION_CHARS + 100),
                success=True,
                context_label="当前消息图片 1",
            ),
        ],
    )

    assert "x" * (MAX_IMAGE_DESCRIPTION_CHARS + 1) not in msgs[-1].content
    assert "[转述内容已截断]" in msgs[-1].content


def test_build_messages_recent_images_off_by_default():
    # Explicit triggers must NOT see recent-buffer images.
    recent = [
        {"user_id": "1", "sender_name": "A", "text": "看图", "image_urls": ["r1.png"]},
    ]
    msgs = build_messages(
        prompt="继续", image_urls=[],
        history=[], recent_messages=recent,
        max_trigger_context_messages=5,
        current_sender_name="B", current_user_id="2",
    )
    assert msgs[-1].image_urls == []


def test_build_messages_recent_images_attached_when_enabled():
    recent = [
        {"user_id": "1", "sender_name": "A", "text": "看图", "image_urls": ["r1.png", "r2.png"]},
    ]
    msgs = build_messages(
        prompt="继续", image_urls=[],
        history=[], recent_messages=recent,
        max_trigger_context_messages=5,
        include_recent_images=True,
        current_sender_name="B", current_user_id="2",
    )
    assert "r1.png" in msgs[-1].image_urls
    assert "r2.png" in msgs[-1].image_urls


def test_build_messages_recent_images_budget_keeps_newest():
    # 8 recent images, budget 5 → only the 5 newest survive, in order.
    recent = [
        {"user_id": str(i), "sender_name": f"u{i}", "text": f"m{i}", "image_urls": [f"img{i}.png"]}
        for i in range(8)
    ]
    msgs = build_messages(
        prompt="继续", image_urls=[],
        history=[], recent_messages=recent,
        max_trigger_context_messages=10,
        include_recent_images=True,
        max_recent_images=5,
        current_sender_name="B", current_user_id="2",
    )
    # Newest-first: img7 (newest) .. img3, so the provider cap keeps the
    # newest recent images, not the oldest.
    assert msgs[-1].image_urls == ["img7.png", "img6.png", "img5.png", "img4.png", "img3.png"]


def test_build_messages_recent_images_dedup_across_messages():
    recent = [
        {"user_id": "1", "sender_name": "A", "text": "a", "image_urls": ["dup.png", "x.png"]},
        {"user_id": "2", "sender_name": "B", "text": "b", "image_urls": ["dup.png", "y.png"]},
    ]
    msgs = build_messages(
        prompt="继续", image_urls=[],
        history=[], recent_messages=recent,
        max_trigger_context_messages=5,
        include_recent_images=True,
        current_sender_name="C", current_user_id="3",
    )
    urls = msgs[-1].image_urls
    # Newest message's images first (y, then x); dup kept from its first
    # (oldest) sighting, so it lands last.
    assert urls == ["y.png", "x.png", "dup.png"]


def test_build_messages_current_image_precedes_recent():
    # Combined order is current → newest recent → oldest recent, so the
    # provider's per-request cap keeps the current image and the newest history.
    recent = [
        {"user_id": "1", "sender_name": "A", "text": "旧图1", "image_urls": ["r_old.png"]},
        {"user_id": "2", "sender_name": "B", "text": "旧图2", "image_urls": ["r_new.png"]},
    ]
    msgs = build_messages(
        prompt="新的", image_urls=["cur.png"],
        history=[], recent_messages=recent,
        max_trigger_context_messages=5,
        include_recent_images=True,
        current_sender_name="C", current_user_id="3",
    )
    assert msgs[-1].image_urls == ["cur.png", "r_new.png", "r_old.png"]


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


# ---------------------------------------------------------------------------
# _compile_structured_persona — behaviour lock for the 7-section renderer.
# Added alongside the refactor that collapsed repeated per-field scaffolding
# into _render_persona_section; guards the edge cases the refactor touched.
# ---------------------------------------------------------------------------

def test_persona_identity_renders_simple_fields():
    out = _compile_structured_persona({
        "identity": {"archetype": "侦探", "scenario": "雨夜", "self_reference": "本侦探"},
    })
    assert "角色原型：侦探" in out
    assert "当前情境：雨夜" in out
    assert "自称方式：本侦探" in out


def test_persona_identity_skips_missing_renders_truthy():
    # Guard is bare truthiness (matching original per-field `if X.get(...)`);
    # falsy values (None, '', 0, []) are skipped, truthy values rendered.
    out = _compile_structured_persona({
        "identity": {"archetype": None, "scenario": "", "self_reference": "侦探"},
    })
    assert "角色原型" not in out
    assert "当前情境" not in out
    assert "自称方式：侦探" in out

    # Truthy non-string scalars are stringified and rendered, same as original.
    out_int = _compile_structured_persona({"identity": {"archetype": 1}})
    assert "角色原型：1" in out_int

    # Whitespace-only strings are truthy and rendered, same as original.
    out_ws = _compile_structured_persona({"identity": {"scenario": "   "}})
    assert "当前情境：   " in out_ws


def test_persona_boundaries_list_only_str_skipped():
    # boundaries.do/do_not only render as bullet lists; a bare string is
    # intentionally skipped (original list-only behaviour preserved).
    out = _compile_structured_persona({
        "boundaries": {"do": ["保持礼貌"], "do_not": ["剧透结局"]},
    })
    assert "允许：\n- 保持礼貌" in out
    assert "禁止：\n- 剧透结局" in out

    out_str = _compile_structured_persona({"boundaries": {"do": "单条"}})
    assert "允许" not in out_str


def test_persona_world_relationships_str_or_list():
    out_list = _compile_structured_persona({
        "world": {"relationships": ["与A是旧识", "与B对立"]},
    })
    assert "关键关系：\n- 与A是旧识" in out_list

    out_str = _compile_structured_persona({"world": {"relationships": "与A是旧识"}})
    assert "关键关系：与A是旧识" in out_str


def test_persona_voice_habits_join_with_delimiter():
    out = _compile_structured_persona({
        "voice": {"verbal_habits": ["常说嗯", "爱用反问"], "verbal_constraints": ["不爆粗", "不撒谎"]},
    })
    assert "口头习惯：常说嗯、爱用反问" in out
    assert "语言约束：\n- 不爆粗\n- 不撒谎" in out


def test_persona_sections_joined_by_double_newline():
    out = _compile_structured_persona({
        "identity": {"archetype": "侦探"},
        "cognition": {"decision_logic": "证据优先"},
    })
    assert "角色原型：侦探\n\n决策逻辑：证据优先" in out


def test_persona_empty_extras_returns_empty():
    assert _compile_structured_persona({}) == ""
    assert _compile_structured_persona({"identity": {}}) == ""


# ---------------------------------------------------------------------------
# 内置搜索（grounding）与 search_web 的提示词引导互斥
# ---------------------------------------------------------------------------

def _builtin_persona():
    return SimpleNamespace(system_prompt="你是测试人格。", style_prompt="", extras={})


def _builtin_vocab():
    return SimpleNamespace(find_matches=lambda prompt: [], find_glossary=lambda prompt: [])


def _prompt_with_tools() -> list:
    from quickquip.llm.tools import LLMToolSpec

    return [
        LLMToolSpec(
            name="get_identity",
            description="身份查询",
            input_schema={"type": "object", "properties": {}},
        )
    ]


def test_builtin_search_guidance_replaces_searxng_lines():
    prompt = build_system_prompt(
        persona=_builtin_persona(),
        group_id=1001,
        user_id=2002,
        sender_name="A",
        prompt="你好",
        memories=[],
        tool_specs=_prompt_with_tools(),
        identities=None,
        vocab=_builtin_vocab(),
        beijing_timezone="Asia/Shanghai",
        search_tool_name="search_web",
        search_mode="builtin",
    )

    assert "联网检索说明" in prompt
    assert "provider 内置联网搜索" in prompt
    # SearXNG / search_web 引导块必须被压制，避免双路径引导
    assert "当前联网后端：SearXNG。" not in prompt
    assert "走项目内 SearXNG" not in prompt


def test_builtin_search_guidance_present_without_tools():
    """声明独立于 tool_calling_enabled：工具为空时 grounding 引导仍然注入。"""
    prompt = build_system_prompt(
        persona=_builtin_persona(),
        group_id=1001,
        user_id=2002,
        sender_name="A",
        prompt="你好",
        memories=[],
        tool_specs=[],
        identities=None,
        vocab=_builtin_vocab(),
        beijing_timezone="Asia/Shanghai",
        search_tool_name="search_web",
        search_mode="builtin",
    )

    assert "联网检索说明" in prompt
    assert "当前可用工具" not in prompt


def test_builtin_search_inactive_keeps_searxng_guidance():
    prompt = build_system_prompt(
        persona=_builtin_persona(),
        group_id=1001,
        user_id=2002,
        sender_name="A",
        prompt="你好",
        memories=[],
        tool_specs=_prompt_with_tools(),
        identities=None,
        vocab=_builtin_vocab(),
        beijing_timezone="Asia/Shanghai",
        search_tool_name="search_web",
        search_mode="searxng",
    )

    assert "当前联网后端：SearXNG。" in prompt
    assert "联网检索说明" not in prompt
