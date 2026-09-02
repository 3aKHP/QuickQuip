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


def test_image_urls_round_trip():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u1", "a", "A", "看这张图", image_urls=["http://x/1.png", "http://x/2.png"], now_ts=0)
    buf.add_message(1, "u2", "b", "B", "纯文字", now_ts=1)
    recent = buf.list_recent(1, now_ts=2)
    assert recent[0]["image_urls"] == ["http://x/1.png", "http://x/2.png"]
    assert recent[1]["image_urls"] == []


def test_image_urls_strips_empty_and_whitespace():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u", "a", "A", "msg", image_urls=["  http://x/1.png  ", "", "  "], now_ts=0)
    recent = buf.list_recent(1, now_ts=1)
    assert recent[0]["image_urls"] == ["http://x/1.png"]


def test_image_urls_default_empty():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u", "a", "A", "msg", now_ts=0)
    recent = buf.list_recent(1, now_ts=1)
    assert recent[0]["image_urls"] == []


def test_image_urls_returns_copy():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u", "a", "A", "msg", image_urls=["http://x/1.png"], now_ts=0)
    recent = buf.list_recent(1, now_ts=1)
    recent[0]["image_urls"].append("http://x/evil.png")
    # Mutating the returned dict must not leak into the buffer's internal state.
    assert buf.list_recent(1, now_ts=1)[0]["image_urls"] == ["http://x/1.png"]


def test_clear_scope_removes_group_and_keeps_others():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u1", "a", "A", "群1消息", now_ts=0)
    buf.add_message(2, "u2", "b", "B", "群2消息", now_ts=0)
    assert buf.clear_scope(1) is True
    assert buf.list_recent(1, now_ts=1) == []
    assert [m["text"] for m in buf.list_recent(2, now_ts=1)] == ["群2消息"]


def test_clear_scope_unknown_group_returns_false():
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    assert buf.clear_scope(999) is False


def test_clear_scope_then_new_messages_only_new_content():
    # clear_context 语义：清空后缓冲只能重新累积清空之后的新消息，
    # 旧消息没有回填路径。
    buf = RecentMessageBuffer(max_messages_per_group=20, ttl_seconds=60)
    buf.add_message(1, "u1", "a", "A", "清空前的旧话", now_ts=0)
    buf.clear_scope(1)
    buf.add_message(1, "u2", "b", "B", "清空后的新话", now_ts=2)
    recent = buf.list_recent(1, now_ts=3)
    assert [m["text"] for m in recent] == ["清空后的新话"]
