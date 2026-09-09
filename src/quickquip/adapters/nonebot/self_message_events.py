"""LLOneBot reportSelfMessage 自消息事件模型。

LLOneBot 开启 ``reportSelfMessage`` 后，bot 自身发言以
``post_type="message_sent"`` 上报（OneBot 11 扩展；LLOneBot 源码中
``senderUin === selfUin`` 时取 ``EventType.MESSAGE_SENT``）。
nonebot-adapter-onebot v11 未内置该模型：事件会落到兜底 ``Event``。

此处注册同构模型并保留独立的 ``message_sent`` 事件类型，再由专用
matcher 在普通消息和命令 matcher 之前处理。群自消息仅入归档（bot
也是群聊参与者），私聊自消息直接丢弃；两者都不进入命令、规则、
统计或 LLM 链路。

部署前提：LLOneBot ob11 连接配置 ``reportSelfMessage: true``
（默认 false，需运维开启后重启 llbot）。
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "GroupMessageSentEvent",
    "PrivateMessageSentEvent",
    "register_self_message_events",
    "register_self_message_matcher",
]

try:
    from nonebot.adapters.onebot.v11 import Adapter
    from nonebot.adapters.onebot.v11.event import (
        GroupMessageEvent,
        PrivateMessageEvent,
    )

    _ADAPTER_AVAILABLE = True
except ModuleNotFoundError:  # 本地工具环境无 nonebot
    _ADAPTER_AVAILABLE = False


if _ADAPTER_AVAILABLE:

    class GroupMessageSentEvent(GroupMessageEvent):
        """bot 自身群消息（post_type=message_sent，message_type=group）。"""

        post_type: Literal["message_sent"]

        def get_type(self) -> str:
            return "message_sent"

    class PrivateMessageSentEvent(PrivateMessageEvent):
        """bot 自身私聊消息（post_type=message_sent，message_type=private）。"""

        post_type: Literal["message_sent"]

        def get_type(self) -> str:
            return "message_sent"


def register_self_message_events() -> bool:
    """向 OneBot V11 适配器注册自消息事件模型；无 nonebot 环境时返回 False。"""
    if not _ADAPTER_AVAILABLE:
        return False
    Adapter.add_custom_model(GroupMessageSentEvent, PrivateMessageSentEvent)
    return True


def register_self_message_matcher(on_type, archive_group_message):
    """优先处理自消息，避免命令和普通消息 matcher 看到事件。"""
    if not _ADAPTER_AVAILABLE:
        return None

    matcher = on_type(
        (GroupMessageSentEvent, PrivateMessageSentEvent),
        priority=1,
        block=True,
    )

    @matcher.handle()
    async def _(event):
        if isinstance(event, GroupMessageSentEvent):
            archive_group_message(event)

    return matcher
