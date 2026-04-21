from __future__ import annotations

from quickquip.common.message_deduper import RecentMessageDeduper


def test_first_id_is_not_duplicate():
    d = RecentMessageDeduper(max_ids_per_group=2)
    assert d.is_duplicate(1, 10001) is False


def test_repeat_id_is_duplicate():
    d = RecentMessageDeduper(max_ids_per_group=2)
    d.is_duplicate(1, 10001)
    assert d.is_duplicate(1, 10001) is True


def test_eviction_allows_reuse_of_old_id():
    d = RecentMessageDeduper(max_ids_per_group=2)
    assert d.is_duplicate(1, 10001) is False
    assert d.is_duplicate(1, 10001) is True
    assert d.is_duplicate(1, 10002) is False
    assert d.is_duplicate(1, 10003) is False
    # 10001 evicted, should be usable again
    assert d.is_duplicate(1, 10001) is False
