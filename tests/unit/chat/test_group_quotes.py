from __future__ import annotations

import pytest

from quickquip.chat.group_quotes import GroupQuoteStore


@pytest.fixture
def store(tmp_path):
    return GroupQuoteStore(tmp_path / "quotes.db")


@pytest.fixture
def clock():
    now = {"value": 1000.0}

    def _time():
        return now["value"]

    def _advance(seconds: float):
        now["value"] += seconds

    _time.advance = _advance  # type: ignore[attr-defined]
    return _time


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


def test_random_prefers_quotes_not_recently_returned(tmp_path, clock):
    store = GroupQuoteStore(tmp_path / "quotes.db", time_func=clock)
    for i in range(5):
        store.add("g1", "u1", "A", f"quote {i}", "u2")

    seen = {store.random("g1")["id"] for _ in range(5)}  # type: ignore[index]

    assert len(seen) == 5
    assert store.recent_random_count("g1") == 5


def test_random_falls_back_after_all_quotes_seen(tmp_path, clock):
    store = GroupQuoteStore(tmp_path / "quotes.db", time_func=clock)
    for i in range(2):
        store.add("g1", "u1", "A", f"quote {i}", "u2")

    first = store.random("g1")
    second = store.random("g1")
    third = store.random("g1")

    assert first is not None
    assert second is not None
    assert third is not None
    assert first["id"] != second["id"]
    assert third["id"] in {first["id"], second["id"]}
    assert store.recent_random_count("g1") == 1


def test_recent_random_window_expires(tmp_path, clock):
    store = GroupQuoteStore(tmp_path / "quotes.db", recent_random_window_seconds=10, time_func=clock)
    for i in range(2):
        store.add("g1", "u1", "A", f"quote {i}", "u2")

    q = store.random("g1")
    assert q is not None
    assert store.recent_random_count("g1") == 1

    clock.advance(11)  # type: ignore[attr-defined]

    assert store.recent_random_count("g1") == 0


def test_recent_random_history_is_group_scoped(tmp_path, clock):
    store = GroupQuoteStore(tmp_path / "quotes.db", time_func=clock)
    store.add("g1", "u1", "A", "g1 quote", "u2")
    store.add("g2", "u1", "A", "g2 quote", "u2")

    assert store.random("g1") is not None
    assert store.recent_random_count("g1") == 1
    assert store.recent_random_count("g2") == 0


def test_close_is_idempotent(store):
    store.close()
    store.close()
