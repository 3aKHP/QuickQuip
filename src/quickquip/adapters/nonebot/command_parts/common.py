"""Re-export shim for legacy ``command_parts.common`` import paths.

历史上所有命令处理辅助函数都堆在这个模块（~470 行的杂物模块）。
现按主题拆分到 ``_chat_utils`` / ``_fortune`` / ``_content`` / ``_parsing`` / ``_formatting``
五个子模块，本文件仅做 re-export，保持现有调用方零改动。

新代码应直接从各子模块 import，不要从本文件 import。
"""

from __future__ import annotations

# ── chat utils ───────────────────────────────────────────────────────────────
from quickquip.adapters.nonebot.command_parts._chat_utils import _allow_scope_management as _allow_scope_management  # noqa: F401
from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_id as _chat_id  # noqa: F401
from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_label as _chat_label  # noqa: F401
from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_type as _chat_type  # noqa: F401
from quickquip.adapters.nonebot.command_parts._chat_utils import _is_admin as _is_admin  # noqa: F401
from quickquip.adapters.nonebot.command_parts._chat_utils import _is_private_chat as _is_private_chat  # noqa: F401

# ── fortune ──────────────────────────────────────────────────────────────────
from quickquip.adapters.nonebot.command_parts._fortune import _daily_fortune as _daily_fortune  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _evaluate_luck as _evaluate_luck  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _fence_luck_tips as _fence_luck_tips  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _FORTUNES as _FORTUNES  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _glue_luck_tips as _glue_luck_tips  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _luck_lookup as _luck_lookup  # noqa: F401
from quickquip.adapters.nonebot.command_parts._fortune import _NUMBER_EMOJIS as _NUMBER_EMOJIS  # noqa: F401

# ── content ──────────────────────────────────────────────────────────────────
from quickquip.adapters.nonebot.command_parts._content import _extract_image_urls as _extract_image_urls  # noqa: F401
from quickquip.adapters.nonebot.command_parts._content import _resolve_forward_content as _resolve_forward_content  # noqa: F401
from quickquip.adapters.nonebot.command_parts._content import _resolve_message_content as _resolve_message_content  # noqa: F401

# ── parsing ──────────────────────────────────────────────────────────────────
from quickquip.adapters.nonebot.command_parts._parsing import _DICE_RE as _DICE_RE  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _DRAW_QUALITY_RE as _DRAW_QUALITY_RE  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _DRAW_SIZE_RE as _DRAW_SIZE_RE  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_music_args as _parse_music_args  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_preset as _parse_preset  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_profile_mode as _parse_profile_mode  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_resume as _parse_resume  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_tieba_command_args as _parse_tieba_command_args  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _parse_tts_args as _parse_tts_args  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _PRESET_RE as _PRESET_RE  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _RESUME_RE as _RESUME_RE  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _safe_shlex_split as _safe_shlex_split  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _select_profile_samples as _select_profile_samples  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import _strip_leading_command_token as _strip_leading_command_token  # noqa: F401
from quickquip.adapters.nonebot.command_parts._parsing import MusicCommandArgs as MusicCommandArgs  # noqa: F401
# _strip_command_name 改为从 common.event_utils 直接 re-export（修 v1.8.9 PR-6 跨层遗留）
from quickquip.common.event_utils import strip_command_name as _strip_command_name  # noqa: F401

# ── formatting ───────────────────────────────────────────────────────────────
from quickquip.adapters.nonebot.command_parts._formatting import _chunk_text as _chunk_text  # noqa: F401
from quickquip.adapters.nonebot.command_parts._formatting import _format_generated_lyrics as _format_generated_lyrics  # noqa: F401
from quickquip.adapters.nonebot.command_parts._formatting import _format_music_models as _format_music_models  # noqa: F401
from quickquip.adapters.nonebot.command_parts._formatting import _format_tts_models as _format_tts_models  # noqa: F401
from quickquip.adapters.nonebot.command_parts._formatting import _format_voice_groups as _format_voice_groups  # noqa: F401
from quickquip.adapters.nonebot.command_parts._formatting import _send_lyrics_forward as _send_lyrics_forward  # noqa: F401
