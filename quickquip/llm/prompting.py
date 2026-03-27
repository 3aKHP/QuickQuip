from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quickquip.llm.tools import LLMConversationMessage, LLMToolSpec


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

    lines.append("当前元数据：")
    lines.append(f"- 当前北京时间：{now_cst:%Y-%m-%d %H:%M}")
    lines.append(f"- 当前星期：{weekday_names[now_cst.weekday()]}")
    lines.append(f"当前群号：{group_id}")
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
    if memories:
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
) -> list[LLMConversationMessage]:
    normalized: list[LLMConversationMessage] = []
    if recent_messages:
        lines = ["以下是本次触发前，当前群里最近的消息，仅供理解上下文："]
        for index, item in enumerate(recent_messages[-max_trigger_context_messages:], 1):
            sender_name = item["sender_name"].strip() or item["user_id"]
            canonical_name = item.get("canonical_name", "").strip()
            user_id = item["user_id"]
            if canonical_name and canonical_name != sender_name:
                speaker = f"{canonical_name}（QQ {user_id}，当前显示名：{sender_name}）"
            elif canonical_name:
                speaker = f"{canonical_name}（QQ {user_id}）"
            else:
                speaker = f"{sender_name}（QQ {user_id}，未登记）"
            lines.append(f"{index}. {speaker}：{item['text']}")
        normalized.append(LLMConversationMessage(role="user", content="\n".join(lines)))

    normalized.extend(
        LLMConversationMessage(role=item["role"], content=item["content"])
        for item in history
        if item["role"] in {"user", "assistant"} and item["content"].strip()
    )
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
    normalized_sender_name = sender_name.strip()
    normalized_user_id = user_id.strip()
    if normalized_sender_name and normalized_user_id and normalized_sender_name != normalized_user_id:
        return f"{normalized_sender_name}（QQ {normalized_user_id}）"
    if normalized_sender_name:
        return normalized_sender_name
    if normalized_user_id:
        return f"QQ {normalized_user_id}"
    return "未知用户"


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
) -> list[LLMConversationMessage]:
    messages = normalize_history(
        history,
        recent_messages=recent_messages,
        max_trigger_context_messages=max_trigger_context_messages,
    )
    messages.append(
        LLMConversationMessage(
            role="user",
            content=prompt,
            image_urls=list(image_urls),
        )
    )
    return messages
