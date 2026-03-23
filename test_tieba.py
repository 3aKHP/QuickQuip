from __future__ import annotations

from pathlib import Path
import random
import shutil

from plugins.tieba_service import TiebaConfig, TiebaService
from plugins.tieba_store import TiebaStore, TiebaThread


artifact_dir = Path("dev/sandbox/test_artifacts/test_tieba")
if artifact_dir.exists():
    shutil.rmtree(artifact_dir)
artifact_dir.mkdir(parents=True, exist_ok=True)

store_path = artifact_dir / "pool.json"
store = TiebaStore(store_path, max_threads=3, recent_sent_limit=3)

threads = [
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

updated = store.record_sync_success(threads, completed_at=10)
assert updated == 3
assert store.count() == 3
assert store.last_sync_status == "ok"
assert store.login_required is False

store.mark_sent("100")
store.mark_sent("102")
random.seed(0)
selected = store.choose_random_thread(prefer_images=True, avoid_recent=2)
assert selected is not None
assert selected.tid == "101"

store.record_sync_failure("需要登录", login_required=True, failed_at=20)
assert store.last_sync_status == "login_required"
assert store.login_required is True

store.save()
restored = TiebaStore(store_path, max_threads=3, recent_sent_limit=3)
restored.load()
assert restored.count() == 3
assert restored.login_required is True
assert restored.last_error == "需要登录"
assert list(restored.recent_sent_ids) == ["100", "102"]

restored.record_sync_success(
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
assert restored.count() == 3
assert "100" not in restored.threads

config = TiebaConfig(
    enabled=True,
    forum_keyword="测试吧",
    sync_interval_seconds=900,
    max_pool_size=240,
    recent_sent_limit=30,
    detail_fetch_limit=18,
    random_avoid_recent=10,
    prefer_image_threads=True,
    browser_headless=True,
    browser_channel="",
    profile_dir=artifact_dir / "profile",
    state_path=artifact_dir / "storage_state.json",
    store_path=store_path,
)
service = TiebaService(config=config)
preview = service.build_thread_preview(
    TiebaThread(
        tid="104",
        title="测试标题",
        thread_url="https://tieba.baidu.com/p/104",
        author_name="楼主",
        main_post_text="这是一段测试摘要" * 20,
        cover_image_url="https://example.com/104.jpg",
        image_urls=["https://example.com/104.jpg"],
    )
)
assert "【测试标题】" in preview
assert "作者：楼主" in preview
assert "https://tieba.baidu.com/p/104" in preview
assert preview.endswith("https://tieba.baidu.com/p/104")

status = service.format_status()
assert "目标贴吧：测试吧" in status
assert "缓存帖子：" in status

print("贴吧相关测试通过")
