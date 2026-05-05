from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
import random
import re
import shlex
from datetime import date, datetime
from io import BytesIO
from time import time

from quickquip.app.message_pipeline import RULE_SWITCH_PATH, STATS_PATH, daily_collector, game_economy, game_registry, game_scores, get_sender_name, group_quote_store, llm_service, niuniu_store, offline_message_store, rate_limiter, reload_chat_rules_pipeline, rule_switch, stats_tracker
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.generation.audio import generate_audio, list_available_voices
from quickquip.generation.errors import GenerationProviderError
from quickquip.generation.image import ImageInput, download_image, generate_image
from quickquip.generation.music import generate_lyrics, generate_music
from quickquip.generation.service import generation_service
from quickquip.adapters.nonebot.long_messages import send_long_group_message
from quickquip.llm.profile import DEFAULT_PROFILE_MODE, PROFILE_MODES, ProfileModeConfig, generate_profile
from quickquip.llm.provider import LLMProviderError
from quickquip.llm.rendering import render_message_for_llm, render_reply_for_llm
from quickquip.search.web_search import SearXNGSearchClient, WebSearchError, format_search_response
from quickquip.tieba.config import TIEBA_RULE_NAME
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError
from quickquip.tieba.service import tieba_service
from quickquip.games.niuniu import (
    _check_cd,
    _comment,
    _fence_cd,
    _fenced_cd,
    _glue_cd,
    fencing,
    gluing,
)

logger = logging.getLogger(__name__)


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


_PRESET_RE = re.compile(r'--preset\s+(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|(\S.*))', re.DOTALL)
_RESUME_RE = re.compile(r'--resume(?:\s+(\d+))?')
_DICE_RE = re.compile(r"^(\d*)[dD](\d+)$")
_DRAW_SIZE_RE = re.compile(r'--size\s+(\d+x\d+)', re.IGNORECASE)
_DRAW_QUALITY_RE = re.compile(r'--quality\s+(\S+)', re.IGNORECASE)


def _extract_image_urls(message) -> list[str]:
    return [
        seg.data.get("url", "")
        for seg in message
        if seg.type == "image" and seg.data.get("url", "").startswith("http")
    ]


async def _resolve_forward_content(bot, seg) -> tuple[str, list[str]]:
    """Fetch text and image URLs from a merged-forward segment."""
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
    """Extract (text, image_urls) from a message, resolving forward segments."""
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
    """Split long text at paragraph/line boundaries for merge-forward nodes."""
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
    """Send lyrics as merge-forward in groups to avoid flooding chat."""
    formatted = _format_generated_lyrics(lyric_result, heading=heading)
    group_id = getattr(event, "group_id", None)
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
    # Fallback: direct message
    if group_id is not None:
        await bot.send_group_msg(group_id=group_id, message=formatted)
    else:
        await bot.send_private_msg(user_id=event.user_id, message=formatted)


def register_commands(on_command, Message, MessageSegment) -> None:
    start_session_cmd = on_command("start_sesssion", priority=10, block=True)
    start_session_alias_cmd = on_command("start_session", priority=10, block=True)
    end_session_cmd = on_command("end_session", priority=10, block=True)

    async def _start_private_session(event, matcher, cmd_name: str) -> None:
        if not _is_private_chat(event):
            await matcher.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, cmd_name)
        has_resume, resume_num = _parse_resume(args)
        if has_resume:
            result = llm_service.resume_private_session(event.user_id, resume_num)
            if "error" in result:
                await matcher.finish(result["error"])
            preset_override = _parse_preset(args)
            if preset_override:
                scope_key = llm_service.build_chat_scope_key(event.user_id, "private")
                llm_service._session_presets[scope_key] = preset_override
            preset = preset_override or result.get("preset", "")
            msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
            if preset:
                preview = preset[:80] + ("..." if len(preset) > 80 else "")
                msg += f"\n附加设定：{preview}"
            await matcher.finish(msg)
        preset = _parse_preset(args)
        llm_service.start_private_session(event.user_id, preset=preset)
        msg = (
            f"当前私聊会话已开启，之后的普通消息、图片和引用回复都会进入 LLM。"
            f" 当前上下文上限为 {llm_service.get_default_history_limit('private')} 条。"
        )
        if preset:
            preview = preset[:80] + ("..." if len(preset) > 80 else "")
            msg += f"\n附加设定：{preview}"
        await matcher.finish(msg)

    async def _end_private_session(event, matcher, cmd_name: str) -> None:
        if not _is_private_chat(event):
            await matcher.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, cmd_name)
        no_save = "--no-save" in args
        result = llm_service.end_private_session(event.user_id, save=not no_save)
        deleted = result["deleted"]
        archive_number = result.get("archive_number")
        if archive_number is not None:
            await matcher.finish(f"当前私聊会话已结束，已存档为 #{archive_number}（{deleted} 条消息）。")
        else:
            suffix = "（未存档）" if no_save else ""
            await matcher.finish(f"当前私聊会话已结束，并清空了 {deleted} 条短期上下文。{suffix}")

    @start_session_cmd.handle()
    async def _(event):
        await _start_private_session(event, start_session_cmd, "start_sesssion")

    @start_session_alias_cmd.handle()
    async def _(event):
        await _start_private_session(event, start_session_alias_cmd, "start_session")

    @end_session_cmd.handle()
    async def _(event):
        await _end_private_session(event, end_session_cmd, "end_session")

    resume_session_cmd = on_command("resume_session", priority=10, block=True)

    @resume_session_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await resume_session_cmd.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "resume_session").strip()
        archive_number = int(args) if args.isdigit() else None
        result = llm_service.resume_private_session(event.user_id, archive_number)
        if "error" in result:
            await resume_session_cmd.finish(result["error"])
        preset = result.get("preset", "")
        msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
        if preset:
            preview = preset[:80] + ("..." if len(preset) > 80 else "")
            msg += f"\n附加设定：{preview}"
        await resume_session_cmd.finish(msg)

    sessions_cmd = on_command("sessions", priority=10, block=True)

    @sessions_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await sessions_cmd.finish("该命令仅支持私聊")
        await sessions_cmd.finish(llm_service.format_session_archives(event.user_id))

    delete_session_cmd = on_command("delete_session", priority=10, block=True)

    @delete_session_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await delete_session_cmd.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "delete_session").strip()
        if not args.isdigit():
            await delete_session_cmd.finish("用法：/delete_session <存档编号>")
        archive_number = int(args)
        deleted = llm_service.delete_session_archive_for_user(event.user_id, archive_number)
        if deleted:
            await delete_session_cmd.finish(f"已删除存档 #{archive_number}。")
        else:
            await delete_session_cmd.finish(f"存档 #{archive_number} 不存在。")

    stats_cmd = on_command("stats", priority=10, block=True)

    @stats_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await stats_cmd.finish("私聊不支持 /stats")
        await stats_cmd.finish(stats_tracker.format_stats(event.group_id))

    llm_cmd = on_command("llm", priority=10, block=True)

    @llm_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "llm")
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        scope_label = _chat_label(event)
        tokens = args.split()

        if not args or args == "status":
            await llm_cmd.finish(llm_service.format_status(chat_id, chat_type=chat_type))

        if args == "current":
            await llm_cmd.finish(llm_service.format_current(chat_id, chat_type=chat_type))

        if tokens[:1] == ["health"]:
            await llm_cmd.finish(
                await llm_service.format_health(
                    chat_id,
                    chat_type=chat_type,
                    verbose=len(tokens) > 1 and tokens[1] in {"verbose", "detail", "full"},
                )
            )

        if args in {"mcp", "mcp status"}:
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "mcp reload":
            if not _allow_scope_management(event):
                await llm_cmd.finish("仅管理员可执行此操作")
            await llm_cmd.send("正在拉取 MCP 镜像并重连，请稍候…")
            await llm_service.reload_mcp(background=False)
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "providers":
            await llm_cmd.finish(llm_service.format_providers())

        if args == "personas":
            await llm_cmd.finish(llm_service.format_personas(chat_type=chat_type))

        if tokens[:1] == ["models"]:
            provider_id = tokens[1] if len(tokens) > 1 else None
            await llm_cmd.finish(llm_service.format_models(provider_id))

        if tokens[:2] == ["memory", "status"]:
            await llm_cmd.finish(llm_service.format_memory_status(chat_id, chat_type=chat_type))

        if not _allow_scope_management(event):
            await llm_cmd.finish("仅管理员可执行此操作")

        if tokens[:1] == ["on"]:
            if chat_type == "private":
                has_resume, resume_num = _parse_resume(args)
                if has_resume:
                    result = llm_service.resume_private_session(chat_id, resume_num)
                    if "error" in result:
                        await llm_cmd.finish(result["error"])
                    preset_override = _parse_preset(args)
                    if preset_override:
                        scope_key = llm_service.build_chat_scope_key(chat_id, "private")
                        llm_service._session_presets[scope_key] = preset_override
                    preset = preset_override or result.get("preset", "")
                    msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
                    if preset:
                        preview = preset[:80] + ("..." if len(preset) > 80 else "")
                        msg += f"\n附加设定：{preview}"
                    await llm_cmd.finish(msg)
                preset = _parse_preset(args)
                llm_service.start_private_session(chat_id, preset=preset)
                msg = f"{scope_label}会话已开启。也可以直接使用 /start_sesssion，当前上下文上限为 {llm_service.get_default_history_limit('private')} 条。"
                if preset:
                    preview = preset[:80] + ("..." if len(preset) > 80 else "")
                    msg += f"\n附加设定：{preview}"
                await llm_cmd.finish(msg)
            else:
                llm_service.set_chat_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已开启")

        if tokens[:1] == ["off"]:
            if chat_type == "private":
                no_save = "--no-save" in args
                result = llm_service.end_private_session(chat_id, save=not no_save)
                deleted = result["deleted"]
                archive_number = result.get("archive_number")
                if archive_number is not None:
                    await llm_cmd.finish(f"{scope_label}会话已结束，已存档为 #{archive_number}（{deleted} 条消息）。")
                else:
                    suffix = "（未存档）" if no_save else ""
                    await llm_cmd.finish(f"{scope_label}会话已结束，并清空了 {deleted} 条短期上下文。{suffix}")
            else:
                llm_service.set_chat_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已关闭")

        if args == "reload":
            llm_service.reset_chat_history_limit(chat_id, chat_type=chat_type)
            config = await llm_service.reload_runtime(background=True)
            if config.load_error:
                await llm_cmd.finish(f"LLM 配置重载失败：{config.load_error}")
            await llm_cmd.finish("LLM 配置已重载")

        if args == "clear_context":
            deleted = llm_service.clear_context(chat_id, chat_type=chat_type)
            await llm_cmd.finish(f"已清空{scope_label}的短期上下文，共删除 {deleted} 条记录")

        if tokens[:1] == ["delete_msg"]:
            reply = getattr(event, "reply", None)
            target_msg_id = ""
            if reply:
                target_msg_id = str(getattr(reply, "message_id", "") or "").strip()
            if not target_msg_id and len(tokens) >= 2:
                target_msg_id = tokens[1].strip()
            if not target_msg_id:
                await llm_cmd.finish("用法：引用一条消息并发送 /llm delete_msg，或 /llm delete_msg <消息ID>")
            scope_key = llm_service.build_chat_scope_key(chat_id, chat_type)
            deleted = llm_service.delete_message_from_context(scope_key, target_msg_id)
            if deleted:
                await llm_cmd.finish(f"已从上下文中删除消息 {target_msg_id}")
            else:
                await llm_cmd.finish(f"未找到消息 {target_msg_id}，可能已过期或未被记录")

        if tokens[:1] == ["use"] and len(tokens) >= 2:
            provider_id = tokens[1]
            model = tokens[2] if len(tokens) >= 3 else ""
            try:
                resolved = llm_service.set_chat_model(chat_id, provider_id, model, chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            if model and model != resolved:
                msg = f"{scope_label} LLM 已切换到 {provider_id} / {resolved}（← {model}）"
            else:
                msg = f"{scope_label} LLM 已切换到 {provider_id} / {resolved}"
            await llm_cmd.finish(msg)

        if tokens[:2] == ["persona", "use"] and len(tokens) >= 3:
            persona_id = tokens[2]
            try:
                llm_service.set_chat_persona(chat_id, persona_id, chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}人格已切换到 {persona_id}")

        if tokens[:2] == ["trigger", "prefix"] and len(tokens) >= 3:
            try:
                llm_service.set_chat_trigger_prefix(chat_id, tokens[2], chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}触发前缀已改为 {tokens[2]}")

        if tokens[:2] == ["trigger", "prefix_mode"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger prefix_mode on|off")
            llm_service.set_chat_allow_prefix(chat_id, value == "on", chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}前缀触发已设为 {value}")

        if tokens[:2] == ["trigger", "at"] and len(tokens) >= 3:
            if chat_type == "private":
                await llm_cmd.finish("私聊仅支持前缀触发，不支持艾特触发")
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger at on|off")
            llm_service.set_group_allow_at(chat_id, value == "on")
            await llm_cmd.finish(f"{scope_label}艾特触发已设为 {value}")

        if tokens[:2] == ["memory", "on"]:
            llm_service.set_chat_memory_enabled(chat_id, True, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已开启")

        if tokens[:2] == ["memory", "off"]:
            llm_service.set_chat_memory_enabled(chat_id, False, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已关闭")

        if tokens[:1] == ["auto_memory"] and len(tokens) >= 2:
            sub = tokens[1].lower()
            if sub == "on":
                llm_service.set_chat_auto_memory_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已开启")
            if sub == "off":
                llm_service.set_chat_auto_memory_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已关闭")
            if sub == "reset":
                llm_service.set_chat_auto_memory_enabled(chat_id, None, chat_type=chat_type)
                default = "开" if llm_service.config.runtime.auto_memory_enabled else "关"
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已跟随全局默认（当前：{default}）")
            if sub == "status":
                settings = llm_service.get_chat_settings(chat_id, chat_type=chat_type)
                default = "开" if llm_service.config.runtime.auto_memory_enabled else "关"
                current = "开" if settings.auto_memory_enabled else "关"
                await llm_cmd.finish(
                    f"{scope_label}自动记忆抽取：{current}（全局默认 {default}）"
                )

        if tokens[:1] == ["context_limit"] and len(tokens) >= 2:
            value = tokens[1].lower()
            if value in {"reset", "off"}:
                llm_service.reset_chat_history_limit(chat_id, chat_type=chat_type)
                await llm_cmd.finish(
                    f"{scope_label}上下文上限已重置为默认（{llm_service.get_default_history_limit(chat_type)} 条）"
                )
            try:
                n = int(value)
            except ValueError:
                await llm_cmd.finish("用法：/llm context_limit <条数> | reset")
            if n < 1:
                await llm_cmd.finish("上下文上限须为正整数")
            llm_service.set_chat_history_limit(chat_id, n, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}上下文上限已设为 {n} 条（/llm reload 可重置）")

        await llm_cmd.finish(
            "LLM 命令用法：/llm status|current|on|off|providers|models [provider]|use <provider> [model]|"
            "personas|persona use <id>|trigger prefix <value>|trigger prefix_mode on|off|trigger at on|off|"
            "memory status|memory on|memory off|auto_memory on|off|reset|status|context_limit <n>|context_limit reset|clear_context|reload|mcp status"
        )

    search_cmd = on_command("search", priority=10, block=True)

    @search_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "search")
        if not args:
            await search_cmd.finish("用法：/search <query> 或 /search news <query>")
        if not rate_limiter.allow("web_search", event.user_id):
            await search_cmd.finish("搜索过于频繁，请稍后再试")

        tokens = args.split()
        topic = "general"
        query = args
        if tokens and tokens[0].lower() in {"general", "news", "finance"}:
            topic = tokens[0].lower()
            query = args[len(tokens[0]):].strip()
        if not query:
            await search_cmd.finish("搜索词不能为空")

        try:
            response = await SearXNGSearchClient().search(query, topic=topic, max_results=5)
        except WebSearchError as exc:
            await search_cmd.finish(f"联网搜索失败：{exc}")
        await search_cmd.finish(format_search_response(response))

    defectify_cmd = on_command("defectify", aliases={"故障化"}, priority=10, block=True)

    @defectify_cmd.handle()
    async def _(event):
        if not rate_limiter.allow("llm_chat", event.user_id):
            await defectify_cmd.finish("转写过于频繁，请稍后再试")

        rendered = render_message_for_llm(
            event.get_message(),
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
        )
        rendered_reply = render_reply_for_llm(
            getattr(event, "reply", None),
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            include_image_placeholder=True,
        )
        prompt = _strip_leading_command_token(rendered.text)
        quoted_text = "" if rendered_reply is None else rendered_reply.text
        quoted_image_urls = [] if rendered_reply is None else rendered_reply.image_urls
        quoted_sender_name = "" if rendered_reply is None else rendered_reply.sender_name
        quoted_user_id = "" if rendered_reply is None else rendered_reply.user_id
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        result = await llm_service.generate_defectify_reply(
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=event.user_id,
            sender_name=get_sender_name(event),
            prompt=prompt,
            image_urls=rendered.image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )
        if chat_type == "group":
            stats_tracker.record_trigger(event.group_id, result.get("rule_name", "unknown"))
        await defectify_cmd.finish(result["reply"])

    draw_cmd = on_command("draw", priority=10, block=True)

    @draw_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        if not rate_limiter.allow("image_gen", event.user_id, group_id=group_id):
            await draw_cmd.finish("图片生成过于频繁，请稍后再试")
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await draw_cmd.finish(f"图片生成配置错误：{generation_config.load_error}")
        image_generation = generation_config.image
        if not image_generation.enabled:
            await draw_cmd.finish("图片生成功能未启用")
        if not image_generation.models:
            await draw_cmd.finish("图片生成模型未配置")
        text = str(event.get_message()).strip()
        prompt = _strip_command_name(text, "draw").strip()
        first_word = prompt.split()[0] if prompt else ""
        resolved_model = None
        if first_word:
            resolved_model = image_generation.resolve_model(first_word)
        if resolved_model is not None:
            prompt = prompt[len(first_word):].strip()
        else:
            resolved_model = image_generation.resolve_model()
        if resolved_model is None:
            await draw_cmd.finish("图片生成默认模型未配置")
        model_config = resolved_model.model_config
        provider = resolved_model.provider
        size_m = _DRAW_SIZE_RE.search(prompt)
        quality_m = _DRAW_QUALITY_RE.search(prompt)
        size_override = size_m.group(1) if size_m else None
        quality_override = quality_m.group(1) if quality_m else None
        if size_m:
            prompt = _DRAW_SIZE_RE.sub("", prompt).strip()
        if quality_m:
            prompt = _DRAW_QUALITY_RE.sub("", prompt).strip()
        # Collect text and images from replied-to message (if any)
        reply = getattr(event, "reply", None)
        reply_text, reply_urls = "", []
        if reply and reply.message:
            reply_text, reply_urls = await _resolve_message_content(bot, reply.message)
        # Own message: text already in prompt, collect images only
        own_urls = _extract_image_urls(event.get_message())
        # Merge: reply text prefixed before user's own prompt
        full_prompt = "\n".join(filter(None, [reply_text, prompt])).strip()
        if not full_prompt and not reply_urls and not own_urls:
            model_ids = list(image_generation.models)
            hint = "用法：/draw [模型] [--size 宽x高] [--quality 值] <描述>"
            if len(model_ids) > 1:
                await draw_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{image_generation.default_model}）"
                )
            await draw_cmd.finish(hint)
        if full_prompt and any(w in full_prompt.lower() for w in image_generation.prompt_blocklist):
            await draw_cmd.finish("提示词包含不允许的内容，请修改后重试")
        await draw_cmd.send("正在生成图片，请稍候…")
        input_images: list[ImageInput] = []
        for url in reply_urls + own_urls:
            try:
                input_images.append(await download_image(url))
            except Exception:
                pass
        try:
            image_b64 = await generate_image(
                model_config, provider, full_prompt,
                input_images=input_images or None,
                size=size_override, quality=quality_override,
            )
        except GenerationProviderError as exc:
            await draw_cmd.finish(f"图片生成失败：{exc}")
        except Exception as exc:
            await draw_cmd.finish(f"图片生成异常：{type(exc).__name__}: {exc}")
        await draw_cmd.finish(Message([MessageSegment.image(f"base64://{image_b64}")]))

    tts_cmd = on_command("tts", priority=10, block=True)

    @tts_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await tts_cmd.finish(f"语音生成配置错误：{generation_config.load_error}")
        audio_generation = generation_config.audio
        if not audio_generation.enabled:
            await tts_cmd.finish("语音生成功能未启用")
        if not audio_generation.models:
            await tts_cmd.finish("语音生成模型未配置")

        text = str(event.get_message()).strip()
        raw_args = _strip_command_name(text, "tts").strip()
        if raw_args == "models":
            await tts_cmd.finish(_format_tts_models(audio_generation))

        if raw_args.startswith("voices"):
            pieces = _safe_shlex_split(raw_args)
            maybe_model = pieces[1] if len(pieces) > 1 and pieces[1] in audio_generation.models else None
            keyword = ""
            if maybe_model is not None:
                keyword = " ".join(pieces[2:]).strip()
            else:
                keyword = " ".join(pieces[1:]).strip() if len(pieces) > 1 else ""
            resolved_for_voices = audio_generation.resolve_model(maybe_model)
            if resolved_for_voices is None:
                await tts_cmd.finish("语音生成默认模型未配置")
            await tts_cmd.send("正在获取可用音色，请稍候…")
            try:
                voice_groups = await list_available_voices(resolved_for_voices.provider)
            except GenerationProviderError as exc:
                await tts_cmd.finish(f"音色列表获取失败：{exc}")
            await tts_cmd.finish(_format_voice_groups(voice_groups, keyword=keyword))

        if not rate_limiter.allow("audio_gen", event.user_id, group_id=group_id):
            await tts_cmd.finish("语音生成过于频繁，请稍后再试")
        model_id, voice_id, prompt = _parse_tts_args(raw_args, set(audio_generation.models))
        resolved_model = audio_generation.resolve_model(model_id)
        if resolved_model is None:
            await tts_cmd.finish("语音生成默认模型未配置")

        reply = getattr(event, "reply", None)
        reply_text = ""
        if reply and reply.message:
            reply_text, _ = await _resolve_message_content(bot, reply.message)
        full_prompt = "\n".join(filter(None, [reply_text, prompt])).strip()

        if not full_prompt:
            model_ids = list(audio_generation.models)
            hint = "用法：/tts [模型] [--voice 音色ID] <文本>"
            if len(model_ids) > 1:
                await tts_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{audio_generation.default_model}）"
                )
            await tts_cmd.finish(hint)
        if any(word in full_prompt.lower() for word in audio_generation.prompt_blocklist):
            await tts_cmd.finish("文本包含不允许的内容，请修改后重试")

        await tts_cmd.send("正在生成语音，请稍候…")
        try:
            result = await generate_audio(
                resolved_model.model_config,
                resolved_model.provider,
                full_prompt,
                voice_id=voice_id,
            )
        except GenerationProviderError as exc:
            await tts_cmd.finish(f"语音生成失败：{exc}")
        except Exception as exc:
            await tts_cmd.finish(f"语音生成异常：{type(exc).__name__}: {exc}")

        audio_file = BytesIO(result.audio_bytes)
        await tts_cmd.finish(
            Message([MessageSegment.record(audio_file)])
        )

    music_cmd = on_command("music", priority=10, block=True)

    @music_cmd.handle()
    async def _(bot, event):
        group_id = getattr(event, "group_id", None)
        generation_config = generation_service.get_config()
        if generation_config.load_error:
            await music_cmd.finish(f"音乐生成配置错误：{generation_config.load_error}")
        music_generation = generation_config.music
        if not music_generation.enabled:
            await music_cmd.finish("音乐生成功能未启用")
        if not music_generation.models:
            await music_cmd.finish("音乐生成模型未配置")

        text = str(event.get_message()).strip()
        raw_args = _strip_command_name(text, "music").strip()
        parsed = _parse_music_args(raw_args, set(music_generation.models))

        if parsed.action == "models":
            await music_cmd.finish(_format_music_models(music_generation))

        reply = getattr(event, "reply", None)
        reply_text = ""
        if reply and reply.message:
            reply_text, _ = await _resolve_message_content(bot, reply.message)

        blocklist_text = "\n".join(
            filter(None, [parsed.prompt, parsed.lyrics, parsed.title, reply_text])
        ).lower()
        if any(word in blocklist_text for word in music_generation.prompt_blocklist):
            await music_cmd.finish("文本包含不允许的内容，请修改后重试")

        default_music_model = music_generation.resolve_model(parsed.model_id)
        if default_music_model is None:
            await music_cmd.finish("音乐生成默认模型未配置")

        if parsed.action in {"lyrics", "lyrics_edit"}:
            if not parsed.prompt:
                if parsed.action == "lyrics_edit":
                    await music_cmd.finish(
                        "用法：/music lyrics edit [--title 标题] [--lyrics 现有歌词] <修改要求>\n"
                        "也可以回复一条歌词文本后发送该命令。"
                    )
                await music_cmd.finish("用法：/music lyrics [--title 标题] <主题或要求>")
            source_lyrics = parsed.lyrics or reply_text
            if parsed.action == "lyrics_edit" and not source_lyrics:
                await music_cmd.finish(
                    "歌词编辑模式需要现有歌词。可用 --lyrics 传入，或回复一条歌词文本后再发送命令。"
                )

            await music_cmd.send("正在生成歌词，请稍候…")
            try:
                lyric_result = await generate_lyrics(
                    default_music_model.provider,
                    parsed.prompt,
                    mode="edit" if parsed.action == "lyrics_edit" else "write_full_song",
                    lyrics=source_lyrics,
                    title=parsed.title,
                )
            except GenerationProviderError as exc:
                await music_cmd.finish(f"歌词生成失败：{exc}")
            except Exception as exc:
                await music_cmd.finish(f"歌词生成异常：{type(exc).__name__}: {exc}")

            heading = "歌词已生成" if parsed.action == "lyrics" else "歌词已编辑"
            await _send_lyrics_forward(bot, event, lyric_result, heading)
            await music_cmd.finish()

        if not rate_limiter.allow("music_gen", event.user_id, group_id=group_id):
            await music_cmd.finish("音乐生成过于频繁，请稍后再试")
        if not parsed.prompt:
            model_ids = list(music_generation.models)
            hint = (
                "用法：/music models | /music lyrics [--title 标题] <主题或要求> | "
                "/music lyrics edit [--title 标题] [--lyrics 现有歌词] <修改要求> | "
                "/music [模型] [--instrumental] [--title 标题] [--lyrics 歌词] <风格描述>"
            )
            reply_hint = "也可以回复一条歌词文本后直接发送 /music [模型] <风格描述>。"
            if len(model_ids) > 1:
                await music_cmd.finish(
                    f"{hint}\n可用模型：{'、'.join(model_ids)}（默认：{music_generation.default_model}）\n{reply_hint}"
                )
            await music_cmd.finish(f"{hint}\n{reply_hint}")

        source_lyrics = parsed.lyrics or reply_text
        if parsed.instrumental and source_lyrics:
            await music_cmd.finish("纯音乐模式不需要歌词，请去掉 --lyrics 或不要回复歌词文本。")

        await music_cmd.send("正在生成音乐，请稍候…")
        lyric_result = None
        prompt_for_music = parsed.prompt
        if not parsed.instrumental and not source_lyrics:
            try:
                lyric_result = await generate_lyrics(
                    default_music_model.provider,
                    parsed.prompt,
                    mode="write_full_song",
                    title=parsed.title,
                )
            except GenerationProviderError as exc:
                await music_cmd.finish(f"歌词生成失败：{exc}")
            except Exception as exc:
                await music_cmd.finish(f"歌词生成异常：{type(exc).__name__}: {exc}")
            source_lyrics = lyric_result.lyrics
            prompt_for_music = lyric_result.style_tags or parsed.prompt

        try:
            music_result = await generate_music(
                default_music_model.model_config,
                default_music_model.provider,
                prompt_for_music,
                lyrics=source_lyrics,
                instrumental=parsed.instrumental,
            )
        except GenerationProviderError as exc:
            await music_cmd.finish(f"音乐生成失败：{exc}")
        except Exception as exc:
            await music_cmd.finish(f"音乐生成异常：{type(exc).__name__}: {exc}")

        if lyric_result is not None:
            await _send_lyrics_forward(bot, event, lyric_result, "已自动生成歌词并开始谱曲")
        else:
            lines = [f"音乐已生成（模型：{default_music_model.id}）"]
            if parsed.instrumental:
                lines.append("模式：纯音乐")
            elif parsed.title:
                lines.append(f"标题：{parsed.title}")
            await music_cmd.send("\n".join(lines))

        await music_cmd.finish(Message([MessageSegment.record(BytesIO(music_result.audio_bytes))]))

    tieba_cmd = on_command("tieba", priority=10, block=True)

    @tieba_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tieba_cmd.finish("私聊不支持 /tieba")
        if not rule_switch.is_enabled(event.group_id, TIEBA_RULE_NAME):
            await tieba_cmd.finish("本群已关闭贴吧随机搬运功能")

        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "tieba")
        action, forum_keyword, text_only = _parse_tieba_command_args(args)

        if action == "random":
            if not rate_limiter.allow(TIEBA_RULE_NAME, event.user_id):
                await tieba_cmd.finish("贴吧搬运过于频繁，请稍后再试")
            try:
                thread = await tieba_service.get_random_thread(forum_keyword=forum_keyword)
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧搬运失败：{exc}")
            if thread is None:
                if tieba_service.is_login_required(forum_keyword):
                    await tieba_cmd.finish("贴吧登录态需要人工续签，请让管理员先运行 python dev/tools/tieba_login.py")
                if forum_keyword:
                    await tieba_cmd.finish(f"{forum_keyword}吧消息池为空，请稍后再试或让管理员执行 /tieba refresh {forum_keyword}")
                await tieba_cmd.finish("当前贴吧池为空，请稍后再试或让管理员执行 /tieba refresh")
            tieba_service.mark_sent(thread)
            stats_tracker.record_trigger(event.group_id, TIEBA_RULE_NAME)
            if text_only:
                await tieba_cmd.finish(tieba_service.build_thread_preview(thread))
            message = Message([MessageSegment.text(tieba_service.build_thread_preview(thread))])
            image_url = thread.cover_image_url or (thread.image_urls[0] if thread.image_urls else "")
            if image_url:
                message.append(MessageSegment.image(image_url))
            await tieba_cmd.finish(message)

        if action == "status":
            try:
                await tieba_cmd.finish(tieba_service.format_status(forum_keyword=forum_keyword))
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧状态读取失败：{exc}")

        if action == "source":
            try:
                await tieba_cmd.finish(tieba_service.format_sources(forum_keyword=forum_keyword))
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧来源读取失败：{exc}")

        if action == "refresh":
            if not _is_admin(event):
                await tieba_cmd.finish("仅管理员可执行此操作")
            try:
                target_forum = None if forum_keyword in {None, "", "all"} else forum_keyword
                result = await tieba_service.sync_now(force=True, forum_keyword=target_forum)
            except TiebaLoginRequiredError as exc:
                await tieba_cmd.finish(f"{exc}\n请运行 python dev/tools/tieba_login.py 续签登录态")
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧同步失败：{exc}")
            await tieba_cmd.finish(str(result["message"]))

        await tieba_cmd.finish(
            "贴吧命令用法：/tieba [贴吧名] | /tieba text [贴吧名] | "
            "/tieba status [贴吧名] | /tieba source [贴吧名] | /tieba refresh [贴吧名|all]"
        )

    reset_stats_cmd = on_command("reset_stats", priority=10, block=True)

    tieba_peek_cmd = on_command("tieba_peek", priority=10, block=True)

    @tieba_peek_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tieba_peek_cmd.finish("私聊不支持 /tieba_peek")
        if not _is_admin(event):
            await tieba_peek_cmd.finish("仅管理员可执行此操作")
        text = str(event.get_message()).strip()
        forum_keyword = _strip_command_name(text, "tieba_peek").strip()
        if not forum_keyword:
            await tieba_peek_cmd.finish("用法：/tieba_peek <贴吧名>")
        await tieba_peek_cmd.send(f"正在从 {forum_keyword}吧 现爬，请稍候…")
        try:
            thread = await tieba_service.peek_random_thread(forum_keyword)
        except TiebaLoginRequiredError:
            await tieba_peek_cmd.finish("贴吧登录态需要人工续签，请运行 python dev/tools/tieba_login.py")
        except TiebaServiceError as exc:
            await tieba_peek_cmd.finish(f"现爬失败：{exc}")
        if thread is None:
            await tieba_peek_cmd.finish(f"{forum_keyword}吧未找到有效帖子")
        message = Message([MessageSegment.text(tieba_service.build_thread_preview(thread))])
        image_url = thread.cover_image_url or (thread.image_urls[0] if thread.image_urls else "")
        if image_url:
            message.append(MessageSegment.image(image_url))
        await tieba_peek_cmd.finish(message)



    @reset_stats_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await reset_stats_cmd.finish("私聊不支持 /reset_stats")
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        stats_tracker.save(STATS_PATH)
        await reset_stats_cmd.finish("统计数据已重置")

    disable_cmd = on_command("disable", priority=10, block=True)

    @disable_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await disable_cmd.finish("私聊不支持 /disable")
        if not _is_admin(event):
            await disable_cmd.finish("仅管理员可执行此操作")
        rule_name = str(event.get_message()).strip().replace("/disable", "").strip()
        if not rule_name:
            await disable_cmd.finish("用法：/disable <rule_name>")
        if rule_switch.disable(event.group_id, rule_name):
            rule_switch.save(RULE_SWITCH_PATH)
            await disable_cmd.finish(f"已禁用规则：{rule_name}")
        await disable_cmd.finish(f"未知规则：{rule_name}")

    enable_cmd = on_command("enable", priority=10, block=True)

    @enable_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await enable_cmd.finish("私聊不支持 /enable")
        if not _is_admin(event):
            await enable_cmd.finish("仅管理员可执行此操作")
        rule_name = str(event.get_message()).strip().replace("/enable", "").strip()
        if not rule_name:
            await enable_cmd.finish("用法：/enable <rule_name>")
        if rule_switch.enable(event.group_id, rule_name):
            rule_switch.save(RULE_SWITCH_PATH)
            await enable_cmd.finish(f"已启用规则：{rule_name}")
        await enable_cmd.finish(f"未知规则：{rule_name}")

    rules_cmd = on_command("rules", priority=10, block=True)

    @rules_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await rules_cmd.finish("私聊不支持 /rules")
        await rules_cmd.finish(rule_switch.format_rules(event.group_id))

    remember_cmd = on_command("remember", priority=10, block=True)

    @remember_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await remember_cmd.finish("仅管理员可执行此操作")
        content = _strip_command_name(str(event.get_message()).strip(), "remember")
        if not content:
            await remember_cmd.finish("用法：/remember <要保存的记忆>")
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        memory_id = llm_service.remember_memory(chat_id, content, chat_type=chat_type)
        await remember_cmd.finish(f"已写入{_chat_label(event)}记忆 #{memory_id}")

    memories_cmd = on_command("memories", priority=10, block=True)

    @memories_cmd.handle()
    async def _(event):
        keyword = _strip_command_name(str(event.get_message()).strip(), "memories")
        reply = llm_service.format_memories(_chat_id(event), keyword=keyword or None, chat_type=_chat_type(event))
        await memories_cmd.finish(reply)

    forget_cmd = on_command("forget", priority=10, block=True)

    @forget_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_cmd.finish("仅管理员可执行此操作")
        keyword = _strip_command_name(str(event.get_message()).strip(), "forget")
        if not keyword:
            await forget_cmd.finish("用法：/forget <关键词>")
        deleted = llm_service.forget_memories(_chat_id(event), keyword, chat_type=_chat_type(event))
        await forget_cmd.finish(f"已删除{_chat_label(event)}中的 {deleted} 条记忆")

    forget_all_cmd = on_command("forget_all", priority=10, block=True)

    @forget_all_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_all_cmd.finish("仅管理员可执行此操作")
        deleted = llm_service.clear_memories(_chat_id(event), chat_type=_chat_type(event))
        await forget_all_cmd.finish(f"已清空{_chat_label(event)}全部长期记忆（共 {deleted} 条）")

    tell_cmd = on_command("tell", priority=10, block=True)

    @tell_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tell_cmd.finish("该命令仅支持群聊")
        to_user_id = None
        content_parts = []
        at_found = False
        for seg in event.get_message():
            seg_type = getattr(seg, "type", None)
            data = getattr(seg, "data", {})
            if seg_type == "at" and not at_found:
                qq = str(data.get("qq", "") or "").strip()
                if qq and qq != "all":
                    to_user_id = qq
                    at_found = True
            elif seg_type == "text" and at_found:
                part = str(data.get("text", "") or "").strip()
                if part:
                    content_parts.append(part)
        if not to_user_id:
            await tell_cmd.finish("用法：/tell @某人 <内容>")
        if str(to_user_id) == str(event.user_id):
            await tell_cmd.finish("不能给自己留言")
        content = " ".join(content_parts).strip()
        if not content:
            await tell_cmd.finish("留言内容不能为空")
        offline_message_store.add(
            group_id=event.group_id,
            from_user_id=event.user_id,
            from_sender_name=get_sender_name(event),
            to_user_id=to_user_id,
            content=content,
        )
        await tell_cmd.finish("留言已存，TA 下次发言时会收到")

    tells_cmd = on_command("tells", priority=10, block=True)

    @tells_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tells_cmd.finish("该命令仅支持群聊")
        pending = offline_message_store.list_pending_for(event.group_id, event.user_id)
        if not pending:
            await tells_cmd.finish("没有待接收的留言")
        lines = [f"有 {len(pending)} 条留言等着你："]
        for m in pending:
            lines.append(m.format_display())
        await tells_cmd.finish("\n".join(lines))

    untell_cmd = on_command("untell", priority=10, block=True)

    @untell_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await untell_cmd.finish("该命令仅支持群聊")
        to_user_id = offline_message_store.retract_latest(event.group_id, event.user_id)
        if to_user_id is None:
            await untell_cmd.finish("没有可撤回的留言")
        await untell_cmd.finish(f"已撤回最新留言（收件人：{to_user_id}）")

    roll_cmd = on_command("roll", priority=10, block=True)

    @roll_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "roll").strip() or "1d6"
        m = _DICE_RE.match(args)
        if not m:
            await roll_cmd.finish("用法：/roll [NdM]，例如 /roll 2d6 /roll d20")
        n = int(m.group(1) or 1)
        sides = int(m.group(2))
        if not 1 <= n <= 10:
            await roll_cmd.finish("骰子数量须在 1~10 之间")
        if not 2 <= sides <= 1000:
            await roll_cmd.finish("面数须在 2~1000 之间")
        results = [random.randint(1, sides) for _ in range(n)]
        if n == 1:
            await roll_cmd.finish(f"🎲 {results[0]}")
        detail = " + ".join(str(r) for r in results)
        await roll_cmd.finish(f"🎲 {detail} = {sum(results)}")

    choose_cmd = on_command("choose", priority=10, block=True)

    @choose_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "choose").strip()
        if not args:
            await choose_cmd.finish("用法：/choose A B C")
        try:
            options = _safe_shlex_split(args)
        except ValueError:
            options = args.split()
        if len(options) < 2:
            await choose_cmd.finish("至少需要两个选项")
        await choose_cmd.finish(f"选择了：{random.choice(options)}")

    fortune_cmd = on_command("fortune", priority=10, block=True)

    @fortune_cmd.handle()
    async def _(event):
        grade, desc = _daily_fortune(event.user_id)
        await fortune_cmd.finish(f"今日运势：{grade}\n{desc}")

    vote_cmd = on_command("vote", priority=10, block=True)

    @vote_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "vote").strip()
        if not args:
            await vote_cmd.finish('用法：/vote "议题" 选项A 选项B ...')
        try:
            parts = _safe_shlex_split(args)
        except ValueError:
            parts = args.split()
        if len(parts) < 3:
            await vote_cmd.finish('用法：/vote "议题" 选项A 选项B（至少两个选项）')
        topic, options = parts[0], parts[1:]
        if len(options) > 9:
            await vote_cmd.finish("选项最多 9 个")
        lines = [f"📊 {topic}"]
        for i, opt in enumerate(options):
            lines.append(f"{_NUMBER_EMOJIS[i]} {opt}")
        await vote_cmd.finish("\n".join(lines))

    profile_cmd = on_command("profile", priority=10, block=True)

    @profile_cmd.handle()
    async def _(bot, event):
        if _is_private_chat(event):
            await profile_cmd.finish("该命令仅支持群聊")
        if not llm_service.config.is_available:
            await profile_cmd.finish("LLM 功能未启用，无法生成人物志")

        target_user_id = None
        for seg in event.get_message():
            seg_type = getattr(seg, "type", None)
            data = getattr(seg, "data", {})
            if seg_type == "at":
                qq = str(data.get("qq", "") or "").strip()
                if qq and qq != "all":
                    target_user_id = qq
                    break
        if not target_user_id:
            m = re.search(r"\[CQ:at,qq=(\d+)\]", str(event.get_message()))
            if m:
                target_user_id = m.group(1)
        if not target_user_id:
            await profile_cmd.finish("用法：/profile [short|middle|long|full] @某人")

        group_id = event.group_id
        profile_mode = _parse_profile_mode(str(event.get_message()))
        group_stats = stats_tracker.get_stats(group_id)
        target_name = group_stats.user_names.get(str(target_user_id), f"QQ:{target_user_id}")
        msg_count = group_stats.user_messages.get(str(target_user_id), 0)

        settings = llm_service.get_chat_settings(group_id, chat_type="group")
        provider_id = settings.provider_id or llm_service.config.runtime.default_provider or ""
        provider = llm_service.config.providers.get(provider_id)
        if not provider:
            await profile_cmd.finish("LLM provider 未配置")
        effective_model = settings.model or provider.default_model

        persona_id = settings.persona_id or llm_service.config.runtime.default_persona or ""
        persona = llm_service.config.personas.get(persona_id) if persona_id else None
        system_parts = []
        if persona:
            if persona.system_prompt:
                system_parts.append(persona.system_prompt)
            if persona.style_prompt:
                system_parts.append(persona.style_prompt)
        if provider.style_overrides:
            system_parts.append(provider.style_overrides)
        system_prompt = "\n\n".join(system_parts)

        now = time()
        try:
            memories_raw, all_msgs = await asyncio.gather(
                asyncio.to_thread(
                    llm_service.store.search_memories,
                    str(group_id),
                    user_id=str(target_user_id),
                    query=target_name,
                    limit=profile_mode.memory_limit,
                    scope="user",
                ),
                asyncio.to_thread(daily_collector.read_all, group_id)
                if profile_mode.full_records
                else asyncio.to_thread(
                    daily_collector.read_window,
                    group_id,
                    now - (profile_mode.read_days or 7) * 86400,
                    now,
                ),
            )
        except Exception:
            logger.exception("profile data collection failed for group=%s user=%s", group_id, target_user_id)
            await profile_cmd.finish("收集用户数据时出错，请稍后重试")

        memories = [m["content"] for m in memories_raw if m.get("content")]
        samples = _select_profile_samples(
            all_msgs,
            str(target_user_id),
            limit=profile_mode.sample_limit,
            max_chars=profile_mode.sample_max_chars,
        )

        await profile_cmd.send(f"正在生成 {target_name} 的{profile_mode.label}人物志，请稍候…")
        try:
            text, _ = await generate_profile(
                target_name=target_name,
                message_count=msg_count,
                memories=memories,
                recent_samples=samples,
                llm_config=llm_service.config,
                system_prompt=system_prompt,
                provider_id=provider.id,
                model=effective_model,
                profile_mode=profile_mode,
            )
        except LLMProviderError as exc:
            await profile_cmd.finish(f"人物志生成失败：{exc}")
        await send_long_group_message(
            bot,
            int(group_id),
            f"👤 {target_name}\n\n{text}",
            node_name="人物志",
            log_name="profile",
        )
        return

    find_cmd = on_command("find", priority=10, block=True)

    @find_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await find_cmd.finish("该命令仅支持群聊")
        keyword = _strip_command_name(str(event.get_message()).strip(), "find").strip()
        if not keyword:
            await find_cmd.finish("用法：/find <关键词>")
        group_id = event.group_id
        now = time()
        messages = await asyncio.to_thread(
            daily_collector.read_window, group_id, now - 30 * 86400, now
        )
        kw_lower = keyword.lower()
        hits = [m for m in messages if kw_lower in m.get("text", "").lower()]
        if not hits:
            await find_cmd.finish(f"没有找到包含「{keyword}」的消息（最近 30 天）")
        shown = hits[-5:]
        header = f"找到 {len(hits)} 条，显示最新 5 条：" if len(hits) > 5 else f"找到 {len(hits)} 条："
        lines = [header]
        for m in shown:
            ts = datetime.fromtimestamp(m["ts"]).strftime("%m-%d %H:%M")
            text = m.get("text", "")
            if len(text) > 50:
                text = text[:50] + "…"
            lines.append(f"[{ts}] {m['sender']}: {text}")
        await find_cmd.finish("\n".join(lines))

    quote_cmd = on_command("quote", priority=10, block=True)

    @quote_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await quote_cmd.finish("该命令仅支持群聊")
        group_id = event.group_id
        args = _strip_command_name(str(event.get_message()).strip(), "quote").strip()
        reply = getattr(event, "reply", None)
        if args.lower() == "random" or (not args and not reply):
            q = group_quote_store.random(group_id)
            if q is None:
                await quote_cmd.finish("语录库还是空的，引用一条消息发 /quote 来收藏吧")
            ts = datetime.fromtimestamp(q["saved_at"]).strftime("%m-%d")
            await quote_cmd.finish(f"「{q['content']}」\n—— {q['quoted_sender_name']} ({ts})")
        if not reply:
            await quote_cmd.finish("用法：引用一条消息后发 /quote 收藏；/quote random 随机一条")
        rendered = render_reply_for_llm(
            reply,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
        )
        if not rendered or not rendered.text.strip():
            await quote_cmd.finish("引用的消息没有文字内容，无法收藏")
        content = rendered.text.strip()
        if len(content) > 500:
            await quote_cmd.finish("内容过长（限 500 字），无法收藏")
        group_quote_store.add(
            group_id=group_id,
            quoted_user_id=rendered.user_id or "",
            quoted_sender_name=rendered.sender_name or "未知",
            content=content,
            saved_by_user_id=event.user_id,
        )
        total = group_quote_store.count(group_id)
        preview = content[:30] + ("…" if len(content) > 30 else "")
        await quote_cmd.finish(f"已收藏「{preview}」（本群共 {total} 条语录）")

    reload_rules_cmd = on_command("reload_rules", priority=10, block=True)

    @reload_rules_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await reload_rules_cmd.finish("仅管理员可执行此操作")
        try:
            summary = reload_chat_rules_pipeline()
        except Exception as exc:
            await reload_rules_cmd.finish(f"chat_rules 重载失败：{exc}")
        await reload_rules_cmd.finish(
            "chat_rules 已重载（"
            f"text {summary['text_rules']} / "
            f"context {summary['context_rules']} / "
            f"chain {summary['chain_games']} / "
            f"rate_limit {summary['rate_limit_rules']}）"
        )

    reload_personas_cmd = on_command("reload_personas", priority=10, block=True)

    @reload_personas_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await reload_personas_cmd.finish("仅管理员可执行此操作")
        count, error = llm_service.reload_personas()
        if error:
            await reload_personas_cmd.finish(f"人格重载失败：{error}")
        default_persona = llm_service.config.runtime.default_persona or "(未配置)"
        await reload_personas_cmd.finish(
            f"人格已重载（{count} 个，默认：{default_persona}）"
        )

    game_cmd = on_command("game", priority=10, block=True)

    @game_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await game_cmd.finish("该命令仅支持群聊")
        group_id = str(event.group_id)
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "game").strip()
        tokens = args.split()
        sub = tokens[0].lower() if tokens else ""

        if sub == "list":
            games = game_registry.list_games()
            if not games:
                await game_cmd.finish("暂无可用游戏")
            lines = ["可用游戏："]
            for g in games:
                aliases_str = f"（别名：{'、'.join(g['aliases'])}）" if g["aliases"] else ""
                lines.append(f"- {g['name']} {aliases_str}")
            await game_cmd.finish("\n".join(lines))

        if sub == "start":
            raw_args = args[len(tokens[0]):].strip() if len(tokens) > 1 else ""
            if not raw_args:
                await game_cmd.finish("用法：/game start <游戏名>，使用 /game list 查看可用游戏")
            # Split into game name and optional argument (e.g. "21点 500" → "21点", "500")
            parts = raw_args.split(maxsplit=1)
            game_name = parts[0]
            start_arg = parts[1] if len(parts) > 1 else ""
            game = game_registry.find(game_name)
            if game is None:
                await game_cmd.finish(f"未找到游戏：{game_name}，使用 /game list 查看可用游戏")
            active_name = game_registry.get_active_game_name(group_id)
            if active_name:
                await game_cmd.finish(f"本群已有进行中的游戏：{active_name}，请先 /game stop 结束")
            opening = game_registry.start_game(group_id, str(event.user_id), game, start_arg=start_arg)
            if opening is None:
                await game_cmd.finish(f"本群已有进行中的游戏：{game_registry.get_active_game_name(group_id)}，请先 /game stop 结束")
            await game_cmd.finish(opening)

        if sub == "stop":
            active_name = game_registry.get_active_game_name(group_id)
            if not active_name:
                await game_cmd.finish("本群没有进行中的游戏")
            closing = game_registry.stop_game(group_id)
            if closing is None:
                await game_cmd.finish(f"无法结束游戏：{active_name}")
            await game_cmd.finish(closing)

        if sub == "score":
            game_name = args[len(tokens[0]):].strip() if len(tokens) > 1 else ""
            if not game_name:
                await game_cmd.finish("用法：/game score <游戏名>，使用 /game list 查看可用游戏")
            game = game_registry.find(game_name)
            if game is None:
                await game_cmd.finish(f"未找到游戏：{game_name}，使用 /game list 查看可用游戏")
            leaderboard = game_scores.get_leaderboard(group_id, game.name, top_n=10)
            if not leaderboard:
                await game_cmd.finish(f"{game.name} 暂无排行数据")
            lines = [f"{game.name} 排行榜（前 {len(leaderboard)} 名）："]
            for i, (uid, score) in enumerate(leaderboard, 1):
                lines.append(f"{i}. QQ:{uid} — {score} 胜")
            await game_cmd.finish("\n".join(lines))

        # No valid subcommand
        await game_cmd.finish(
            "游戏命令用法：\n"
            "/game list — 查看可用游戏\n"
            "/game start <游戏名> — 开始游戏\n"
            "/game stop — 结束当前游戏\n"
            "/game score <游戏名> — 查看排行榜"
        )

    sign_cmd = on_command("sign", aliases={"签到"}, priority=10, block=True)

    @sign_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await sign_cmd.finish("私聊不支持签到")
        result = game_economy.sign_in(str(event.user_id), str(event.group_id))
        lines = [
            result["message"],
            f"金币：{result['total_gold']} | 好感度：{result['total_affection']}",
        ]
        if result["streak"] > 1:
            lines.append(f"连续签到：{result['streak']} 天")
        await sign_cmd.finish("\n".join(lines))

    gold_cmd = on_command("gold", aliases={"金币", "我的"}, priority=10, block=True)

    @gold_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await gold_cmd.finish("私聊不支持此命令")
        balance = game_economy.get_balance(str(event.user_id), str(event.group_id))
        lines = [
            f"💰 金币：{balance['gold']}",
            f"💗 好感度：{balance['affection']}",
            f"🔥 连续签到：{balance['sign_streak']} 天",
        ]
        await gold_cmd.finish("\n".join(lines))

    gold_rank_cmd = on_command("gold_rank", aliases={"金币排行"}, priority=10, block=True)

    @gold_rank_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await gold_rank_cmd.finish("私聊不支持此命令")
        rank = game_economy.get_rank(str(event.group_id), top_n=10)
        if not rank:
            await gold_rank_cmd.finish("本群暂无金币数据，快去签到吧！")
        lines = ["🏆 本群金币排行："]
        for i, entry in enumerate(rank, 1):
            lines.append(f"{i}. QQ:{entry['user_id']} — {entry['gold']} 💰")
        await gold_rank_cmd.finish("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # 牛牛大作战 commands
    # ═══════════════════════════════════════════════════════════════

    nn_register = on_command("注册牛牛", priority=10, block=True)

    @nn_register.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_register.finish("私聊不支持此命令")
        uid = str(event.user_id)
        if niuniu_store.exists(uid):
            length = niuniu_store.get_length(uid)
            await nn_register.finish(f"你已经有过牛牛啦！当前长度 {length} cm")
        length = niuniu_store.register(uid)
        if length > 0:
            await nn_register.finish(f"牛牛长出来啦！足足有 {length} cm 呢！")
        else:
            await nn_register.finish(
                f"牛牛长出来了？牛牛不见了！你是个可爱的女孩子！！深度足足有 {abs(length)} cm 呢！"
            )

    nn_unsubscribe = on_command("注销牛牛", priority=10, block=True)

    @nn_unsubscribe.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_unsubscribe.finish("私聊不支持此命令")
        uid = str(event.user_id)
        length = niuniu_store.get_length(uid)
        if length is None:
            await nn_unsubscribe.finish("你还没有牛牛呢！请发送 注册牛牛 领取你的牛牛！")
        balance = game_economy.get_balance(uid, str(event.group_id))
        if balance["gold"] < niuniu_store.config.unsubscribe_gold:
            await nn_unsubscribe.finish(
                f"你的金币不足 {niuniu_store.config.unsubscribe_gold}，无法注销牛牛！（当前 {balance['gold']} 金币）"
            )
        game_economy.deduct_gold(uid, str(event.group_id), niuniu_store.config.unsubscribe_gold)
        niuniu_store.unsubscribe(uid)
        await nn_unsubscribe.finish("从今往后你就没有牛牛啦！")

    nn_my = on_command("我的牛牛", priority=10, block=True)

    @nn_my.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_my.finish("私聊不支持此命令")
        uid = str(event.user_id)
        length = niuniu_store.get_length(uid)
        if length is None:
            await nn_my.finish("你还没有牛牛呢！请发送 注册牛牛 领取你的牛牛！")
        rank = niuniu_store.get_rank_position(uid)
        rank_str = f"第 {rank} 名" if rank > 0 else "未上榜（深度状态）"
        last_glue = niuniu_store.latest_record_time(uid, "gluing")
        lines = [
            "🐂 我的牛牛",
            f"当前长度：{length} cm",
            f"排名：{rank_str}",
            f"最后打胶：{last_glue}",
            f"评价：{_comment(length)}",
        ]
        await nn_my.finish("\n".join(lines))

    nn_glue = on_command("打胶", priority=10, block=True)

    @nn_glue.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_glue.finish("私聊不支持此命令")
        uid = str(event.user_id)
        remaining = _check_cd(_glue_cd, uid)
        if remaining > 0:
            tips = [
                f"不行不行，你的身体会受不了的，歇 {int(remaining)}s 再来吧",
                f"休息一下吧，会炸膛的！{int(remaining)}s 后再来吧",
            ]
            await nn_glue.finish(random.choice(tips))
        msg, _ = gluing(niuniu_store, uid)
        await nn_glue.finish(msg)

    nn_fence = on_command("击剑", aliases={"jj", "JJ", "Jj", "jJ"}, priority=10, block=True)

    @nn_fence.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_fence.finish("私聊不支持此命令")
        uid = str(event.user_id)

        # CD check
        remaining = _check_cd(_fence_cd, uid)
        if remaining > 0:
            tips = [
                f"不行不行，你的身体会受不了的，歇 {int(remaining)}s 再来吧",
                f"你这种男同就应该被送去集中营！等待 {int(remaining)}s 再来吧",
                f"打咩哟！你的牛牛会炸的，休息 {int(remaining)}s 再来吧",
            ]
            await nn_fence.finish(random.choice(tips))

        # Extract @target
        target_uid = None
        at_found = False
        for seg in event.get_message():
            seg_type = getattr(seg, "type", None)
            data = getattr(seg, "data", {})
            if seg_type == "at" and not at_found:
                qq = str(data.get("qq", "") or "").strip()
                if qq and qq != "all":
                    target_uid = qq
                    at_found = True
        if not target_uid:
            await nn_fence.finish("你要和谁击剑？请 @一位用户")

        if target_uid == uid:
            await nn_fence.finish("不能和自己击剑哦！")

        # Check defender CD
        remaining = _check_cd(_fenced_cd, target_uid)
        if remaining > 0:
            tips = [
                f"对方刚被击剑过，需要休息 {int(remaining)}s 才能再次被击剑",
                f"对方牛牛还在恢复中，{int(remaining)}s 后再来吧",
            ]
            await nn_fence.finish(random.choice(tips))

        result = fencing(niuniu_store, uid, target_uid)
        await nn_fence.finish(result)

    def _build_rank_text(entries: list[dict], title: str, unit: str = "cm") -> str:
        if not entries:
            return f"{title}\n暂无数据…"
        lines = [f"🏆 {title}："]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. QQ:{e['uid']} — {e['length']} {unit}")
        return "\n".join(lines)

    nn_len_rank = on_command("牛牛长度排行", priority=10, block=True)

    @nn_len_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_len_rank.finish("私聊不支持此命令，请使用 牛牛长度总排行")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛长度排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_length(limit=n)
        await nn_len_rank.finish(_build_rank_text(entries, "牛牛长度排行"))

    nn_len_rank_all = on_command("牛牛长度总排行", priority=10, block=True)

    @nn_len_rank_all.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛长度总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_length(limit=n)
        await nn_len_rank_all.finish(_build_rank_text(entries, "牛牛长度总排行（全局）"))

    nn_depth_rank = on_command("牛牛深度排行", priority=10, block=True)

    @nn_depth_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_depth_rank.finish("私聊不支持此命令，请使用 牛牛深度总排行")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛深度排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_depth(limit=n)
        await nn_depth_rank.finish(_build_rank_text(entries, "牛牛深度排行"))

    nn_depth_rank_all = on_command("牛牛深度总排行", priority=10, block=True)

    @nn_depth_rank_all.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛深度总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_depth(limit=n)
        await nn_depth_rank_all.finish(_build_rank_text(entries, "牛牛深度总排行（全局）"))

    nn_records = on_command("我的牛牛战绩", priority=10, block=True)

    @nn_records.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_records.finish("私聊不支持此命令")
        uid = str(event.user_id)
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "我的牛牛战绩").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        records = niuniu_store.get_records(uid, limit=n)
        if not records:
            await nn_records.finish("你还没有任何牛牛战绩哦~")
        action_labels = {
            "register": "📝 注册",
            "unsubscribe": "❌ 注销",
            "gluing": "💦 打胶",
            "fencing": "⚔️ 击剑（主动）",
            "fenced": "🎯 被击剑",
        }
        lines = ["📋 我的牛牛战绩："]
        for r in records:
            act = action_labels.get(r["action"], r["action"])
            diff = r["diff"]
            sign = "+" if diff > 0 else ""
            lines.append(f"{act} | {r['origin_length']} → {r['new_length']} ({sign}{diff}) | {r['created_at']}")
        await nn_records.finish("\n".join(lines))
