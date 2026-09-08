"""LLOneBot reportSelfMessage 自消息事件模型。

LLOneBot 开启 ``reportSelfMessage`` 后，bot 自身发言以
``post_type="message_sent"`` 上报（OneBot 11 扩展；LLOneBot 源码中
``senderUin === selfUin`` 时取 ``EventType.MESSAGE_SENT``）。
nonebot-adapter-onebot v11 未内置该模型：事件会落到兜底 ``Event``，
``get_type()`` 回报 ``"message_sent"``，``on_message`` 永不派发。

此处注册同构模型：继承既有群/私聊 MessageEvent，仅收窄 ``post_type``
字面量并覆写 ``get_type()`` 回报 ``"message"``，使消息管线照常收到
自消息，再由 group_messages / private_messages 的 ``is_self_message``
守卫分流——群自消息仅入归档（bot 也是群聊参与者），不进触发/统计
/唤醒链路。

部署前提：LLOneBot ob11 连接配置 ``reportSelfMessage: true``
（默认 false，需运维开启后重启 llbot）。
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "GroupMessageSentEvent",
    "PrivateMessageSentEvent",
    "register_self_message_events",
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
            # 回报 "message" 让 on_message 管线照常派发，
            # 自消息身份由 is_self_message（user_id == self_id）识别。
            return "message"

    class PrivateMessageSentEvent(PrivateMessageEvent):
        """bot 自身私聊消息（post_type=message_sent，message_type=private）。"""

        post_type: Literal["message_sent"]

        def get_type(self) -> str:
            return "message"


def register_self_message_events() -> bool:
    """向 OneBot V11 适配器注册自消息事件模型；无 nonebot 环境时返回 False。"""
    if not _ADAPTER_AVAILABLE:
        return False
    Adapter.add_custom_model(GroupMessageSentEvent, PrivateMessageSentEvent)
    return True
