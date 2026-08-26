"""NoneBot2 / OneBot V11 message dummies for testing.

These are standalone classes that mimic the shape of nonebot.Message /
MessageSegment / Event / Reply / Sender, without depending on the real adapter.
"""
from __future__ import annotations

from typing import Any


class DummySegment:
    def __init__(self, segment_type: str, data: dict[str, Any]):
        self.type = segment_type
        self.data = data


class DummyMessage(list):
    def __str__(self) -> str:
        parts: list[str] = []
        for segment in self:
            if segment.type == "text":
                parts.append(segment.data.get("text", ""))
            elif segment.type == "at":
                parts.append(f"[CQ:at,qq={segment.data.get('qq', '')}]")
            elif segment.type == "image":
                parts.append("[CQ:image]")
            elif segment.type == "record":
                parts.append("[CQ:record]")
            else:
                parts.append(f"[CQ:{segment.type}]")
        return "".join(parts)


class DummyEvent:
    def __init__(self, user_id, self_id):
        self.user_id = user_id
        self.self_id = self_id


class DummySender:
    def __init__(self, *, card: str = "", nickname: str = ""):
        self.card = card
        self.nickname = nickname


class DummyReply:
    def __init__(self, *, message, user_id, sender=None, message_id=None):
        self.message = message
        self.user_id = user_id
        self.sender = sender
        self.message_id = message_id


def text_seg(text: str) -> DummySegment:
    return DummySegment("text", {"text": text})


def at_seg(qq: str) -> DummySegment:
    return DummySegment("at", {"qq": qq})


def face_seg(face_id: str = "264") -> DummySegment:
    return DummySegment("face", {"id": face_id})


def image_seg(url: str) -> DummySegment:
    return DummySegment("image", {"url": url})


def record_seg(file: str, **data: Any) -> DummySegment:
    return DummySegment("record", {"file": file, **data})


def forward_seg(forward_id: str) -> DummySegment:
    return DummySegment("forward", {"id": forward_id})
