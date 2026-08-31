from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable
from urllib.parse import urlsplit

from quickquip.llm.identity import IdentityIndex
from quickquip.llm.message_segments import message_has_segments, normalize_bot_self_ids, render_segment_leaf
from quickquip.llm.provider.base import LLMWebSearchReport


@dataclass(slots=True)
class RenderedMessage:
    text: str
    image_urls: list[str] = field(default_factory=list)
    mentioned_bot: bool = False


@dataclass(slots=True)
class RenderedReply:
    text: str
    image_urls: list[str] = field(default_factory=list)
    mentioned_bot: bool = False
    is_bot_self: bool = False
    sender_name: str = ""
    user_id: str = ""
    message_id: str = ""


def _get_sender_name(sender) -> str:
    if sender is None:
        return ""
    card = str(getattr(sender, "card", "") or "").strip()
    if card:
        return card
    nickname = str(getattr(sender, "nickname", "") or "").strip()
    if nickname:
        return nickname
    return ""


def _source_domain(url: str) -> str:
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return ""
    return (host or "").strip().lower()


# Gemini grounding 返回的 uri 是 vertexaisearch.cloud.google.com 重定向链，
# 其 host 不指向真实站点（grounding chunk 的 title 才是站点名/域名），
# 展示时该 host 视为无信息量。
_REDIRECT_HOST_SUFFIX = "vertexaisearch.cloud.google.com"


def append_web_search_source_block(
    text: str,
    report: LLMWebSearchReport,
    *,
    max_sources: int = 3,
) -> str:
    """在聊天回复末尾追加 grounding 来源块。

    展示条目用「标题 — 域名」形式；provider 侧的重定向长链不直接贴出，
    正文已出现的来源不重复列出。
    """
    entries: list[str] = []
    seen_urls: set[str] = set()
    for source in report.sources:
        if len(entries) >= max_sources:
            break
        if not source.url or source.url in seen_urls or source.url in text:
            continue
        title = source.title.strip()
        domain = _source_domain(source.url)
        if domain.endswith(_REDIRECT_HOST_SUFFIX):
            domain = ""
        if title and domain and title != domain:
            entry = f"- {title} — {domain}"
        elif title or domain:
            entry = f"- {title or domain}"
        else:
            continue
        seen_urls.add(source.url)
        entries.append(entry)
    if not entries:
        return text
    return text + "\n\n来源：\n" + "\n".join(entries)


def render_message_for_llm(
    message,
    *,
    bot_self_id: int | str | None = None,
    bot_self_ids: Iterable[int | str] | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> RenderedMessage:
    if isinstance(message, str):
        return RenderedMessage(text=message.strip())

    segments = list(message)
    if not segments or not any(
        hasattr(segment, "type") or isinstance(segment, dict)
        for segment in segments
    ):
        return RenderedMessage(text=str(message).strip())

    plain_parts: list[str] = []
    image_urls: list[str] = []
    mentioned_bot = False
    bot_keys = normalize_bot_self_ids(bot_self_id=bot_self_id, bot_self_ids=bot_self_ids)
    identities = identity_index or IdentityIndex()

    for segment in segments:
        text, segment_images, was_bot = render_segment_leaf(
            segment,
            bot_self_ids=bot_keys,
            identity_index=identities,
            include_image_placeholder=include_image_placeholder,
        )
        if text:
            plain_parts.append(text)
        if segment_images:
            image_urls.extend(segment_images)
        mentioned_bot = mentioned_bot or was_bot

    return RenderedMessage(
        text="".join(plain_parts).strip(),
        image_urls=image_urls,
        mentioned_bot=mentioned_bot,
    )


def render_reply_for_llm(
    reply,
    *,
    bot_self_id: int | str | None = None,
    bot_self_ids: Iterable[int | str] | None = None,
    identity_index: IdentityIndex | None = None,
    include_image_placeholder: bool = False,
) -> RenderedReply | None:
    if reply is None:
        return None

    reply_message = getattr(reply, "message", None)
    raw_reply_message = getattr(reply, "raw_message", None)
    if not message_has_segments(reply_message) and message_has_segments(raw_reply_message):
        reply_message = raw_reply_message
    elif reply_message is None:
        reply_message = raw_reply_message
    rendered = render_message_for_llm(
        reply_message,
        bot_self_id=bot_self_id,
        bot_self_ids=bot_self_ids,
        identity_index=identity_index,
        include_image_placeholder=include_image_placeholder,
    )
    user_id = str(getattr(reply, "user_id", "") or "").strip()
    sender_name = _get_sender_name(getattr(reply, "sender", None))
    if not sender_name:
        sender_name = str(getattr(reply, "nickname", "") or "").strip()
    if not sender_name:
        sender_name = user_id
    is_bot_self = user_id in normalize_bot_self_ids(bot_self_id=bot_self_id, bot_self_ids=bot_self_ids)

    return RenderedReply(
        text=rendered.text,
        image_urls=rendered.image_urls,
        mentioned_bot=rendered.mentioned_bot,
        is_bot_self=is_bot_self,
        sender_name=sender_name,
        user_id=user_id,
        message_id=str(getattr(reply, "message_id", "") or "").strip(),
    )
