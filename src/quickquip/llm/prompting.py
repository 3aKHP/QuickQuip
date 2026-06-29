from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.llm.tools import (
    LLMConversationMessage,
    LLMSceneMessage,
    LLMToolSpec,
    SCENE_MARKER_CONTEXT,
    SCENE_MARKER_CURRENT,
)

# Upper bound on how many images from the recent-message buffer are attached
# to a passive/boredom trigger. Keeps multimodal token cost bounded regardless
# of how image-heavy the recent window is.
MAX_RECENT_CONTEXT_IMAGES = 5


def format_participant_label(
    *,
    user_id: str,
    sender_name: str = "",
    canonical_name: str = "",
    include_unregistered_note: bool = True,
) -> str:
    normalized_user_id = user_id.strip()
    normalized_sender_name = sender_name.strip()
    normalized_canonical_name = canonical_name.strip()
    if normalized_canonical_name and normalized_sender_name and normalized_canonical_name != normalized_sender_name:
        return f"{normalized_canonical_name}（QQ {normalized_user_id}，当前显示名：{normalized_sender_name}）"
    if normalized_canonical_name:
        return f"{normalized_canonical_name}（QQ {normalized_user_id}）"
    if normalized_sender_name and normalized_user_id and normalized_sender_name != normalized_user_id:
        if include_unregistered_note:
            return f"{normalized_sender_name}（QQ {normalized_user_id}，未登记）"
        return f"{normalized_sender_name}（QQ {normalized_user_id}）"
    if normalized_sender_name:
        return normalized_sender_name
    if normalized_user_id:
        if include_unregistered_note:
            return f"QQ {normalized_user_id}（未登记）"
        return f"QQ {normalized_user_id}"
    return "未知用户"


def _compile_structured_persona(extras: dict[str, object]) -> str:
    """Compile structured persona fields into prompt text.

    Structured fields (TOML tables like [identity], [cognition], etc.) are
    stored in ``PersonaConfig.extras`` as dicts.  This function renders them
    into natural-language sections that precede the free-text system_prompt.
    """
    sections: list[str] = []

    identity = extras.get("identity")
    if isinstance(identity, dict):
        sections.append(_render_persona_section(identity, {
            "archetype": "角色原型",
            "scenario": "当前情境",
            "self_reference": "自称方式",
        }))

    biography = extras.get("biography")
    if isinstance(biography, dict):
        parts: list[str] = []
        origin = biography.get("origin")
        if origin:
            parts.append(f"身世背景：{origin}")
        marks = biography.get("defining_marks")
        if marks:
            if isinstance(marks, list):
                parts.append("关键印记：\n" + "\n".join(f"- {m}" for m in marks))
            else:
                parts.append(f"关键印记：{marks}")
        if parts:
            sections.append("\n".join(parts))

    cognition = extras.get("cognition")
    if isinstance(cognition, dict):
        sections.append(_render_persona_section(cognition, {
            "decision_logic": "决策逻辑",
            "emotional_processing": "情绪处理",
            "perception_filter": "感知滤镜",
            "attention_bias": "注意力偏向",
        }))

    instinct = extras.get("instinct")
    if isinstance(instinct, dict):
        sections.append(_render_persona_section(instinct, {
            "core_desire": "核心渴望",
            "stress_response": "压力反应",
            "comfort_zone": "舒适区",
        }))

    voice = extras.get("voice")
    if isinstance(voice, dict):
        parts = []
        syntax_rhythm = voice.get("syntax_rhythm")
        if syntax_rhythm:
            parts.append(f"句法节奏：{syntax_rhythm}")
        tone_shift = voice.get("tone_shift")
        if tone_shift:
            parts.append(f"语气变化：{tone_shift}")
        if voice.get("verbal_habits"):
            habits = voice["verbal_habits"]
            if isinstance(habits, list):
                parts.append(f"口头习惯：{'、'.join(str(h) for h in habits)}")
            else:
                parts.append(f"口头习惯：{habits}")
        if voice.get("verbal_constraints"):
            constraints = voice["verbal_constraints"]
            if isinstance(constraints, list):
                parts.append("语言约束：\n" + "\n".join(f"- {c}" for c in constraints))
            else:
                parts.append(f"语言约束：{constraints}")
        if parts:
            sections.append("\n".join(parts))

    boundaries = extras.get("boundaries")
    if isinstance(boundaries, dict):
        parts = []
        if boundaries.get("do"):
            do_list = boundaries["do"]
            if isinstance(do_list, list):
                parts.append("允许：\n" + "\n".join(f"- {item}" for item in do_list))
        if boundaries.get("do_not"):
            dont_list = boundaries["do_not"]
            if isinstance(dont_list, list):
                parts.append("禁止：\n" + "\n".join(f"- {item}" for item in dont_list))
        if parts:
            sections.append("\n".join(parts))

    world = extras.get("world")
    if isinstance(world, dict):
        parts = []
        if world.get("relationships"):
            rels = world["relationships"]
            if isinstance(rels, list):
                parts.append("关键关系：\n" + "\n".join(f"- {r}" for r in rels))
            elif isinstance(rels, str):
                parts.append(f"关键关系：{rels}")
        context = world.get("context")
        if context:
            parts.append(f"世界观背景：{context}")
        if parts:
            sections.append("\n".join(parts))

    return "\n\n".join(section for section in sections if section)


def _render_persona_section(table: dict[str, object], field_labels: dict[str, str]) -> str:
    """Render a persona TOML table's simple scalar fields into a section.

    Each ``{toml_key: chinese_label}`` entry whose value is truthy becomes
    ``label：str(value)``, mirroring the original per-field ``if X.get(...)``
    truthiness guard. Non-string truthy values (e.g. integers) are stringified
    just as the original f-string did. Returns empty string if no fields
    were present.
    """
    parts: list[str] = []
    for key, label in field_labels.items():
        value = table.get(key)
        if value:
            parts.append(f"{label}：{value}")
    return "\n".join(parts)


def build_system_prompt(
    *,
    persona,
    group_id: int | str,
    user_id: int | str,
    sender_name: str,
    prompt: str,
    memories: list[dict[str, object]],
    tool_specs: list[LLMToolSpec],
    identities,
    vocab,
    beijing_timezone: str,
    search_tool_name: str,
    auto_search_enabled: bool = False,
    tool_discovery_enabled: bool = False,
    tool_search_name: str = "tool_search",
    tool_list_name: str = "tool_list",
    deferred_tool_categories: list[str] | None = None,
    chat_type: str = "group",
    participants: list[dict[str, str]] | None = None,
    provider_style_overrides: str = "",
    session_preset: str = "",
) -> str:
    now_cst = datetime.now(ZoneInfo(beijing_timezone))
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

    lines: list[str] = []

    # Structured persona fields (compiled from TOML tables in extras)
    structured = _compile_structured_persona(getattr(persona, "extras", {}))
    if structured:
        lines.append(structured)

    # Free-text persona prompts (can coexist with structured fields)
    if persona.system_prompt.strip():
        lines.append(persona.system_prompt.strip())
    if persona.style_prompt.strip():
        lines.append(persona.style_prompt.strip())
    if provider_style_overrides.strip():
        lines.append(provider_style_overrides.strip())

    lines.append("认人规则：")
    lines.append("- 不同 QQ 号默认视为不同的人，不要把两个人合并成同一发言者。")
    lines.append("- 优先按 QQ 号识别身份，其次再参考当前显示名、标准身份和别名。")
    lines.append('- 当上下文里已经标出“标准身份（QQ …）”时，后续继续沿用，不要自行改口或张冠李戴。')
    lines.append("- 只输出给用户看的最终回答，禁止输出任何内部推理、思维链、草稿、隐藏分析或 <think>/<thinking>/<reasoning> 之类标签。")
    lines.append("引用判定：")
    lines.append("- 当前提问者永远是本条消息的发送者；引用发送者只是被引用对象，不是当前说话者。")
    lines.append("- 当 A 引用 B 的消息向你提问时，始终把 A 视为当前提问者，把 B 视为引用来源，不要把 B 当成当前发言者。")
    lines.append("- 即使引用来源是机器人自己，也要把当前提问者和引用来源分开理解。")

    lines.append("消息格式说明：")
    lines.append("- 所有消息均标注了发言者身份，格式为：身份（QQ 号）或 身份（QQ 号，当前显示名）")
    lines.append(f"- 以「{SCENE_MARKER_CURRENT}」标记的是当前需要回复的消息")
    lines.append(f"- 以「{SCENE_MARKER_CONTEXT}」标记的是上文对话历史")

    lines.append("当前元数据：")
    lines.append(f"- 当前北京时间：{now_cst:%Y-%m-%d %H:%M}")
    lines.append(f"- 当前星期：{weekday_names[now_cst.weekday()]}")
    from quickquip.chat.festival import get_festival_persona_appendix
    festival_appendix = get_festival_persona_appendix()
    if festival_appendix:
        lines.append("节日提示：")
        lines.append(f"- {festival_appendix}")
    if chat_type == "private":
        lines.append("- 当前会话类型：私聊")
        lines.append(f"- 当前私聊对象 QQ：{group_id}")
    else:
        lines.append("- 当前会话类型：群聊")
        lines.append(f"- 当前群号：{group_id}")
    if chat_type == "private":
        lines.append("当前处于一对一私聊场景，可以比群聊更自然、细致，但不要失去当前人格的底色。")
    if session_preset.strip():
        lines.append("本次会话的附加设定：")
        lines.append(session_preset.strip())
    if participants:
        participant_lines = ["当前对话参与成员："]
        for item in participants[:8]:
            name = item.get("canonical_name") or item.get("sender_name") or f"QQ {item.get('user_id')}"
            participant_lines.append(f"- {name}")
        lines.append("\n".join(participant_lines))

    if memories:
        if chat_type == "private":
            lines.append("以下是与当前私聊相关的持久记忆，仅在确实相关时参考：")
        else:
            lines.append("以下是与当前群聊相关的持久记忆，仅在确实相关时参考：")
        for index, memory in enumerate(memories, 1):
            lines.append(f"{index}. {memory['content']}")

    vocab_lines: list[str] = []
    vocab_matches = vocab.find_matches(prompt)
    if vocab_matches:
        vocab_lines.append("以下词表命中仅用于帮助你做称呼消歧，不要机械复读：")
        for item in vocab_matches:
            line = f"- {item.alias} 通常指 {item.name}"
            if item.note:
                line += f"；注意：{item.note}"
            vocab_lines.append(line)

    glossary_matches = vocab.find_glossary(prompt)
    if glossary_matches:
        vocab_lines.append("以下黑话解释仅在当前话题相关时参考：")
        for term, meaning in glossary_matches:
            vocab_lines.append(f"- {term}：{meaning}")

    if vocab_lines:
        lines.append("\n".join(vocab_lines))

    if tool_specs:
        tool_lines = [
            "工具使用规则：",
            "- 只有在确实需要外部信息、身份查询或记忆查询时才调用工具。",
            "- 优先直接回答，不要为了显得聪明而滥用工具。",
        ]
        if tool_discovery_enabled:
            tool_lines.extend([
                f"- 当前只展示常驻工具；需要未展示的外部能力、MCP 能力或专门查询能力时，先调用 {tool_search_name}。",
                f"- {tool_search_name} 会按能力描述返回并加载少量相关工具，之后再调用对应工具名。",
                f"- 如果 {tool_search_name} 没找到但你认为工具存在，用 {tool_list_name} 查看工具组、名称或摘要；确认工具名后用 {tool_list_name} 的 load 模式加载。",
            ])
            categories = [item for item in deferred_tool_categories or [] if item.strip()]
            if categories:
                tool_lines.append(f"- 可搜索工具类别：{'、'.join(categories[:12])}")
        if auto_search_enabled:
            tool_lines.extend([
                "- 当前联网后端：SearXNG。",
                f"- 遇到需要最新事实、网页、新闻、价格、版本、公告或来源链接的问题时，请主动调用 {search_tool_name}。",
                f"- 当前 {search_tool_name} 走项目内 SearXNG；搜索结果不够时，可以继续多次调用 {search_tool_name} 细化检索。",
                "- 优先先搜再答，再根据搜索结果组织结论。",
            ])
        tool_lines.append("- 工具结果不足时，明确告诉用户不足，不要编造。")
        tool_lines.append("当前可用工具：")
        for spec in tool_specs:
            tool_lines.append(f"- {spec.name}：{spec.description}")
        lines.append("\n".join(tool_lines))

    return "\n\n".join(line for line in lines if line)


def _resolve_canonical_name(identities, user_id: str, sender_name: str, stored_canonical: str) -> str:
    if identities is None or not user_id.strip():
        return stored_canonical
    match = identities.resolve_user(user_id, sender_name)
    if match.is_registered:
        return match.canonical_name or stored_canonical
    return stored_canonical


# ---------------------------------------------------------------------------
# Scene-based message assembly (new pipeline)
# ---------------------------------------------------------------------------

def _build_scenes_from_history(
    history: list[dict[str, str]],
    *,
    identities=None,
) -> list[LLMSceneMessage]:
    """Group consecutive human messages between bot replies into scenes.

    Each stretch of consecutive user messages becomes one scene.
    An assistant message flushes the pending scene and acts as a boundary.
    """
    scenes: list[LLMSceneMessage] = []
    pending_speakers: list[dict[str, str]] = []
    pending_images: list[str] = []

    for item in history:
        if item["role"] not in {"user", "assistant"} or not item.get("content", "").strip():
            continue

        if item["role"] == "assistant":
            if pending_speakers:
                scenes.append(LLMSceneMessage(
                    speakers=pending_speakers,
                    images=pending_images,
                    scene_type="history",
                ))
                pending_speakers = []
                pending_images = []
        else:
            user_id = item.get("user_id", "")
            sender_name = item.get("sender_name", "")
            raw_text = item.get("raw_content") or item.get("content", "")
            canonical_name = _resolve_canonical_name(
                identities, user_id, sender_name, item.get("canonical_name", ""),
            )
            pending_speakers.append({
                "user_id": user_id,
                "sender_name": sender_name,
                "canonical_name": canonical_name,
                "text": raw_text,
            })

    if pending_speakers:
        scenes.append(LLMSceneMessage(
            speakers=pending_speakers,
            images=pending_images,
            scene_type="history",
        ))

    return scenes


def _build_scene_from_recent_buffer(
    recent_messages: list[dict[str, str]],
    *,
    max_trigger_context_messages: int,
    identities=None,
) -> LLMSceneMessage | None:
    """Convert the recent-message buffer into a single scene."""
    if not recent_messages:
        return None

    speakers: list[dict[str, str]] = []
    for item in recent_messages[-max_trigger_context_messages:]:
        user_id = item["user_id"]
        sender_name = item.get("sender_name", "")
        canonical_name = _resolve_canonical_name(
            identities, user_id, sender_name, item.get("canonical_name", ""),
        )
        speakers.append({
            "user_id": user_id,
            "sender_name": sender_name,
            "canonical_name": canonical_name,
            "text": item["text"],
        })

    return LLMSceneMessage(
        speakers=speakers,
        images=[],
        scene_type="recent",
    )


def _build_scene_from_current_message(
    *,
    prompt: str,
    image_urls: list[str],
    sender_name: str,
    user_id: str,
    quoted_text: str = "",
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
    quoted_image_urls: list[str] | None = None,
    quoted_is_bot_self: bool = False,
    forward_text: str = "",
    forward_image_urls: list[str] | None = None,
    identities=None,
    image_descriptions: list[object] | None = None,
) -> LLMSceneMessage:
    """Build the current scene from the user's message and its context.

    Quoted and forwarded messages appear as inline speakers within the
    same scene, preserving conversational context without nesting.
    """
    speakers: list[dict[str, str]] = []
    all_images: list[str] = list(image_urls or [])

    # Quoted message appears as an inline contextual speaker
    if quoted_text.strip() or (quoted_image_urls or []):
        q_user_id = quoted_user_id.strip()
        q_sender = "机器人自己" if quoted_is_bot_self else quoted_sender_name.strip()
        q_canonical = "机器人自己" if quoted_is_bot_self else _resolve_canonical_name(identities, q_user_id, q_sender, "")
        q_text = quoted_text.strip()
        if q_text:
            suffix = f" [附图 {len(quoted_image_urls)} 张]" if quoted_image_urls else ""
            q_text += suffix
        else:
            q_text = f"[图片 {len(quoted_image_urls or [])} 张]"
        speakers.append({
            "user_id": q_user_id,
            "sender_name": q_sender,
            "canonical_name": q_canonical,
            "text": f"[引用] {q_text}",
        })
        if quoted_image_urls:
            all_images.extend(quoted_image_urls)

    # Forwarded content as inline contextual speaker
    if forward_text.strip() or (forward_image_urls or []):
        fw_text = forward_text.strip() or "[合并转发消息]"
        if forward_image_urls:
            fw_text += f" [附图 {len(forward_image_urls)} 张]"
        speakers.append({
            "user_id": "",
            "sender_name": "转发",
            "canonical_name": "转发消息",
            "text": f"[转发] {fw_text}",
        })
        if forward_image_urls:
            all_images.extend(forward_image_urls)

    # Image pre-processing results as context lines
    if image_descriptions:
        for desc in image_descriptions:
            if hasattr(desc, 'success') and desc.success and hasattr(desc, 'text_description'):
                speakers.append({
                    "user_id": "",
                    "sender_name": "图片解析",
                    "canonical_name": "图片解析",
                    "text": f"{desc.text_description}",
                })

    # Current speaker (always last in the scene so the model knows who to answer)
    current_canonical = _resolve_canonical_name(identities, user_id, sender_name, "")
    speakers.append({
        "user_id": user_id,
        "sender_name": sender_name,
        "canonical_name": current_canonical,
        "text": prompt or "[图片消息]",
    })

    seen: set[str] = set()
    deduped_images: list[str] = []
    for url in all_images:
        if url.strip() and url not in seen:
            seen.add(url)
            deduped_images.append(url)

    return LLMSceneMessage(
        speakers=speakers,
        images=deduped_images,
        scene_type="current",
    )


def _render_scene_to_text(
    scene: LLMSceneMessage,
    *,
    identities=None,
) -> str:
    """Render a scene to the unified speaker format.

    Called once at assembly time, never stored.
    """
    marker = SCENE_MARKER_CURRENT if scene.scene_type == "current" else SCENE_MARKER_CONTEXT
    lines = [marker]
    for speaker in scene.speakers:
        label = format_participant_label(
            user_id=speaker.get("user_id", ""),
            sender_name=speaker.get("sender_name", ""),
            canonical_name=speaker.get("canonical_name", ""),
            include_unregistered_note=True,
        )
        lines.append(f"{label}：{speaker['text']}")
    return "\n".join(lines)


def build_messages(
    *,
    prompt: str,
    image_urls: list[str],
    history: list[dict[str, str]],
    recent_messages: list[dict[str, str]] | None,
    max_trigger_context_messages: int,
    include_recent_images: bool = False,
    max_recent_images: int = MAX_RECENT_CONTEXT_IMAGES,
    chat_type: str = "group",
    identities=None,
    current_sender_name: str = "",
    current_user_id: str = "",
    quoted_text: str = "",
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
    quoted_image_urls: list[str] | None = None,
    quoted_is_bot_self: bool = False,
    forward_text: str = "",
    forward_image_urls: list[str] | None = None,
    image_descriptions: list[object] | None = None,
) -> list[LLMConversationMessage]:
    """Build the final messages array using scene-based grouping.

    History + recent buffer + current message are assembled into scenes,
    each becoming a single role="user" message.  Assistant messages
    from history are interleaved as role="assistant".

    The resulting array maintains user/assistant alternation, which
    satisfies the ordering requirements of all three providers.
    """
    messages: list[LLMConversationMessage] = []

    # Group pending human messages into a scene, flush when we hit an
    # assistant message.
    pending_speakers: list[dict[str, str]] = []
    pending_images: list[str] = []

    def _flush_pending():
        if not pending_speakers:
            return
        scene = LLMSceneMessage(
            speakers=list(pending_speakers),
            images=list(pending_images),
            scene_type="history",
        )
        messages.append(LLMConversationMessage(
            role="user",
            content=_render_scene_to_text(scene, identities=identities),
            image_urls=scene.images,
        ))
        pending_speakers.clear()
        pending_images.clear()

    for item in history:
        if item["role"] not in {"user", "assistant"} or not item.get("content", "").strip():
            continue

        if item["role"] == "assistant":
            _flush_pending()
            messages.append(LLMConversationMessage(
                role="assistant",
                content=item["content"],
            ))
        else:
            user_id = item.get("user_id", "")
            sender_name = item.get("sender_name", "")
            raw_text = item.get("raw_content") or item.get("content", "")
            canonical_name = _resolve_canonical_name(
                identities, user_id, sender_name, item.get("canonical_name", ""),
            )
            pending_speakers.append({
                "user_id": user_id,
                "sender_name": sender_name,
                "canonical_name": canonical_name,
                "text": raw_text,
            })

    # Recent buffer: merge into pending rather than creating a separate scene,
    # so the boundary between recent buffer and history is invisible to the LLM.
    if recent_messages:
        recent_slice = recent_messages[-max_trigger_context_messages:]
        for item in recent_slice:
            user_id = item["user_id"]
            sender_name = item.get("sender_name", "")
            canonical_name = _resolve_canonical_name(
                identities, user_id, sender_name, item.get("canonical_name", ""),
            )
            pending_speakers.append({
                "user_id": user_id,
                "sender_name": sender_name,
                "canonical_name": canonical_name,
                "text": item["text"],
            })
        # Attach recent-buffer images so passive/boredom triggers can "see" what
        # was shared in the group recently.  Newer images win when the budget is
        # exceeded; duplicates across messages are skipped.
        if include_recent_images:
            seen = set(pending_images)
            for item in recent_slice:
                for url in item.get("image_urls", []):
                    url = url.strip()
                    if url and url not in seen:
                        seen.add(url)
                        pending_images.append(url)
            if len(pending_images) > max_recent_images:
                pending_images[:] = pending_images[-max_recent_images:]

    # Build current scene first, then merge any pending context into it.
    # This avoids consecutive role="user" messages and keeps the
    # user/assistant alternation that all three providers require.
    current_scene = _build_scene_from_current_message(
        prompt=prompt,
        image_urls=image_urls,
        sender_name=current_sender_name,
        user_id=current_user_id,
        quoted_text=quoted_text,
        quoted_sender_name=quoted_sender_name,
        quoted_user_id=quoted_user_id,
        quoted_image_urls=quoted_image_urls,
        quoted_is_bot_self=quoted_is_bot_self,
        forward_text=forward_text,
        forward_image_urls=forward_image_urls,
        identities=identities,
        image_descriptions=image_descriptions,
    )

    if pending_speakers:
        # Merge context into the current scene so we emit a single
        # role="user" message with 【上文】/【当前提问】 separating
        # the two parts in text.
        context_text = _render_scene_to_text(
            LLMSceneMessage(
                speakers=list(pending_speakers),
                images=list(pending_images),
                scene_type="history",
            ),
            identities=identities,
        )
        current_text = _render_scene_to_text(current_scene, identities=identities)
        combined_images = merge_image_urls(
            current_scene.images, pending_images,
        )
        messages.append(LLMConversationMessage(
            role="user",
            content=context_text + "\n" + current_text,
            image_urls=combined_images,
        ))
    else:
        messages.append(LLMConversationMessage(
            role="user",
            content=_render_scene_to_text(current_scene, identities=identities),
            image_urls=current_scene.images,
        ))

    return messages


def merge_image_urls(*collections: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for items in collections:
        for item in items:
            url = item.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(url)
    return merged
