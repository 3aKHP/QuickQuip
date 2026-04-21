from __future__ import annotations

from quickquip.common.recent_message_buffer import RecentMessageBuffer


def test_ring_buffer_caps_and_orders():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    for i in range(25):
        buf.add_message(1, i, f"用户{i}", f"标准名{i}", f"消息{i}", now_ts=i)
    recent = buf.list_recent(1, now_ts=25)
    assert len(recent) == 20
    assert recent[0]["text"] == "消息5"
    assert recent[-1]["text"] == "消息24"
    assert recent[-1]["canonical_name"] == "标准名24"


def test_ttl_expiry_filters_old_messages():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    for i in range(5):
        buf.add_message(1, i, "n", "c", f"m{i}", now_ts=i)
    # All messages are older than ttl from now_ts=90
    assert buf.list_recent(1, now_ts=90) == []


def test_group_isolation():
    buf = RecentMessageBuffer(max_messages_per_group=10, ttl_seconds=60)
    buf.add_message(1, "u1", "a", "A", "msg-group-1", now_ts=0)
    buf.add_message(2, "u2", "b", "B", "msg-group-2", now_ts=0)
    r1 = buf.list_recent(1, now_ts=1)
    r2 = buf.list_recent(2, now_ts=1)
    assert [m["text"] for m in r1] == ["msg-group-1"]
    assert [m["text"] for m in r2] == ["msg-group-2"]
