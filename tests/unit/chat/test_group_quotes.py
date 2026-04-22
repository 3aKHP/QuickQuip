from __future__ import annotations

import pytest

from quickquip.chat.group_quotes import GroupQuoteStore


@pytest.fixture
def store(tmp_path):
    return GroupQuoteStore(tmp_path / "quotes.db")


def test_add_and_count(store):
    assert store.count("g1") == 0
    store.add("g1", "u1", "Alice", "金句一", "u2")
    assert store.count("g1") == 1


def test_random_empty(store):
    assert store.random("g1") is None


def test_random_returns_entry(store):
    store.add("g1", "u1", "Alice", "经典名言", "u2")
    q = store.random("g1")
    assert q is not None
    assert q["content"] == "经典名言"
    assert q["quoted_sender_name"] == "Alice"
    assert isinstance(q["saved_at"], int)


def test_group_isolation(store):
    store.add("g1", "u1", "A", "g1 quote", "u2")
    assert store.count("g1") == 1
    assert store.count("g2") == 0
    assert store.random("g2") is None


def test_random_from_multiple(store):
    for i in range(10):
        store.add("g1", "u1", "A", f"quote {i}", "u2")
    assert store.count("g1") == 10
    q = store.random("g1")
    assert q is not None
    assert q["content"].startswith("quote ")
