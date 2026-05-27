from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import shlex
from datetime import date

from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.common.bot_action_trace import overlay_bot_action_trace
from quickquip.llm.profile import DEFAULT_PROFILE_MODE, PROFILE_MODES, ProfileModeConfig


def _is_private_chat(event) -> bool:
    return getattr(event, "message_type", "") == "private" or getattr(event, "group_id", None) is None


def _chat_type(event) -> str:
    return "private" if _is_private_chat(event) else "group"


def _chat_id(event):
    if _is_private_chat(event):
        return event.user_id
    return event.group_id


def _chat_label(event) -> str:
    return "当前私聊" if _is_private_chat(event) else "本群"


def _allow_scope_management(event) -> bool:
    return _is_private_chat(event) or _is_admin(event)


def _evaluate_luck(value: float) -> str:
    if value < 0.2:
        return "大凶"
    elif value < 0.5:
        return "凶"
    elif value < 0.8:
        return "平"
    elif value < 1.2:
        return "吉"
    elif value < 3.0:
        return "大吉"
    else:
        return "神运"


def _luck_lookup(value: float, table: list[dict]) -> str:
    """Find the first luck tip whose range contains *value*."""
    for entry in table:
        if entry["min"] <= value < entry["max"]:
            return entry["text"]
    return table[-1]["text"] if table else "运势未知…"


def _glue_luck_tips(value: float, text=None) -> str:
    if text is not None and text.luck_glue:
        return _luck_lookup(value, text.luck_glue)
    return _luck_lookup(value, _DEFAULT_GLUE_LUCK)


def _fence_luck_tips(value: float, text=None) -> str:
    if text is not None and text.luck_fence:
        return _luck_lookup(value, text.luck_fence)
    return _luck_lookup(value, _DEFAULT_FENCE_LUCK)


# Built-in fallbacks used when no text object is available
_DEFAULT_GLUE_LUCK: list[dict] = [
    {"min": 0.0, "max": 0.2, "text": "今日不宜打胶，牛牛极易萎缩…"},
    {"min": 0.2, "max": 0.5, "text": "运势低迷，打胶效果减半，小心凹进去！"},
    {"min": 0.5, "max": 0.8, "text": "运势平平，平常心对待即可~"},
    {"min": 0.8, "max": 1.2, "text": "运势尚可，正常发挥！"},
    {"min": 1.2, "max": 3.0, "text": "运势旺盛，打胶事半功倍！"},
    {"min": 3.0, "max": 999.0, "text": "运势如虹！今日打胶效果极佳，冲！！"},
]

_DEFAULT_FENCE_LUCK: list[dict] = [
    {"min": 0.0, "max": 0.2, "text": "今日击剑大凶，极易翻车…建议避战！"},
    {"min": 0.2, "max": 0.5, "text": "击剑运势不佳，谨慎出手！"},
    {"min": 0.5, "max": 0.8, "text": "运势中规中矩，可战可不战~"},
    {"min": 0.8, "max": 1.2, "text": "运势良好，可放手一战！"},
    {"min": 1.2, "max": 3.0, "text": "运势高涨！今日击剑胜率大幅提升！"},
    {"min": 3.0, "max": 999.0, "text": "运势如神！今日击剑无往不利，战无不胜！！"},
]


def _extract_image_urls(message) -> list[str]:
    return [
        seg.data.get("url", "")
        for seg in message
        if seg.type == "image" and seg.data.get("url", "").startswith("http")
    ]


async def _resolve_forward_content(bot, seg) -> tuple[str, list[str]]:
    raw_nodes = seg.data.get("content") or []
    if not raw_nodes:
        fwd_id = seg.data.get("id", "")
        if fwd_id:
            try:
                raw_nodes = await bot.get_forward_msg(message_id=fwd_id) or []
            except Exception:
                return "", []
    texts: list[str] = []
    urls: list[str] = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        for sd in node.get("message", []):
            if not isinstance(sd, dict):
                continue
            if sd.get("type") == "text":
                t = sd.get("data", {}).get("text", "").strip()
                if t:
                    texts.append(t)
            elif sd.get("type") == "image":
                url = sd.get("data", {}).get("url", "")
                if url.startswith("http"):
                    urls.append(url)
    return "\n".join(filter(None, texts)), urls


async def _resolve_message_content(bot, message) -> tuple[str, list[str]]:
    texts: list[str] = []
    urls: list[str] = []
    for seg in message:
        if seg.type == "text":
            t = seg.data.get("text", "").strip()
            if t:
                texts.append(t)
        elif seg.type == "image":
            url = seg.data.get("url", "")
            if url.startswith("http"):
                urls.append(url)
        elif seg.type == "forward":
            ft, fu = await _resolve_forward_content(bot, seg)
            if ft:
                texts.append(ft)
            urls.extend(fu)
    return "\n".join(filter(None, texts)), urls


_FORTUNES = [
    ("大吉", "财运亨通，诸事大顺，今日宜出行、宜交友"),
    ("吉", "今日顺遂，保持当下状态即可"),
    ("中吉", "稳中求进，努力终有回报"),
    ("小吉", "小有收获，量力而行，不必强求"),
    ("末吉", "平稳即福，顺势而为，随心所欲"),
    ("平", "波澜不惊，平常心是最贵的"),
    ("小凶", "遇事三思而后行，不宜冒进"),
    ("凶", "今日多有阻碍，静待时机，勿急于求成"),
]
_NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")


def _daily_fortune(user_id: int | str) -> tuple[str, str]:
    h = int(hashlib.md5(f"{user_id}:{date.today().isoformat()}".encode()).hexdigest(), 16)
    return _FORTUNES[h % len(_FORTUNES)]


def _safe_shlex_split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _select_profile_samples(
    messages: list[dict],
    target_user_id: str,
    *,
    limit: int | None,
    max_chars: int | None,
) -> list[str]:
    target_messages = [
        m["text"].strip()
        for m in messages
        if m.get("user_id") == target_user_id and m.get("text", "").strip()
    ]
    if limit is not None:
        target_messages = target_messages[-limit:]
    if max_chars is None:
        return target_messages
    return [text[:max_chars] for text in target_messages]


def _parse_profile_mode(message_text: str) -> ProfileModeConfig:
    args = _strip_command_name(message_text.strip(), "profile").strip()
    for mode_id, mode_config in PROFILE_MODES.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(mode_id)}(?![A-Za-z])", args, re.IGNORECASE):
            return mode_config
    return DEFAULT_PROFILE_MODE


_PRESET_RE = re.compile(r'--preset\s+(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|(\S.*))', re.DOTALL)
_RESUME_RE = re.compile(r'--resume(?:\s+(\d+))?')
_DICE_RE = re.compile(r"^(\d*)[dD](\d+)$")
_DRAW_SIZE_RE = re.compile(r'--size\s+(\d+x\d+)', re.IGNORECASE)
_DRAW_QUALITY_RE = re.compile(r'--quality\s+(\S+)', re.IGNORECASE)


def _parse_preset(args: str) -> str:
    m = _PRESET_RE.search(args)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def _parse_resume(args: str) -> tuple[bool, int | None]:
    m = _RESUME_RE.search(args)
    if not m:
        return False, None
    num_str = m.group(1)
    return True, int(num_str) if num_str else None


def _parse_tieba_command_args(args: str) -> tuple[str, str | None, bool]:
    normalized_args = args.strip()
    if not normalized_args:
        return "random", None, False

    tokens = normalized_args.split()
    head = tokens[0].lower()
    remainder = normalized_args[len(tokens[0]):].strip()

    if head in {"random", "status", "refresh", "source"}:
        return head, remainder or None, False
    if head == "text":
        return "random", remainder or None, True
    if head == "list":
        return "status", None, False
    return "random", normalized_args, False


def _strip_leading_command_token(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    parts = normalized.split(maxsplit=1)
    if len(parts) == 1:
        return ""
    return parts[1].strip()


def _parse_tts_args(args: str, available_models: set[str]) -> tuple[str | None, str | None, str]:
    tokens = _safe_shlex_split(args)
    if not tokens:
        return None, None, ""

    model_id: str | None = None
    voice_id: str | None = None
    index = 0
    if tokens and tokens[0] in available_models:
        model_id = tokens[0]
        index = 1

    text_parts: list[str] = []
    while index < len(tokens):
        token = tokens[index]
        if token == "--voice" and index + 1 < len(tokens):
            voice_id = tokens[index + 1].strip() or None
            index += 2
            continue
        text_parts.append(token)
        index += 1

    return model_id, voice_id, " ".join(text_parts).strip()


@dataclass(slots=True)
class MusicCommandArgs:
    action: str = "generate"
    model_id: str | None = None
    prompt: str = ""
    lyrics: str = ""
    title: str = ""
    instrumental: bool = False


def _parse_music_args(args: str, available_models: set[str]) -> MusicCommandArgs:
    tokens = _safe_shlex_split(args)
    if not tokens:
        return MusicCommandArgs()

    parsed = MusicCommandArgs()
    index = 0
    if tokens[0] == "models":
        parsed.action = "models"
        return parsed
    if tokens[0] == "lyrics":
        parsed.action = "lyrics"
        index = 1
        if index < len(tokens) and tokens[index] == "edit":
            parsed.action = "lyrics_edit"
            index += 1
    elif tokens[0] in available_models:
        parsed.model_id = tokens[0]
        index = 1

    prompt_parts: list[str] = []
    while index < len(tokens):
        token = tokens[index]
        if token == "--lyrics" and index + 1 < len(tokens):
            parsed.lyrics = tokens[index + 1].strip()
            index += 2
            continue
        if token == "--title" and index + 1 < len(tokens):
            parsed.title = tokens[index + 1].strip()
            index += 2
            continue
        if token == "--instrumental":
            parsed.instrumental = True
            index += 1
            continue
        prompt_parts.append(token)
        index += 1

    parsed.prompt = " ".join(prompt_parts).strip()
    return parsed


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

    def _trace_context():
        return overlay_bot_action_trace(
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
        )

    if group_id is not None:
        chunks = _chunk_text(formatted)
        try:
            trace_context = _trace_context()
            with trace_context:
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
        trace_context = _trace_context()
        with trace_context:
            await bot.send_group_msg(group_id=group_id, message=formatted)
    else:
        trace_context = _trace_context()
        with trace_context:
            await bot.send_private_msg(user_id=event.user_id, message=formatted)
