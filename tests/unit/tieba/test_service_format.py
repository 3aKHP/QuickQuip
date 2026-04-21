from __future__ import annotations

from pathlib import Path

import pytest

from plugins.tieba_service import TiebaConfig, TiebaService
from plugins.tieba_store import TiebaStore, TiebaThread


@pytest.fixture
def seeded_service(tmp_path: Path) -> TiebaService:
    store_path = tmp_path / "pool.json"
    store = TiebaStore(store_path, max_threads=3, recent_sent_limit=3)
    store.record_sync_success(
        "测试",
        [
            TiebaThread(
                tid=str(100 + i),
                title=f"第{i + 1}条",
                thread_url=f"https://tieba.baidu.com/p/{100 + i}",
                main_post_text=f"主楼内容 {i}",
                fetched_at=i + 1,
            )
            for i in range(3)
        ],
        completed_at=10,
    )
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
    store.record_sync_failure("第二", "需要登录", login_required=True, failed_at=20)
    store.save()

    config = TiebaConfig(
        enabled=True,
        sync_interval_seconds=900,
        max_pool_size=240,
        recent_sent_limit=30,
        detail_fetch_limit=18,
        random_avoid_recent=10,
        prefer_image_threads=True,
        browser_headless=True,
        browser_channel="",
        profile_dir=tmp_path / "profile",
        state_path=tmp_path / "storage_state.json",
        store_path=store_path,
        forum_keyword="测试",
        forum_keywords=("测试", "第二"),
    )
    return TiebaService(config=config)


def test_config_exposes_keywords(seeded_service: TiebaService):
    assert seeded_service.config.forum_keyword == "测试"
    assert seeded_service.config.forum_keywords == ("测试", "第二")


def test_build_thread_preview_contains_expected_fields(seeded_service: TiebaService):
    preview = seeded_service.build_thread_preview(
        TiebaThread(
            tid="104",
            title="测试标题",
            thread_url="https://tieba.baidu.com/p/104",
            forum_keyword="第二",
            author_name="楼主",
            main_post_text="这是一段测试摘要" * 20,
            cover_image_url="https://example.com/104.jpg",
            image_urls=["https://example.com/104.jpg"],
        )
    )
    assert "【测试标题】" in preview
    assert "来源：第二吧" in preview
    assert "作者：楼主" in preview
    assert preview.endswith("https://tieba.baidu.com/p/104")


def test_format_status_includes_source_count(seeded_service: TiebaService):
    status = seeded_service.format_status()
    assert "已配置来源：2 个" in status
    assert "来源：测试吧" in status
    assert "来源：第二吧" in status
    assert "缓存帖子：" in status


def test_format_sources_lists_every_source(seeded_service: TiebaService):
    sources = seeded_service.format_sources()
    assert "贴吧来源" in sources
    assert "- 测试吧 | 缓存 3 条 | 状态 ok | 登录态 正常或未判定" in sources
    assert "- 第二吧 | 缓存 1 条 | 状态 login_required | 登录态 需要续签" in sources


def test_format_sources_filter(seeded_service: TiebaService):
    sources = seeded_service.format_sources("第二")
    assert "已配置来源：2 个" in sources
    assert "- 第二吧 | 缓存 1 条 | 状态 login_required | 登录态 需要续签" in sources
