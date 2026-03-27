from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.llm.tools import LLMConversationMessage, LLMToolSpec


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
    get_search_backend_name,
    chat_type: str = "group",
    participants: list[dict[str, str]] | None = None,
    provider_style_overrides: str = "",
) -> str:
    now_cst = datetime.now(ZoneInfo(beijing_timezone))
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    identity = identities.resolve_user(user_id, sender_name)

    lines = [persona.system_prompt.strip()]
    if persona.style_prompt.strip():
        lines.append(persona.style_prompt.strip())
    if provider_style_overrides.strip():
        lines.append(provider_style_overrides.strip())

    lines.append("认人规则：")
    lines.append("- 不同 QQ 号默认视为不同的人，不要把两个人合并成同一发言者。")
    lines.append("- 优先按 QQ 号识别身份，其次再参考当前显示名、标准身份和别名。")
    lines.append("- 当上下文里已经标出“标准身份（QQ …）”时，后续继续沿用，不要自行改口或张冠李戴。")

    lines.append("当前元数据：")
    lines.append(f"- 当前北京时间：{now_cst:%Y-%m-%d %H:%M}")
    lines.append(f"- 当前星期：{weekday_names[now_cst.weekday()]}")
    if chat_type == "private":
        lines.append("- 当前会话类型：私聊")
        lines.append(f"- 当前私聊对象 QQ：{group_id}")
    else:
        lines.append("- 当前会话类型：群聊")
        lines.append(f"- 当前群号：{group_id}")
    lines.append(f"当前提问者昵称：{sender_name}")
    lines.append("当前提问者身份：")
    lines.append(f"- QQ：{identity.user_id}")
    lines.append(f"- 当前显示名：{sender_name}")
    if identity.is_registered:
        lines.append(f"- 标准身份：{identity.canonical_name}")
        if identity.aliases:
            lines.append(f"- 常见别名：{'、'.join(identity.aliases)}")
        if identity.note:
            lines.append(f"- 备注：{identity.note}")
    else:
        lines.append("- 标准身份：未登记")
    if chat_type == "private":
        lines.append("当前处于一对一私聊场景，可以比群聊更自然、细致，但不要失去当前人格的底色。")
    if participants:
        participant_lines = ["当前已知参与者："]
        for item in participants[:8]:
            label = format_participant_label(
                user_id=str(item.get("user_id", "")),
                sender_name=str(item.get("sender_name", "")),
                canonical_name=str(item.get("canonical_name", "")),
                include_unregistered_note=True,
            )
            participant_lines.append(f"- {label}")
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
        search_backend = get_search_backend_name()
        backend_label = "SearXNG" if search_backend == "searxng" else "Tavily"
        tool_lines = [
            "工具使用规则：",
            "- 只有在确实需要外部信息、身份查询或记忆查询时才调用工具。",
            "- 优先直接回答，不要为了显得聪明而滥用工具。",
            f"- 当前联网后端：{backend_label}。",
            f"- 遇到需要最新事实、网页、新闻、价格、版本、公告或来源链接的问题时，优先调用 {search_tool_name}。",
            "- 工具结果不足时，明确告诉用户不足，不要编造。",
        ]
        if search_backend == "searxng":
            tool_lines.extend([
                f"- 当前 {search_tool_name} 走项目内 SearXNG；搜索结果不够时，可以继续多次调用 {search_tool_name} 细化检索。",
                "- 优先先搜再答，再根据搜索结果组织结论。",
            ])
        tool_lines.append("当前可用工具：")
        for spec in tool_specs:
            tool_lines.append(f"- {spec.name}：{spec.description}")
        lines.append("\n".join(tool_lines))

    return "\n\n".join(line for line in lines if line)


def normalize_history(
    history: list[dict[str, str]],
    *,
    recent_messages: list[dict[str, str]] | None = None,
    max_trigger_context_messages: int,
    chat_type: str = "group",
) -> list[LLMConversationMessage]:
    normalized: list[LLMConversationMessage] = []
    if recent_messages:
        if chat_type == "private":
            lines = ["以下是本次触发前，当前私聊里最近的消息，仅供理解上下文："]
        else:
            lines = ["以下是本次触发前，当前群里最近的消息，仅供理解上下文："]
        for index, item in enumerate(recent_messages[-max_trigger_context_messages:], 1):
            speaker = format_participant_label(
                user_id=item["user_id"],
                sender_name=item.get("sender_name", ""),
                canonical_name=item.get("canonical_name", ""),
                include_unregistered_note=True,
            )
            lines.append(f"{index}. {speaker}：{item['text']}")
        normalized.append(LLMConversationMessage(role="user", content="\n".join(lines)))

    for item in history:
        if item["role"] not in {"user", "assistant"} or not item["content"].strip():
            continue
        if item["role"] == "assistant":
            normalized.append(LLMConversationMessage(role="assistant", content=item["content"]))
            continue
        if item.get("user_id"):
            speaker = format_participant_label(
                user_id=item.get("user_id", ""),
                sender_name=item.get("sender_name", ""),
                canonical_name=item.get("canonical_name", ""),
                include_unregistered_note=True,
            )
            normalized.append(
                LLMConversationMessage(
                    role="user",
                    content=f"历史会话消息\n- 发言者：{speaker}\n- 内容：{item['content']}",
                )
            )
            continue
        normalized.append(LLMConversationMessage(role="user", content=item["content"]))
    return normalized


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


def format_quoted_speaker(sender_name: str, user_id: str) -> str:
    return format_participant_label(
        user_id=user_id,
        sender_name=sender_name,
        canonical_name="",
        include_unregistered_note=False,
    )


def build_user_message_content(
    *,
    prompt: str,
    quoted_text: str = "",
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
    quoted_image_urls: list[str] | None = None,
    max_quoted_message_chars: int,
) -> str:
    normalized_prompt = prompt.strip()
    normalized_quoted_text = quoted_text.strip()[:max_quoted_message_chars]
    normalized_quoted_images = [url.strip() for url in (quoted_image_urls or []) if url.strip()]
    if not normalized_quoted_text and not normalized_quoted_images:
        return normalized_prompt

    lines = ["以下是当前用户显式引用的消息，请结合它理解本轮提问："]
    lines.append(f"- 引用发送者：{format_quoted_speaker(quoted_sender_name, quoted_user_id)}")
    if normalized_quoted_text:
        lines.append(f"- 引用内容：{normalized_quoted_text}")
    if normalized_quoted_images:
        lines.append(f"- 引用附图：{len(normalized_quoted_images)} 张")
    if normalized_prompt:
        lines.append("当前用户消息：")
        lines.append(normalized_prompt)
    else:
        lines.append("当前用户没有额外文字，请优先围绕引用消息作答。")
    return "\n".join(lines)


def build_messages(
    *,
    prompt: str,
    image_urls: list[str],
    history: list[dict[str, str]],
    recent_messages: list[dict[str, str]] | None,
    max_trigger_context_messages: int,
    chat_type: str = "group",
) -> list[LLMConversationMessage]:
    messages = normalize_history(
        history,
        recent_messages=recent_messages,
        max_trigger_context_messages=max_trigger_context_messages,
        chat_type=chat_type,
    )
    messages.append(
        LLMConversationMessage(
            role="user",
            content=prompt,
            image_urls=list(image_urls),
        )
    )
    return messages
