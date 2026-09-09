"""self_message_events 单测：LLOneBot message_sent 载荷可解析并按消息派发。

钉住的契约：reportSelfMessage 开启后 LLOneBot 以 post_type="message_sent"
上报自身发言；注册自定义模型后，事件应解析为 GroupMessageSentEvent /
PrivateMessageSentEvent、get_type() 回报 "message_sent"（只由专用 matcher
派发）、is_self_message 可识别（user_id == self_id）。
"""

from __future__ import annotations

from quickquip.adapters.nonebot.self_message_events import (
    GroupMessageSentEvent,
    PrivateMessageSentEvent,
    register_self_message_events,
)
from quickquip.common.event_utils import is_self_message


def _group_payload() -> dict:
    return {
        "post_type": "message_sent",
        "message_type": "group",
        "sub_type": "normal",
        "time": 1_700_000_000,
        "self_id": 123456789,
        "user_id": 123456789,
        "group_id": 10001,
        "message_id": 4242,
        "message": [{"type": "text", "data": {"text": "bot 的自发言论"}}],
        "raw_message": "bot 的自发言论",
        "font": 0,
        "sender": {"user_id": 123456789, "nickname": "QuickQuip", "card": ""},
    }


def _private_payload() -> dict:
    return {
        "post_type": "message_sent",
        "message_type": "private",
        "sub_type": "friend",
        "time": 1_700_000_000,
        "self_id": 123456789,
        "user_id": 123456789,
        "message_id": 4243,
        "message": [{"type": "text", "data": {"text": "私聊自消息"}}],
        "raw_message": "私聊自消息",
        "font": 0,
        "sender": {"user_id": 123456789, "nickname": "QuickQuip"},
    }


def test_register_and_parse_group_self_message():
    from nonebot.adapters.onebot.v11.adapter import Adapter

    assert register_self_message_events() is True
    event = Adapter.json_to_event(_group_payload())
    assert isinstance(event, GroupMessageSentEvent)
    assert event.get_type() == "message_sent"
    assert is_self_message(event)
    assert event.group_id == 10001
    assert "自发言论" in event.get_message().extract_plain_text()


def test_register_and_parse_private_self_message():
    from nonebot.adapters.onebot.v11.adapter import Adapter

    assert register_self_message_events() is True
    event = Adapter.json_to_event(_private_payload())
    assert isinstance(event, PrivateMessageSentEvent)
    assert event.get_type() == "message_sent"
    assert is_self_message(event)


def test_normal_group_message_still_uses_default_model():
    """普通用户消息不受自定义模型影响（回归保护）。"""
    from nonebot.adapters.onebot.v11.adapter import Adapter
    from nonebot.adapters.onebot.v11.event import GroupMessageEvent

    register_self_message_events()
    payload = _group_payload()
    payload["post_type"] = "message"
    payload["user_id"] = 10001
    event = Adapter.json_to_event(payload)
    assert type(event) is GroupMessageEvent
    assert not is_self_message(event)
