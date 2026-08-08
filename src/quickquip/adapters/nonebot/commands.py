from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import (
    _format_tts_models as _format_tts_models,
    _format_voice_groups as _format_voice_groups,
    _parse_music_args as _parse_music_args,
    _parse_profile_mode as _parse_profile_mode,
    _parse_tts_args as _parse_tts_args,
    _select_profile_samples as _select_profile_samples,
)
from quickquip.adapters.nonebot.command_parts.games import register_games_commands
from quickquip.adapters.nonebot.command_parts.history import register_history_commands
from quickquip.adapters.nonebot.command_parts.llm import register_llm_commands
from quickquip.adapters.nonebot.command_parts.media import register_media_commands
from quickquip.adapters.nonebot.command_parts.memory import register_memory_commands
from quickquip.adapters.nonebot.command_parts.niuniu import register_niuniu_commands
from quickquip.adapters.nonebot.command_parts.rules import register_rules_commands
from quickquip.adapters.nonebot.command_parts.session import register_session_commands
from quickquip.adapters.nonebot.command_parts.sts import register_sts_commands
from quickquip.adapters.nonebot.command_parts.tieba import register_tieba_commands
from quickquip.adapters.nonebot.command_parts.utility import register_utility_commands


def register_commands(on_command, Message, MessageSegment) -> None:
    register_session_commands(on_command, Message, MessageSegment)
    register_sts_commands(on_command, Message, MessageSegment)
    register_llm_commands(on_command, Message, MessageSegment)
    register_media_commands(on_command, Message, MessageSegment)
    register_tieba_commands(on_command, Message, MessageSegment)
    register_rules_commands(on_command, Message, MessageSegment)
    register_memory_commands(on_command, Message, MessageSegment)
    register_utility_commands(on_command, Message, MessageSegment)
    register_history_commands(on_command, Message, MessageSegment)
    register_games_commands(on_command, Message, MessageSegment)
    register_niuniu_commands(on_command, Message, MessageSegment)
