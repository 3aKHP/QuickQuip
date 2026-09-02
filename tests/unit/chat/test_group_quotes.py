from __future__ import annotations

import pytest

from quickquip.chat.group_quotes import GroupQuoteStore, resolve_quote_display_name


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


def test_random_returns_quoted_user_id(store):
    store.add("g1", "u1", "Alice", "经典名言", "u2")
    q = store.random("g1")
    assert q is not None
    assert q["quoted_user_id"] == "u1"


def test_search_by_sender_user_ids(store):
    store.add("g1", "u1", "Alice", "金句一", "u2")
    store.add("g1", "u2", "Bob", "金句二", "u3")
    rows, total = store.search_by_sender("g1", user_ids=["u1"])
    assert total == 1
    assert rows[0]["content"] == "金句一"


def test_search_by_sender_name_pattern_matches_legacy_rows(store):
    store.add("g1", "", "Carol", "老语录", "u9")
    rows, total = store.search_by_sender("g1", name_pattern="Caro")
    assert total == 1
    assert rows[0]["quoted_sender_name"] == "Carol"


def test_search_by_sender_combines_ids_and_pattern(store):
    store.add("g1", "u1", "Alice", "新语录", "u2")
    store.add("g1", "", "Alice", "旧语录", "u2")
    rows, total = store.search_by_sender("g1", user_ids=["u1"], name_pattern="Alice")
    assert total == 2
    assert {r["content"] for r in rows} == {"新语录", "旧语录"}


def test_search_by_sender_empty_query_returns_empty(store):
    store.add("g1", "u1", "Alice", "金句", "u2")
    assert store.search_by_sender("g1") == ([], 0)


class _FakeMatch:
    def __init__(self, canonical_name: str):
        self.canonical_name = canonical_name


class _FakeIdentityIndex:
    def __init__(self, canonical_by_uid=None):
        self._by_uid = canonical_by_uid or {}

    def resolve_user(self, user_id, sender_name=""):
        return _FakeMatch(self._by_uid.get(str(user_id), ""))


def test_resolve_display_prefers_latest_card_over_identity():
    resolved, changed = resolve_quote_display_name(
        "u1", "旧名片",
        user_names={"u1": "新名片"},
        identity_index=_FakeIdentityIndex({"u1": "规范名"}),
    )
    assert (resolved, changed) == ("新名片", True)


def test_resolve_display_falls_back_to_canonical_name():
    resolved, changed = resolve_quote_display_name(
        "u1", "旧名片",
        user_names={},
        identity_index=_FakeIdentityIndex({"u1": "规范名"}),
    )
    assert (resolved, changed) == ("规范名", True)


def test_resolve_display_falls_back_to_snapshot_without_sources():
    assert resolve_quote_display_name("u1", "快照名") == ("快照名", False)
    assert resolve_quote_display_name(
        "u1", "快照名",
        user_names={"u2": "别人"},
        identity_index=_FakeIdentityIndex(),
    ) == ("快照名", False)


def test_resolve_display_without_user_id_keeps_snapshot():
    assert resolve_quote_display_name("", "快照名", user_names={"": "x"}) == ("快照名", False)


def test_resolve_display_unknown_snapshot_shows_resolved_only():
    resolved, changed = resolve_quote_display_name(
        "u1", "未知", user_names={"u1": "新名片"}, identity_index=None,
    )
    assert (resolved, changed) == ("新名片", False)


def test_resolve_display_unchanged_name_not_marked_changed():
    resolved, changed = resolve_quote_display_name(
        "u1", "同名", user_names={"u1": "同名"}, identity_index=None,
    )
    assert (resolved, changed) == ("同名", False)


def test_resolve_display_placeholder_card_falls_through():
    resolved, changed = resolve_quote_display_name(
        "u1", "Alice",
        user_names={"u1": "未知"},
        identity_index=_FakeIdentityIndex({"u1": "规范名"}),
    )
    assert (resolved, changed) == ("规范名", True)

    resolved, changed = resolve_quote_display_name(
        "u1", "Alice",
        user_names={"u1": "未知"},
        identity_index=_FakeIdentityIndex(),
    )
    assert (resolved, changed) == ("Alice", False)
