from __future__ import annotations

import os
import tempfile

import pytest

from quickquip.chat.offline_messages import OfflineMessageStore, PendingMessage


@pytest.fixture
def store(tmp_path):
    return OfflineMessageStore(tmp_path / "test.db")


def test_add_and_pop(store):
    store.add("g1", "u1", "Alice", "u2", "hello")
    msgs = store.pop_pending("g1", "u2")
    assert len(msgs) == 1
    m = msgs[0]
    assert m.from_user_id == "u1"
    assert m.from_sender_name == "Alice"
    assert m.content == "hello"
    assert isinstance(m.created_at, int)
    assert store.pop_pending("g1", "u2") == []


def test_pop_empty(store):
    assert store.pop_pending("g1", "u1") == []


def test_pop_multiple_ordered(store):
    store.add("g1", "u1", "A", "u2", "first")
    store.add("g1", "u3", "B", "u2", "second")
    msgs = store.pop_pending("g1", "u2")
    assert [m.content for m in msgs] == ["first", "second"]
    assert store.pop_pending("g1", "u2") == []


def test_retract_latest(store):
    store.add("g1", "u1", "A", "u2", "first")
    store.add("g1", "u1", "A", "u2", "second")
    result = store.retract_latest("g1", "u1")
    assert result == "u2"
    msgs = store.pop_pending("g1", "u2")
    assert len(msgs) == 1
    assert msgs[0].content == "first"


def test_retract_no_messages(store):
    assert store.retract_latest("g1", "u1") is None


def test_list_pending_does_not_consume(store):
    store.add("g1", "u1", "A", "u2", "hello")
    listed = store.list_pending_for("g1", "u2")
    assert len(listed) == 1
    popped = store.pop_pending("g1", "u2")
    assert len(popped) == 1


def test_group_isolation(store):
    store.add("g1", "u1", "A", "u2", "in g1")
    store.add("g2", "u1", "A", "u2", "in g2")
    assert store.pop_pending("g1", "u2")[0].content == "in g1"
    assert store.pop_pending("g2", "u2")[0].content == "in g2"


def test_user_isolation(store):
    store.add("g1", "u1", "A", "u2", "for u2")
    store.add("g1", "u1", "A", "u3", "for u3")
    assert store.pop_pending("g1", "u2")[0].content == "for u2"
    assert store.pop_pending("g1", "u3")[0].content == "for u3"


def test_retract_only_own_messages(store):
    store.add("g1", "u1", "A", "u3", "from u1")
    store.add("g1", "u2", "B", "u3", "from u2")
    result = store.retract_latest("g1", "u2")
    assert result == "u3"
    msgs = store.pop_pending("g1", "u3")
    assert len(msgs) == 1
    assert msgs[0].from_user_id == "u1"
