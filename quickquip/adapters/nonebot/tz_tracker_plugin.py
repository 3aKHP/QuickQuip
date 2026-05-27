from __future__ import annotations

try:
    import nonebot
    from nonebot import on_command, on_message, on_notice
    from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
except ModuleNotFoundError:
    nonebot = None
    Bot = None
    on_command = None
    on_message = None
    on_notice = None
    Message = None
    MessageSegment = None

from quickquip.adapters.nonebot.trace import traced_on_command
from quickquip.adapters.nonebot.commands import register_commands
from quickquip.adapters.nonebot.daily_briefing_plugin import setup as setup_daily_briefing
from quickquip.adapters.nonebot.daily_summary_plugin import setup as setup_daily_summary
from quickquip.adapters.nonebot.wordcloud_plugin import setup as setup_wordcloud
from quickquip.adapters.nonebot.awakening_plugin import setup as setup_awakening
from quickquip.adapters.nonebot.group_messages import register_message_matcher
from quickquip.adapters.nonebot.private_messages import register_private_message_matcher
from quickquip.adapters.nonebot.recall_handler import register_recall_handlers
from quickquip.adapters.nonebot.lifecycle import register_lifecycle
from quickquip.common.bot_action_trace import install_nonebot_api_trace_hook


matcher = None
private_matcher = None

if nonebot is not None:
    if Bot is not None:
        install_nonebot_api_trace_hook(Bot)
    try:
        driver = nonebot.get_driver()
    except ValueError:
        driver = None
        on_message = None
        on_command = None

    if driver is not None:
        register_lifecycle(driver)

if on_message is not None:
    matcher = register_message_matcher(on_message, Message, MessageSegment)
    private_matcher = register_private_message_matcher(on_message)

if on_command is not None:
    traced_command = traced_on_command(on_command)
    register_commands(traced_command, Message, MessageSegment)
    setup_daily_briefing(traced_command)
    setup_daily_summary(traced_command)
    setup_wordcloud(traced_command)
    setup_awakening(traced_command)

if on_notice is not None:
    recall_matcher = register_recall_handlers(on_notice)
