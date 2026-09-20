from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
import shlex
from typing import Any

from quickquip.common.event_utils import strip_command_name as _strip_command_name
from quickquip.llm.profile import DEFAULT_PROFILE_MODE, PROFILE_MODES, ProfileModeConfig


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


_PRESET_RE = re.compile(
    r'--preset\s+(?:"((?:[^"\\]|\\.)*)"|'
    r'\'((?:[^\'\\]|\\.)*)\''
    r'|(\S.*))',
    re.DOTALL,
)
_RESUME_RE = re.compile(r'--resume(?:\s+(\d+))?')
_DICE_RE = re.compile(r"^(\d*)[dD](\d+)$")
_DRAW_SIZE_RE = re.compile(r'--size\s+(\d+x\d+)', re.IGNORECASE)
_DRAW_QUALITY_RE = re.compile(r'--quality\s+(\S+)', re.IGNORECASE)
# qq 数字后收尾放宽为 `,` 或 `]`：LLOneBot 的 at 码带 name= 扩展键，
# 只认裸 `qq=数字]` 会漏掉全部 @ 目标。
_AT_TARGET_RE = re.compile(r"\[CQ:at,qq=(\d+)[,\]]")


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


def _raw_message_text(event) -> str:
    """event 的原始 CQ 文本；raw_message 缺失或为空时用段序列化兜底。"""
    return getattr(event, "raw_message", None) or str(event.get_message())


def _extract_at_target(raw: str | None, segments: Iterable[Any] | None) -> str | None:
    """提取消息里第一个被 @ 的普通用户 QQ 号，@全体不算目标。

    段解析优先：指向 bot 自身的 at 段会被 NoneBot 的 to_me 识别从
    get_message() 里剥掉，剩下的段恰好是用户指向他人的目标（如
    「@bot /profile @某人」应取某人）。段里已无 at 时（如「/击剑 @bot」
    只有 self-@ 被剥空）回退 raw_message 的 CQ 码，那是被剥掉的
    self-@ 的唯一残留来源。
    """
    for seg in segments or ():
        seg_type = getattr(seg, "type", None)
        data = getattr(seg, "data", {})
        if seg_type == "at":
            qq = str(data.get("qq", "") or "").strip()
            if qq and qq != "all":
                return qq
    if raw:
        m = _AT_TARGET_RE.search(raw)
        if m:
            return m.group(1)
    return None


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
