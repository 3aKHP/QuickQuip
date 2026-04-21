from __future__ import annotations

import random
from pathlib import Path

from plugins.tieba_store import TiebaStore, TiebaThread


def _make_threads() -> list[TiebaThread]:
    return [
        TiebaThread(
            tid="100",
            title="第一条",
            thread_url="https://tieba.baidu.com/p/100",
            main_post_text="主楼内容 A",
            cover_image_url="https://example.com/a.jpg",
            image_urls=["https://example.com/a.jpg"],
            fetched_at=1,
        ),
        TiebaThread(
            tid="101",
            title="第二条",
            thread_url="https://tieba.baidu.com/p/101",
            main_post_text="主楼内容 B",
            fetched_at=2,
        ),
        TiebaThread(
            tid="102",
            title="第三条",
            thread_url="https://tieba.baidu.com/p/102",
            main_post_text="主楼内容 C",
            cover_image_url="https://example.com/c.jpg",
            image_urls=["https://example.com/c.jpg"],
            fetched_at=3,
        ),
    ]


def test_record_sync_success_sets_state(tmp_path: Path):
    store = TiebaStore(tmp_path / "pool.json", max_threads=3, recent_sent_limit=3)
    updated = store.record_sync_success("测试", _make_threads(), completed_at=10)
    assert updated == 3
    assert store.count(("测试",)) == 3
    assert store.count() == 3

    state = store.get_forum_state("测试")
    assert state.last_sync_status == "ok"
    assert state.login_required is False


def test_random_thread_prefers_images_and_avoids_recent(tmp_path: Path):
    store = TiebaStore(tmp_path / "pool.json", max_threads=3, recent_sent_limit=3)
    store.record_sync_success("测试", _make_threads(), completed_at=10)
    store.mark_sent("100", "测试")
    store.mark_sent("102", "测试")

    random.seed(0)
    selected = store.choose_random_thread(
        forum_keywords=("测试",), prefer_images=True, avoid_recent=2
    )
    assert selected is not None
    # 100 / 102 are in recent_sent with avoid_recent=2 -> excluded. Only 101 remains.
    assert selected.tid == "101"
    assert selected.forum_keyword == "测试"


def test_multi_source_counts_are_per_forum(tmp_path: Path):
    store = TiebaStore(tmp_path / "pool.json", max_threads=3, recent_sent_limit=3)
    store.record_sync_success("测试", _make_threads(), completed_at=10)
    store.record_sync_success(
        "第二",
        [
            TiebaThread(
                tid="200",
                title="第二池第一条",
                thread_url="https://tieba.baidu.com/p/200",
                forum_keyword="第二",
                main_post_text="第二池内容",
                fetched_at=4,
            )
        ],
        completed_at=12,
    )
    assert store.count(("第二",)) == 1
    assert store.count(("测试",)) == 3


def test_record_sync_failure_sets_login_required(tmp_path: Path):
    store = TiebaStore(tmp_path / "pool.json", max_threads=3, recent_sent_limit=3)
    store.record_sync_success("测试", _make_threads(), completed_at=10)
    store.record_sync_failure("第二", "需要登录", login_required=True, failed_at=20)

    state = store.get_forum_state("第二")
    assert state.last_sync_status == "login_required"
    assert state.login_required is True
    assert store.any_login_required(("第二",)) is True


def test_save_and_load_round_trip(tmp_path: Path):
    pool_path = tmp_path / "pool.json"
    store = TiebaStore(pool_path, max_threads=3, recent_sent_limit=3)
    store.record_sync_success("测试", _make_threads(), completed_at=10)
    store.mark_sent("100", "测试")
    store.mark_sent("102", "测试")
    store.record_sync_failure("第二", "需要登录", login_required=True, failed_at=20)
    store.save()

    restored = TiebaStore(pool_path, max_threads=3, recent_sent_limit=3)
    restored.load()
    assert restored.count(("测试",)) == 3
    assert restored.get_forum_state("第二").last_error == "需要登录"
    assert list(restored.get_forum_state("测试").recent_sent_ids) == ["100", "102"]


def test_max_threads_eviction_after_reload(tmp_path: Path):
    pool_path = tmp_path / "pool.json"
    store = TiebaStore(pool_path, max_threads=3, recent_sent_limit=3)
    store.record_sync_success("测试", _make_threads(), completed_at=10)
    store.save()

    restored = TiebaStore(pool_path, max_threads=3, recent_sent_limit=3)
    restored.load()
    # Adding a fourth thread should evict the oldest (tid=100, earliest fetched_at)
    restored.record_sync_success(
        "测试",
        [
            TiebaThread(
                tid="103",
                title="第四条",
                thread_url="https://tieba.baidu.com/p/103",
                main_post_text="主楼内容 D",
                fetched_at=11,
            )
        ],
        completed_at=30,
    )
    assert restored.count(("测试",)) == 3
    assert "100" not in restored.get_forum_state("测试").threads
