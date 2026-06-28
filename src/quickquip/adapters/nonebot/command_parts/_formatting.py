from __future__ import annotations

from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_type
from quickquip.common.bot_action_trace import overlay_bot_action_trace


def _format_tts_models(audio_generation) -> str:
    lines = ["可用语音模型："]
    for model_id, resolved in audio_generation.models.items():
        label = resolved.model_config.label or model_id
        default_mark = "（默认）" if model_id == audio_generation.default_model else ""
        voice_hint = f" / 默认音色 {resolved.model_config.voice_id}" if resolved.model_config.voice_id else ""
        lines.append(
            f"- {model_id}：{label} / provider {resolved.provider.id}{voice_hint}{default_mark}"
        )
    return "\n".join(lines)


def _format_music_models(music_generation) -> str:
    lines = ["可用音乐模型："]
    for model_id, resolved in music_generation.models.items():
        label = resolved.model_config.label or model_id
        default_mark = "（默认）" if model_id == music_generation.default_model else ""
        lines.append(
            f"- {model_id}：{label} / provider {resolved.provider.id}{default_mark}"
        )
    return "\n".join(lines)


def _format_voice_groups(voice_groups: dict[str, list], keyword: str = "") -> str:
    labels = {
        "system_voice": "系统音色",
        "voice_cloning": "声音复刻",
        "voice_generation": "声音生成",
    }
    lines: list[str] = []
    normalized_keyword = keyword.strip().lower()
    total = 0
    for key in ("system_voice", "voice_cloning", "voice_generation"):
        items = voice_groups.get(key, [])
        if normalized_keyword:
            filtered = []
            for item in items:
                haystacks = [
                    item.voice_id.lower(),
                    item.voice_name.lower(),
                    " ".join(item.description or []).lower(),
                ]
                if any(normalized_keyword in text for text in haystacks):
                    filtered.append(item)
            items = filtered
        if not items:
            continue
        total += len(items)
        lines.append(f"{labels[key]}（{len(items)}）")
        for item in items[:20]:
            desc = ""
            if item.voice_name:
                desc = item.voice_name
            elif item.description:
                desc = " / ".join(item.description[:2])
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- {item.voice_id}{suffix}")
        if len(items) > 20:
            lines.append(f"- ... 其余 {len(items) - 20} 个未展开")
    if not total:
        if normalized_keyword:
            return f"未找到包含“{keyword}”的音色。"
        return "当前 provider 未返回可用音色。"
    return "\n".join(lines)


def _format_generated_lyrics(result, *, heading: str) -> str:
    lines = [heading]
    if result.title:
        lines.append(f"标题：{result.title}")
    if result.style_tags:
        lines.append(f"风格：{result.style_tags}")
    if result.lyrics:
        lines.append("歌词：")
        lines.append(result.lyrics)
    return "\n".join(lines)


def _chunk_text(content: str, max_chars: int = 600) -> list[str]:
    if len(content) <= max_chars:
        return [content]
    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_chars:
        pos = remaining.rfind("\n\n", 0, max_chars)
        if pos != -1:
            chunks.append(remaining[:pos].rstrip())
            remaining = remaining[pos + 2:].lstrip()
            continue
        pos = remaining.rfind("\n", 0, max_chars)
        if pos != -1:
            chunks.append(remaining[:pos])
            remaining = remaining[pos + 1:]
            continue
        chunks.append(remaining[:max_chars])
        remaining = remaining[max_chars:]
    if remaining.strip():
        chunks.append(remaining.strip())
    return chunks


async def _send_lyrics_forward(bot, event, lyric_result, heading: str) -> None:
    formatted = _format_generated_lyrics(lyric_result, heading=heading)
    group_id = getattr(event, "group_id", None)

    with overlay_bot_action_trace(
        trigger_kind="command",
        reason_code="command.music.lyrics",
        reason_detail="命令触发：歌词生成结果发送",
        rule_name="music_gen",
        chat_type=_chat_type(event),
        group_id=group_id,
        user_id=getattr(event, "user_id", ""),
        incoming_message_id=str(getattr(event, "message_id", "") or ""),
        incoming_preview=str(event.get_message()).strip() if hasattr(event, "get_message") else "",
        reply_preview=formatted,
        source="command.music.lyrics_forward",
    ):
        if group_id is not None:
            chunks = _chunk_text(formatted)
            try:
                await bot.call_api(
                    "send_group_forward_msg",
                    group_id=group_id,
                    messages=[
                        {
                            "type": "node",
                            "data": {
                                "name": "歌词",
                                "uin": str(bot.self_id),
                                "content": [{"type": "text", "data": {"text": chunk}}],
                            },
                        }
                        for chunk in chunks
                    ],
                )
                return
            except Exception:
                pass
        if group_id is not None:
            await bot.send_group_msg(group_id=group_id, message=formatted)
        else:
            await bot.send_private_msg(user_id=event.user_id, message=formatted)
